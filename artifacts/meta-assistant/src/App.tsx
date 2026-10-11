import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Router as WouterRouter, Switch, useLocation } from 'wouter';
import {
  useAbortAssistantTask,
  useChooseAssistantTaskApproval,
  useChooseAssistantTaskModel,
  useCreateAssistantNote,
  useCreateAssistantTask,
  useCreateAssistantTimer,
  useDownloadAssistantWorkspace,
  useDeleteAssistantFile,
  useDeleteAssistantNote,
  useDeleteAssistantTimer,
  useGetAssistantDashboard,
  useGetAssistantTask,
  useGetAssistantSettings,
  useGetWorkspacePreview,
  useListAssistantFiles,
  useGetConversationThread,
  getGetConversationThreadQueryKey,
  getListConversationThreadsQueryKey,
  useListAssistantNotes,
  useListAssistantTasks,
  useListAssistantTimers,
  useUpdateAssistantSettings,
  useApplyAssistantModel,
  useSaveAssistantProviderKeys,
  useStopWorkspacePreviewApp,
  useRetryAssistantTaskStep,
  getGetAssistantDashboardQueryKey,
  getGetAssistantTaskQueryKey,
  getGetAssistantSettingsQueryKey,
  getGetWorkspacePreviewQueryKey,
  getDownloadAssistantWorkspaceQueryKey,
  getListAssistantFilesQueryKey,
  getListAssistantNotesQueryKey,
  getListAssistantTasksQueryKey,
  getListAssistantTimersQueryKey,
} from '@workspace/api-client-react';
import type { AssistantFile, AssistantNote, AssistantSettings, AssistantSettingsInput, AssistantTask, AssistantTimer, WorkspacePreviewApp } from '@workspace/api-client-react';
import {
  Activity, AlertCircle, ArrowDownToLine, ArrowRight, Bell, BookOpen, Check, CheckCircle2,
  ChevronDown, ChevronRight, CircleHelp, Clock3, Copy, ExternalLink, FileText, FolderOpen, Gauge, HardDrive, Layers3, Moon, Sun,
  KeyRound, LoaderCircle, LockKeyhole, Menu, MoreHorizontal, Plus, RefreshCw, Search,
  Send, Settings2, ShieldCheck, Sparkles, StopCircle, Trash2, Upload, X, Zap, PanelRight, GripVertical,
} from 'lucide-react';
import { ConversationProvider, useConversations } from '@/components/conversation-provider';
import { ChatSidebar } from '@/components/chat-sidebar';
import { ChatModelPicker } from '@/components/chat-model-picker';
import { ActivityStream } from '@/components/activity-stream';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { toast } from '@/hooks/use-toast';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient();
type Page = 'home' | 'tasks' | 'workspace' | 'alarms' | 'settings';

const navItems: { href: string; label: string; icon: typeof Activity }[] = [
  { href: '/', label: 'Command center', icon: Gauge },
  { href: '/tasks', label: 'Task activity', icon: Activity },
  { href: '/workspace', label: 'Workspace files', icon: FolderOpen },
  { href: '/alarms', label: 'Scheduled alarms', icon: Bell },
  { href: '/settings', label: 'Preferences', icon: Settings2 },
];

const THEMES = [
  { id: 'cyberdeck', label: 'Sci-Fi', fullLabel: 'Sci-Fi' },
  { id: 'dark', label: 'Dark', fullLabel: 'Dark' },
  { id: 'light', label: 'Light', fullLabel: 'Light' },
] as const;

function ThemeChooser() {
  const [theme, setTheme] = useState(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem('morrow-theme'); } catch { /* Storage can be disabled. */ }
    return saved === 'dark' || saved === 'light' ? saved : 'cyberdeck';
  });
  const chooseTheme = (value: string) => {
    if (!THEMES.some((item) => item.id === value)) return;
    setTheme(value);
    document.documentElement.dataset.theme = value === 'cyberdeck' ? 'scifi' : value;
    localStorage.setItem('morrow-theme', value);
    window.dispatchEvent(new Event('morrow:theme'));
  };
  useEffect(() => {
    const sync = () => {
      const active = document.documentElement.dataset.theme;
      setTheme(active === 'dark' || active === 'light' ? active : 'cyberdeck');
    };
    window.addEventListener('morrow:theme', sync);
    return () => window.removeEventListener('morrow:theme', sync);
  }, []);
  return <div className="theme-chooser" role="radiogroup" aria-label="Choose appearance theme" data-testid="select-theme">
    {THEMES.map((item) => <button type="button" role="radio" aria-checked={theme === item.id} aria-label={`${item.fullLabel} theme`} title={`${item.fullLabel} theme`} className={`theme-option ${theme === item.id ? 'selected' : ''}`} key={item.id} onClick={() => chooseTheme(item.id)} data-testid={`theme-${item.id}`}>{item.id === 'dark' ? <Moon size={12} /> : item.id === 'light' ? <Sun size={12} /> : <Sparkles size={12} />}<span>{item.label}</span></button>)}
  </div>;
}

function CyberFxToggle() {
  const [enabled, setEnabled] = useState(() => document.documentElement.dataset.cyberFx !== 'off');
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme);
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => {
      setEnabled(root.dataset.cyberFx !== 'off');
      setTheme(root.dataset.theme);
    };
    window.addEventListener('morrow:cyber-fx', sync);
    window.addEventListener('morrow:theme', sync);
    return () => {
      window.removeEventListener('morrow:cyber-fx', sync);
      window.removeEventListener('morrow:theme', sync);
    };
  }, []);
  const toggle = () => {
    const next = !enabled;
    setEnabled(next);
    document.documentElement.dataset.cyberFx = next ? 'on' : 'off';
    try { localStorage.setItem('forge-cyber-fx', next ? 'on' : 'off'); } catch { /* The current session still honors the choice. */ }
    window.dispatchEvent(new Event('morrow:cyber-fx'));
  };
  if (theme !== 'scifi') return null;
  return <button type="button" className={`cyber-fx-toggle ${enabled ? 'is-on' : ''}`} role="switch" aria-checked={enabled} aria-label={`Cyber FX: ${enabled ? 'ON' : 'OFF'}`} onClick={toggle} data-testid="toggle-cyber-fx"><Sparkles size={13} /><span>Cyber FX: {enabled ? 'ON' : 'OFF'}</span><i aria-hidden="true" /></button>;
}

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
  if (status === 'running' || status === 'processing' || status === 'queued' || status === 'awaiting_confirmation' || status === 'awaiting_approval' || status === 'active') return 'live';
  if (status === 'completed' || status === 'fired') return 'done';
  if (status === 'failed' || status === 'cancelled') return 'issue';
  return 'neutral';
}

function StatusPill({ status }: { status: string }) {
  const label = status === 'awaiting_confirmation' ? 'awaiting confirmation' : status === 'awaiting_approval' ? 'approval needed' : status;
  return <span className={`status-pill ${statusTone(status)}`} data-testid={`status-${status}`}>{label}</span>;
}

function modelDisplayName(provider?: string | null, model?: string | null) {
  if (provider === 'deepseek' && model === 'deepseek-reasoner') return 'DeepSeek Reasoner';
  if (provider === 'gemini' && model === 'gemini-2.5-pro') return 'Gemini 2.5 Pro';
  if (provider === 'openrouter' && model === 'anthropic/claude-3.7-sonnet') return 'Claude 3.7 Sonnet';
  if (provider === 'openai' && model === 'gpt-4.1') return 'GPT-4.1';
  return model || 'recommended model';
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
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') closeRef.current(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  return createPortal(<div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal-card enter" role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><h2 className="font-display">{title}</h2><button className="icon-button" onClick={onClose} aria-label="Close dialog" data-testid="button-close-modal"><X size={18} /></button></div>{children}</section></div>, document.body);
}

function AppShell({ children, page }: { children: ReactNode; page: Page }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth > 900);
  const [inspectorWidth, setInspectorWidth] = useState(410);
  const [resizingInspector, setResizingInspector] = useState(false);
  const [location] = useLocation();
  const routePage = (location === '/' ? 'home' : location.slice(1)) as Page;
  const current = page || routePage;
  useEffect(() => {
    const viewport = window.matchMedia('(max-width: 900px)');
    const closeInspectorOnNarrowViewport = (event: MediaQueryListEvent) => {
      if (event.matches) setInspectorOpen(false);
    };
    viewport.addEventListener('change', closeInspectorOnNarrowViewport);
    return () => viewport.removeEventListener('change', closeInspectorOnNarrowViewport);
  }, []);
  useEffect(() => {
    if (!resizingInspector) return;
    const move = (event: PointerEvent) => setInspectorWidth(Math.max(380, Math.min(450, window.innerWidth - event.clientX)));
    const stop = () => setResizingInspector(false);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); };
  }, [resizingInspector]);
  useEffect(() => {
    const openPreview = () => {
      setInspectorOpen(true);
      window.dispatchEvent(new Event('morrow:show-preview'));
    };
    window.addEventListener('morrow:open-preview-inspector', openPreview);
    return () => window.removeEventListener('morrow:open-preview-inspector', openPreview);
  }, []);
  return <div className={`app-frame shell-noise ${inspectorOpen ? 'inspector-open' : 'inspector-closed'}`} style={{ '--inspector-width': `${inspectorWidth}px` } as CSSProperties}>
    <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="brand"><div className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M5 9.5 16 4l11 5.5-4.7 2.35L16 9l-6.3 2.85L5 9.5Z" /><path d="m5 9.5 2.8 12L16 27l8.2-5.5L27 9.5" /><path d="m9.7 11.85 1.55 7.1L16 22l4.75-3.05 1.55-7.1" /><path d="m11.25 18.95 4.75-2.6 4.75 2.6M16 9v7.35" /></svg></div><div><div className="brand-name">Forge</div><div className="brand-caption">LOCAL OPERATIONS</div></div><span className="runtime-ready-dot" aria-label="Local runtime ready" title="Local runtime ready" /><button className="sidebar-close icon-button" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={17} /></button></div>
      <ChatSidebar onPicked={() => setMobileOpen(false)} />
      <div className="workspace-label">YOUR WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">{navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={`nav-link ${current === (href === '/' ? 'home' : href.slice(1)) ? 'active' : ''}`} onClick={() => setMobileOpen(false)} data-testid={`link-nav-${href === '/' ? 'home' : href.slice(1)}`}><Icon size={17} /><span>{label}</span>{href === '/tasks' && <span className="nav-trailing"><span className="nav-dot" /></span>}</Link>)}</nav>
      <div className="side-divider" />
      <div className="sidebar-section-title">QUICK STATUS</div>
      <QuickSidebarStatus />
      <div className="sidebar-spacer" />
      <div className="agent-card"><div className="agent-orbit"><span /><i /></div><div className="agent-card-copy"><strong>Your agent is ready</strong><span>Waiting for direction</span></div><span className="ready-indicator" /></div>
      <div className="sidebar-bottom"><div className="user-avatar">F</div><div className="user-meta"><strong>My workspace</strong><span>Personal account</span></div><button className="icon-button user-menu" aria-label="Account options" onClick={() => window.dispatchEvent(new Event('morrow:account'))}><MoreHorizontal size={18} /></button></div>
    </aside>
    {mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu" />}
    <main className="main-area">
      <header className="topbar"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)} data-testid="button-open-navigation"><Menu size={20} /></button><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{navItems.find((n) => (n.href === '/' ? 'home' : n.href.slice(1)) === current)?.label ?? 'Overview'}</strong></div><div className="topbar-right"><span className="ops-tagline">LOCAL OPS // 6570</span><div className="system-online"><span className="online-pip" />All systems operational</div><ThemeChooser /><CyberFxToggle /><button className="inspector-toggle icon-button" aria-label={inspectorOpen ? 'Close workspace inspector' : 'Open workspace inspector'} aria-expanded={inspectorOpen} onClick={() => setInspectorOpen((open) => !open)} data-testid="button-toggle-inspector"><PanelRight size={17} /></button><button className="topbar-icon" aria-label="Help" onClick={() => window.alert('Your agent can help with documents, reminders, research, and code-related work.')} data-testid="button-help"><CircleHelp size={18} /></button><div className="topbar-avatar">F</div></div></header>
      <div className={`center-pane ${page === 'home' ? 'center-pane-home' : ''}`}><div className="page-wrap">{children}</div><footer className="app-footer"><span>Made for thoughtful delegation.</span><span className="footer-build">FORGE <span>·</span> LOCAL COMMAND CENTER</span></footer></div>
    </main>
    {inspectorOpen && <div className="inspector-resize" role="separator" aria-orientation="vertical" aria-label="Resize workspace inspector" aria-valuemin={380} aria-valuemax={450} aria-valuenow={inspectorWidth} tabIndex={0} onPointerDown={(event) => { event.preventDefault(); setResizingInspector(true); }} onKeyDown={(event) => { if (event.key === 'ArrowLeft') setInspectorWidth((width) => Math.min(450, width + 10)); if (event.key === 'ArrowRight') setInspectorWidth((width) => Math.max(380, width - 10)); }} data-testid="separator-inspector"><GripVertical size={14} /></div>}
    {inspectorOpen && <InspectorPanel onClose={() => setInspectorOpen(false)} />}
  </div>;
}

