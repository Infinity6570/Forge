import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Router as WouterRouter, Switch, useLocation } from 'wouter';
import {
  useAbortAssistantTask,
  useCreateAssistantNote,
  useCreateAssistantTask,
  useCreateAssistantTimer,
  useDeleteAssistantFile,
  useDeleteAssistantNote,
  useDeleteAssistantTimer,
  useGetAssistantDashboard,
  useGetAssistantTask,
  useGetWorkspacePreview,
  useListAssistantFiles,
  useListAssistantNotes,
  useListAssistantTasks,
  useListAssistantTimers,
  useStopWorkspacePreviewApp,
  getGetAssistantDashboardQueryKey,
  getGetAssistantTaskQueryKey,
  getGetWorkspacePreviewQueryKey,
  getListAssistantFilesQueryKey,
  getListAssistantNotesQueryKey,
  getListAssistantTasksQueryKey,
  getListAssistantTimersQueryKey,
} from '@workspace/api-client-react';
import type { AssistantFile, AssistantNote, AssistantTask, AssistantTimer, WorkspacePreviewApp } from '@workspace/api-client-react';
import {
  Activity, AlertCircle, ArrowDownToLine, ArrowRight, Bell, BookOpen, Check, CheckCircle2,
  CircleHelp, Clock3, ExternalLink, FileText, FolderOpen, Gauge, HardDrive, Layers3,
  KeyRound, LoaderCircle, LockKeyhole, Menu, MoreHorizontal, Plus, RefreshCw, Search,
  Send, Settings2, ShieldCheck, Sparkles, StopCircle, Trash2, Upload, X, Zap,
} from 'lucide-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient();
type Page = 'home' | 'tasks' | 'workspace' | 'settings';

const navItems: { href: string; label: string; icon: typeof Activity }[] = [
  { href: '/', label: 'Command center', icon: Gauge },
  { href: '/tasks', label: 'Task activity', icon: Activity },
  { href: '/workspace', label: 'Workspace', icon: FolderOpen },
  { href: '/settings', label: 'Preferences', icon: Settings2 },
];

function timeAgo(value?: string) {
  if (!value) return 'Just now';
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatDate(value?: string) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusTone(status: string) {
  if (status === 'running' || status === 'queued' || status === 'active') return 'live';
  if (status === 'completed' || status === 'fired') return 'done';
  if (status === 'failed' || status === 'cancelled') return 'issue';
  return 'neutral';
}

function StatusPill({ status }: { status: string }) {
  return <span className={`status-pill ${statusTone(status)}`} data-testid={`status-${status}`}>{status}</span>;
}

function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div className="skeleton-stack" aria-label="Loading"><div className="skeleton-line wide" />{Array.from({ length: rows }, (_, index) => <div className="skeleton-line" key={index} />)}</div>;
}

function QueryProblem({ retry, message = 'We couldn’t load this right now.' }: { retry: () => void; message?: string }) {
  return <div className="query-problem"><AlertCircle size={18} /><div><strong>Something interrupted the connection</strong><p>{message}</p></div><button className="button button-quiet button-small" onClick={retry} data-testid="button-retry"><RefreshCw size={14} /> Retry</button></div>;
}

function PageHeading({ eyebrow, title, description, right }: { eyebrow: string; title: string; description: string; right?: ReactNode }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1 className="font-display">{title}</h1><p className="page-description">{description}</p></div>{right && <div className="heading-actions">{right}</div>}</div>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal-card enter" role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><h2 className="font-display">{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog" data-testid="button-close-modal"><X size={18} /></button></div>{children}</section></div>;
}

function AppShell({ children, page }: { children: ReactNode; page: Page }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [location] = useLocation();
  const routePage = (location === '/' ? 'home' : location.slice(1)) as Page;
  const current = page || routePage;
  return <div className="app-frame shell-noise">
    <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Layers3 size={19} strokeWidth={2.3} /></div><div><div className="brand-name">Morrow</div><div className="brand-caption">PERSONAL AGENT</div></div><button className="sidebar-close icon-button" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={17} /></button></div>
      <div className="workspace-label">YOUR WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">{navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={`nav-link ${current === (href === '/' ? 'home' : href.slice(1)) ? 'active' : ''}`} onClick={() => setMobileOpen(false)} data-testid={`link-nav-${href === '/' ? 'home' : href.slice(1)}`}><Icon size={17} /><span>{label}</span>{href === '/tasks' && <span className="nav-trailing"><span className="nav-dot" /></span>}</Link>)}</nav>
      <div className="side-divider" />
      <div className="sidebar-section-title">QUICK STATUS</div>
      <QuickSidebarStatus />
      <div className="sidebar-spacer" />
      <div className="agent-card"><div className="agent-orbit"><span /><i /></div><div className="agent-card-copy"><strong>Your agent is ready</strong><span>Waiting for direction</span></div><span className="ready-indicator" /></div>
      <div className="sidebar-bottom"><div className="user-avatar">M</div><div className="user-meta"><strong>My workspace</strong><span>Personal account</span></div><button className="icon-button user-menu" aria-label="Account options" onClick={() => window.dispatchEvent(new Event('morrow:account'))}><MoreHorizontal size={18} /></button></div>
    </aside>
    {mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu" />}
    <main className="main-area">
      <header className="topbar"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={20} /></button><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{navItems.find((n) => (n.href === '/' ? 'home' : n.href.slice(1)) === current)?.label ?? 'Overview'}</strong></div><div className="topbar-right"><div className="system-online"><span className="online-pip" />All systems operational</div><button className="topbar-icon" aria-label="Help" onClick={() => window.alert('Your agent can help with documents, reminders, research, and code-related work.')} data-testid="button-help"><CircleHelp size={18} /></button><div className="topbar-avatar">M</div></div></header>
      <div className="page-wrap">{children}</div>
      <footer className="app-footer"><span>Made for thoughtful delegation.</span><span className="footer-build">MORROW <span>·</span> PERSONAL COMMAND CENTER</span></footer>
    </main>
  </div>;
}

function QuickSidebarStatus() {
  const { data, isLoading } = useGetAssistantDashboard();
  return <div className="quick-status">
    <div><span className="quick-status-icon"><Activity size={14} /></span><span>In progress</span><strong>{isLoading ? '—' : data?.activeTasks ?? 0}</strong></div>
    <div><span className="quick-status-icon amber"><Bell size={14} /></span><span>Reminders</span><strong>{isLoading ? '—' : data?.activeTimers ?? 0}</strong></div>
  </div>;
}

function ReminderNotifications() {
  const [notice, setNotice] = useState<{ id: string; label: string }>();
  const seen = useRef(new Set<string>());
  const audio = useRef<AudioContext | undefined>(undefined);
  useEffect(() => {
    const unlockAudio = () => {
      if (!audio.current && window.AudioContext) audio.current = new AudioContext();
      if (audio.current?.state === 'suspended') void audio.current.resume();
    };
    window.addEventListener('pointerdown', unlockAudio, { once: true });
    const poll = async () => {
      try {
        const response = await fetch('/api/assistant/timers');
        if (!response.ok) return;
        const timers = await response.json() as AssistantTimer[];
        for (const timer of timers) {
          const justFired = Date.now() - new Date(timer.scheduledFor).getTime() < 5 * 60_000;
          if (timer.status !== 'fired' || !justFired || seen.current.has(timer.id)) continue;
          seen.current.add(timer.id);
          setNotice({ id: timer.id, label: timer.label });
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Assistant reminder', { body: timer.label });
          }
          if (audio.current) {
            try {
              await audio.current.resume();
              const oscillator = audio.current.createOscillator();
              const gain = audio.current.createGain();
              oscillator.type = 'sine';
              oscillator.frequency.value = 740;
              gain.gain.value = 0.16;
              oscillator.connect(gain);
              gain.connect(audio.current.destination);
              oscillator.start();
              oscillator.stop(audio.current.currentTime + 0.45);
            } catch { /* Browsers may block audio until the user interacts. */ }
          }
          window.setTimeout(() => setNotice((current) => current?.id === timer.id ? undefined : current), 10_000);
        }
      } catch { /* Timer polling is best effort; the reminder list remains available. */ }
    };
    void poll();
    const interval = window.setInterval(() => { void poll(); }, 4_000);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('pointerdown', unlockAudio);
      void audio.current?.close();
    };
  }, []);
  if (!notice) return null;
  return <div className="reminder-toast" role="alert" aria-live="assertive"><span className="reminder-toast-icon"><Bell size={17} /></span><div><strong>Reminder</strong><span>{notice.label}</span></div><button className="icon-button" aria-label="Dismiss reminder alert" onClick={() => setNotice(undefined)}><X size={16} /></button></div>;
}

