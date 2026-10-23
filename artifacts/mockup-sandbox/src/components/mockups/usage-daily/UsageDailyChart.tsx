import { useMemo, useState } from 'react';
import { CandlestickChart, ChevronDown } from 'lucide-react';
import './_group.css';

const colors = ['#61A9BD', '#1F74AD', '#DD83C9', '#E98E2E'];
const models = ['Claude Haiku 5.5', 'Claude Sonnet 5.5', 'Gemini 3.5 Flash-Lite', 'Claude Opus 5.5'];
type SampleKey = 'haiku' | 'sonnet' | 'gemini' | 'opus';
type SampleRow = { day: string } & Record<SampleKey, number>;
const series = [
  { key: 'haiku' as const, label: models[0], color: colors[0] },
  { key: 'sonnet' as const, label: models[1], color: colors[1] },
  { key: 'gemini' as const, label: models[2], color: colors[2] },
  { key: 'opus' as const, label: models[3], color: colors[3] },
];
const format = (value: number) => value.toLocaleString();
const short = (value: number) => value >= 1_000_000
  ? `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  : value >= 1_000 ? `${(value / 1_000).toFixed(0)}K` : `${value}`;

function makeSample(): SampleRow[] {
  const today = new Date();
  return Array.from({ length: 30 }, (_, index) => {
    const date = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - 29 + index));
    const day = date.toISOString().slice(0, 10);
    const pulse = [6, 11, 13, 17, 21, 26, 29].includes(index);
    return {
      day,
      haiku: pulse ? 1_200_000 + index * 70_000 : 0,
      sonnet: [11, 17, 21, 26].includes(index) ? 800_000 + index * 23_000 : 0,
      gemini: [13, 21, 29].includes(index) ? 450_000 + index * 12_000 : 0,
      opus: [17, 26].includes(index) ? 190_000 + index * 4_000 : 0,
    };
  });
}

export function UsageDailyChart() {
  const [range, setRange] = useState(30);
  const data = useMemo(() => makeSample().slice(-range), [range]);
  const totals = useMemo(() => data.reduce((out, item) => {
    out.input += item.haiku + item.sonnet + item.gemini + item.opus;
    return out;
  }, { input: 0 }), [data]);
  const graph = useMemo(() => {
    const width = 1000;
    const height = 310;
    const margin = { top: 10, right: 12, bottom: 32, left: 52 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maxTotal = Math.max(1, ...data.map((row) => series.reduce((sum, item) => sum + row[item.key], 0)));
    const step = maxTotal / 4;
    const cellWidth = plotWidth / data.length;
    const barWidth = Math.min(22, cellWidth * 0.7);
    return { width, height, margin, plotWidth, plotHeight, maxTotal: step * 4, cellWidth, barWidth };
  }, [data]);

  return <main className="usage-mockup">
    <section className="usage-panel">
      <header className="usage-head">
        <span className="usage-mark"><CandlestickChart size={16} /></span>
        <div><small>DAILY TOKENS · UTC</small><h1>Usage over time</h1></div>
        <div className="range" role="group" aria-label="Date range">
          {[7, 30].map((item) => <button key={item} className={range === item ? 'active' : ''} onClick={() => setRange(item)} aria-pressed={range === item}>{item}D</button>)}
        </div>
      </header>
      <div className="stats">
        <div><span>Tokens in</span><strong>{format(totals.input)}</strong><small>Cache-inclusive prompts</small></div>
        <div><span>Tokens out</span><strong>484,284</strong><small>Generated responses</small></div>
        <div><span>Estimated cost</span><strong>$21.95</strong><small>Published provider rates</small></div>
      </div>
      <div className="chart-card">
        <div className="chart-title"><div><strong>Daily input tokens</strong><small>Stacked by model · hover for details</small></div><span>{format(totals.input)} total</span></div>
        <div className="plot" role="img" aria-label="Stacked daily token usage by model">
          <svg viewBox={`0 0 ${graph.width} ${graph.height}`} preserveAspectRatio="none" aria-hidden="true">
            {Array.from({ length: 5 }, (_, index) => {
              const y = graph.margin.top + graph.plotHeight - graph.plotHeight * index / 4;
              return <g key={`grid-${index}`}>
                <line x1={graph.margin.left} y1={y} x2={graph.width - graph.margin.right} y2={y} stroke="rgba(0,240,255,.13)" strokeDasharray={index ? '3 5' : undefined} />
                <text x={graph.margin.left - 8} y={y + 3} textAnchor="end" fill="#4e7696" fontSize="10">{short(graph.maxTotal * index / 4)}</text>
              </g>;
            })}
            <line x1={graph.margin.left} y1={graph.margin.top + graph.plotHeight} x2={graph.width - graph.margin.right} y2={graph.margin.top + graph.plotHeight} stroke="rgba(0,240,255,.22)" />
            {data.map((row, rowIndex) => {
              const x = graph.margin.left + rowIndex * graph.cellWidth + (graph.cellWidth - graph.barWidth) / 2;
              let accumulated = 0;
              const topSeriesKey = series.reduce((top, item) => row[item.key] > 0 ? item.key : top, '' as SampleKey | '');
              return <g key={row.day}>
                {series.map((item, seriesIndex) => {
                  const value = row[item.key];
                  if (!value) return null;
                  const segmentHeight = value / graph.maxTotal * graph.plotHeight;
                  const y = graph.margin.top + graph.plotHeight - (accumulated + value) / graph.maxTotal * graph.plotHeight;
                  accumulated += value;
                  return <rect key={item.key} x={x} y={y} width={graph.barWidth} height={segmentHeight} fill={item.color} rx={item.key === topSeriesKey ? 2 : 0}>
                    <title>{`${item.label} · ${row.day} UTC · ${format(value)} input tokens`}</title>
                  </rect>;
                })}
                {(rowIndex % (range === 7 ? 1 : 5) === 0 || rowIndex === data.length - 1) && <text x={x + graph.barWidth / 2} y={graph.height - 8} textAnchor="middle" fill="#4e7696" fontSize="10">
                  {new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(`${row.day}T00:00:00Z`))}
                </text>}
              </g>;
            })}
          </svg>
        </div>
        <div className="legend">{models.map((model, index) => <span key={model}><i style={{ background: colors[index] }} />{model}</span>)}</div>
      </div>
      <details className="daily-details"><summary>View daily breakdown <ChevronDown size={14} /></summary><p>Exact daily counts remain available here; hover any bar for per-model input, output, cache, and cost detail.</p></details>
      <p className="note">Counts only calls made through Forge, cache-inclusive, in UTC. Sample values shown in this design preview.</p>
    </section>
    <style>{`
      .usage-mockup { min-height:100vh; padding:28px; background:radial-gradient(ellipse at 52% 0%,rgba(0,240,255,.07),transparent 46%),var(--bg-main); }
      .usage-panel { max-width:1180px; margin:0 auto; padding:20px; border:1px solid var(--border); border-radius:6px; background:rgba(5,10,23,.86); box-shadow:0 0 28px rgba(0,240,255,.07); }
      .usage-head { display:flex; align-items:center; gap:12px; }
      .usage-mark { display:grid; width:34px; height:34px; place-items:center; border:1px solid var(--border); color:var(--accent); }
      .usage-head small { color:var(--text-muted); font:10px var(--font-mono); letter-spacing:.08em; }
      .usage-head h1 { margin:2px 0 0; font-size:19px; font-weight:600; }
      .range { display:flex; gap:3px; margin-left:auto; padding:3px; border:1px solid var(--border); border-radius:4px; }
      .range button { min-width:38px; height:25px; border:0; border-radius:2px; background:transparent; color:var(--text-muted); font:10px var(--font-mono); cursor:pointer; }
      .range button.active { background:var(--accent); color:var(--bg-main); }
      .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin:16px 0 12px; }
      .stats div { display:grid; gap:5px; padding:11px 13px; border:1px solid rgba(0,240,255,.2); border-radius:4px; background:rgba(0,240,255,.025); }
      .stats span,.stats small { color:var(--text-muted); font-size:10px; }
      .stats strong { font-size:19px; font-weight:600; }
      .chart-card { padding:13px 12px 8px; border:1px solid rgba(0,240,255,.2); border-radius:5px; background:rgba(2,4,10,.6); }
      .chart-title { display:flex; justify-content:space-between; gap:12px; margin-bottom:5px; }
      .chart-title div { display:grid; gap:3px; }
      .chart-title strong { font-size:11px; }
      .chart-title small,.chart-title > span { color:var(--text-muted); font:9px var(--font-mono); }
      .plot { height:310px; }
      .plot svg { display:block; width:100%; height:100%; }
      .legend { display:flex; flex-wrap:wrap; gap:8px 16px; padding:4px 3px; color:var(--text-muted); font-size:9px; }
      .legend span { display:flex; align-items:center; gap:6px; }
      .legend i,.mock-tooltip i { display:inline-block; width:8px; height:8px; border-radius:2px; }
      .mock-tooltip { display:grid; gap:7px; min-width:190px; padding:10px 12px; border:1px solid var(--accent); border-radius:4px; background:#050a17; color:var(--text-primary); box-shadow:0 0 16px rgba(0,240,255,.16); font-size:10px; }
      .mock-tooltip strong { padding-bottom:5px; border-bottom:1px solid var(--border); font-size:11px; }
      .mock-tooltip strong small { color:var(--text-muted); font:9px var(--font-mono); }
      .mock-tooltip span { display:flex; align-items:center; gap:6px; }
      .mock-tooltip span b { margin-left:auto; font-family:var(--font-mono); }
      .mock-tooltip footer { display:flex; justify-content:space-between; padding-top:5px; border-top:1px solid var(--border); color:var(--text-muted); }
      .mock-tooltip footer b { color:var(--text-primary); }
      .daily-details { margin-top:10px; padding-top:9px; border-top:1px solid var(--border); color:var(--accent); font:10px var(--font-mono); }
      .daily-details summary { display:flex; justify-content:space-between; cursor:pointer; }
      .daily-details[open] summary svg { transform:rotate(180deg); }
      .daily-details p,.note { color:var(--text-muted); font:10px/1.5 var(--font-mono); }
      .note { margin:12px 0 0; }
      @media(max-width:650px) { .usage-mockup { padding:12px; } .usage-panel { padding:14px; } .stats { grid-template-columns:1fr; } .plot { height:240px; } .usage-head h1 { font-size:16px; } }
    `}</style>
  </main>;
}