function QuickSidebarStatus() {
  const { data, isLoading, isError } = useGetAssistantDashboard();
  const settings = useGetAssistantSettings();
  const files = useListAssistantFiles();
  const timers = useListAssistantTimers();
  const activeModel = settings.isLoading ? 'Loading model…' : settings.isError ? 'Unavailable' : modelDisplayName(settings.data?.provider, settings.data?.modelId);
  const storage = (files.data ?? []).reduce((total, file) => total + file.sizeBytes, 0);
  const runningCount = data?.activeTasks ?? 0;
  const systemState = isLoading ? 'Online' : isError ? 'Offline' : runningCount ? `Running · ${runningCount}` : 'Idle';
  return <div className="quick-status">
    <div data-testid="system-status"><span className="quick-status-icon"><Activity size={14} /></span><span>System status</span><strong>{systemState}</strong></div>
    <div data-testid="active-model"><span className="quick-status-icon"><Zap size={14} /></span><span>Active model</span><strong className="model-name" title={activeModel}>{activeModel}</strong></div>
    <div><span className="quick-status-icon amber"><Bell size={14} /></span><span>Active alarms</span><strong>{timers.isLoading ? '—' : (timers.data ?? []).filter((timer) => timer.status === 'active').length}</strong></div>
    <div className="sidebar-storage"><span className="quick-status-icon"><HardDrive size={14} /></span><span>Workspace storage</span><strong>{files.isLoading ? '—' : formatSize(storage)}</strong></div>
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
  return <button className={`task-row ${compact ? 'compact' : ''}`} onClick={onClick} data-task-status={task.status} data-task-running={task.status === 'running' || String(task.status) === 'processing' ? 'true' : 'false'} data-testid={`button-task-${task.id}`}>
    <span className={`task-symbol ${statusTone(task.status)}`}>{task.status === 'completed' ? <Check size={14} /> : task.status === 'failed' ? <AlertCircle size={14} /> : task.status === 'cancelled' ? <StopCircle size={14} /> : task.status === 'awaiting_confirmation' || task.status === 'awaiting_approval' ? <CircleHelp size={14} /> : <span className="tiny-spinner" />}</span>
    <span className="task-row-main"><strong>{task.objective}</strong><span>{task.currentStep || task.result || task.error || (task.status === 'queued' ? 'Queued for the agent' : 'Task updated')} </span></span>
    <span className="task-row-side"><StatusPill status={task.status} /><time>{timeAgo(task.updatedAt)}</time></span>
    {!compact && <ArrowRight className="task-arrow" size={15} />}
  </button>;
}

function CodeSnippet({ source, language }: { source: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch { setCopied(false); }
  };
  return <div className="stream-code"><div><span>{language || 'code'}</span><button onClick={() => void copy()} data-testid="button-copy-task-code"><Copy size={12} />{copied ? 'Copied' : 'Copy'}</button></div><pre><code>{source}</code></pre></div>;
}

function LogMessage({ message, kind }: { message: string; kind: string }) {
  const pieces = message.split(/(```[\s\S]*?```)/g);
  return <div className="log-message"><span className="terminal-prefix" aria-hidden="true">{kind === 'tool' ? '[OP_RUNNER]' : 'FORGE://SYS_OUT >'}</span>{pieces.map((piece, index) => {
    const match = piece.match(/^```([\w-]*)\n?([\s\S]*?)```$/);
    return match ? <CodeSnippet key={index} language={match[1]} source={match[2].replace(/\n$/, '')} /> : <p key={index}>{piece}</p>;
  })}</div>;
}

function TaskActionDock({ task }: { task?: AssistantTask }) {
  const qc = useQueryClient();
  const approval = useChooseAssistantTaskApproval();
  const model = useChooseAssistantTaskModel();
  const retry = useRetryAssistantTaskStep();
  const [error, setError] = useState('');
  if (!task) return null;
  const update = (updated: AssistantTask) => {
    qc.setQueryData(getGetAssistantTaskQueryKey(updated.id), updated);
    qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
    qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
  };
  const isElevated = task.pendingApprovalKind === 'elevated_command';
  const needsApproval = task.requiresApproval && !!task.pendingApprovalId;
  const needsModel = task.requiresModelConfirmation;
  const needsFallback = task.recommendationKind === 'fallback' && task.retryAvailable && task.status !== 'running';
  if (!needsApproval && !needsModel && !needsFallback) return null;
  const decide = (approve: boolean) => {
    if (!task.pendingApprovalId) return;
    setError('');
    approval.mutate({ id: task.id, data: { approvalId: task.pendingApprovalId, approve } }, { onSuccess: update, onError: () => setError('The workspace approval decision could not be saved. Please try again.') });
  };
  const choose = (switchToRecommendation: boolean) => {
    setError('');
    model.mutate({ id: task.id, data: { switchToRecommendation } }, { onSuccess: update, onError: () => setError('Your model choice could not be saved. Please try again.') });
  };
  const retryStep = (shouldRetry: boolean) => {
    setError('');
    retry.mutate({ id: task.id, data: { retry: shouldRetry } }, { onSuccess: update, onError: () => setError('The specialist retry could not be started. Please try again.') });
  };
  const recommended = modelDisplayName(task.recommendedProvider, task.recommendedModelId);
  return <section className="action-dock" aria-label="Task decisions" data-testid="task-action-dock">
    <div className="dock-heading"><span className="dock-alert" /><strong>Waiting for your decision</strong><span>{task.objective}</span></div>
    {needsApproval && <div className={`dock-card ${isElevated ? 'security-warning' : ''}`} data-testid={isElevated ? 'dock-elevated-approval' : 'dock-workspace-approval'}>
      {isElevated ? <><strong>Administrative Privilege Requested:</strong><p>The agent is requesting permission to execute:</p><code>{task.approvalSummary}</code><span> with elevated system permissions.</span><p>Nothing runs until you approve. The invocation will be recorded in <code>logs/elevated_audit.log</code>.</p><p>If pkexec is unavailable, the sudo fallback requires an already-authorized non-interactive sudo session and fails closed otherwise.</p></> : <><strong>Workspace action needs your approval</strong><p>{task.approvalSummary} The agent is paused; no change has been made yet.</p></>}
      <div className="model-recommendation-actions"><button className="button button-primary" onClick={() => decide(true)} disabled={approval.isPending} data-testid="button-dock-approve">{approval.isPending ? 'Applying…' : isElevated ? 'Approve & Run with UAC' : 'Approve and continue'}</button><button className="button button-quiet" onClick={() => decide(false)} disabled={approval.isPending} data-testid="button-dock-reject">{isElevated ? 'Reject Action' : 'Reject and continue'}</button></div>
    </div>}
    {needsModel && <div className="dock-card" data-testid="dock-model-recommendation"><strong>Recommendation:</strong><p>This task involves {task.recommendationReason}. Running on a high-capability model like {recommended} may produce better results. Would you like to switch for this task?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => choose(true)} disabled={model.isPending} data-testid="button-dock-switch-model">{model.isPending ? 'Saving choice…' : 'Switch to Recommended Model'}</button><button className="button button-quiet" onClick={() => choose(false)} disabled={model.isPending} data-testid="button-dock-stay-model">Stay on Current Model</button></div></div>}
    {needsFallback && <div className="dock-card security-warning" data-testid="dock-fallback-recommendation"><strong>Task encountered persistent errors on the current model.</strong><p>Would you like to retry this step with {recommended}?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => retryStep(true)} disabled={retry.isPending} data-testid="button-dock-retry-model">{retry.isPending ? 'Starting retry…' : 'Retry this step with Recommended Pro Model'}</button><button className="button button-quiet" onClick={() => retryStep(false)} disabled={retry.isPending} data-testid="button-dock-dismiss-retry">Not now</button></div></div>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}