function TaskStatusLine({ task, compact = false, onClick }: { task: AssistantTask; compact?: boolean; onClick?: () => void }) {
  return <button className={`task-row ${compact ? 'compact' : ''}`} onClick={onClick} data-testid={`button-task-${task.id}`}>
    <span className={`task-symbol ${statusTone(task.status)}`}>{task.status === 'completed' ? <Check size={14} /> : task.status === 'failed' ? <AlertCircle size={14} /> : task.status === 'cancelled' ? <StopCircle size={14} /> : <span className="tiny-spinner" />}</span>
    <span className="task-row-main"><strong>{task.objective}</strong><span>{task.currentStep || task.result || task.error || (task.status === 'queued' ? 'Queued for the agent' : 'Task updated')} </span></span>
    <span className="task-row-side"><StatusPill status={task.status} /><time>{timeAgo(task.updatedAt)}</time></span>
    {!compact && <ArrowRight className="task-arrow" size={15} />}
  </button>;
}

function Dashboard() {
  const qc = useQueryClient();
  const summary = useGetAssistantDashboard();
  const listTasks = useListAssistantTasks();
  const createTask = useCreateAssistantTask();
  const [objective, setObjective] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const details = useGetAssistantTask(selectedTaskId ?? '', { query: { enabled: !!selectedTaskId, queryKey: getGetAssistantTaskQueryKey(selectedTaskId ?? ''), refetchInterval: (query) => {
    const task = query.state.data;
    return task && ['queued', 'running'].includes(task.status) ? 2500 : false;
  } } });
  const abort = useAbortAssistantTask();
  const tasks = summary.data?.recentTasks ?? listTasks.data ?? [];
  const isPending = createTask.isPending;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = objective.trim();
    if (!text) return;
    setSubmitError('');
    createTask.mutate({ data: { objective: text } }, {
      onSuccess: (task) => {
        setObjective('');
        setSelectedTaskId(task.id);
        qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
        qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
      },
      onError: () => setSubmitError('Your request could not be sent. Please try again.'),
    });
  };
  const counts = [
    { label: 'In motion', value: summary.data?.activeTasks, icon: Activity, tint: 'teal', note: 'tasks running now' },
    { label: 'Completed', value: summary.data?.completedTasks, icon: CheckCircle2, tint: 'blue', note: 'outcomes delivered' },
    { label: 'Reminders', value: summary.data?.activeTimers, icon: Bell, tint: 'amber', note: 'upcoming or active' },
    { label: 'Knowledge', value: (summary.data?.notesCount ?? 0) + (summary.data?.filesCount ?? 0), icon: BookOpen, tint: 'plum', note: `${summary.data?.notesCount ?? 0} notes · ${summary.data?.filesCount ?? 0} files` },
  ];
  return <AppShell page="home"><div className="dashboard-page enter">
    <div className="welcome-row"><div><p className="eyebrow">YOUR COMMAND CENTER</p><h1 className="font-display">Make room for<br /><em>the work that matters.</em></h1><p className="page-description">Give your agent the busywork. Keep your attention for the big picture.</p></div><div className="welcome-stamp"><div className="stamp-orbit"><span /><i /></div><span>AGENT<br />STANDBY</span></div></div>
    <section className="composer-panel">
      <div className="composer-heading"><span className="composer-icon"><Sparkles size={16} /></span><div><strong>What should I take care of?</strong><span>Documents, research, reminders, or code tasks</span></div><span className="composer-shortcut">⌘ ↵</span></div>
      <form onSubmit={submit}><textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="For example: Compare these two proposals and summarize the trade-offs…" maxLength={12000} rows={2} data-testid="input-objective" aria-label="Task objective" /><div className="composer-bottom"><span>{submitError ? <span className="field-error">{submitError}</span> : <span>Be specific. Your agent will show its work as it goes.</span>}<span className="char-count">{objective.length.toLocaleString()} / 12,000</span></span><button className="button button-primary submit-button" disabled={!objective.trim() || isPending} data-testid="button-submit-task">{isPending ? <LoaderCircle className="spin" size={16} /> : <Send size={15} />}{isPending ? 'Sending…' : 'Send to agent'}</button></div></form>
    </section>
    {summary.isError && <QueryProblem retry={() => summary.refetch()} message="Your overview is temporarily unavailable." />}
    <section className="stat-grid stagger" aria-label="Workspace summary">{counts.map(({ label, value, icon: Icon, tint, note }) => <article className="stat-card" key={label} data-testid={`stat-${label.toLowerCase().replaceAll(' ', '-')}`}><div className={`stat-icon ${tint}`}><Icon size={17} /></div><div className="stat-label">{label}</div><div className="stat-number">{summary.isLoading ? <span className="number-skeleton" /> : value ?? 0}</div><div className="stat-note">{note}</div></article>)}</section>
    <section className="dashboard-lower">
      <div className="panel recent-panel"><div className="panel-heading"><div><p className="eyebrow">LATEST ACTIVITY</p><h2 className="font-display">Recent tasks</h2></div><Link href="/tasks" className="text-link" data-testid="link-all-tasks">See all <ArrowRight size={14} /></Link></div>
        {summary.isLoading && listTasks.isLoading ? <Skeleton rows={4} /> : listTasks.isError && !summary.data ? <QueryProblem retry={() => listTasks.refetch()} /> : tasks.length ? <div className="task-list">{tasks.slice(0, 5).map((task) => <TaskStatusLine key={task.id} task={task} compact onClick={() => setSelectedTaskId(task.id)} />)}</div> : <div className="empty-state compact-empty"><div className="empty-mark"><Zap size={18} /></div><strong>A clear desk</strong><p>Your agent’s work will show up here.</p></div>}
      </div>
      <div className="right-rail">
        <div className="focus-card"><div className="focus-kicker"><span className="online-pip" />READY WHEN YOU ARE</div><h2 className="font-display">One clear<br />request at a time.</h2><p>Tasks stay visible from first step to final result. You’re always in control.</p><div className="focus-rule" /><Link href="/settings" className="focus-link" data-testid="link-safety-controls">Explore safety controls <ArrowRight size={14} /></Link></div>
        <div className="mini-resource"><div className="mini-resource-top"><span className="mini-resource-icon"><HardDrive size={16} /></span><span>Workspace library</span><ArrowRight size={14} /></div><strong>{summary.data?.filesCount ?? 0} files <i /> {summary.data?.notesCount ?? 0} notes</strong><Link href="/workspace" className="mini-resource-link" data-testid="link-open-workspace">Browse saved material</Link></div>
      </div>
    </section>
    {selectedTaskId && <TaskDetailDialog task={details.data} loading={details.isLoading} error={details.isError} retry={() => details.refetch()} close={() => setSelectedTaskId(undefined)} abort={(id) => abort.mutate({ id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() }); } })} aborting={abort.isPending} />}
  </div></AppShell>;
}

