import { useMemo, useRef, useState } from 'react';
import type { FocusEvent, MouseEvent as ReactMouseEvent } from 'react';
import { CandlestickChart, ChevronDown } from 'lucide-react';

export type UsageDailyModel = {
  provider: string;
  model: string;
  calls: number;
  totalIn: number;
  uncachedOrPrompt: number;
  cacheRead: number;
  cacheWrite: number;
  output: number;
  costUsd: number;
  unknownCalls: number;
};

export type UsageDailyDay = {
  day: string;
  totalIn: number;
  totalOut: number;
  costUsd: number;
  models: UsageDailyModel[];
};

export type UsageDailyResponse = {
  since: string;
  timezone: string;
  pricingUpdatedAt: string;
  note: string;
  days: UsageDailyDay[];
};

type UsageSeries = {
  id: string;
  provider: string;
  model: string;
  label: string;
  color: string;
};

type UsageChartRow = {
  day: string;
  totalIn: number;
  totalOut: number;
  costUsd: number;
  modelsBySeries: Record<string, UsageDailyModel>;
  [seriesId: string]: string | number | Record<string, UsageDailyModel>;
};

type UsageDailyChartProps = {
  days: UsageDailyDay[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  note?: string;
  modelLabel: (provider: string, modelId: string) => string;
};

const MODEL_COLORS = [
  '#61A9BD',
  '#1F74AD',
  '#DD83C9',
  '#E98E2E',
  '#9267C6',
  '#CED14E',
  '#8D6C5B',
  '#979797',
];

const formatTokens = (value: number) => Math.max(0, value).toLocaleString();
const formatUsd = (value: number) => value.toLocaleString(undefined, {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 4,
  maximumFractionDigits: 6,
});

function formatAxisTokens(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}M`;
  if (value >= 1_000) return `${(value / 1_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}K`;
  return value.toLocaleString();
}

function formatUtcDay(day: string, options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }) {
  const [year, month, date] = day.split('-').map(Number);
  return new Intl.DateTimeFormat(undefined, { ...options, timeZone: 'UTC' })
    .format(new Date(Date.UTC(year, month - 1, date)));
}

function addUtcDays(day: string, offset: number) {
  const [year, month, date] = day.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, date + offset)).toISOString().slice(0, 10);
}

function getTodayUtc() {
  return new Date().toISOString().slice(0, 10);
}

function DailyUsageTooltip({ row, series }: { row: UsageChartRow; series: UsageSeries[] }) {
  const date = formatUtcDay(row.day, { weekday: 'short', month: 'long', day: 'numeric', year: 'numeric' });
  const visibleModels = series
    .map((item) => ({ series: item, usage: row.modelsBySeries[item.id] }))
    .filter(({ usage }) => usage && (usage.totalIn > 0 || usage.output > 0 || usage.calls > 0));

  return <div className="usage-chart-tooltip" role="status" aria-live="polite">
    <strong className="usage-chart-tooltip-date">{date} <span>UTC</span></strong>
    {visibleModels.map(({ series: item, usage }) => <div className="usage-chart-tooltip-model" key={item.id}>
      <span className="usage-chart-tooltip-name"><i style={{ background: item.color }} />{item.label}</span>
      <span><b>{formatTokens(usage.totalIn)}</b> in · <b>{formatTokens(usage.output)}</b> out</span>
      <small>{usage.calls.toLocaleString()} calls · cache read {formatTokens(usage.cacheRead)} · write {formatTokens(usage.cacheWrite)}</small>
      <small>{usage.unknownCalls ? `${usage.unknownCalls} unpriced calls · ` : ''}{formatUsd(usage.costUsd)}</small>
    </div>)}
    <div className="usage-chart-tooltip-total">
      <span>Total input</span><b>{formatTokens(row.totalIn)}</b>
      <span>Total output</span><b>{formatTokens(row.totalOut)}</b>
      <span>Estimated cost</span><b>{formatUsd(row.costUsd)}</b>
    </div>
  </div>;
}

export function UsageDailyChart({
  days,
  isLoading,
  isError,
  onRetry,
  note,
  modelLabel,
}: UsageDailyChartProps) {
  const [rangeDays, setRangeDays] = useState<7 | 30>(30);
  const chartPlotRef = useRef<HTMLDivElement>(null);
  const [hoveredRow, setHoveredRow] = useState<UsageChartRow | null>(null);
  const [tooltipPosition, setTooltipPosition] = useState({ left: 12, top: 12 });
  const chart = useMemo(() => {
    const today = getTodayUtc();
    const lastRecordedDay = days.reduce((latest, item) => item.day > latest ? item.day : latest, today);
    const startDay = addUtcDays(lastRecordedDay, -(rangeDays - 1));
    const sourceByDay = new Map(days.map((item) => [item.day, item]));
    const filteredSource = days.filter((item) => item.day >= startDay && item.day <= lastRecordedDay);
    const totalsByModel = new Map<string, { provider: string; model: string; totalIn: number }>();

    filteredSource.forEach((day) => day.models.forEach((model) => {
      const key = `${model.provider}\u0000${model.model}`;
      const current = totalsByModel.get(key) ?? { provider: model.provider, model: model.model, totalIn: 0 };
      current.totalIn += model.totalIn;
      totalsByModel.set(key, current);
    }));

    const modelList = [...totalsByModel.values()]
      .sort((left, right) => right.totalIn - left.totalIn)
      .map((item, index) => ({
        id: `model-${index}`,
        provider: item.provider,
        model: item.model,
        label: modelLabel(item.provider, item.model),
        color: MODEL_COLORS[index % MODEL_COLORS.length],
      }));

    const rows: UsageChartRow[] = Array.from({ length: rangeDays }, (_, index) => {
      const day = addUtcDays(startDay, index);
      const source = sourceByDay.get(day);
      const modelsBySeries: Record<string, UsageDailyModel> = {};
      const row: UsageChartRow = {
        day,
        totalIn: source?.totalIn ?? 0,
        totalOut: source?.totalOut ?? 0,
        costUsd: source?.costUsd ?? 0,
        modelsBySeries,
      };
      modelList.forEach((series) => {
        const usage = source?.models.find((model) => model.provider === series.provider && model.model === series.model);
        if (usage) modelsBySeries[series.id] = usage;
        row[series.id] = usage?.totalIn ?? 0;
      });
      return row;
    });

    return {
      rows,
      series: modelList,
      totalIn: rows.reduce((total, item) => total + item.totalIn, 0),
      totalOut: rows.reduce((total, item) => total + item.totalOut, 0),
      costUsd: rows.reduce((total, item) => total + item.costUsd, 0),
    };
  }, [days, modelLabel, rangeDays]);

  const hasUsage = chart.totalIn > 0 || chart.totalOut > 0;
  const svg = useMemo(() => {
    const width = 1000;
    const height = 292;
    const margin = { top: 12, right: 12, bottom: 36, left: 58 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maxTotal = Math.max(1, ...chart.rows.map((row) => chart.series.reduce((total, series) => total + Number(row[series.id] || 0), 0)));
    const rawStep = maxTotal / 4;
    const magnitude = 10 ** Math.floor(Math.log10(rawStep || 1));
    const normalized = rawStep / magnitude;
    const niceStep = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
    const maxValue = niceStep * 4;
    const cellWidth = plotWidth / Math.max(1, chart.rows.length);
    const barWidth = Math.min(22, Math.max(4, cellWidth * 0.66));
    const tickIndexes = new Set<number>();
    const labelEvery = rangeDays === 7 ? 1 : 5;
    chart.rows.forEach((_, index) => {
      if (index % labelEvery === 0 || index === chart.rows.length - 1) tickIndexes.add(index);
    });
    return { width, height, margin, plotWidth, plotHeight, maxValue, cellWidth, barWidth, tickIndexes };
  }, [chart.rows, chart.series, rangeDays]);

  const showTooltip = (event: ReactMouseEvent<SVGRectElement> | FocusEvent<SVGRectElement>, row: UsageChartRow) => {
    const bounds = chartPlotRef.current?.getBoundingClientRect();
    const target = event.currentTarget.getBoundingClientRect();
    if (!bounds) return;
    const pointer = 'clientX' in event
      ? { x: event.clientX, y: event.clientY }
      : { x: target.left + target.width / 2, y: target.top };
    const left = pointer.x - bounds.left + 12;
    const top = pointer.y - bounds.top + 12;
    setTooltipPosition({
      left: Math.min(Math.max(8, left), Math.max(8, bounds.width - 330)),
      top: Math.min(Math.max(8, top), Math.max(8, bounds.height - 210)),
    });
    setHoveredRow(row);
  };

  return <section className="telemetry-section usage-daily" data-testid="section-usage-daily">
    <div className="telemetry-section-head usage-daily-heading">
      <span className="telemetry-section-mark"><CandlestickChart size={14} /></span>
      <div><span className="telemetry-kicker">DAILY TOKENS · UTC</span><h3>Usage over time</h3></div>
      <div className="usage-range-switch" role="group" aria-label="Usage chart date range">
        {[7, 30].map((range) => <button
          key={range}
          type="button"
          className={rangeDays === range ? 'selected' : ''}
          aria-pressed={rangeDays === range}
          onClick={() => setRangeDays(range as 7 | 30)}
          data-testid={`button-usage-range-${range}`}
        >{range}D</button>)}
      </div>
    </div>
    {isLoading
      ? <div className="telemetry-skeleton"><i /><i /><i /></div>
      : isError
        ? <div className="telemetry-error"><span>Daily usage unavailable.</span><button type="button" onClick={onRetry}>Retry</button></div>
        : !hasUsage
          ? <p className="telemetry-empty">No Forge usage recorded in the last {rangeDays} days.</p>
          : <>
            <div className="usage-kpi-grid" data-testid="usage-daily-summary">
              <div className="usage-kpi-card"><span>Tokens in</span><strong>{formatTokens(chart.totalIn)}</strong><small>Cache-inclusive prompt tokens</small></div>
              <div className="usage-kpi-card"><span>Tokens out</span><strong>{formatTokens(chart.totalOut)}</strong><small>Generated response tokens</small></div>
              <div className="usage-kpi-card"><span>Estimated cost</span><strong>{formatUsd(chart.costUsd)}</strong><small>Published provider rates</small></div>
            </div>
            <div className="usage-chart-card">
              <div className="usage-chart-title">
                <div><strong>Daily input tokens</strong><span>Stacked by model · hover a bar for the breakdown</span></div>
                <span className="usage-chart-total">{formatTokens(chart.totalIn)} total</span>
              </div>
              <div className="usage-chart-plot" ref={chartPlotRef} data-testid="usage-daily-chart">
                <svg viewBox={`0 0 ${svg.width} ${svg.height}`} preserveAspectRatio="none" role="img" aria-label={`Stacked column chart of daily input tokens by model for the last ${rangeDays} days`}>
                  {Array.from({ length: 5 }, (_, index) => {
                    const value = svg.maxValue * index / 4;
                    const y = svg.margin.top + svg.plotHeight - svg.plotHeight * index / 4;
                    return <g key={`grid-${index}`}>
                      <line x1={svg.margin.left} y1={y} x2={svg.width - svg.margin.right} y2={y} stroke="var(--usage-chart-grid)" strokeDasharray={index === 0 ? undefined : '3 5'} />
                      <text x={svg.margin.left - 8} y={y + 3} textAnchor="end" fill="var(--text-muted)" fontSize="10" fontFamily="var(--font-mono)">{formatAxisTokens(value)}</text>
                    </g>;
                  })}
                  <line x1={svg.margin.left} y1={svg.margin.top + svg.plotHeight} x2={svg.width - svg.margin.right} y2={svg.margin.top + svg.plotHeight} stroke="var(--border)" />
                  {chart.rows.map((row, rowIndex) => {
                    const x = svg.margin.left + rowIndex * svg.cellWidth + (svg.cellWidth - svg.barWidth) / 2;
                    let accumulated = 0;
                    const topSeriesId = chart.series.reduce(
                      (top, series) => Number(row[series.id] || 0) > 0 ? series.id : top,
                      '',
                    );
                    return <g key={row.day}>
                      {chart.series.map((series, seriesIndex) => {
                        const value = Number(row[series.id] || 0);
                        if (!value) return null;
                        const segmentHeight = value / svg.maxValue * svg.plotHeight;
                        const y = svg.margin.top + svg.plotHeight - (accumulated + value) / svg.maxValue * svg.plotHeight;
                        accumulated += value;
                        const usage = row.modelsBySeries[series.id];
                        const title = `${formatUtcDay(row.day, { weekday: 'short', month: 'long', day: 'numeric', year: 'numeric' })} UTC · ${series.label}: ${formatTokens(value)} input tokens · ${formatTokens(usage?.output ?? 0)} output tokens · ${usage?.calls ?? 0} calls · cache read ${formatTokens(usage?.cacheRead ?? 0)} · cache write ${formatTokens(usage?.cacheWrite ?? 0)} · ${formatUsd(usage?.costUsd ?? 0)}`;
                        return <rect
                          key={series.id}
                          x={x}
                          y={y}
                          width={svg.barWidth}
                          height={Math.max(1, segmentHeight)}
                          fill={series.color}
                          rx={series.id === topSeriesId ? 2 : 0}
                          tabIndex={0}
                          aria-label={title}
                          onMouseEnter={(event) => showTooltip(event, row)}
                          onMouseMove={(event) => showTooltip(event, row)}
                          onMouseLeave={() => setHoveredRow(null)}
                          onFocus={(event) => showTooltip(event, row)}
                          onBlur={() => setHoveredRow(null)}
                        ><title>{title}</title></rect>;
                      })}
                      {svg.tickIndexes.has(rowIndex) && <text
                        x={x + svg.barWidth / 2}
                        y={svg.height - 11}
                        textAnchor="middle"
                        fill="var(--text-muted)"
                        fontSize="10"
                        fontFamily="var(--font-mono)"
                      >{formatUtcDay(row.day)}</text>}
                    </g>;
                  })}
                </svg>
                {hoveredRow && <div className="usage-chart-tooltip-anchor" style={tooltipPosition}>
                  <DailyUsageTooltip row={hoveredRow} series={chart.series} />
                </div>}
              </div>
              <div className="usage-chart-legend" aria-label="Models in chart">
                {chart.series.map((series) => <span key={series.id}><i style={{ background: series.color }} />{series.label}</span>)}
              </div>
            </div>
            <details className="usage-daily-details">
              <summary><span>View daily breakdown</span><ChevronDown size={14} aria-hidden="true" /></summary>
              <div className="usage-daily-table-wrap">
                <table>
                  <thead><tr><th scope="col">UTC day</th><th scope="col">Model</th><th scope="col">In</th><th scope="col">Out</th><th scope="col">Calls</th><th scope="col">Cost</th></tr></thead>
                  <tbody>{[...chart.rows].reverse().flatMap((day) => {
                    const source = days.find((item) => item.day === day.day);
                    if (!source) return [];
                    return source.models.map((model) => <tr key={`${day.day}-${model.provider}-${model.model}`}>
                      <td>{formatUtcDay(day.day, { month: 'short', day: 'numeric', year: 'numeric' })}</td>
                      <td>{modelLabel(model.provider, model.model)}</td>
                      <td>{formatTokens(model.totalIn)}</td>
                      <td>{formatTokens(model.output)}</td>
                      <td>{model.calls.toLocaleString()}</td>
                      <td>{formatUsd(model.costUsd)}{model.unknownCalls ? ` · ${model.unknownCalls} unpriced` : ''}</td>
                    </tr>);
                  })}</tbody>
                </table>
              </div>
            </details>
          </>}
    <p className="telemetry-footnote">{note ?? 'Counts only calls made through Forge, cache-inclusive, in UTC. Provider console totals can include other keys and traffic.'}</p>
  </section>;
}