function Dashboard() {
  const qc = useQueryClient();
  const summary = useGetAssistantDashboard({ query: { queryKey: getGetAssistantDashboardQueryKey(), refetchInterval: 4000 } });
  const listTasks = useListAssistantTasks({ query: { queryKey: getListAssistantTasksQueryKey(), refetchInterval: 2000 } });
  const createTask = useCreateAssistantTask();
  const conv = useConversations();
  const { selectedId: threadId } = conv;
  const threadDetail = useGetConversationThread(threadId ?? '', { query: { enabled: !!threadId, queryKey: getGetConversationThreadQueryKey(threadId ?? ''), refetchInterval: 2000 } });
  const threadStale = (threadDetail.error as { status?: number } | null)?.status === 404;
  const settingsQuery = useGetAssistantSettings();
  const [objective, setObjective] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const [attachments, setAttachments] = useState<AssistantFile[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState('');
  const [modelMode, setModelMode] = useState('configured');
  const attachmentInput = useRef<HTMLInputElement>(null);
  const objectiveInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const input = objectiveInput.current;
    if (input) {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    }
  }, [objective]);
  useEffect(() => {
    const syncModel = () => setModelMode('configured');
    window.addEventListener('forge:model-applied', syncModel);
    return () => window.removeEventListener('forge:model-applied', syncModel);
  }, []);
  const details = useGetAssistantTask(selectedTaskId ?? '', { query: { enabled: !!selectedTaskId, queryKey: getGetAssistantTaskQueryKey(selectedTaskId ?? ''), refetchInterval: (query) => {
    const task = query.state.data;
    return task && ['queued', 'running', 'processing', 'awaiting_approval', 'awaiting_confirmation'].includes(task.status) ? 2500 : false;
  } } });
  const abort = useAbortAssistantTask();
  const { select: selectThread, resetSignal } = conv;
  const selectedThreadRef = useRef(threadId);
  selectedThreadRef.current = threadId;
  const adoptingSentThread = useRef<string | undefined>(undefined);
  useEffect(() => { if (threadStale) selectThread(undefined); }, [threadStale, selectThread]);
  useEffect(() => {
    if (!adoptingSentThread.current || adoptingSentThread.current !== threadId) {
      setObjective(''); setAttachments([]);
    }
    adoptingSentThread.current = undefined;
    setSubmitError(''); setAttachmentError(''); setSelectedTaskId(undefined);
  }, [threadId, resetSignal]);
  const tasks = useMemo(() => (threadId ? threadDetail.data?.tasks ?? [] : []), [threadId, threadDetail.data]);
  const threadMessages = threadDetail.data?.messages;
  const threadTitle = threadId ? threadDetail.data?.title ?? conv.threads.find((t) => t.id === threadId)?.title ?? 'Chat' : 'New chat';
  const actionTaskId = tasks.find((task) => task.requiresApproval || task.requiresModelConfirmation)?.id
    ?? tasks.find((task) => ['running', 'processing', 'queued', 'awaiting_confirmation', 'awaiting_approval'].includes(task.status))?.id
    ?? [...tasks].reverse().find((task) => task.recommendationKind === 'fallback')?.id ?? '';
  const actionTask = useGetAssistantTask(actionTaskId, { query: { enabled: !!actionTaskId, queryKey: getGetAssistantTaskQueryKey(actionTaskId), refetchInterval: (query) => {
    const task = query.state.data;
    return task && ['queued', 'running', 'processing', 'awaiting_approval', 'awaiting_confirmation'].includes(task.status) ? 2500 : false;
  } } });
  const activeExecution = [...tasks, details.data, actionTask.data].some((task) => task?.status === 'running' || String(task?.status) === 'processing');
  const referenceModel = [...tasks].reverse().find((task) => task.modelId);
  const isPending = createTask.isPending;
  const threadBusy = !!threadId && (!threadDetail.data || !!threadDetail.data.activeTaskId);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = objective.trim();
    if (!text || createTask.isPending || uploadingAttachment || threadBusy) return;
    setSubmitError('');
    const directModel = modelMode.startsWith('direct|') ? modelMode.split('|') : undefined;
    createTask.mutate({ data: { objective: text, ...(threadId ? { threadId } : {}), ...(attachments.length ? { fileIds: attachments.map((file) => file.id) } : {}), ...(directModel?.length === 3 ? { provider: directModel[1] as AssistantTask['provider'], modelId: directModel[2] } : modelMode === 'last-used' && referenceModel ? { provider: referenceModel.provider, modelId: referenceModel.modelId } : {}) } }, {
      onSuccess: async (task) => {
        if (task.threadId) {
          await qc.invalidateQueries({ queryKey: getGetConversationThreadQueryKey(task.threadId) });
          if (selectedThreadRef.current === threadId) {
            setObjective(''); setAttachments([]);
            if (task.threadId !== threadId) adoptingSentThread.current = task.threadId;
            await conv.adopt(task.threadId);
          } else {
            await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
          }
        }
        qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
        qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
      },
      onError: (error) => { if (selectedThreadRef.current === threadId) setSubmitError((error as { status?: number }).status === 409 ? 'This chat is still working. Wait for it to finish or stop the task.' : 'Your request could not be sent. Please try again.'); },
    });
  };
  const attachFile = async (file?: File) => {
    if (!file) return;
    setUploadingAttachment(true);
    setAttachmentError('');
    try {
      const body = new FormData();
      body.append('file', file);
      const response = await fetch('/api/assistant/files', { method: 'POST', body, credentials: 'include' });
      if (!response.ok) throw new Error('Upload failed');
      const uploaded = await response.json() as AssistantFile;
      setAttachments((current) => [...current, uploaded]);
      await qc.invalidateQueries({ queryKey: getListAssistantFilesQueryKey() });
      await qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
    } catch {
      setAttachmentError('The attachment could not be uploaded. Try again from Workspace Files.');
    } finally {
      setUploadingAttachment(false);
      if (attachmentInput.current) attachmentInput.current.value = '';
    }
  };
  const counts = [
    { label: 'In motion', value: summary.data?.activeTasks, icon: Activity, tint: 'teal', note: 'tasks running now' },
    { label: 'Completed', value: summary.data?.completedTasks, icon: CheckCircle2, tint: 'blue', note: 'outcomes delivered' },
    { label: 'Reminders', value: summary.data?.activeTimers, icon: Bell, tint: 'amber', note: 'upcoming or active' },
    { label: 'Knowledge', value: (summary.data?.notesCount ?? 0) + (summary.data?.filesCount ?? 0), icon: BookOpen, tint: 'plum', note: `${summary.data?.notesCount ?? 0} notes · ${summary.data?.filesCount ?? 0} files` },
  ];
  return <AppShell page="home"><div className="dashboard-page command-center enter" data-task-active={activeExecution ? 'true' : 'false'} data-testid="dashboard-command-center">
    <div className="command-heading"><div><p className="eyebrow">FORGE / COMMAND CENTER</p><h1>Work in motion</h1></div><div className="command-status" data-testid="status-agent-state"><span className={`online-pip ${activeExecution ? 'working' : ''}`} />{summary.isLoading ? 'Connecting' : activeExecution ? 'Running' : 'Idle'}<span className="status-divider" />{settingsQuery.data ? modelDisplayName(settingsQuery.data.provider, settingsQuery.data.modelId) : 'Configured model'}</div></div>
    {summary.isError && <QueryProblem retry={() => summary.refetch()} message="Your overview is temporarily unavailable." />}
    <div className="command-metrics" aria-label="Workspace status">{counts.map(({ label, value }) => <span key={label} data-testid={`metric-${label.toLowerCase().replaceAll(' ', '-')}`}><i />{label}<strong>{summary.isLoading ? '—' : value ?? 0}</strong></span>)}</div>
    <section className="activity-panel execution-panel" data-task-active={activeExecution ? 'true' : 'false'}><div className="activity-panel-heading"><div><span className="live-label"><span className="online-pip" />LIVE TASK STREAM</span><h2 className="thread-title" data-testid="text-thread-title">{threadTitle}</h2></div><Link href="/tasks" className="text-link" data-testid="link-all-tasks">Task activity <ArrowRight size={14} /></Link></div>
      {threadId && threadDetail.isError && !threadStale && !threadDetail.data ? <QueryProblem retry={() => threadDetail.refetch()} message="This chat could not be loaded." /> : <ActivityStream key={threadId ?? 'new'} tasks={tasks} messages={threadMessages} loading={!!threadId && threadDetail.isLoading} onOpen={(task) => setSelectedTaskId(task.id)} />}
    </section>
    <TaskActionDock task={actionTask.data} />
    <section className="composer-panel command-composer">
      <div className="composer-heading"><span className="composer-icon"><Sparkles size={15} /></span><div><strong>Give Forge a task</strong><span>Specific requests produce better work.</span></div></div>
      <form onSubmit={submit}><div className="terminal-input-row"><span className="terminal-prompt" aria-hidden="true">USR@FORGE-6570:~$</span><textarea ref={objectiveInput} value={objective} onChange={(event) => setObjective(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!event.repeat) event.currentTarget.form?.requestSubmit(); } }} placeholder="Describe what you want done…" maxLength={12000} rows={1} data-testid="input-objective" aria-label="Task objective" aria-keyshortcuts="Enter Shift+Enter" /></div>
        {attachments.length > 0 && <div className="task-attachments">{attachments.map((file) => <span className="attachment-chip" key={file.id}><FileText size={13} />{file.name}<button type="button" onClick={() => setAttachments((current) => current.filter((item) => item.id !== file.id))} aria-label={`Remove ${file.name}`} data-testid={`button-remove-attachment-${file.id}`}><X size={13} /></button></span>)}</div>}
        {attachmentError && <p className="field-error" role="alert">{attachmentError}</p>}
        {submitError && <p className="field-error" role="alert">{submitError}</p>}
        <div className="composer-bottom"><div className="composer-actions">
          <span className="composer-counter" data-testid="text-prompt-counter">{objective.length.toLocaleString()} / 12,000</span>
          <ChatModelPicker value={modelMode} onChange={setModelMode} configuredLabel={settingsQuery.data ? modelDisplayName(settingsQuery.data.provider, settingsQuery.data.modelId) : 'Loading model…'} lastUsedLabel={referenceModel ? modelDisplayName(referenceModel.provider, referenceModel.modelId) : null} groups={Object.entries(models).filter(([groupProvider]) => groupProvider !== 'ollama' || settingsQuery.data?.localSetupAllowed).map(([groupProvider, items]) => ({ id: groupProvider, label: groupProvider === 'gemini' ? 'Google Gemini' : groupProvider === 'openrouter' ? 'OpenRouter' : groupProvider === 'ollama' ? 'Local · Ollama' : groupProvider === 'openai' ? 'OpenAI' : 'DeepSeek', items }))} />
          <input ref={attachmentInput} type="file" hidden onChange={(event) => { void attachFile(event.currentTarget.files?.[0]); }} data-testid="input-task-attachment" />
          <button type="button" className="button button-quiet submit-button composer-attach" title="Attach a file" aria-label={uploadingAttachment ? 'Uploading attachment' : 'Attach a file'} onClick={() => attachmentInput.current?.click()} disabled={uploadingAttachment} data-testid="button-attach-task-file">{uploadingAttachment ? <LoaderCircle className="spin" size={12} /> : <Upload size={12} />}</button>
          <button className="button button-primary submit-button" disabled={!objective.trim() || isPending || uploadingAttachment || threadBusy} title={threadBusy ? 'Wait for this chat to finish its current task, or stop it in View Details.' : 'Send task'} data-testid="button-submit-task">{isPending ? <LoaderCircle className="spin" size={12} /> : <Send size={12} />}{isPending ? 'Sending…' : threadBusy ? 'Working' : 'Send'}</button>
        </div></div></form>
    </section>
    {selectedTaskId && <TaskDetailDialog task={details.data} loading={details.isLoading} error={details.isError} retry={() => details.refetch()} close={() => setSelectedTaskId(undefined)} abort={(id) => abort.mutate({ id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() }); } })} aborting={abort.isPending} />}
  </div></AppShell>;
}

