import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Children, isValidElement } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Activity, AlertCircle, ArrowDown, ArrowRight, Brain, CheckCircle2, ChevronDown, Copy, FileEdit, Globe, ListChecks, Terminal, Wrench } from 'lucide-react';
import { SearchPayloadView, SourcesAccordion, parseSearchPayload } from '@/components/search-sources';
import type { AssistantTask, ConversationMessage, TaskLog } from '@workspace/api-client-react';

type Props = { tasks: AssistantTask[]; loading: boolean; onOpen: (task: AssistantTask) => void; messages?: ConversationMessage[] };

const time = (v: string) => new Date(v).getTime() || 0;
const isLive = (t: AssistantTask) => t.status === 'running' || String(t.status) === 'processing';
const clock = (v: string) => { const d = new Date(v); return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); };

function Code({ source, language }: { source: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(source); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); }
  };
  return <div className="stream-code"><div><span>{language || 'code'}</span><button type="button" onClick={() => void copy()} data-testid="button-copy-stream-code"><Copy size={12} />{copied ? 'Copied' : 'Copy'}</button></div><pre><code>{source}</code></pre></div>;
}

function Rich({ text }: { text: string }) {
  return <div className="exec-rich">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        pre({ children }) {
          const code = Children.toArray(children).find((child) =>
            isValidElement<{ children?: ReactNode; className?: string }>(child) && child.type === 'code',
          );
          if (!isValidElement<{ children?: ReactNode; className?: string }>(code)) return <pre>{children}</pre>;
          const language = code.props.className?.match(/language-([\w-]+)/)?.[1] ?? 'code';
          const source = String(code.props.children ?? '').replace(/\n$/, '');
          return <Code source={source} language={language} />;
        },
        table({ children }) {
          return <div className="exec-table-scroll"><table>{children}</table></div>;
        },
      }}
    >{text}</ReactMarkdown>
  </div>;
}