function TaskDetailDialog({ task, loading, error, retry, close, abort, aborting }: { task?: AssistantTask; loading: boolean; error: boolean; retry: () => void; close: () => void; abort: (id: string) => void; aborting: boolean }) {
  return <Modal title="Task details" onClose={close}>{loading ? <Skeleton rows={5} /> : error || !task ? <QueryProblem retry={retry} /> : <div className="detail-content"><div className="detail-objective"><StatusPill status={task.status} /><h3>{task.objective}</h3><p>Started {formatDate(task.createdAt)} <span>·</span> Updated {timeAgo(task.updatedAt)}</p></div>
    <p className="settings-footnote">Model used: <strong>{task.modelId}</strong></p>
    {task.currentStep && <div className="current-step"><span className="tiny-spinner" /><div><small>CURRENT STEP</small><strong>{task.currentStep}</strong></div></div>}
    {task.result && <div className="outcome-box"><strong><CheckCircle2 size={16} /> Outcome</strong><p>{task.result}</p></div>}
    {task.error && <div className="error-box"><strong><AlertCircle size={16} /> What happened</strong><p>{task.error}</p></div>}
    <div className="log-heading"><strong>Execution log</strong><span>{task.logs?.length ?? 0} entries</span></div>
    <div className="log-list">{task.logs?.length ? task.logs.map((log) => <div className="log-item" key={log.id}><span className={`log-dot ${log.kind}`} /><div><div className="log-meta"><strong>{log.kind}</strong><time>{formatDate(log.createdAt)}</time></div><p>{log.message}</p></div></div>) : <div className="log-empty">No execution updates yet. This view refreshes while your task is active.</div>}</div>
    <div className="modal-actions"><button className="button button-quiet" onClick={close}>Close</button>{['queued', 'running'].includes(task.status) && <button className="button button-danger" onClick={() => abort(task.id)} disabled={aborting} data-testid="button-abort-task"><StopCircle size={15} />{aborting ? 'Stopping…' : 'Stop task'}</button>}</div>
  </div>}</Modal>;
}

function TasksPage() {
  const qc = useQueryClient();
  const tasksQuery = useListAssistantTasks();
  const [selected, setSelected] = useState<string>();
  const detail = useGetAssistantTask(selected ?? '', { query: { enabled: !!selected, queryKey: getGetAssistantTaskQueryKey(selected ?? ''), refetchInterval: (query) => {
    const item = query.state.data;
    return item && ['running', 'queued'].includes(item.status) ? 2500 : false;
  } } });
  const abort = useAbortAssistantTask();
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const options = ['all', 'running', 'queued', 'completed', 'failed', 'cancelled'];
  const tasks = useMemo(() => (tasksQuery.data ?? []).filter((task) => (filter === 'all' || task.status === filter) && task.objective.toLowerCase().includes(search.toLowerCase())), [tasksQuery.data, filter, search]);
  return <AppShell page="tasks"><div className="content-page enter">
    <PageHeading eyebrow="EXECUTION LOG" title="Task activity" description="A clear view of every request, from first thought to finished result." right={<Link href="/" className="button button-primary" data-testid="link-new-task"><Plus size={16} /> New task</Link>} />
    <div className="task-overview-strip"><div><span className="strip-icon"><Activity size={17} /></span><div><strong>Every step, in view</strong><span>Open any task to follow its execution log.</span></div></div><span className="live-label"><span className="online-pip" />LIVE UPDATES</span></div>
    <section className="panel tasks-table-panel"><div className="list-toolbar"><div className="filter-pills">{options.map((option) => <button key={option} onClick={() => setFilter(option)} className={`filter-pill ${filter === option ? 'selected' : ''}`} data-testid={`filter-task-${option}`}>{option === 'all' ? 'All tasks' : option}</button>)}</div><label className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tasks" aria-label="Search tasks" data-testid="input-search-tasks" /></label></div>
      {tasksQuery.isLoading ? <div className="table-loading"><Skeleton rows={7} /></div> : tasksQuery.isError ? <QueryProblem retry={() => tasksQuery.refetch()} /> : tasks.length ? <div className="full-task-list">{tasks.map((task) => <TaskStatusLine key={task.id} task={task} onClick={() => setSelected(task.id)} />)}</div> : <div className="empty-state"><div className="empty-mark"><Activity size={20} /></div><strong>{search || filter !== 'all' ? 'No matching tasks' : 'Nothing in the queue'}</strong><p>{search || filter !== 'all' ? 'Try another search or status filter.' : 'Send your first request and watch the work unfold here.'}</p>{!search && filter === 'all' && <Link href="/" className="button button-primary button-small" data-testid="link-first-task"><Plus size={14} /> Create a task</Link>}</div>}
    </section>
    {selected && <TaskDetailDialog task={detail.data} loading={detail.isLoading} error={detail.isError} retry={() => detail.refetch()} close={() => setSelected(undefined)} abort={(id) => abort.mutate({ id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } })} aborting={abort.isPending} />}
  </div></AppShell>;
}

function safePreviewUrl(value?: string | null) {
  if (!value) return '';
  try {
    const parsed = new URL(value, window.location.origin);
    return parsed.origin === window.location.origin && (parsed.protocol === 'http:' || parsed.protocol === 'https:') ? parsed.href : '';
  } catch {
    return '';
  }
}