function TaskDetailDialog({ task, loading, error, retry, close, abort, aborting }: { task?: AssistantTask; loading: boolean; error: boolean; retry: () => void; close: () => void; abort: (id: string) => void; aborting: boolean }) {
  const qc = useQueryClient();
  const resolveApproval = useChooseAssistantTaskApproval();
  const chooseModel = useChooseAssistantTaskModel();
  const retryStep = useRetryAssistantTaskStep();
  const [actionError, setActionError] = useState('');
  const updateTask = (updated: AssistantTask) => {
    qc.setQueryData(getGetAssistantTaskQueryKey(updated.id), updated);
    qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
    qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
  };
  const recommendedName = task ? modelDisplayName(task.recommendedProvider, task.recommendedModelId) : 'recommended model';
  const choose = (switchToRecommendation: boolean) => {
    if (!task) return;
    setActionError('');
    chooseModel.mutate({ id: task.id, data: { switchToRecommendation } }, {
      onSuccess: updateTask,
      onError: () => setActionError('Your model choice could not be saved. Please try again.'),
    });
  };
  const retryFailedStep = (retry: boolean) => {
    if (!task) return;
    setActionError('');
    retryStep.mutate({ id: task.id, data: { retry } }, {
      onSuccess: updateTask,
      onError: () => setActionError('The specialist retry could not be started. Please try again.'),
    });
  };
  const decideApproval = (approve: boolean) => {
    if (!task?.pendingApprovalId) return;
    setActionError('');
    resolveApproval.mutate({ id: task.id, data: { approvalId: task.pendingApprovalId, approve } }, {
      onSuccess: updateTask,
      onError: () => setActionError('The workspace approval decision could not be saved. Please try again.'),
    });
  };
  const elevatedApproval = task?.pendingApprovalKind === 'elevated_command';
  const elevationButtonLabel = typeof navigator !== 'undefined' && navigator.platform.toLowerCase().startsWith('win')
    ? 'Approve & Run with UAC'
    : 'Approve & Run with OS elevation';
  return <Modal title="Task details" onClose={close}>{loading ? <Skeleton rows={5} /> : error || !task ? <QueryProblem retry={retry} /> : <div className="detail-content"><div className="detail-objective"><StatusPill status={task.status} /><h3>{task.objective}</h3><p>Started {formatDate(task.createdAt)} <span>·</span> Updated {timeAgo(task.updatedAt)}</p></div>
    <p className="settings-footnote">Model used: <strong>{task.modelId}</strong></p>
    {task.requiresApproval && task.pendingApprovalId && <section className={`model-recommendation approval-recommendation ${elevatedApproval ? 'elevated-approval' : ''}`} aria-live="polite" data-testid={elevatedApproval ? 'task-elevated-approval' : 'task-workspace-approval'}>
      {elevatedApproval ? <>
        <strong>Administrative Privilege Requested</strong>
        <p>The agent is requesting permission to execute this command with elevated system permissions:</p>
        <code className="elevated-command" data-testid="text-elevated-command">{task.approvalSummary}</code>
        <p>Nothing runs until you approve. The invocation will be recorded in <code>logs/elevated_audit.log</code>.</p>
        <p>If pkexec is unavailable, the sudo fallback requires an already-authorized non-interactive sudo session and fails closed otherwise.</p>
      </> : <>
        <strong>Workspace action needs your approval</strong>
        <p>{task.approvalSummary} The agent is paused; no change has been made yet.</p>
      </>}
      <div className="model-recommendation-actions">
        <button className="button button-primary" onClick={() => decideApproval(true)} disabled={resolveApproval.isPending} data-testid="button-approve-workspace-action">{resolveApproval.isPending ? 'Applying…' : elevatedApproval ? elevationButtonLabel : 'Approve and continue'}</button>
        <button className="button button-quiet" onClick={() => decideApproval(false)} disabled={resolveApproval.isPending} data-testid="button-reject-workspace-action">{elevatedApproval ? 'Reject Action' : 'Reject and continue'}</button>
      </div>
    </section>}
    {task.requiresModelConfirmation && <section className="model-recommendation" aria-live="polite" data-testid="task-model-recommendation"><strong>Recommendation:</strong><p>This task involves {task.recommendationReason}. Running on a high-capability model like {recommendedName} may produce better results. Would you like to switch for this task?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => choose(true)} disabled={chooseModel.isPending} data-testid="button-switch-recommended-model">{chooseModel.isPending ? 'Saving choice…' : 'Switch to Recommended Model'}</button><button className="button button-quiet" onClick={() => choose(false)} disabled={chooseModel.isPending} data-testid="button-stay-current-model">Stay on Current Model</button></div></section>}
    {task.recommendationKind === 'fallback' && task.retryAvailable && task.status !== 'running' && <section className="model-recommendation fallback-recommendation" aria-live="polite" data-testid="task-fallback-recommendation"><strong>Task encountered persistent errors on the current model.</strong><p>Would you like to retry this step with {recommendedName}?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => retryFailedStep(true)} disabled={retryStep.isPending} data-testid="button-retry-step-recommended">{retryStep.isPending ? 'Starting retry…' : 'Retry this step with Recommended Pro Model'}</button><button className="button button-quiet" onClick={() => retryFailedStep(false)} disabled={retryStep.isPending} data-testid="button-dismiss-retry-suggestion">Not now</button></div></section>}
    {actionError && <p className="field-error" role="alert">{actionError}</p>}
    {task.currentStep && <div className="current-step"><span>{task.status === 'awaiting_confirmation' || task.status === 'awaiting_approval' ? <CircleHelp size={16} /> : <span className="tiny-spinner" />}</span><div><small>{task.status === 'awaiting_confirmation' || task.status === 'awaiting_approval' ? 'WAITING FOR YOU' : 'CURRENT STEP'}</small><strong>{task.currentStep}{(task.status === 'running' || String(task.status) === 'processing') && <span className="terminal-cursor" aria-hidden="true">▋</span>}</strong></div></div>}
    {task.result && <div className="outcome-box"><strong><CheckCircle2 size={16} /> Outcome</strong><p>{task.result}</p></div>}
    {task.error && <div className="error-box"><strong><AlertCircle size={16} /> What happened</strong><p>{task.error}</p></div>}
    <div className="log-heading"><strong>Execution log</strong><span>{task.logs?.length ?? 0} entries</span></div>
    <div className="log-list">{task.logs?.length ? task.logs.map((log) => <div className="log-item" key={log.id}><span className={`log-dot ${log.kind}`} /><div><div className="log-meta"><strong>{log.kind}</strong><time>{formatDate(log.createdAt)}</time></div><span className="terminal-prefix" aria-hidden="true">{log.kind === 'tool' ? '[OP_RUNNER]' : 'FORGE://SYS_OUT >'}</span><p>{log.message}</p></div></div>) : <div className="log-empty">No execution updates yet. This view refreshes while your task is active.</div>}</div>
    <div className="modal-actions"><button className="button button-quiet" onClick={close}>Close</button>{['queued', 'running'].includes(task.status) && task.currentStep !== 'Running approved command; waiting for operating-system elevation' && <button className="button button-danger" onClick={() => abort(task.id)} disabled={aborting} data-testid="button-abort-task"><StopCircle size={15} />{aborting ? 'Stopping…' : 'Stop task'}</button>}</div>
  </div>}</Modal>;
}

function TasksPage() {
  const qc = useQueryClient();
  const tasksQuery = useListAssistantTasks();
  const [selected, setSelected] = useState<string>();
  const detail = useGetAssistantTask(selected ?? '', { query: { enabled: !!selected, queryKey: getGetAssistantTaskQueryKey(selected ?? ''), refetchInterval: (query) => {
    const item = query.state.data;
    return item && ['running', 'queued', 'awaiting_approval', 'awaiting_confirmation'].includes(item.status) ? 2500 : false;
  } } });
  const abort = useAbortAssistantTask();
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const options = ['all', 'running', 'queued', 'awaiting_confirmation', 'awaiting_approval', 'completed', 'failed', 'cancelled'];
  const tasks = useMemo(() => (tasksQuery.data ?? []).filter((task) => (filter === 'all' || task.status === filter) && task.objective.toLowerCase().includes(search.toLowerCase())), [tasksQuery.data, filter, search]);
  return <AppShell page="tasks"><div className="content-page enter">
    <PageHeading eyebrow="EXECUTION LOG" title="Task activity" description="A clear view of every request, from first thought to finished result." right={<Link href="/" className="button button-primary" data-testid="link-new-task"><Plus size={16} /> New task</Link>} />
    <div className="task-overview-strip"><div><span className="strip-icon"><Activity size={17} /></span><div><strong>Every step, in view</strong><span>Open any task to follow its execution log.</span></div></div><span className="live-label"><span className="online-pip" />LIVE UPDATES</span></div>
      <section className="panel tasks-table-panel"><div className="list-toolbar"><div className="filter-pills">{options.map((option) => <button key={option} onClick={() => setFilter(option)} className={`filter-pill ${filter === option ? 'selected' : ''}`} data-testid={`filter-task-${option}`}>{option === 'all' ? 'All tasks' : option === 'awaiting_confirmation' ? 'Awaiting confirmation' : option === 'awaiting_approval' ? 'Approval needed' : option}</button>)}</div><label className="search-box"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tasks" aria-label="Search tasks" data-testid="input-search-tasks" /></label></div>
      {tasksQuery.isLoading ? <div className="table-loading"><Skeleton rows={7} /></div> : tasksQuery.isError ? <QueryProblem retry={() => tasksQuery.refetch()} /> : tasks.length ? <div className="full-task-list">{tasks.map((task) => <TaskStatusLine key={task.id} task={task} onClick={() => setSelected(task.id)} />)}</div> : <div className={`empty-state task-queue-empty ${search || filter !== 'all' ? 'no-match' : 'queue-empty'}`} data-testid="status-task-list-empty"><div className="empty-mark"><Activity size={20} /></div><strong>{search || filter !== 'all' ? 'No matching tasks' : '[ QUEUE_EMPTY // 0 ACTIVE_OPERATIONS ]'}</strong><p>{search || filter !== 'all' ? 'Try another search or status filter.' : 'Awaiting task dispatch from command center.'}</p>{!search && filter === 'all' && <Link href="/" className="button button-primary button-small" data-testid="link-first-task"><Plus size={14} /> [ + DISPATCH_TASK ]</Link>}</div>}
    </section>
    {selected && <TaskDetailDialog task={detail.data} loading={detail.isLoading} error={detail.isError} retry={() => detail.refetch()} close={() => setSelected(undefined)} abort={(id) => abort.mutate({ id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } })} aborting={abort.isPending} />}
  </div></AppShell>;
}