type Summary = { icon: typeof Terminal; label: string; text: string; tone: string };
const clip = (s: string, n = 140) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function summarize(log: TaskLog): Summary {
  const msg = log.message.trim();
  const first = clip(msg.split('\n').find((l) => l.trim())?.trim() ?? msg);
  const lower = first.toLowerCase();
  const fence = msg.match(/```[\w-]*\n?([\s\S]*?)```/);
  const inline = msg.match(/`([^`\n]+)`/);
  const dollar = msg.match(/^\s*\$\s*(.+)$/m);
  const path = msg.match(/((?:[A-Za-z]:)?[\w.\-\\/]+\.[A-Za-z0-9]{1,6})\b/);
  if (log.kind === 'error') return { icon: AlertCircle, label: 'Error', text: first, tone: 'error' };
  if (log.kind === 'warning') return { icon: AlertCircle, label: 'Warning', text: first, tone: 'warn' };
  if (log.kind === 'plan') return { icon: ListChecks, label: 'Plan', text: first, tone: 'plan' };
  if (log.kind === 'success' || log.kind === 'result') return { icon: CheckCircle2, label: 'Done', text: first, tone: 'ok' };
  if (/reasoning step|planning|thinking|reasoning/.test(lower)) return { icon: Brain, label: 'Reasoning', text: first, tone: 'think' };
  if (/search|browse|fetch|http|url|web/.test(lower) && log.kind === 'tool') return { icon: Globe, label: 'Web', text: clip(inline?.[1] ?? first), tone: 'web' };
  if (log.kind === 'tool') {
    if (/edit|write|wrote|creat|updat|patch|sav|delet|renam/.test(lower) && path) return { icon: FileEdit, label: 'Edit', text: `${/^editing/i.test(first) ? 'Editing' : 'Edited'} ${path[1]}`, tone: 'edit' };
    if (fence || dollar || inline || /terminal|shell|command|run|exec|python|node|npm|bash/.test(lower)) {
      const cmd = (fence?.[1].trim().split('\n')[0]) ?? dollar?.[1] ?? inline?.[1] ?? first;
      return { icon: Terminal, label: 'Run', text: clip(cmd), tone: 'run' };
    }
    return { icon: Wrench, label: 'Tool', text: first, tone: 'tool' };
  }
  if (log.kind === 'agent') return { icon: Brain, label: 'Reasoning', text: first, tone: 'think' };
  return { icon: Activity, label: 'Note', text: first, tone: 'info' };
}

type Row = { log: TaskLog; count: number };
function rowsFor(logs: TaskLog[]): Row[] {
  const sorted = logs.map((log, i) => ({ log, i })).sort((a, b) => time(a.log.createdAt) - time(b.log.createdAt) || a.i - b.i).map((x) => x.log);
  const rows: Row[] = [];
  for (const log of sorted) {
    const prev = rows[rows.length - 1];
    // Only collapse truly identical consecutive info notes.
    if (prev && log.kind === 'info' && prev.log.kind === 'info' && prev.log.message.trim() === log.message.trim()) prev.count += 1;
    else rows.push({ log, count: 1 });
  }
  return rows;
}

function Step({ row }: { row: Row }) {
  const s = summarize(row.log);
  const Icon = s.icon;
  const multi = row.log.message.trim() !== s.text || row.log.message.includes('\n');
  return <details className={`exec-step tone-${s.tone}`} data-testid={`step-log-${row.log.id}`}>
    <summary><Icon size={14} className="exec-ico" /><span className="exec-label">{s.label}</span><span className="exec-text" title={s.text}>{s.text}</span>{row.count > 1 && <span className="exec-count">x{row.count}</span>}<time>{clock(row.log.createdAt)}</time><ChevronDown size={13} className="exec-chev" aria-label={multi ? 'Show details' : 'Show raw log'} /></summary>
    <div className="exec-raw"><Rich text={row.log.message} /></div>
  </details>;
}

function ErrorLine({ error }: { error: string }) {
  const line = clip(error.split('\n')[0], 160);
  const more = error.trim() !== line;
  return <details className="exec-error"><summary><AlertCircle size={14} /><span>{line}</span>{more && <ChevronDown size={13} className="exec-chev" />}</summary>{more && <div className="exec-raw"><Rich text={error} /></div>}</details>;
}

function ToolOutput({ message }: { message: ConversationMessage }) {
  const tool = message.role === 'tool' || message.isToolCall;
  const search = parseSearchPayload(message.content);
  const first = search ? `Search via ${search.engine}: ${search.results.length} sources` : clip(message.content.split('\n').find((l) => l.trim())?.trim() ?? message.content);
  return <details className="exec-step exec-tool-out tone-tool" data-testid={`step-message-${message.id}`}>
    <summary>{tool ? <Wrench size={14} className="exec-ico" /> : <Brain size={14} className="exec-ico" />}<span className="exec-label">{search ? 'Search' : tool ? 'Output' : 'Note'}</span><span className="exec-text" title={first}>{first}</span><time>{clock(message.createdAt)}</time><ChevronDown size={13} className="exec-chev" /></summary>
    <div className="exec-raw">{search ? <SearchPayloadView payload={search} /> : <Rich text={message.content} />}</div>
  </details>;
}

export function ActivityStream({ tasks, loading, onOpen, messages }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const hydrated = useRef(false);
  const programmatic = useRef(false);
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [paused, setPaused] = useState(false);
  const ordered = useMemo(() => tasks.map((t, i) => ({ t, i })).sort((a, b) => time(a.t.createdAt) - time(b.t.createdAt) || a.i - b.i).map((x) => x.t), [tasks]);
  const key = ordered.map((t) => `${t.id}:${t.status}:${t.logs?.length ?? 0}:${t.logs?.at(-1)?.message ?? ''}:${t.result?.length ?? 0}:${t.updatedAt}`).join('|') + `|m${messages?.length ?? 0}`;

  const toBottom = useCallback((smooth: boolean) => {
    const el = scroller.current;
    if (!el) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.cyberFx === 'off';
    programmatic.current = true;
    if (scrollTimer.current) clearTimeout(scrollTimer.current);
    el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reduced ? 'smooth' : 'auto' });
    scrollTimer.current = setTimeout(() => { programmatic.current = false; }, smooth && !reduced ? 800 : 0);
  }, []);
  const pauseFollow = useCallback(() => {
    programmatic.current = false;
    following.current = false;
    setPaused(true);
    if (scrollTimer.current) clearTimeout(scrollTimer.current);
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollTop, behavior: 'instant' });
  }, []);
  useEffect(() => () => { if (scrollTimer.current) clearTimeout(scrollTimer.current); }, []);

  useLayoutEffect(() => {
    if (loading) return;
    if (following.current) toBottom(hydrated.current);
    hydrated.current = true;
  }, [loading, key, toBottom]);

  useEffect(() => {
    if (loading) return;
    const el = scroller.current;
    if (!el || typeof ResizeObserver === 'undefined' || !el.firstElementChild) return;
    const ro = new ResizeObserver(() => { if (following.current && !programmatic.current) toBottom(false); });
    ro.observe(el.firstElementChild);
    return () => ro.disconnect();
  }, [loading, toBottom, ordered.length]);

  if (loading) return <div className="activity-stream exec-stream"><div className="exec-skeleton" aria-busy="true"><i /><i /><i /><i /></div></div>;
  if (!ordered.length) return <div className="activity-stream exec-stream"><div className="stream-empty"><Activity size={20} /><strong>Waiting for your first task</strong><span>Send a request below. Real execution steps will appear here.</span></div></div>;

  return <div className="exec-wrap">
    <div className="activity-stream exec-stream" ref={scroller} data-testid="activity-stream" tabIndex={0} onPointerDown={(e) => { if (e.clientX >= e.currentTarget.getBoundingClientRect().right - 16) pauseFollow(); }} onWheel={(e) => { if (e.deltaY < 0) pauseFollow(); }} onTouchStart={pauseFollow} onKeyDown={(e) => { if (['ArrowUp', 'PageUp', 'Home'].includes(e.key)) pauseFollow(); }} onScroll={(e) => {
      if (programmatic.current) return;
      const el = e.currentTarget;
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      following.current = near;
      setPaused((p) => (p === !near ? p : !near));
    }}><div className="exec-inner">
      {ordered.map((task) => {
        const live = isLive(task);
        const rows = rowsFor(task.logs ?? []);
        const extras = (messages ?? []).filter((m) => m.taskId === task.id && (m.role === 'tool' || m.isToolCall)).sort((a, b) => time(a.createdAt) - time(b.createdAt));
        const stepCount = rows.length + extras.length;
        const searchPayloads = extras.map((m) => parseSearchPayload(m.content)).filter((payload) => payload !== null);
        const sources = searchPayloads.flatMap((payload) => payload.results).filter((r, i, all) => r.url && all.findIndex((x) => x.url === r.url) === i);
        const sourceProviders = [...new Set(searchPayloads.map((payload) => payload.engine))];
        return <article className="stream-task exec-task" key={task.id} data-task-status={task.status} data-active={live ? 'true' : 'false'} data-testid={`stream-task-${task.id}`}>
          <div className="exec-user">
            <p className="exec-user-text">{task.objective}</p>
            <div className="exec-user-meta"><span>You</span><time>{clock(task.createdAt)}</time><span className="exec-status">{String(task.status)}</span><button type="button" className="exec-view" onClick={() => onOpen(task)} data-testid={`button-stream-task-${task.id}`}>View Details<ArrowRight size={12} /></button></div>
          </div>
          {(stepCount > 0 || (live && !task.result) || task.error) && <details className="exec-thinking" data-testid={`thinking-${task.id}`}>
            <summary><Brain size={14} /><span>Thinking ({stepCount} {stepCount === 1 ? 'step' : 'steps'})</span>{live && <span className="exec-working"><span className="exec-dot live" />Working</span>}<ChevronDown size={13} className="exec-chev" /></summary>
            <div className="exec-steps">{rows.map((r) => <Step key={r.log.id} row={r} />)}{extras.map((m) => <ToolOutput key={m.id} message={m} />)}</div>
            {live && task.currentStep && <div className="exec-pending"><span className="exec-dot live" />{clip(task.currentStep, 160)}</div>}
            {task.error && !rows.some((row) => row.log.kind === 'error' && row.log.message.includes(task.error!)) && <ErrorLine error={task.error} />}
          </details>}
          {task.error && <div className="exec-failure"><AlertCircle size={14} />Task failed. Open Thinking or View Details for the cause.</div>}
          {task.result && <div className="exec-result"><div className="exec-result-label">{live ? <><span className="exec-dot live" />Responding</> : <><CheckCircle2 size={14} />Forge</>}</div><Rich text={task.result} />{sources.length > 0 && <div className="exec-sources" data-testid={`sources-${task.id}`}><SourcesAccordion results={sources} providers={sourceProviders} limit={6} /></div>}</div>}
          {!rows.length && !task.result && !task.error && !task.currentStep && !live && <p className="stream-no-events">No execution updates yet.</p>}
        </article>;
      })}
    </div></div>
    {paused && <button type="button" className="exec-jump" onClick={() => { following.current = true; setPaused(false); toBottom(true); }} data-testid="button-jump-latest"><ArrowDown size={13} />Jump to latest</button>}
  </div>;
}