function WorkspacePreview() {
  const qc = useQueryClient();
  const previewQuery = useGetWorkspacePreview({
    query: { queryKey: getGetWorkspacePreviewQueryKey(), staleTime: 0, refetchOnMount: 'always', refetchInterval: 15000 },
  });
  const stopApp = useStopWorkspacePreviewApp();
  const [selectedId, setSelectedId] = useState('static');
  const [refreshKey, setRefreshKey] = useState(0);
  const preview = previewQuery.data;
  const apps = preview?.apps ?? [];
  const selectionExists = selectedId === 'static' ? !!preview?.staticAvailable : apps.some((app) => app.id === selectedId);
  const activeId = selectionExists ? selectedId : preview?.staticAvailable ? 'static' : apps[0]?.id ?? '';
  const activeApp = apps.find((app) => app.id === activeId);
  const rawUrl = activeId === 'static' ? preview?.staticPreviewUrl : activeApp?.previewUrl;
  const iframeUrl = safePreviewUrl(rawUrl);
  const label = activeId === 'static' ? 'Workspace preview' : activeApp?.entryPath ?? 'Running app';
  const onStop = (app: WorkspacePreviewApp) => {
    if (!window.confirm(`Stop the ${app.framework} preview at ${app.entryPath}?`)) return;
    stopApp.mutate({ data: { appId: app.id } }, {
      onSuccess: async (status) => {
        qc.setQueryData(getGetWorkspacePreviewQueryKey(), status);
        setSelectedId(status.staticAvailable ? 'static' : status.apps[0]?.id ?? '');
        await qc.invalidateQueries({ queryKey: getGetWorkspacePreviewQueryKey() });
      },
      onError: () => undefined,
    });
  };

  return <section className="preview-workspace" aria-label="Live app previews" data-testid="workspace-live-preview">
    <div className="preview-toolbar">
      <div className="preview-view-label"><span className="preview-status-dot" /><div><strong>Live preview</strong><span>Private workspace · updates every 15 seconds</span></div></div>
      <button className="button button-quiet button-small" onClick={() => { setRefreshKey((n) => n + 1); void previewQuery.refetch(); }} disabled={previewQuery.isFetching} data-testid="button-refresh-preview"><RefreshCw size={14} className={previewQuery.isFetching ? 'preview-spinning' : ''} />{previewQuery.isFetching ? 'Refreshing' : 'Refresh'}</button>
    </div>
    {previewQuery.isLoading ? <div className="preview-loading" aria-label="Loading previews"><div className="preview-loading-bar" /><div className="preview-loading-stage" /></div>
      : previewQuery.isError ? <div className="preview-state preview-error"><div className="preview-state-icon"><AlertCircle size={20} /></div><strong>Preview status is unavailable</strong><p>We couldn’t reach the workspace preview service.</p><button className="button button-primary button-small" onClick={() => void previewQuery.refetch()} data-testid="button-retry-preview"><RefreshCw size={14} /> Try again</button></div>
      : !preview?.staticAvailable && apps.length === 0 ? <div className="preview-state preview-empty"><div className="preview-empty-art"><span /><span /><span /></div><strong>No app previews yet</strong><p>When your agent builds a small app or a static workspace, it will appear here.</p></div>
      : <>
        <div className="preview-controls">
          <div className="preview-choices" role="group" aria-label="Choose a preview">
            {preview?.staticAvailable && <button className={`preview-choice ${activeId === 'static' ? 'selected' : ''}`} onClick={() => setSelectedId('static')} aria-pressed={activeId === 'static'} data-testid="preview-choice-static"><span className="choice-symbol">S</span><span><strong>Workspace</strong><small>{preview.staticEntryPath || 'Static site'}</small></span></button>}
            {apps.map((app) => <div className={`preview-choice-wrap ${activeId === app.id ? 'selected' : ''}`} key={app.id}>
              <button className={`preview-choice ${activeId === app.id ? 'selected' : ''}`} onClick={() => setSelectedId(app.id)} aria-pressed={activeId === app.id} data-testid={`preview-choice-app-${app.id}`}><span className="choice-symbol app-symbol">{app.framework.slice(0, 1).toUpperCase()}</span><span><strong>{app.framework}</strong><small>{app.entryPath}</small></span></button>
              <button className="preview-stop" aria-label={`Stop ${app.framework} preview`} title="Stop app" disabled={stopApp.isPending} onClick={() => onStop(app)} data-testid={`button-stop-preview-${app.id}`}><StopCircle size={15} /></button>
            </div>)}
          </div>
          {activeApp && <div className="preview-app-meta"><span className="preview-status-dot" /> Running on port {activeApp.port} <span className="preview-meta-divider" /> Started {timeAgo(activeApp.startedAt)}</div>}
        </div>
        <div className="preview-address-row">
          <div className="preview-address" aria-label="Preview URL" data-testid="text-preview-address"><span className="address-lock"><ShieldCheck size={14} /></span><span className="address-host">{iframeUrl ? new URL(iframeUrl).host : 'Preview URL unavailable'}</span><span className="address-path">{iframeUrl ? new URL(iframeUrl).pathname : 'The supplied address is not a safe same-origin URL'}</span></div>
          {iframeUrl && <a className="button button-quiet button-small preview-open" href={iframeUrl} target="_blank" rel="noopener noreferrer" data-testid="link-open-preview"><ExternalLink size={14} /> Open in New Tab</a>}
        </div>
        <div className="preview-frame-shell" data-testid="preview-frame-shell">
          {iframeUrl ? <iframe key={`${activeId}-${refreshKey}-${iframeUrl}`} title={`${label} live preview`} className="preview-frame" src={iframeUrl} sandbox="allow-scripts allow-forms" referrerPolicy="same-origin" data-testid="iframe-live-preview" />
            : <div className="preview-state preview-unavailable"><div className="preview-state-icon"><LockKeyhole size={19} /></div><strong>This preview address can’t be opened safely</strong><p>Only workspace addresses on this site can be loaded here.</p></div>}
        </div>
      </>}
    {stopApp.isError && <div className="preview-stop-error" role="alert" data-testid="status-stop-preview-error">The app could not be stopped. Refresh the preview list and try again.</div>}
  </section>;
}