function safePreviewUrl(value?: string | null) {
  if (!value) return '';
  try {
    const parsed = new URL(value, window.location.origin);
    const previewPath = parsed.pathname.startsWith('/api/workspace/preview/static/')
      || parsed.pathname.startsWith('/api/workspace/preview/server/');
    return parsed.origin === window.location.origin
      && (parsed.protocol === 'http:' || parsed.protocol === 'https:')
      && !parsed.username
      && !parsed.password
      && previewPath
      ? parsed.href
      : '';
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
  const [navigatedUrl, setNavigatedUrl] = useState('');
  const [addressValue, setAddressValue] = useState('');
  const [addressError, setAddressError] = useState(false);
  const preview = previewQuery.data;
  const apps = preview?.apps ?? [];
  const selectionExists = selectedId === 'static' ? !!preview?.staticAvailable : apps.some((app) => app.id === selectedId);
  const activeId = selectionExists ? selectedId : preview?.staticAvailable ? 'static' : apps[0]?.id ?? '';
  const activeApp = apps.find((app) => app.id === activeId);
  const rawUrl = activeId === 'static' ? preview?.staticPreviewUrl : activeApp?.previewUrl;
  const iframeUrl = safePreviewUrl(navigatedUrl || rawUrl);
  const label = activeId === 'static' ? 'Workspace preview' : activeApp?.entryPath ?? 'Running app';
  useEffect(() => {
    const nextUrl = safePreviewUrl(rawUrl);
    setNavigatedUrl(nextUrl);
    setAddressValue(nextUrl);
    setAddressError(false);
  }, [activeId, rawUrl]);
  useEffect(() => {
    const stopRunningPreviews = () => {
      if (!navigator.sendBeacon) return;
      const body = new Blob([], { type: 'text/plain' });
      navigator.sendBeacon('/api/workspace/preview/stop-all', body);
    };
    window.addEventListener('pagehide', stopRunningPreviews);
    return () => {
      window.removeEventListener('pagehide', stopRunningPreviews);
      stopRunningPreviews();
    };
  }, []);
  const navigateToAddress = (event: FormEvent) => {
    event.preventDefault();
    const nextUrl = safePreviewUrl(addressValue);
    if (!nextUrl) {
      setAddressError(true);
      return;
    }
    setNavigatedUrl(nextUrl);
    setAddressValue(nextUrl);
    setAddressError(false);
    setRefreshKey((current) => current + 1);
  };
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
        : !preview?.staticAvailable && apps.length === 0 ? <div className="preview-state preview-empty"><div className="preview-empty-art"><span /><span /><span /><div className="preview-holo-terminal" aria-hidden="true"><i /><i /><i /><i /></div></div><strong>No preview yet</strong><p>{preview?.pythonPreviewsEnabled ? 'Create a Python web app in the workspace and launch it with the assistant to preview it here.' : 'Create workspace/index.html for a static preview. Local Python app previews can be enabled in Preferences; they are always disabled in Replit.'}</p></div>
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
          <form className="preview-address" onSubmit={navigateToAddress} data-testid="form-preview-address">
            <span className="address-lock"><ShieldCheck size={14} /></span>
            <input aria-label="Preview address" aria-invalid={addressError} value={addressValue} onChange={(event) => { setAddressValue(event.target.value); setAddressError(false); }} spellCheck={false} data-testid="input-preview-address" />
            <button type="submit" data-testid="button-go-preview">Go</button>
          </form>
          {iframeUrl && <a className="button button-quiet button-small preview-open" href={iframeUrl} target="_blank" rel="noopener noreferrer" data-testid="link-open-preview"><ExternalLink size={14} /> Open in New Tab</a>}
        </div>
        {addressError && <p className="preview-address-error" role="alert" data-testid="status-preview-address-error">Enter a same-origin workspace preview URL.</p>}
        <div className="preview-frame-shell" data-testid="preview-frame-shell">
          {iframeUrl ? <iframe key={`${activeId}-${refreshKey}-${iframeUrl}`} title={`${label} live preview`} className="preview-frame" src={iframeUrl} sandbox="allow-scripts allow-forms" referrerPolicy="same-origin" data-testid="iframe-live-preview" />
            : <div className="preview-state preview-unavailable"><div className="preview-state-icon"><LockKeyhole size={19} /></div><strong>This preview address can’t be opened safely</strong><p>Only workspace addresses on this site can be loaded here.</p></div>}
        </div>
      </>}
    {stopApp.isError && <div className="preview-stop-error" role="alert" data-testid="status-stop-preview-error">The app could not be stopped. Refresh the preview list and try again.</div>}
  </section>;
}

function WorkspaceInspector() {
  const filesQuery = useListAssistantFiles();
  const files = filesQuery.data ?? [];
  const [selectedId, setSelectedId] = useState('');
  const selected = files.find((file) => file.id === selectedId) ?? files[0];
  const [copied, setCopied] = useState(false);
  const lines = (selected?.extractedText ?? '').split('\n');
  const language = selected?.name.split('.').pop()?.toLowerCase() ?? 'text';
  return <div className="workspace-inspector" data-testid="workspace-inspector">
    <div className="inspector-files">
      <div className="inspector-section-label"><FolderOpen size={14} /> WORKSPACE FILES</div>
      {filesQuery.isLoading ? <Skeleton rows={4} /> : filesQuery.isError ? <QueryProblem retry={() => filesQuery.refetch()} /> : files.length ? files.map((file) =>
        <button key={file.id} className={`inspector-file ${selected?.id === file.id ? 'selected' : ''}`} onClick={() => setSelectedId(file.id)} data-testid={`button-inspector-file-${file.id}`}>
          <FileText size={14} /><span>{file.name}</span><small>{formatSize(file.sizeBytes)}</small>
        </button>) : <div className="inspector-empty">No workspace files yet.</div>}
    </div>
    <div className="inspector-file-preview">
      {selected ? <>
        <div className="inspector-file-heading"><div><strong>{selected.name}</strong><span>{language.toUpperCase()} · {lines.length} lines</span></div><button className="icon-button" aria-label="Copy file contents" onClick={() => { void navigator.clipboard?.writeText(selected.extractedText).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); }); }} data-testid="button-copy-inspector-file"><Copy size={14} /></button></div>
        {copied && <span className="copy-feedback" role="status" data-testid="status-file-copied">Copied</span>}
        <pre className={`file-code lang-${language}`} data-testid="code-inspector-file"><code>{lines.map((line, index) => <span className="code-line" key={index}><i>{index + 1}</i><span>{line.split(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\/\/.*$|#.*$|\b(?:const|let|var|function|return|import|from|if|else|class|def|for|while|async|await|export|true|false|null|None)\b)/g).map((token, part) => {
          const cls = /^["']/.test(token) ? 'syntax-string' : /^(\/\/|#)/.test(token) ? 'syntax-comment' : /^(const|let|var|function|return|import|from|if|else|class|def|for|while|async|await|export|true|false|null|None)$/.test(token) ? 'syntax-keyword' : '';
          return <span className={cls} key={part}>{token}</span>;
        })}</span></span>)}</code></pre>
      </> : <div className="inspector-empty-preview"><FileText size={22} /><strong>Select a file</strong><span>Choose a workspace file to inspect its extracted contents.</span></div>}
    </div>
  </div>;
}

function InspectorPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'preview' | 'files'>('preview');
  useEffect(() => {
    const showPreview = () => setTab('preview');
    window.addEventListener('morrow:show-preview', showPreview);
    return () => window.removeEventListener('morrow:show-preview', showPreview);
  }, []);
  return <aside className="right-inspector" aria-label="Workspace inspector" data-testid="right-inspector">
    <div className="inspector-heading"><div><span className="eyebrow">INSPECTOR</span><strong>Workspace</strong></div><button className="icon-button" onClick={onClose} aria-label="Close inspector" data-testid="button-close-inspector"><X size={16} /></button></div>
    <div className="inspector-tabs" role="tablist" aria-label="Inspector views">
      <button role="tab" aria-selected={tab === 'preview'} className={tab === 'preview' ? 'active' : ''} onClick={() => setTab('preview')} data-testid="tab-inspector-live-preview">Live Preview</button>
      <button role="tab" aria-selected={tab === 'files'} className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')} data-testid="tab-workspace-inspector">Workspace Inspector</button>
    </div>
    <div className="inspector-content">{tab === 'preview' ? <WorkspacePreview /> : <WorkspaceInspector />}</div>
  </aside>;
}

function WorkspacePage() {
  const qc = useQueryClient();
  const notesQuery = useListAssistantNotes();
  const filesQuery = useListAssistantFiles();
  const downloadWorkspace = useDownloadAssistantWorkspace({ query: { enabled: false, queryKey: getDownloadAssistantWorkspaceQueryKey() } });
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
  const [downloadError, setDownloadError] = useState('');
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
  const onDownload = async () => {
    setDownloadError('');
    const result = await downloadWorkspace.refetch();
    if (result.isError || !result.data) {
      setDownloadError('Workspace archive is unavailable. Check the connection and retry.');
      return;
    }
    const url = URL.createObjectURL(result.data);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'forge-workspace.zip';
    anchor.click();
    URL.revokeObjectURL(url);
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
    <PageHeading eyebrow="REFERENCE LIBRARY" title="Workspace" description="Files and notes your agent can draw on when the context matters." right={<><button className="button button-quiet" onClick={() => void onDownload()} disabled={downloadWorkspace.isFetching} data-testid="button-download-workspace"><ArrowDownToLine size={15} /> {downloadWorkspace.isFetching ? 'Preparing ZIP…' : 'Download ZIP'}</button><label className={`button button-quiet ${uploading ? 'disabled' : ''}`} htmlFor="workspace-upload" data-testid="button-upload-file"><Upload size={15} />{uploading ? 'Uploading…' : 'Upload file'}<input id="workspace-upload" type="file" hidden disabled={uploading} onChange={(e) => { void onUpload(e.currentTarget.files?.[0]); e.currentTarget.value = ''; }} /></label><button className="button button-primary" onClick={() => setNoteOpen(true)} data-testid="button-new-note"><Plus size={16} /> New note</button></>} />
    <div className="library-intro info-banner" role="note" data-testid="status-workspace-context-tip"><div className="library-graphic"><div className="graphic-file"><FileText size={22} /></div><div className="graphic-note"><BookOpen size={19} /></div><div className="graphic-orbit" /></div><div><strong>A little context goes a long way.</strong><p>Keep source material and useful details close. Your agent can reference uploaded files and saved notes in future work.</p></div></div>
    {uploadError && <div className="inline-error"><AlertCircle size={15} />{uploadError}<button onClick={() => setUploadError('')} aria-label="Dismiss upload error"><X size={14} /></button></div>}
    {downloadError && <div className="inline-error" role="alert" data-testid="status-download-error"><AlertCircle size={15} />{downloadError}<button onClick={() => setDownloadError('')} aria-label="Dismiss download error"><X size={14} /></button></div>}
    <section className="panel library-panel"><div className="library-toolbar"><div className="library-tabs"><button onClick={() => setTab('files')} className={tab === 'files' ? 'active' : ''} data-testid="tab-files"><FileText size={15} /> Files <span>{filesQuery.data?.length ?? 0}</span></button><button onClick={() => setTab('notes')} className={tab === 'notes' ? 'active' : ''} data-testid="tab-notes"><BookOpen size={15} /> Notes <span>{notesQuery.data?.length ?? 0}</span></button><button onClick={() => { setTab('preview'); window.dispatchEvent(new Event('morrow:open-preview-inspector')); }} className={tab === 'preview' ? 'active' : ''} data-testid="tab-live-preview"><Layers3 size={15} /> Live Preview</button></div>{tab !== 'preview' && <label className="search-box"><Search size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={`Search ${tab}`} aria-label={`Search ${tab}`} data-testid="input-search-library" /></label>}</div>
      {tab === 'preview' ? <div className="preview-in-inspector"><div className="preview-state-icon"><Layers3 size={20} /></div><strong>Live preview is open in the inspector</strong><p>Refresh, navigate, and stop preview apps from the right-side workspace panel.</p><button className="button button-primary button-small" onClick={() => window.dispatchEvent(new Event('morrow:open-preview-inspector'))} data-testid="button-open-preview-inspector"><PanelRight size={14} /> Show inspector</button></div> : <>
      {tab === 'files' ? filesQuery.isLoading ? <div className="library-loading"><Skeleton rows={4} /></div> : filesQuery.isError ? <QueryProblem retry={() => filesQuery.refetch()} /> : filteredFiles.length ? <div className="file-list">{filteredFiles.map((file) => <div className="file-row" key={file.id}><span className="file-type-icon"><FileText size={18} /></span><div className="file-main"><strong>{file.name}</strong><span>{file.mimeType || 'Document'} <i /> {formatSize(file.sizeBytes)}</span></div><span className="file-added">{timeAgo(file.createdAt)}</span><div className="row-actions"><button onClick={() => setSelectedFile(file)} className="icon-button" aria-label={`Preview ${file.name}`} data-testid={`button-preview-file-${file.id}`}><ArrowDownToLine size={16} /></button><button onClick={() => removeFile(file)} className="icon-button danger-hover" aria-label={`Delete ${file.name}`} data-testid={`button-delete-file-${file.id}`}><Trash2 size={16} /></button></div></div>)}</div> : <div className="empty-state"><div className="empty-mark"><Upload size={19} /></div><strong>{search ? 'No files found' : 'Start with a source file'}</strong><p>{search ? 'Try a different name.' : 'Upload a document, PDF, or text file to give your agent context.'}</p>{!search && <label htmlFor="workspace-upload" className="button button-primary button-small"><Upload size={14} /> Upload your first file</label>}</div>
      : notesQuery.isLoading ? <div className="library-loading"><Skeleton rows={4} /></div> : notesQuery.isError ? <QueryProblem retry={() => notesQuery.refetch()} /> : filteredNotes.length ? <div className="note-grid">{filteredNotes.map((note) => <article className="note-card" key={note.id}><div className="note-card-top"><span className="note-glyph"><BookOpen size={15} /></span><button className="icon-button danger-hover" aria-label={`Delete ${note.title}`} onClick={() => removeNote(note)} data-testid={`button-delete-note-${note.id}`}><Trash2 size={15} /></button></div><h3>{note.title}</h3><p>{note.content || 'An empty note, ready for useful context.'}</p><div className="note-tags">{note.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><div className="note-card-foot">UPDATED {timeAgo(note.updatedAt).toUpperCase()}</div></article>)}</div> : <div className="empty-state"><div className="empty-mark"><BookOpen size={19} /></div><strong>{search ? 'No notes found' : 'Nothing noted yet'}</strong><p>{search ? 'Try another search.' : 'Save a detail you want your agent to remember.'}</p>{!search && <button className="button button-primary button-small" onClick={() => setNoteOpen(true)} data-testid="button-first-note"><Plus size={14} /> Write a note</button>}</div>}
      </>}
    </section>
    {noteOpen && <Modal title="Save a note" onClose={() => setNoteOpen(false)}><form className="form-stack" onSubmit={saveNote}><label className="form-label">Title<input value={noteTitle} onChange={(e) => setNoteTitle(e.target.value)} maxLength={300} placeholder="A detail worth remembering" autoFocus data-testid="input-note-title" /></label><label className="form-label">Note<textarea value={noteContent} onChange={(e) => setNoteContent(e.target.value)} maxLength={200000} rows={5} placeholder="Add context, a useful fact, or a thought to keep nearby…" data-testid="input-note-content" /></label><label className="form-label">Tags <span className="optional-label">optional, comma separated</span><input value={noteTags} onChange={(e) => setNoteTags(e.target.value)} placeholder="research, project, follow-up" data-testid="input-note-tags" /></label>{noteError && <p className="field-error">{noteError}</p>}<div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setNoteOpen(false)}>Cancel</button><button className="button button-primary" disabled={createNote.isPending} data-testid="button-save-note">{createNote.isPending ? 'Saving…' : <><Check size={15} /> Save note</>}</button></div></form></Modal>}
    {selectedFile && <Modal title={selectedFile.name} onClose={() => setSelectedFile(undefined)}><div className="file-preview-meta"><span>{selectedFile.mimeType || 'File'}</span><span>{formatSize(selectedFile.sizeBytes)}</span><span>Added {formatDate(selectedFile.createdAt)}</span></div><div className="extracted-text">{selectedFile.extractedText || 'There is no extracted text available for this file.'}</div><div className="modal-actions"><button className="button button-quiet" onClick={() => setSelectedFile(undefined)}>Close</button></div></Modal>}
  </div></AppShell>;
}

const GEMINI_MODEL_IDS = new Set([
  'gemini-3.5-flash-lite',
  'gemini-3.8-flash',
  'gemma-4-31b-it',
]);
const DEEPSEEK_MODEL_IDS = new Set(['deepseek-chat', 'deepseek-reasoner']);

const models = {
  openai: [
    { id: 'gpt-4o', name: 'GPT-4o', detail: 'Multimodal general-purpose model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'gpt-4o-mini', name: 'GPT-4o mini', detail: 'Fast, efficient everyday tasks', descriptor: 'QUICK', color: 'blue' },
    { id: 'o3-mini', name: 'o3-mini', detail: 'Reasoning for technical work', descriptor: 'DEEP FOCUS', color: 'gold' },
  ],
  deepseek: [
    { id: 'deepseek-chat', name: 'deepseek-chat', detail: 'Default · Balanced V3/V4-Flash mode · Tool calling', descriptor: 'BALANCED', color: 'sage' },
    { id: 'deepseek-reasoner', name: 'deepseek-reasoner', detail: 'Thinking mode for complex logic and math', descriptor: 'DEEP FOCUS', color: 'gold' },
  ],
  gemini: [
    { id: 'gemini-3.5-flash-lite', name: 'Gemini 3.5 Flash Lite', detail: 'Default · Budget-first', descriptor: 'QUICK', color: 'blue' },
    { id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash', detail: 'High-capability Flash model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'gemma-4-31b-it', name: 'Gemma 4 31B', detail: 'Google open-weight model', descriptor: 'BALANCED', color: 'sage' },
  ],
  openrouter: [
    { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat (OpenRouter)', detail: 'Balanced tool-calling model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'anthropic/claude-3.7-sonnet', name: 'Claude 3.7 Sonnet', detail: 'High reasoning for demanding tasks', descriptor: 'DEEP FOCUS', color: 'gold' },
    { id: 'anthropic/claude-haiku-5.5', name: 'Claude Haiku 5.5', detail: 'Fast model for everyday tasks', descriptor: 'QUICK', color: 'blue' },
    { id: 'anthropic/claude-sonnet-5.5', name: 'Claude Sonnet 5.5', detail: 'Balanced model for broader work', descriptor: 'BALANCED', color: 'sage' },
    { id: 'anthropic/claude-opus-5.5', name: 'Claude Opus 5.5', detail: 'More capacity for demanding tasks', descriptor: 'DEEP FOCUS', color: 'gold' },
  ],
  ollama: [
    { id: 'qwen2.5-coder', name: 'qwen2.5-coder', detail: 'Local coding model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'llama3.3', name: 'llama3.3', detail: 'Local general-purpose model', descriptor: 'QUICK', color: 'blue' },
    { id: 'deepseek-r1', name: 'deepseek-r1', detail: 'Local reasoning model', descriptor: 'DEEP FOCUS', color: 'gold' },
  ],
} as const;

function SettingsPage() {
  const qc = useQueryClient();
  const settingsQuery = useGetAssistantSettings();
  const updateSettings = useUpdateAssistantSettings();
  const applyModel = useApplyAssistantModel();
  const saveVault = useSaveAssistantProviderKeys();
  const [provider, setProvider] = useState<'openai' | 'deepseek' | 'gemini' | 'openrouter' | 'ollama'>('deepseek');
  const [modelId, setModelId] = useState('deepseek-chat');
  const [customModelId, setCustomModelId] = useState('');
  const [fallbackModelId, setFallbackModelId] = useState('');
  const initialized = useRef(false);
  const credentialStatus = settingsQuery.data;
  const [apiKeys, setApiKeys] = useState({ openaiApiKey: '', deepseekApiKey: '', geminiApiKey: '', openrouterApiKey: '' });
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState('http://localhost:11434/v1');
  const [codeRunnerEnabled, setCodeRunnerEnabled] = useState(false);
  const [appPreviewsEnabled, setAppPreviewsEnabled] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [providerSaved, setProviderSaved] = useState(false);
  const [modelApplied, setModelApplied] = useState('');
  const [confirmBeforeActions, setConfirmBeforeActions] = useState(true);
  const [allowExternalResearch, setAllowExternalResearch] = useState(true);
  const [includeFiles, setIncludeFiles] = useState(true);
  const [saved, setSaved] = useState(false);
  const onSetting = (setter: (value: boolean) => void, value: boolean) => { setter(value); setSaved(false); };
  useEffect(() => {
    const data = settingsQuery.data;
    if (!data || initialized.current) return;
    initialized.current = true;
    setProvider(data.provider);
    setModelId(data.modelId);
    setFallbackModelId(data.fallbackModelId ?? '');
    const isStandardModel = data.provider === 'gemini'
      ? GEMINI_MODEL_IDS.has(data.modelId)
      : data.provider === 'deepseek'
        ? DEEPSEEK_MODEL_IDS.has(data.modelId)
        : models[data.provider].some((item) => item.id === data.modelId);
    setCustomModelId(isStandardModel ? '' : data.modelId);
    setOllamaBaseUrl(data.ollamaBaseUrl || 'http://localhost:11434/v1');
    setCodeRunnerEnabled(data.codeRunnerEnabled);
    setAppPreviewsEnabled(data.appPreviewsEnabled);
  }, [settingsQuery.data]);
  const configured = provider === 'openai'
    ? credentialStatus?.hasOpenaiKey
    : provider === 'deepseek'
      ? credentialStatus?.hasDeepseekKey
    : provider === 'gemini'
      ? credentialStatus?.hasGeminiKey
      : provider === 'openrouter'
        ? credentialStatus?.hasOpenrouterKey
        : credentialStatus?.localSetupAllowed;
  const saveProviderSettings = () => {
    setProviderError('');
    if (!credentialStatus) return;
    const payload: AssistantSettingsInput = { provider: credentialStatus.provider, modelId: credentialStatus.modelId, codeRunnerEnabled, appPreviewsEnabled };
    updateSettings.mutate({ data: payload }, {
      onSuccess: (result: AssistantSettings) => {
        syncSettings(result);
        setSaved(true);
      },
      onError: (error) => setProviderError(settingsError(error)),
    });
  };
  const syncSettings = (result: AssistantSettings) => {
    qc.setQueryData(getGetAssistantSettingsQueryKey(), result);
    void qc.invalidateQueries({ queryKey: getGetAssistantSettingsQueryKey() });
  };
  const settingsError = (error: unknown) => {
    const detail = (error as { data?: { detail?: unknown } })?.data?.detail;
    return typeof detail === 'string' ? detail : 'Settings could not be saved. Check the connection and try again.';
  };
  const saveKeys = () => {
    setProviderError('');
    setProviderSaved(false);
    saveVault.mutate({ data: { ...Object.fromEntries(Object.entries(apiKeys).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()])), ollamaBaseUrl } }, {
      onSuccess: (result) => {
        syncSettings(result);
        setApiKeys({ openaiApiKey: '', deepseekApiKey: '', geminiApiKey: '', openrouterApiKey: '' });
        setOllamaBaseUrl(result.ollamaBaseUrl || ollamaBaseUrl);
        setProviderSaved(true);
        toast({ title: 'API KEYS SAVED', description: 'Provider status refreshed. Existing blank keys were preserved.' });
      },
      onError: (error) => setProviderError(settingsError(error)),
    });
  };
  const applyWorkingModel = () => {
    setProviderError('');
    const selectedModelId = customModelId.trim() || modelId;
    applyModel.mutate({ data: { provider, modelId: selectedModelId, ...(provider === 'gemini' ? { fallbackModelId: fallbackModelId.trim() } : {}) } }, {
      onSuccess: (result) => {
        syncSettings(result);
        setModelId(result.modelId);
        setModelApplied(result.modelId);
        window.dispatchEvent(new Event('forge:model-applied'));
        toast({ title: `ACTIVE MODEL SET: ${result.modelId}` });
      },
      onError: (error) => setProviderError(settingsError(error)),
    });
  };
  return <AppShell page="settings"><div className="content-page settings-page enter">
    <section className="settings-section theme-settings"><div className="settings-section-heading"><div><h2>Appearance</h2><p>Choose the command center color system.</p></div><ThemeChooser /></div></section>
    <PageHeading eyebrow="AGENT CONFIGURATION" title="Preferences" description="Choose how your agent works and where it should pause for your approval." />
    {settingsQuery.isLoading && <div className="settings-section" aria-label="Loading provider preferences" data-testid="status-settings-loading"><Skeleton rows={3} /></div>}
    {settingsQuery.isError && <div data-testid="status-settings-connection-error"><QueryProblem retry={() => { void settingsQuery.refetch(); }} message="Provider preferences are disconnected. Your saved configuration remains untouched." /></div>}
    <section className="settings-section model-section"><div className="settings-section-heading"><div className="section-symbol"><Zap size={17} /></div><div><h2>ACTIVE WORKING MODEL</h2><p>Choose which provider and model will run new tasks.</p></div></div>
      <label className="form-label provider-select-label">ACTIVE AI PROVIDER<select className="provider-hud-select" value={provider} onChange={(event) => { const next = event.target.value as typeof provider; setProvider(next); setModelId(models[next][0].id); setCustomModelId(''); setProviderSaved(false); }} data-testid="select-model-provider"><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="gemini">Google Gemini</option><option value="openrouter">OpenRouter</option><option value="ollama" disabled={!credentialStatus?.localSetupAllowed}>Ollama / Local{!credentialStatus?.localSetupAllowed ? ' (localhost only)' : ''}</option></select></label>
      <label className="form-label model-choice-label">WORKING MODEL<select className="provider-hud-select model-hud-select" value={`${provider}::${customModelId ? 'custom' : modelId}`} onChange={(event) => { const [nextProvider, nextModel] = event.target.value.split('::'); if (nextProvider in models && (nextProvider !== 'ollama' || credentialStatus?.localSetupAllowed)) { const next = nextProvider as typeof provider; setProvider(next); if (nextModel === 'custom') { setCustomModelId(customModelId || modelId); } else { setModelId(nextModel); setCustomModelId(''); } setProviderSaved(false); } }} data-testid="select-active-model">
        {Object.entries(models).map(([groupProvider, items]) => groupProvider === 'ollama' && !credentialStatus?.localSetupAllowed ? null : <optgroup key={groupProvider} label={groupProvider === 'gemini' ? 'Google Gemini' : groupProvider === 'openrouter' ? 'OpenRouter' : groupProvider === 'ollama' ? 'Local · Ollama' : groupProvider === 'openai' ? 'OpenAI' : 'DeepSeek'}>{items.map((item) => <option key={item.id} value={`${groupProvider}::${item.id}`}>{item.name}</option>)}<option value={`${groupProvider}::custom`}>Custom model name…</option></optgroup>)}
      </select></label>
      <label className="form-label custom-model-control">Custom Model Name <span className="optional-label">Optional; overrides the model selected above.</span><input type="text" autoComplete="off" spellCheck={false} value={customModelId} onChange={(event) => { setCustomModelId(event.target.value); setProviderSaved(false); }} placeholder={provider === 'gemini' ? 'e.g. gemini-3.1-pro-preview' : 'Enter a provider model ID'} data-testid="input-custom-model-id" /></label>
      {provider === 'gemini' && <label className="form-label custom-model-control">Automatic fallback model <span className="optional-label">Optional; retry once after a Gemini 429 or 503. Leave blank to disable.</span><input type="text" autoComplete="off" spellCheck={false} value={fallbackModelId} onChange={(event) => { setFallbackModelId(event.target.value); setProviderSaved(false); }} placeholder="e.g. gemini-3.5-flash-lite" data-testid="input-gemini-fallback-model-id" /></label>}
      <p className="settings-footnote"><LockKeyhole size={13} /> {provider === 'ollama' ? 'Local Ollama endpoint selected.' : configured ? 'Provider key configured.' : 'Add a provider key to run tasks.'} Keys are never sent back to the browser.</p>
      <div className="settings-save-row model-apply-row"><span className="save-state" role="status">{modelApplied === (customModelId.trim() || modelId) && <><CheckCircle2 size={15} /> ACTIVE MODEL SET: {modelApplied}</>}</span><button type="button" className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || applyModel.isPending || saveVault.isPending || updateSettings.isPending} onClick={applyWorkingModel} data-testid="button-apply-model">{applyModel.isPending ? <LoaderCircle className="spin" size={15} /> : <Zap size={15} />}{applyModel.isPending ? 'APPLYING…' : 'APPLY MODEL'}</button></div>
    </section>
    <section className="settings-section key-vault" data-testid="settings-api-keys-vault">
      <div className="settings-section-heading"><div className="section-symbol"><KeyRound size={17} /></div><div><h2>API KEYS VAULT</h2><p>Credentials stay local. Saved values are never shown or prefilled.</p></div><span className={`connection-state ${credentialStatus?.providerSettingsAllowed ? 'connected' : 'disconnected'}`} data-testid="status-provider-settings-access">{credentialStatus?.providerSettingsAllowed ? 'KEY STORAGE AVAILABLE' : 'KEY STORAGE RESTRICTED'}</span></div>
      <form className="key-vault-form" onSubmit={(event) => { event.preventDefault(); saveKeys(); }}><div className="key-vault-grid">
        <label className="form-label">DeepSeek API key <span className={`key-status ${credentialStatus?.hasDeepseekKey ? 'active' : ''}`}>{credentialStatus?.hasDeepseekKey ? 'ACTIVE KEY' : 'NO KEY'}</span><span className="optional-label">{credentialStatus?.hasDeepseekKey ? 'Blank keeps existing key' : 'Optional · not configured'}</span><input type="password" autoComplete="new-password" value={apiKeys.deepseekApiKey} onChange={(event) => { setApiKeys({ ...apiKeys, deepseekApiKey: event.target.value }); setProviderSaved(false); }} placeholder="Enter sk-…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-deepseek-api-key" /></label>
        <label className="form-label">Gemini API key <span className={`key-status ${credentialStatus?.hasGeminiKey ? 'active' : ''}`}>{credentialStatus?.hasGeminiKey ? 'ACTIVE KEY' : 'NO KEY'}</span><span className="optional-label">{credentialStatus?.hasGeminiKey ? 'Blank keeps existing key' : 'Optional · not configured'}</span><input type="password" autoComplete="new-password" value={apiKeys.geminiApiKey} onChange={(event) => { setApiKeys({ ...apiKeys, geminiApiKey: event.target.value }); setProviderSaved(false); }} placeholder="Enter AIza…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-gemini-api-key" /></label>
        <label className="form-label">OpenAI API key <span className={`key-status ${credentialStatus?.hasOpenaiKey ? 'active' : ''}`}>{credentialStatus?.hasOpenaiKey ? 'ACTIVE KEY' : 'NO KEY'}</span><span className="optional-label">{credentialStatus?.hasOpenaiKey ? 'Blank keeps existing key' : 'Optional · not configured'}</span><input type="password" autoComplete="new-password" value={apiKeys.openaiApiKey} onChange={(event) => { setApiKeys({ ...apiKeys, openaiApiKey: event.target.value }); setProviderSaved(false); }} placeholder="Enter sk-…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-openai-api-key" /></label>
        <label className="form-label">OpenRouter / Custom Endpoint key <span className={`key-status ${credentialStatus?.hasOpenrouterKey ? 'active' : ''}`}>{credentialStatus?.hasOpenrouterKey ? 'ACTIVE KEY' : 'NO KEY'}</span><span className="optional-label">{credentialStatus?.hasOpenrouterKey ? 'Blank keeps existing key' : 'Optional · not configured'}</span><input type="password" autoComplete="new-password" value={apiKeys.openrouterApiKey} onChange={(event) => { setApiKeys({ ...apiKeys, openrouterApiKey: event.target.value }); setProviderSaved(false); }} placeholder="Enter key…" disabled={!credentialStatus?.providerSettingsAllowed} data-testid="input-openrouter-api-key" /></label>
        <label className="form-label">Ollama / Local Base URL <span className="key-status local">LOCAL</span><span className="optional-label">OpenAI-compatible local endpoint</span><input type="url" value={ollamaBaseUrl} onChange={(event) => { setOllamaBaseUrl(event.target.value); setProviderSaved(false); }} placeholder="http://localhost:11434/v1" disabled={!credentialStatus?.providerSettingsAllowed || !credentialStatus?.localSetupAllowed} data-testid="input-ollama-base-url" /></label>
      </div></form>
      <p className="settings-footnote"><LockKeyhole size={13} /> Blank key fields mean “keep existing key”. Key values are never returned to this screen.</p>
      {providerError && <p className="field-error" role="alert" data-testid="status-provider-save-error">{providerError}</p>}
      {providerSaved && <p className="save-state" role="status" data-testid="status-provider-saved"><CheckCircle2 size={15} /> Provider settings saved. Key values remain hidden.</p>}
      <div className="settings-save-row"><span className="settings-footnote">Keys and local URL save independently. Use Apply Model to activate a model.</span><button type="button" className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || saveVault.isPending || applyModel.isPending || updateSettings.isPending} onClick={saveKeys} data-testid="button-save-provider"><Check size={15} /> {saveVault.isPending ? 'Saving…' : 'Save Keys'}</button></div>
    </section>
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Local code runner</h2><p>Optional Python execution in the local workspace, disabled by default.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><KeyRound size={16} /></div><div className="setting-copy"><strong>Allow safe workspace commands</strong><span>Local-only and off by default. Only read-only commands are supported, restricted to workspace files, and limited to 30 seconds.</span></div><button className={`switch ${codeRunnerEnabled ? 'on' : ''}`} role="switch" aria-checked={codeRunnerEnabled} disabled={!credentialStatus?.localSetupAllowed} onClick={() => { setCodeRunnerEnabled(!codeRunnerEnabled); setProviderSaved(false); }} aria-label="Allow safe workspace commands" data-testid="switch-local-code-runner"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><ShieldCheck size={16} /></div><div className="setting-copy"><strong>Enable Local App Previews (Unrestricted Workspace Execution)</strong><span>When enabled on localhost, Flask, Streamlit, and FastAPI apps can run from workspace/ with a cleaned environment and a one-hour runtime limit. Closing the Live Preview tab stops the child processes.</span><p className="settings-footnote" role="note">Running generated Python apps executes code with standard local user permissions.</p></div><button className={`switch ${appPreviewsEnabled ? 'on' : ''}`} role="switch" aria-checked={appPreviewsEnabled} disabled={!credentialStatus?.localSetupAllowed} onClick={() => { setAppPreviewsEnabled(!appPreviewsEnabled); setProviderSaved(false); }} aria-label="Enable Local App Previews (Unrestricted Workspace Execution)" data-testid="switch-local-app-previews"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><Bell size={16} /></div><div className="setting-copy"><strong>Desktop notifications</strong><span>Show browser notifications when a scheduled reminder fires.</span></div><button className="button button-quiet button-small" onClick={() => { if ('Notification' in window) void Notification.requestPermission(); }} data-testid="button-enable-notifications">Enable alerts</button></div>
      {!credentialStatus?.localSetupAllowed && <p className="settings-footnote"><LockKeyhole size={13} /> Python app previews and workspace commands can only be enabled from a localhost copy of the app. Replit Cloud keeps Python previews disabled.</p>}
    </section>
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Safety &amp; permissions</h2><p>Make your boundaries explicit. Change these any time.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><CheckCircle2 size={16} /></div><div className="setting-copy"><strong>Confirm before consequential actions</strong><span>Pause and ask before an action that changes or sends something.</span></div><button className={`switch ${confirmBeforeActions ? 'on' : ''}`} role="switch" aria-checked={confirmBeforeActions} onClick={() => onSetting(setConfirmBeforeActions, !confirmBeforeActions)} aria-label="Confirm before consequential actions" data-testid="switch-confirm-actions"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><Search size={16} /></div><div className="setting-copy"><strong>Allow external research</strong><span>Let the agent consult public sources when research needs it.</span></div><button className={`switch ${allowExternalResearch ? 'on' : ''}`} role="switch" aria-checked={allowExternalResearch} onClick={() => onSetting(setAllowExternalResearch, !allowExternalResearch)} aria-label="Allow external research" data-testid="switch-external-research"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><FileText size={16} /></div><div className="setting-copy"><strong>Use workspace files as context</strong><span>Allow saved documents and notes to inform relevant tasks.</span></div><button className={`switch ${includeFiles ? 'on' : ''}`} role="switch" aria-checked={includeFiles} onClick={() => onSetting(setIncludeFiles, !includeFiles)} aria-label="Use workspace files as context" data-testid="switch-workspace-context"><span /></button></div>
    </section>
    <div className="settings-save-row"><div className="save-state">{saved && <><CheckCircle2 size={15} /> Preferences updated.</>}</div><button className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || updateSettings.isPending || saveVault.isPending || applyModel.isPending} onClick={saveProviderSettings} data-testid="button-save-settings"><Check size={15} /> Save preferences</button></div>
    <div className="settings-note"><LockKeyhole size={15} /><div><strong>Your work stays yours.</strong><p>These controls guide the agent; it will never claim to have completed work until a task reports an outcome.</p></div></div>
    <TimersManager />
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
    {deleteTimer.isError && <div className="inline-error" role="alert" data-testid="status-delete-reminder-error"><AlertCircle size={15} />Reminder could not be dismissed. Check the connection and retry.</div>}
    {timerQuery.isLoading ? <Skeleton rows={2} /> : timerQuery.isError ? <QueryProblem retry={() => timerQuery.refetch()} /> : timers.length ? <div className="reminder-list">{timers.map((timer: AssistantTimer) => <div className="reminder-row" key={timer.id}><span className={`reminder-icon ${timer.kind}`}><Clock3 size={16} /></span><div className="reminder-copy"><strong>{timer.label}</strong><span>{timer.kind} <i /> {formatDate(timer.scheduledFor)}</span></div><StatusPill status={timer.status} />{timer.status !== 'dismissed' && <button className="icon-button danger-hover" aria-label={`Dismiss ${timer.label}`} onClick={() => deleteTimer.mutate({ id: timer.id }, { onSuccess: () => { qc.invalidateQueries({ queryKey: getListAssistantTimersQueryKey() }); qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() }); } })} data-testid={`button-delete-timer-${timer.id}`}><X size={16} /></button>}</div>)}</div> : <div className="empty-inline"><Clock3 size={16} /><span>No reminders set. Add one when a task needs a nudge.</span></div>}
    {open && <Modal title="Add a reminder" onClose={() => setOpen(false)}><form className="form-stack" onSubmit={onCreate}><label className="form-label">What should you remember?<input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} placeholder="Follow up on the proposal" autoFocus data-testid="input-reminder-label" /></label><div className="form-label">Reminder type<div className="segmented-control"><button type="button" className={kind === 'countdown' ? 'selected' : ''} onClick={() => setKind('countdown')} data-testid="button-kind-countdown"><Clock3 size={14} /> Countdown</button><button type="button" className={kind === 'alarm' ? 'selected' : ''} onClick={() => setKind('alarm')} data-testid="button-kind-alarm"><Bell size={14} /> Scheduled</button></div></div><label className="form-label">When<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} data-testid="input-reminder-time" /></label><label className="form-label">Repeat<select value={recurrence} onChange={(e) => setRecurrence(e.target.value as typeof recurrence)} data-testid="select-reminder-recurrence"><option value="none">Does not repeat</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>{error && <p className="field-error">{error}</p>}<div className="modal-actions"><button type="button" className="button button-quiet" onClick={() => setOpen(false)}>Cancel</button><button className="button button-primary" disabled={createTimer.isPending} data-testid="button-save-reminder">{createTimer.isPending ? 'Setting…' : <><Bell size={14} /> Set reminder</>}</button></div></form></Modal>}
  </section>;
}

function AlarmsPage() {
  return <AppShell page="alarms"><div className="content-page enter">
    <PageHeading eyebrow="TIME & REMINDERS" title="Scheduled alarms" description="Set a precise nudge, then let it arrive when it matters." />
    <TimersManager />
  </div></AppShell>;
}

function Router() {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}><Switch>
    <Route path="/" component={Dashboard} />
    <Route path="/tasks" component={TasksPage} />
    <Route path="/workspace" component={WorkspacePage} />
    <Route path="/alarms" component={AlarmsPage} />
    <Route path="/settings" component={SettingsPage} />
    <Route component={NotFound} />
  </Switch></ErrorBoundary>;
}

function App() {
  return <QueryClientProvider client={queryClient}><TooltipProvider><ReminderNotifications /><WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}><ConversationProvider><Router /></ConversationProvider></WouterRouter><Toaster /></TooltipProvider></QueryClientProvider>;
}

export default App;