function WorkspacePage() {
  const qc = useQueryClient();
  const notesQuery = useListAssistantNotes();
  const filesQuery = useListAssistantFiles();
  const createNote = useCreateAssistantNote();
  const deleteNote = useDeleteAssistantNote();
  const deleteFile = useDeleteAssistantFile();
  const [tab, setTab] = useState<'files' | 'notes' | 'preview'>('files');
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');
  const [noteTags, setNoteTags] = useState('');
  const [noteError, setNoteError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [selectedFile, setSelectedFile] = useState<AssistantFile>();
  const [search, setSearch] = useState('');
  const filteredNotes = (notesQuery.data ?? []).filter((n) => `${n.title} ${n.content} ${n.tags.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  const filteredFiles = (filesQuery.data ?? []).filter((f) => f.name.toLowerCase().includes(search.toLowerCase()));
  const onUpload = async (file?: File) => {
    if (!file) return;
    setUploading(true); setUploadError('');
    try {
      const body = new FormData();
      body.append('file', file);
      const response = await fetch('/api/assistant/files', { method: 'POST', body, credentials: 'include' });
      if (!response.ok) throw new Error('Upload failed');
      await qc.invalidateQueries({ queryKey: getListAssistantFilesQueryKey() });
      await qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
    } catch {
      setUploadError('This file could not be uploaded. Check the file and try again.');
    } finally { setUploading(false); }
  };
  const saveNote = (event: FormEvent) => {
    event.preventDefault(); setNoteError('');
    if (!noteTitle.trim()) { setNoteError('Give your note a title before saving.'); return; }
    createNote.mutate({ data: { title: noteTitle.trim(), content: noteContent, tags: noteTags.split(',').map((x) => x.trim()).filter(Boolean) } }, {
      onSuccess: () => { setNoteOpen(false); setNoteTitle(''); setNoteContent(''); setNoteTags(''); qc.invalidateQueries({ queryKey: getListAssistantNotesQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); },
      onError: () => setNoteError('We couldn’t save this note. Please try again.'),
    });
  };
  const removeNote = (note: AssistantNote) => { if (window.confirm(`Delete “${note.title}”? This cannot be undone.`)) deleteNote.mutate({ id: note.id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantNotesQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } }); };
  const removeFile = (file: AssistantFile) => { if (window.confirm(`Delete “${file.name}”? This cannot be undone.`)) deleteFile.mutate({ id: file.id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantFilesQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } }); };
  return <AppShell page="workspace"><div className="content-page enter">
    <PageHeading eyebrow="REFERENCE LIBRARY" title="Workspace" description="Files and notes your agent can draw on when the context matters." right={<><a className="button button-quiet" href="/api/assistant/workspace.zip" download data-testid="button-download-workspace"><ArrowDownToLine size={15} /> Download ZIP</a><label className={`button button-quiet ${uploading ? 'disabled' : ''}`} htmlFor="workspace-upload" data-testid="button-upload-file"><Upload size={15} />{uploading ? 'Uploading…' : 'Upload file'}<input id="workspace-upload" type="file" hidden disabled={uploading} onChange={(e) => { void onUpload(e.currentTarget.files?.[0]); e.currentTarget.value = ''; }} /></label><button className="button button-primary" onClick={() => setNoteOpen(true)} data-testid="button-new-note"><Plus size={16} /> New note</button></>} />
    <div className="library-intro"><div className="library-graphic"><div className="graphic-file"><FileText size={22} /></div><div className="graphic-note"><BookOpen size={19} /></div><div className="graphic-orbit" /></div><div><strong>A little context goes a long way.</strong><p>Keep source material and useful details close. Your agent can reference uploaded files and saved notes in future work.</p></div></div>
    {uploadError && <div className="inline-error"><AlertCircle size={15} />{uploadError}<button onClick={() => setUploadError('')} aria-label="Dismiss upload error"><X size={14} /></button></div>}
    <section className="panel library-panel"><div className="library-toolbar"><div className="library-tabs"><button onClick={() => setTab('files')} className={tab === 'files' ? 'active' : ''} data-testid="tab-files"><FileText size={15} /> Files <span>{filesQuery.data?.length ?? 0}</span></button><button onClick={() => setTab('notes')} className={tab === 'notes' ? 'active' : ''} data-testid="tab-notes"><BookOpen size={15} /> Notes <span>{notesQuery.data?.length ?? 0}</span></button><button onClick={() => setTab('preview')} className={tab === 'preview' ? 'active' : ''} data-testid="tab-live-preview"><Layers3 size={15} /> Live Preview</button></div>{tab !== 'preview' && <label className="search-box"><Search size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={`Search ${tab}`} aria-label={`Search ${tab}`} data-testid="input-search-library" /></label>}</div>
      {tab === 'preview' ? <WorkspacePreview /> : <>
      {tab === 'files' ? filesQuery.isLoading ? <div className="library-loading"><Skeleton rows={4} /></div> : filesQuery.isError ? <QueryProblem retry={() => filesQuery.refetch()} /> : filteredFiles.length ? <div className="file-list">{filteredFiles.map((file) => <div className="file-row" key={file.id}><span className="file-type-icon"><FileText size={18} /></span><div className="file-main"><strong>{file.name}</strong><span>{file.mimeType || 'Document'} <i /> {formatSize(file.sizeBytes)}</span></div><span className="file-added">{timeAgo(file.createdAt)}</span><div className="row-actions"><button onClick={() => setSelectedFile(file)} className="icon-button" aria-label={`Preview ${file.name}`} data-testid={`button-preview-file-${file.id}`}><ArrowDownToLine size={16} /></button><button onClick={() => removeFile(file)} className="icon-button danger-hover" aria-label={`Delete ${file.name}`} data-testid={`button-delete-file-${file.id}`}><Trash2 size={16} /></button></div></div>)}</div> : <div className="empty-state"><div className="empty-mark"><Upload size={19} /></div><strong>{search ? 'No files found' : 'Start with a source file'}</strong><p>{search ? 'Try a different name.' : 'Upload a document, PDF, or text file to give your agent context.'}</p>{!search && <label htmlFor="workspace-upload" className="button button-primary button-small"><Upload size={14} /> Upload your first file</label>}</div>
      : notesQuery.isLoading ? <div className="library-loading"><Skeleton rows={4} /></div> : notesQuery.isError ? <QueryProblem retry={() => notesQuery.refetch()} /> : filteredNotes.length ? <div className="note-grid">{filteredNotes.map((note) => <article className="note-card" key={note.id}><div className="note-card-top"><span className="note-glyph"><BookOpen size={15} /></span><button className="icon-button danger-hover" aria-label={`Delete ${note.title}`} onClick={() => removeNote(note)} data-testid={`button-delete-note-${note.id}`}><Trash2 size={15} /></button></div><h3>{note.title}</h3><p>{note.content || 'An empty note, ready for useful context.'}</p><div className="note-tags">{note.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><div className="note-card-foot">UPDATED {timeAgo(note.updatedAt).toUpperCase()}</div></article>)}</div> : <div className="empty-state"><div className="empty-mark"><BookOpen size={19} /></div><strong>{search ? 'No notes found' : 'Nothing noted yet'}</strong><p>{search ? 'Try another search.' : 'Save a detail you want your agent to remember.'}</p>{!search && <button className="button button-primary button-small" onClick={() => setNoteOpen(true)} data-testid="button-first-note"><Plus size={14} /> Write a note</button>}</div>}
      </>}
    </section>
    {noteOpen && <Modal title="Save a note" onClose={() => setNoteOpen(false)}><form className="form-stack" onSubmit={saveNote}><label className="form-label">Title<input value={noteTitle} onChange={(e) => setNoteTitle(e.target.value)} maxLength={300} placeholder="A detail worth remembering" autoFocus data-testid="input-note-title" /></label><label className="form-label">Note<textarea value={noteContent} onChange={(e) => setNoteContent(e.target.value)} maxLength={200000} rows={5} placeholder="Add context, a useful fact, or a thought to keep nearby…" data-testid="input-note-content" /></label><label className="form-label">Tags <span className="optional-label">optional, comma separated</span><input value={noteTags} onChange={(e) => setNoteTags(e.target.value)} placeholder="research, project, follow-up" data-testid="input-note-tags" /></label>{noteError && <p className="field-error">{noteError}</p>}<div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setNoteOpen(false)}>Cancel</button><button className="button button-primary" disabled={createNote.isPending} data-testid="button-save-note">{createNote.isPending ? 'Saving…' : <><Check size={15} /> Save note</>}</button></div></form></Modal>}
    {selectedFile && <Modal title={selectedFile.name} onClose={() => setSelectedFile(undefined)}><div className="file-preview-meta"><span>{selectedFile.mimeType || 'File'}</span><span>{formatSize(selectedFile.sizeBytes)}</span><span>Added {formatDate(selectedFile.createdAt)}</span></div><div className="extracted-text">{selectedFile.extractedText || 'There is no extracted text available for this file.'}</div><div className="modal-actions"><button className="button button-quiet" onClick={() => setSelectedFile(undefined)}>Close</button></div></Modal>}
  </div></AppShell>;
}

const GEMINI_MODEL_IDS = new Set([
  'gemini-2.5-flash',
  'gemini-2.5-pro',
  'gemini-2.5-flash-lite',
  'gemini-3.5-flash-lite',
  'gemini-3.8-flash',
]);

function SettingsPage() {
  const [provider, setProvider] = useState<'openai' | 'gemini' | 'openrouter'>('openai');
  const [modelId, setModelId] = useState('gpt-4.1-mini');
  const [customModelId, setCustomModelId] = useState('');
  const [fallbackModelId, setFallbackModelId] = useState('');
  const [credentialStatus, setCredentialStatus] = useState<{
    provider: 'openai' | 'gemini' | 'openrouter';
    modelId: string;
    localSetupAllowed: boolean;
    providerSettingsAllowed: boolean;
    hasOpenaiKey: boolean;
    hasGeminiKey: boolean;
    hasOpenrouterKey: boolean;
    codeRunnerEnabled: boolean;
  }>();
  const [providerModalOpen, setProviderModalOpen] = useState(false);
  const [apiKeys, setApiKeys] = useState({ openaiApiKey: '', geminiApiKey: '', openrouterApiKey: '' });
  const [codeRunnerEnabled, setCodeRunnerEnabled] = useState(false);
  const [providerSaving, setProviderSaving] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [providerSaved, setProviderSaved] = useState(false);
  const [confirmBeforeActions, setConfirmBeforeActions] = useState(true);
  const [allowExternalResearch, setAllowExternalResearch] = useState(true);
  const [includeFiles, setIncludeFiles] = useState(true);
  const [saved, setSaved] = useState(false);
  const onSetting = (setter: (value: boolean) => void, value: boolean) => { setter(value); setSaved(false); };
  const models = {
    openai: [
      { id: 'gpt-4.1-mini', name: 'GPT-4.1 mini', detail: 'A fast general-purpose model.', descriptor: 'BALANCED', color: 'sage' },
      { id: 'gpt-4.1', name: 'GPT-4.1', detail: 'More capacity for complex tasks.', descriptor: 'DEEP FOCUS', color: 'gold' },
      { id: 'gpt-4.1-nano', name: 'GPT-4.1 nano', detail: 'A lighter option for quick work.', descriptor: 'QUICK', color: 'blue' },
    ],
    gemini: [
      { id: 'gemini-2.5-flash', name: 'gemini-2.5-flash', detail: 'Default · Balanced', descriptor: 'BALANCED', color: 'sage' },
      { id: 'gemini-2.5-pro', name: 'gemini-2.5-pro', detail: 'High reasoning', descriptor: 'DEEP FOCUS', color: 'gold' },
      { id: 'gemini-2.5-flash-lite', name: 'gemini-2.5-flash-lite', detail: 'Cost-effective · Reliable fallback', descriptor: 'QUICK', color: 'blue' },
      { id: 'gemini-3.5-flash-lite', name: 'gemini-3.5-flash-lite', detail: 'Ultra-fast · High throughput', descriptor: 'QUICK', color: 'blue' },
      { id: 'gemini-3.8-flash', name: 'gemini-3.8-flash', detail: 'Latest agentic and coding model', descriptor: 'DEEP FOCUS', color: 'gold' },
    ],
    openrouter: [
      { id: 'anthropic/claude-haiku-5.5', name: 'Claude Haiku 5.5', detail: 'A fast model for everyday tasks.', descriptor: 'QUICK', color: 'blue' },
      { id: 'anthropic/claude-sonnet-5.5', name: 'Claude Sonnet 5.5', detail: 'A balanced model for broader work.', descriptor: 'BALANCED', color: 'sage' },
      { id: 'anthropic/claude-opus-5.5', name: 'Claude Opus 5.5', detail: 'More capacity for demanding tasks.', descriptor: 'DEEP FOCUS', color: 'gold' },
    ],
  };
  useEffect(() => {
    let active = true;
    fetch('/api/assistant/settings')
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load provider settings.');
        return response.json();
      })
      .then((data) => {
        if (!active) return;
        setCredentialStatus(data);
        setProvider(data.provider);
        setModelId(data.modelId);
        setFallbackModelId(data.fallbackModelId ?? '');
        setCustomModelId(data.provider === 'gemini' && !GEMINI_MODEL_IDS.has(data.modelId) ? data.modelId : '');
        setCodeRunnerEnabled(data.codeRunnerEnabled);
      })
      .catch(() => {
        if (active) setProviderError('Provider settings could not be loaded.');
      });
    return () => { active = false; };
  }, []);
  const activeModels = models[provider];
  const configured = provider === 'openai'
    ? credentialStatus?.hasOpenaiKey
    : provider === 'gemini'
      ? credentialStatus?.hasGeminiKey
      : credentialStatus?.hasOpenrouterKey;
  const saveProviderSettings = async () => {
    setProviderSaving(true);
    setProviderError('');
    setProviderSaved(false);
    const selectedModelId = provider === 'gemini' && customModelId.trim() ? customModelId.trim() : modelId;
    const payload: Record<string, unknown> = { provider, modelId: selectedModelId, codeRunnerEnabled };
    if (provider === 'gemini') payload.fallbackModelId = fallbackModelId.trim();
    for (const [field, value] of Object.entries(apiKeys)) {
      if (value.trim()) payload[field] = value.trim();
    }
    try {
      const response = await fetch('/api/assistant/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Settings could not be saved.');
      setCredentialStatus(result);
      setModelId(selectedModelId);
      setApiKeys({ openaiApiKey: '', geminiApiKey: '', openrouterApiKey: '' });
      setProviderSaved(true);
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : 'Settings could not be saved.');
    } finally {
      setProviderSaving(false);
    }
  };
  return <AppShell page="settings"><div className="content-page settings-page enter">
    <PageHeading eyebrow="AGENT CONFIGURATION" title="Preferences" description="Choose how your agent works and where it should pause for your approval." />
    <section className="settings-section model-section"><div className="settings-section-heading"><div className="section-symbol"><Zap size={17} /></div><div><h2>Model selection</h2><p>Choose a provider and working model for new tasks.</p></div><button className="button button-quiet button-small" onClick={() => { setProviderError(''); setProviderModalOpen(true); }} data-testid="button-configure-provider"><KeyRound size={14} /> Configure provider</button></div>
      <label className="form-label provider-select-label">Provider<select value={provider} onChange={(event) => { const next = event.target.value as typeof provider; setProvider(next); setModelId(models[next][0].id); setCustomModelId(''); }} data-testid="select-model-provider"><option value="openai">OpenAI</option><option value="gemini">Google Gemini</option><option value="openrouter">OpenRouter (Anthropic)</option></select></label>
      <div className="model-options">{activeModels.map((item) => <button className={`model-option ${modelId === item.id && !customModelId ? 'chosen' : ''}`} key={item.id} onClick={() => { setModelId(item.id); setCustomModelId(''); setSaved(false); }} data-testid={`button-model-${item.id}`}><span className={`model-mark ${item.color}`}>{item.descriptor === 'QUICK' ? <Zap size={17} /> : item.descriptor === 'DEEP FOCUS' ? <Search size={17} /> : <Layers3 size={17} />}</span><span className="model-copy"><strong>{item.name} {item.descriptor === 'BALANCED' && <span className="recommended">BALANCED</span>}</strong><span>{item.detail}</span></span><span className="model-descriptor">{item.descriptor}</span><span className={`radio-mark ${modelId === item.id && !customModelId ? 'checked' : ''}`}>{modelId === item.id && !customModelId && <Check size={12} />}</span></button>)}</div>
      {provider === 'gemini' && customModelId && <p className="settings-footnote">Custom Gemini model active: <strong>{customModelId}</strong></p>}
      <p className="settings-footnote"><LockKeyhole size={13} /> {configured ? 'Provider key configured.' : 'Add a provider key to run tasks.'} Keys are never sent back to the browser.</p>
    </section>
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Local code runner</h2><p>Optional Python execution in the local workspace, disabled by default.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><KeyRound size={16} /></div><div className="setting-copy"><strong>Allow short Python runs</strong><span>Local-only and off by default. If enabled, generated code can access files and run commands with your account's normal computer permissions.</span></div><button className={`switch ${codeRunnerEnabled ? 'on' : ''}`} role="switch" aria-checked={codeRunnerEnabled} disabled={!credentialStatus?.localSetupAllowed} onClick={() => { setCodeRunnerEnabled(!codeRunnerEnabled); setProviderSaved(false); }} aria-label="Allow local Python code runner" data-testid="switch-local-code-runner"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><Bell size={16} /></div><div className="setting-copy"><strong>Desktop notifications</strong><span>Show browser notifications when a scheduled reminder fires.</span></div><button className="button button-quiet button-small" onClick={() => { if ('Notification' in window) void Notification.requestPermission(); }} data-testid="button-enable-notifications">Enable alerts</button></div>
      {!credentialStatus?.localSetupAllowed && <p className="settings-footnote"><LockKeyhole size={13} /> The local code runner can only be enabled from a localhost copy of the app.</p>}
    </section>
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Safety &amp; permissions</h2><p>Make your boundaries explicit. Change these any time.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><CheckCircle2 size={16} /></div><div className="setting-copy"><strong>Confirm before consequential actions</strong><span>Pause and ask before an action that changes or sends something.</span></div><button className={`switch ${confirmBeforeActions ? 'on' : ''}`} role="switch" aria-checked={confirmBeforeActions} onClick={() => onSetting(setConfirmBeforeActions, !confirmBeforeActions)} aria-label="Confirm before consequential actions" data-testid="switch-confirm-actions"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><Search size={16} /></div><div className="setting-copy"><strong>Allow external research</strong><span>Let the agent consult public sources when research needs it.</span></div><button className={`switch ${allowExternalResearch ? 'on' : ''}`} role="switch" aria-checked={allowExternalResearch} onClick={() => onSetting(setAllowExternalResearch, !allowExternalResearch)} aria-label="Allow external research" data-testid="switch-external-research"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><FileText size={16} /></div><div className="setting-copy"><strong>Use workspace files as context</strong><span>Allow saved documents and notes to inform relevant tasks.</span></div><button className={`switch ${includeFiles ? 'on' : ''}`} role="switch" aria-checked={includeFiles} onClick={() => onSetting(setIncludeFiles, !includeFiles)} aria-label="Use workspace files as context" data-testid="switch-workspace-context"><span /></button></div>
    </section>
    <div className="settings-save-row"><div className="save-state">{saved && <><CheckCircle2 size={15} /> Preferences updated for this session.</>}{providerSaved && <><CheckCircle2 size={15} /> Provider settings saved.</>}</div><button className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || providerSaving} onClick={() => { setSaved(true); void saveProviderSettings(); }} data-testid="button-save-settings"><Check size={15} /> Save preferences</button></div>
    <div className="settings-note"><LockKeyhole size={15} /><div><strong>Your work stays yours.</strong><p>These controls guide the agent; it will never claim to have completed work until a task reports an outcome.</p></div></div>
    <TimersManager />
    {providerModalOpen && <Modal title="Connect an AI provider" onClose={() => setProviderModalOpen(false)}><form className="form-stack" onSubmit={(event) => { event.preventDefault(); void saveProviderSettings(); }}>
      <p className="modal-description">Keys are saved to the .env file for the environment running this app and are never returned to the browser. In Replit they stay in this workspace; in a local copy they stay on your PC.</p>
      <label className="form-label">Default provider<select value={provider} onChange={(event) => { const next = event.target.value as typeof provider; setProvider(next); setModelId(models[next][0].id); setCustomModelId(''); }} data-testid="select-settings-provider"><option value="openai">OpenAI</option><option value="gemini">Google Gemini</option><option value="openrouter">OpenRouter</option></select></label>
      <label className="form-label">Default model<select value={customModelId.trim() || modelId} onChange={(event) => { setModelId(event.target.value); setCustomModelId(''); }} data-testid="select-settings-model">{customModelId.trim() && !models[provider].some((item) => item.id === customModelId.trim()) && <option value={customModelId.trim()}>{customModelId.trim()} (custom)</option>}{models[provider].map((item) => <option key={item.id} value={item.id}>{item.id} — {item.detail}</option>)}</select></label>
      {provider === 'gemini' && <label className="form-label">Custom Model ID <span className="optional-label">Optional; overrides the selected model. Use an available fallback if a request returns 429 or 503.</span><input type="text" autoComplete="off" spellCheck={false} value={customModelId} onChange={(event) => { setCustomModelId(event.target.value); setProviderSaved(false); }} placeholder="e.g. gemini-3.1-pro-preview" data-testid="input-custom-model-id" /></label>}
      {provider === 'gemini' && <label className="form-label">Automatic fallback model <span className="optional-label">Optional; retry once after a Gemini 429 or 503. Leave blank to disable.</span><input type="text" autoComplete="off" spellCheck={false} value={fallbackModelId} onChange={(event) => { setFallbackModelId(event.target.value); setProviderSaved(false); }} placeholder="e.g. gemini-2.5-flash-lite" data-testid="input-gemini-fallback-model-id" /></label>}
      <label className="form-label">OpenAI API key <span className="optional-label">{credentialStatus?.hasOpenaiKey ? 'configured — leave blank to keep' : 'optional'}</span><input type="password" autoComplete="new-password" value={apiKeys.openaiApiKey} onChange={(event) => setApiKeys({ ...apiKeys, openaiApiKey: event.target.value })} placeholder="sk-…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-openai-api-key" /></label>
      <label className="form-label">Gemini API key <span className="optional-label">{credentialStatus?.hasGeminiKey ? 'configured — leave blank to keep' : 'optional'}</span><input type="password" autoComplete="new-password" value={apiKeys.geminiApiKey} onChange={(event) => setApiKeys({ ...apiKeys, geminiApiKey: event.target.value })} placeholder="Enter your Gemini key" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-gemini-api-key" /></label>
      <label className="form-label">OpenRouter API key <span className="optional-label">{credentialStatus?.hasOpenrouterKey ? 'configured — leave blank to keep' : 'optional'}</span><input type="password" autoComplete="new-password" value={apiKeys.openrouterApiKey} onChange={(event) => setApiKeys({ ...apiKeys, openrouterApiKey: event.target.value })} placeholder="sk-or-…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-openrouter-api-key" /></label>
      {providerError && <p className="field-error" role="alert">{providerError}</p>}
      {providerSaved && <p className="save-state"><CheckCircle2 size={15} /> Saved to the current .env file. Key values are not shown again.</p>}
      <div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setProviderModalOpen(false)}>Close</button><button type="submit" className="button button-primary" disabled={providerSaving || !credentialStatus?.providerSettingsAllowed} data-testid="button-save-provider">{providerSaving ? 'Saving…' : 'Save provider settings'}</button></div>
    </form></Modal>}
  </div></AppShell>;
}

function TimersManager() {
  const qc = useQueryClient();
  const timerQuery = useListAssistantTimers();
  const createTimer = useCreateAssistantTimer();
  const deleteTimer = useDeleteAssistantTimer();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [kind, setKind] = useState<'countdown' | 'alarm'>('countdown');
  const [recurrence, setRecurrence] = useState<'none' | 'daily' | 'weekly'>('none');
  const [when, setWhen] = useState('');
  const [error, setError] = useState('');
  const onCreate = (event: FormEvent) => {
    event.preventDefault();
    if (!label.trim() || !when) { setError('Add a reminder label and time.'); return; }
    const date = new Date(when);
    if (Number.isNaN(date.getTime()) || date.getTime() <= Date.now()) { setError('Choose a time in the future.'); return; }
    setError('');
    createTimer.mutate({ data: { label: label.trim(), kind, scheduledFor: date.toISOString(), recurrence } }, { onSuccess: () => { setOpen(false); setLabel(''); setWhen(''); setRecurrence('none'); qc.invalidateQueries({ queryKey: getListAssistantTimersQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); }, onError: () => setError('Reminder could not be set. Try again.') });
  };
  const timers = timerQuery.data ?? [];
  return <section className="settings-section reminders-section"><div className="settings-section-heading"><div className="section-symbol amber"><Bell size={17} /></div><div><h2>Reminders</h2><p>Keep a time-sensitive nudge where you can see it.</p></div><button className="button button-quiet button-small" onClick={() => setOpen(true)} data-testid="button-add-reminder"><Plus size={14} /> Add reminder</button></div>
    {timerQuery.isLoading ? <Skeleton rows={2} /> : timerQuery.isError ? <QueryProblem retry={() => timerQuery.refetch()} /> : timers.length ? <div className="reminder-list">{timers.map((timer: AssistantTimer) => <div className="reminder-row" key={timer.id}><span className={`reminder-icon ${timer.kind}`}><Clock3 size={16} /></span><div className="reminder-copy"><strong>{timer.label}</strong><span>{timer.kind} <i /> {formatDate(timer.scheduledFor)}</span></div><StatusPill status={timer.status} />{timer.status !== 'dismissed' && <button className="icon-button danger-hover" aria-label={`Dismiss ${timer.label}`} onClick={() => deleteTimer.mutate({ id: timer.id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantTimersQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } })} data-testid={`button-delete-timer-${timer.id}`}><X size={16} /></button>}</div>)}</div> : <div className="empty-inline"><Clock3 size={16} /><span>No reminders set. Add one when a task needs a nudge.</span></div>}
    {open && <Modal title="Add a reminder" onClose={() => setOpen(false)}><form className="form-stack" onSubmit={onCreate}><label className="form-label">What should you remember?<input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} placeholder="Follow up on the proposal" autoFocus data-testid="input-reminder-label" /></label><div className="form-label">Reminder type<div className="segmented-control"><button type="button" className={kind === 'countdown' ? 'selected' : ''} onClick={() => setKind('countdown')} data-testid="button-kind-countdown"><Clock3 size={14} /> Countdown</button><button type="button" className={kind === 'alarm' ? 'selected' : ''} onClick={() => setKind('alarm')} data-testid="button-kind-alarm"><Bell size={14} /> Scheduled</button></div></div><label className="form-label">When<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} data-testid="input-reminder-time" /></label><label className="form-label">Repeat<select value={recurrence} onChange={(e) => setRecurrence(e.target.value as typeof recurrence)} data-testid="select-reminder-recurrence"><option value="none">Does not repeat</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>{error && <p className="field-error">{error}</p>}<div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setOpen(false)}>Cancel</button><button className="button button-primary" disabled={createTimer.isPending} data-testid="button-save-reminder">{createTimer.isPending ? 'Setting…' : <><Bell size={14} /> Set reminder</>}</button></div></form></Modal>}
  </section>;
}

function Router() {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}><Switch>
    <Route path="/" component={Dashboard} />
    <Route path="/tasks" component={TasksPage} />
    <Route path="/workspace" component={WorkspacePage} />
    <Route path="/settings" component={SettingsPage} />
    <Route component={NotFound} />
  </Switch></ErrorBoundary>;
}

function App() {
  return <QueryClientProvider client={queryClient}><TooltipProvider><ReminderNotifications /><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><Router /></WouterRouter><Toaster /></TooltipProvider></QueryClientProvider>;
}

export default App;
