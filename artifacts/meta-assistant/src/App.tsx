import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useThreadHistory } from '@/hooks/use-thread-history';
import { SmoothStreamer } from '@/lib/smooth-streamer';
import {
  loadChatModelPreference,
  modeForSavedPreference,
  newestThreadModel,
  saveChatModelPreference,
} from '@/lib/chat-model-preference';
import type { CSSProperties, DragEvent, FormEvent, ReactNode } from 'react';
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
  useGetAssistantSystemPrompt,
  useGetWorkspacePreview,
  useListAssistantFiles,
  useGetConversationThread,
  getGetConversationThreadQueryKey,
  getListConversationThreadsQueryKey,
  useListAssistantNotes,
  useListAssistantTasks,
  useListAssistantTimers,
  useUpdateAssistantSettings,
  useUpdateAssistantSystemPrompt,
  useApplyAssistantModel,
  useGetVaultKeys,
  getGetVaultKeysQueryKey,
  useSaveVaultKeys,
  useStopWorkspacePreviewApp,
  useRetryAssistantTaskStep,
  getGetAssistantDashboardQueryKey,
  getGetAssistantTaskQueryKey,
  getGetAssistantSettingsQueryKey,
  getGetAssistantSystemPromptQueryKey,
  getGetWorkspacePreviewQueryKey,
  getDownloadAssistantWorkspaceQueryKey,
  getListAssistantFilesQueryKey,
  getListAssistantNotesQueryKey,
  getListAssistantTasksQueryKey,
  getListAssistantTimersQueryKey,
} from '@workspace/api-client-react';
import type { AssistantFile, AssistantNote, AssistantSettings, AssistantSettingsInput, AssistantTask, AssistantTimer, SystemPromptUpdate, VaultKeysInput, VaultKeyStatuses, WorkspacePreviewApp } from '@workspace/api-client-react';
import {
  Activity, AlertCircle, ArrowDownToLine, ArrowRight, Bell, BookOpen, Check, CheckCircle2,
  ChevronDown, ChevronRight, CircleHelp, Clock3, Copy, Cpu, ExternalLink, FileText, FolderOpen, Gauge, HardDrive, Layers3, Moon, Sun,
  KeyRound, LoaderCircle, LockKeyhole, Menu, Plus, RefreshCw, Search,
  Send, Settings2, ShieldCheck, Sparkles, StopCircle, Trash2, Upload, X, Zap, PanelRight, GripVertical, Eye, EyeOff, CandlestickChart,
} from 'lucide-react';
import { ConversationProvider, useConversations } from '@/components/conversation-provider';
import { SearchSettingsPanel } from '@/components/search-settings-panel';
import { NewChatAction, RecentSessions } from '@/components/chat-sidebar';
import { ChatModelPicker } from '@/components/chat-model-picker';
import { ActivityStream } from '@/components/activity-stream';
import { ErrorBoundary } from '@/components/error-boundary';
import { RecentFileRows, RecentNoteRows, RecentTaskLogRows } from '@/components/telemetry-records';
import { TradingViewChart } from '@/components/TradingViewChart';
import { AmbientBackground } from '@/components/ambient-background';
import { Toaster } from '@/components/ui/toaster';
import { toast } from '@/hooks/use-toast';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import { getRecentFiles, getRecentNotes, getRecentTaskLogs, timeAgo } from '@/lib/telemetry';

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

function formatDate(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date);
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function modelDisplayName(provider?: string | null, model?: string | null) {
  const knownNames: Record<string, string> = {
    'deepseek-chat': 'DeepSeek Chat',
    'deepseek-reasoner': 'DeepSeek Reasoner',
    'gemini-2.5-flash': 'Gemini 2.5 Flash',
    'gemini-2.5-pro': 'Gemini 2.5 Pro',
    'gemini-4-argon': 'Gemini 4 Argon',
    'gemini-3.8-live': 'Gemini 3.8 Live',
    'gemini-3.8-live-extended-thinking': 'Gemini 3.8 Live Extended Thinking',
    'gemini-3.8-flash-tts': 'Gemini 3.8 Flash TTS',
    'gemini-3.8-flash-lite-tts': 'Gemini 3.8 Flash-Lite TTS',
    'gemini-3.6-flash': 'Gemini 3.6 Flash',
    'gemini-3.5-flash-lite': 'Gemini 3.5 Flash-Lite',
    'gemini-3.8-flash': 'Gemini 3.8 Flash',
    'gemini-3.1-flash-lite': 'Gemini 3.1 Flash-Lite',
    'gemini-nano-banana-2.1': 'Nano Banana 2.1',
    'gemini-3.1-flash-image': 'Nano Banana 2',
    'gemini-3.1-flash-lite-image': 'Nano Banana 2 Lite',
    'gemini-3-pro-image': 'Nano Banana Pro',
    'gemini-3.1-pro-preview': 'Gemini 3.1 Pro',
    'gemini-3-flash-preview': 'Gemini 3 Flash',
    'gemma-4-31b-it': 'Gemma 4 31B',
    'gpt-4o': 'GPT-4o',
    'gpt-4o-mini': 'GPT-4o mini',
    'gpt-4.1': 'GPT-4.1',
    'o3-mini': 'o3-mini',
    'claude-haiku-5-5': 'Claude Haiku 5.5',
    'claude-sonnet-5-5': 'Claude Sonnet 5.5',
    'claude-opus-5-5': 'Claude Opus 5.5',
    'anthropic/claude-3.7-sonnet': 'Claude 3.7 Sonnet',
    'anthropic/claude-haiku-5.5': 'Claude Haiku 5.5',
    'anthropic/claude-sonnet-5.5': 'Claude Sonnet 5.5',
    'anthropic/claude-opus-5.5': 'Claude Opus 5.5',
    'deepseek/deepseek-chat': 'DeepSeek Chat (OpenRouter)',
  };
  if (!model) return 'recommended model';
  return knownNames[model] ?? (provider === 'anthropic' ? `Claude · ${model}` : model);
}

const AUTO_ROUTE_MODES = ['auto-gemini', 'auto-claude', 'auto-openai', 'auto-global'] as const;
type AutoRouteMode = typeof AUTO_ROUTE_MODES[number];
type ResolvedChatModel = {
  provider: AssistantTask['provider'];
  model: string;
  autoRouteMode?: AutoRouteMode;
};
const AUTO_ROUTE_PROVIDERS: Record<AutoRouteMode, AssistantTask['provider']> = {
  'auto-gemini': 'gemini',
  'auto-claude': 'anthropic',
  'auto-openai': 'openai',
  'auto-global': 'gemini',
};
const AUTO_ROUTE_LABELS: Record<AutoRouteMode, string> = {
  'auto-gemini': 'Gemini Auto Select',
  'auto-claude': 'Claude Auto Select',
  'auto-openai': 'OpenAI Auto Select',
  'auto-global': 'Global Auto Select',
};

function isAutoRouteMode(value: string): value is AutoRouteMode {
  return AUTO_ROUTE_MODES.includes(value as AutoRouteMode);
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

// Inspector width bounds track the viewport so the CSS cap and the resizer agree.
function inspectorRange(viewportWidth = typeof window === 'undefined' ? 1400 : window.innerWidth) {
  if (viewportWidth >= 1500) {
    const max = Math.max(500, Math.floor((viewportWidth - 268) * 0.45));
    return { min: 500, max };
  }
  const max = Math.max(320, Math.min(450, Math.floor(viewportWidth * 0.34)));
  return { min: Math.min(380, max), max };
}

function AppShell({ children, page }: { children: ReactNode; page: Page }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('forge-sidebar-collapsed') === 'true'; } catch { return false; }
  });
  const [inspectorOpen, setInspectorOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1600);
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    const width = typeof window === 'undefined' ? 1400 : window.innerWidth;
    return width >= 1500 ? Math.floor((width - 268) * 0.45) : 450;
  });
  const [previewMaximized, setPreviewMaximized] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(() => typeof window === 'undefined' ? 1400 : window.innerWidth);
  const range = inspectorRange(viewportWidth);
  const displayedInspectorWidth = Math.max(range.min, Math.min(range.max, inspectorWidth));
  const [resizingInspector, setResizingInspector] = useState(false);
  const [location] = useLocation();
  const routePage = (location === '/' ? 'home' : location.slice(1)) as Page;
  const current = page || routePage;
  useEffect(() => {
    try { localStorage.setItem('forge-sidebar-collapsed', String(sidebarCollapsed)); } catch { /* Persistence is optional when storage is blocked. */ }
  }, [sidebarCollapsed]);
  useEffect(() => {
    const viewport = window.matchMedia('(min-width: 1600px)');
    const syncViewport = () => {
      const width = window.innerWidth;
      setViewportWidth(width);
      setInspectorWidth(width >= 1500 ? Math.floor((width - 268) * 0.45) : 450);
    };
    const setDefaultDockForBreakpoint = (event: MediaQueryListEvent) => setInspectorOpen(event.matches);
    viewport.addEventListener('change', setDefaultDockForBreakpoint);
    window.addEventListener('resize', syncViewport);
    return () => {
      viewport.removeEventListener('change', setDefaultDockForBreakpoint);
      window.removeEventListener('resize', syncViewport);
    };
  }, []);
  useEffect(() => {
    if (!resizingInspector) return;
    const move = (event: PointerEvent) => { const { min, max } = inspectorRange(); setInspectorWidth(Math.max(min, Math.min(max, window.innerWidth - event.clientX))); };
    const stop = () => setResizingInspector(false);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); };
  }, [resizingInspector]);
  useEffect(() => {
    const openPreview = () => {
      setInspectorOpen(true);
      setPreviewMaximized(false);
      window.dispatchEvent(new Event('morrow:show-preview'));
    };
    window.addEventListener('morrow:open-preview-inspector', openPreview);
    return () => window.removeEventListener('morrow:open-preview-inspector', openPreview);
  }, []);
  const toggleInspector = () => {
    if (inspectorOpen) setPreviewMaximized(false);
    setInspectorOpen((open) => !open);
  };
  const closeInspector = () => {
    setInspectorOpen(false);
    setPreviewMaximized(false);
  };
  const renderNavItem = ({ href, label, icon: Icon }: typeof navItems[number]) => <Link key={href} href={href} className={`nav-link ${current === (href === '/' ? 'home' : href.slice(1)) ? 'active' : ''}`} onClick={() => setMobileOpen(false)} aria-label={label} title={sidebarCollapsed ? label : undefined} data-testid={`link-nav-${href === '/' ? 'home' : href.slice(1)}`}><Icon size={17} /><span>{label}</span>{href === '/tasks' && <span className="nav-trailing"><span className="nav-dot" /></span>}</Link>;
  return <><AmbientBackground /><div className={`app-frame shell-noise ${inspectorOpen ? 'inspector-open' : 'inspector-closed'} ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${previewMaximized ? 'preview-maximized' : ''}`} style={{ '--inspector-width': `${displayedInspectorWidth}px`, ...(sidebarCollapsed && viewportWidth > 900 ? { '--sidebar-w': '64px' } : {}) } as CSSProperties}>
    <aside className={`sidebar ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
      <div className="brand"><div className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M5 9.5 16 4l11 5.5-4.7 2.35L16 9l-6.3 2.85L5 9.5Z" /><path d="m5 9.5 2.8 12L16 27l8.2-5.5L27 9.5" /><path d="m9.7 11.85 1.55 7.1L16 22l4.75-3.05 1.55-7.1" /><path d="m11.25 18.95 4.75-2.6 4.75 2.6M16 9v7.35" /></svg></div><div className="brand-copy"><div className="brand-name">Forge</div><div className="brand-caption">LOCAL OPERATIONS</div></div><span className="runtime-ready-dot" aria-label="Local runtime ready" title="Local runtime ready" /><button className="sidebar-close icon-button" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={17} /></button></div>
      <NewChatAction collapsed={sidebarCollapsed} onPicked={() => setMobileOpen(false)} />
      <div className="workspace-label">YOUR WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {renderNavItem(navItems[0])}
        {current === 'home' && <RecentSessions onPicked={() => setMobileOpen(false)} collapsed={sidebarCollapsed} />}
        {navItems.slice(1).map(renderNavItem)}
      </nav>
      <div className="sidebar-spacer" />
      <div className="agent-card"><div className="agent-orbit"><span /><i /></div><div className="agent-card-copy"><strong>Your agent is ready</strong><span>Waiting for direction</span></div><span className="ready-indicator" /></div>
    </aside>
    {mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close menu" />}
    <main className="main-area">
      <header className={`topbar ${current === 'home' ? 'topbar-command-center' : ''}`}><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)} data-testid="button-open-navigation"><Menu size={20} /></button><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{navItems.find((n) => (n.href === '/' ? 'home' : n.href.slice(1)) === current)?.label ?? 'Overview'}</strong></div><div className="topbar-right"><span className="ops-tagline">LOCAL OPS // 6570</span><div className="system-online"><span className="online-pip" />All systems operational</div><ThemeChooser /><CyberFxToggle /><button type="button" className="icon-button console-toggle" onClick={toggleInspector} aria-label={inspectorOpen ? 'Close telemetry and workspace console' : 'Open telemetry and workspace console'} aria-expanded={inspectorOpen} title={inspectorOpen ? 'Close system console' : 'Open system console'} data-testid="button-toggle-console"><PanelRight size={16} /><span>Console</span></button><button type="button" className="sidebar-collapse-toggle icon-button" onClick={() => setSidebarCollapsed((collapsed) => !collapsed)} aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!sidebarCollapsed} title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} data-testid="button-toggle-sidebar"><ChevronRight size={16} className={sidebarCollapsed ? '' : 'is-expanded'} /></button></div></header>
      <div className={`center-pane ${page === 'home' ? 'center-pane-home' : ''}`}><div className="page-wrap">{children}</div><footer className="app-footer"><span>Made for thoughtful delegation.</span><span className="footer-build">FORGE <span>·</span> LOCAL COMMAND CENTER</span></footer></div>
    </main>
    {inspectorOpen && <div className="inspector-resize" role="separator" aria-orientation="vertical" aria-label="Resize workspace inspector" aria-valuemin={range.min} aria-valuemax={range.max} aria-valuenow={displayedInspectorWidth} tabIndex={0} onPointerDown={(event) => { event.preventDefault(); setResizingInspector(true); }} onKeyDown={(event) => { if (event.key === 'ArrowLeft') setInspectorWidth(Math.min(range.max, displayedInspectorWidth + 10)); if (event.key === 'ArrowRight') setInspectorWidth(Math.max(range.min, displayedInspectorWidth - 10)); }} data-testid="separator-inspector"><GripVertical size={14} /></div>}
    {inspectorOpen && <InspectorPanel onClose={closeInspector} defaultTab={current === 'home' ? 'telemetry' : 'preview'} previewMaximized={previewMaximized} onPreviewMaximizedChange={setPreviewMaximized} />}
  </div></>;
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

function EngineApprovalReview({ task }: { task: AssistantTask }) {
  if (task.pendingApprovalKind !== 'blender_automation' && task.pendingApprovalKind !== 'engine_remote_command') return null;
  const isBlender = task.pendingApprovalKind === 'blender_automation';
  return <div className="engine-approval-review">
    <p>{isBlender
      ? 'This generated Blender Python script runs with your normal local-user permissions. It is not sandboxed and may access or modify any files your account can access.'
      : 'This exact request will be sent to the local engine listener and may change the open Blender scene or Unreal project.'}</p>
    <details open data-testid={`details-engine-approval-${task.id}`}>
      <summary>{isBlender ? 'Review exact Blender script' : 'Review exact endpoint and JSON payload'}</summary>
      <pre>{task.approvalDetails || '(No script or request details were supplied.)'}</pre>
    </details>
    {isBlender && <p className="settings-footnote">The run has a 10-minute timeout. Review the complete script before approving.</p>}
  </div>;
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
  const isBlenderApproval = task.pendingApprovalKind === 'blender_automation';
  const isEngineApproval = task.pendingApprovalKind === 'engine_remote_command';
  const isEngineAction = isBlenderApproval || isEngineApproval;
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
  const isTerminalCommand = task.pendingApprovalKind === 'terminal_command';
  return <section className="action-dock" aria-label="Task decisions" data-testid="task-action-dock">
    <div className="dock-heading"><span className="dock-alert" /><strong>Waiting for your decision</strong><span>{task.objective}</span></div>
    {needsApproval && <div className={`dock-card ${isElevated || isTerminalCommand || isEngineAction ? 'security-warning' : ''}`} data-testid={isElevated ? 'dock-elevated-approval' : isTerminalCommand ? 'dock-terminal-approval' : isBlenderApproval ? 'dock-blender-approval' : isEngineApproval ? 'dock-engine-approval' : 'dock-workspace-approval'}>
      {isElevated ? <><strong>Administrative Privilege Requested:</strong><p>The agent is requesting permission to execute:</p><code>{task.approvalSummary}</code><span> with elevated system permissions.</span><p>Nothing runs until you approve. The invocation will be recorded in <code>logs/elevated_audit.log</code>.</p><p>If pkexec is unavailable, the sudo fallback requires an already-authorized non-interactive sudo session and fails closed otherwise.</p></>
        : isTerminalCommand ? <><strong>Local terminal command needs approval</strong><p>The agent requests to run this exact command with your normal local-user permissions:</p><code>{task.approvalSummary}</code><p>It runs from workspace/ with a cleaned environment and a 30-second limit. It is not elevated, but can still change local files or data. No command has run yet.</p></>
          : isBlenderApproval ? <><strong>Blender automation needs approval</strong><p>{task.approvalSummary}</p><EngineApprovalReview task={task} /></>
            : isEngineApproval ? <><strong>Local engine command needs approval</strong><p>{task.approvalSummary}</p><EngineApprovalReview task={task} /></>
          : <><strong>Workspace action needs your approval</strong><p>{task.approvalSummary} The agent is paused; no change has been made yet.</p></>}
      <div className="model-recommendation-actions"><button className="button button-primary" onClick={() => decide(true)} disabled={approval.isPending} data-testid="button-dock-approve">{approval.isPending ? 'Applying…' : isElevated ? 'Approve & Run with UAC' : isTerminalCommand ? 'Approve & Run' : isBlenderApproval ? 'Approve & Run in Blender' : isEngineApproval ? 'Approve & Send to Engine' : 'Approve and continue'}</button><button className="button button-quiet" onClick={() => decide(false)} disabled={approval.isPending} data-testid="button-dock-reject">{isElevated ? 'Reject Action' : isTerminalCommand ? 'Reject Command' : isEngineAction ? 'Reject 3D action' : 'Reject and continue'}</button></div>
    </div>}
    {needsModel && <div className="dock-card" data-testid="dock-model-recommendation"><strong>Recommendation:</strong><p>This task involves {task.recommendationReason}. Running on a high-capability model like {recommended} may produce better results. Would you like to switch for this task?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => choose(true)} disabled={model.isPending} data-testid="button-dock-switch-model">{model.isPending ? 'Saving choice…' : 'Switch to Recommended Model'}</button><button className="button button-quiet" onClick={() => choose(false)} disabled={model.isPending} data-testid="button-dock-stay-model">Stay on Current Model</button></div></div>}
    {needsFallback && <div className="dock-card security-warning" data-testid="dock-fallback-recommendation"><strong>Task encountered persistent errors on the current model.</strong><p>Would you like to retry this step with {recommended}?</p><div className="model-recommendation-actions"><button className="button button-primary" onClick={() => retryStep(true)} disabled={retry.isPending} data-testid="button-dock-retry-model">{retry.isPending ? 'Starting retry…' : 'Retry this step with Recommended Pro Model'}</button><button className="button button-quiet" onClick={() => retryStep(false)} disabled={retry.isPending} data-testid="button-dock-dismiss-retry">Not now</button></div></div>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}

function Dashboard() {
  const qc = useQueryClient();
  const summary = useGetAssistantDashboard({ query: { queryKey: getGetAssistantDashboardQueryKey(), refetchInterval: 4000 } });
  const createTask = useCreateAssistantTask();
  const conv = useConversations();
  const { selectedId: threadId } = conv;
  const threadDetail = useThreadHistory(threadId);
  const threadStale = (threadDetail.error as { status?: number } | null)?.status === 404;
  const settingsQuery = useGetAssistantSettings();
  const [objective, setObjective] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [liveText, setLiveText] = useState<{ taskId: string; text: string }>();
  const liveStreamer = useRef<SmoothStreamer | null>(null);
  const flushLiveText = useCallback(() => { liveStreamer.current?.flush(); }, []);
  const [stopRequestedTaskId, setStopRequestedTaskId] = useState<string>();
  const [stoppedTaskId, setStoppedTaskId] = useState<string>();
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const [attachments, setAttachments] = useState<AssistantFile[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState('');
  const [draggingFiles, setDraggingFiles] = useState(false);
  const [modelMode, setModelMode] = useState('configured');
  const [cyberFxActive, setCyberFxActive] = useState(() => {
    const root = document.documentElement;
    return root.dataset.theme === 'scifi' && root.dataset.cyberFx === 'on';
  });
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
    const syncCyberFx = () => {
      const root = document.documentElement;
      setCyberFxActive(root.dataset.theme === 'scifi' && root.dataset.cyberFx === 'on');
    };
    window.addEventListener('morrow:cyber-fx', syncCyberFx);
    window.addEventListener('morrow:theme', syncCyberFx);
    return () => {
      window.removeEventListener('morrow:cyber-fx', syncCyberFx);
      window.removeEventListener('morrow:theme', syncCyberFx);
    };
  }, []);
  const details = useGetAssistantTask(selectedTaskId ?? '', { query: { enabled: !!selectedTaskId, queryKey: getGetAssistantTaskQueryKey(selectedTaskId ?? ''), refetchInterval: (query) => {
    const task = query.state.data;
    return task && ['queued', 'running', 'processing', 'awaiting_approval', 'awaiting_confirmation'].includes(task.status) ? 2500 : false;
  } } });
  const abort = useAbortAssistantTask();
  const { select: selectThread, resetSignal } = conv;
  const selectedThreadRef = useRef(threadId);
  selectedThreadRef.current = threadId;
  const modelSelectionVersion = useRef(0);
  const adoptingSentThread = useRef<string | undefined>(undefined);
  useEffect(() => { if (threadStale) selectThread(undefined); }, [threadStale, selectThread]);
  useEffect(() => {
    if (!adoptingSentThread.current || adoptingSentThread.current !== threadId) {
      setObjective(''); setAttachments([]);
    }
    adoptingSentThread.current = undefined;
    setStopRequestedTaskId(undefined); setStoppedTaskId(undefined);
    setSubmitError(''); setAttachmentError(''); setSelectedTaskId(undefined);
  }, [threadId, resetSignal]);
  const tasks = useMemo(() => (threadId ? threadDetail.data?.tasks ?? [] : []), [threadId, threadDetail.data]);
  const threadMessages = threadDetail.data?.messages;
  const threadTitle = threadId ? threadDetail.data?.title ?? conv.threads.find((t) => t.id === threadId)?.title ?? 'Chat' : 'New chat';
  const latestTaskModel = newestThreadModel(tasks);
  const referenceModel = useMemo(
    () => threadDetail.data?.provider && threadDetail.data.modelId
      ? { provider: threadDetail.data.provider, modelId: threadDetail.data.modelId }
      : latestTaskModel,
    [threadDetail.data?.provider, threadDetail.data?.modelId, latestTaskModel],
  );
  const savedModelPreference = loadChatModelPreference(threadId);
  const lastUsedModel = referenceModel ?? (savedModelPreference?.mode === 'last-used'
    ? { provider: savedModelPreference.provider, modelId: savedModelPreference.model }
    : undefined);
  const resolveModelMode = useCallback((mode: string): ResolvedChatModel | undefined => {
    if (isAutoRouteMode(mode)) {
      return { provider: AUTO_ROUTE_PROVIDERS[mode], model: mode, autoRouteMode: mode };
    }
    const parts = mode.split('|');
    if (parts.length === 3 && parts[0] === 'direct' && Object.hasOwn(models, parts[1])) {
      return { provider: parts[1] as AssistantTask['provider'], model: parts[2] };
    }
    if (mode === 'last-used' && lastUsedModel?.provider && lastUsedModel.modelId) {
      return { provider: lastUsedModel.provider as AssistantTask['provider'], model: lastUsedModel.modelId };
    }
    if (mode === 'configured' && settingsQuery.data) {
      return { provider: settingsQuery.data.provider, model: settingsQuery.data.modelId };
    }
    return undefined;
  }, [lastUsedModel, settingsQuery.data]);
  const changeModelMode = useCallback((mode: string) => {
    setModelMode(mode);
    const model = resolveModelMode(mode);
    saveChatModelPreference(threadId, model?.autoRouteMode
      ? { mode: 'auto', autoRouteMode: model.autoRouteMode }
      : model
        ? { mode: mode === 'configured' || mode === 'last-used' ? mode : 'direct', provider: model.provider, model: model.model }
        : { mode: 'configured' });
    if (!threadId || !model?.provider || model.autoRouteMode) return;
    const version = ++modelSelectionVersion.current;
    setSubmitError('');
    void conv.setModel(threadId, model.provider as Parameters<typeof conv.setModel>[1], model.model).catch(() => {
      if (modelSelectionVersion.current !== version) return;
      const persisted = referenceModel;
      const restoredMode = persisted?.provider && persisted.modelId
        ? `direct|${persisted.provider}|${persisted.modelId}`
        : 'configured';
      setModelMode(restoredMode);
      saveChatModelPreference(threadId, persisted?.provider && persisted.modelId
        ? { mode: 'direct', provider: persisted.provider, model: persisted.modelId }
        : { mode: 'configured' });
      setSubmitError('The selected model could not be saved. The previous session model was restored.');
    });
  }, [conv.setModel, referenceModel, resolveModelMode, threadId]);
  useEffect(() => {
    if (threadId && !threadDetail.data) return;
    const saved = loadChatModelPreference(threadId);
    if (saved?.mode === 'auto' && saved.autoRouteMode) {
      setModelMode(saved.autoRouteMode);
      return;
    }
    const sessionProvider = threadDetail.data?.provider;
    const sessionModel = threadDetail.data?.modelId;
    if (sessionProvider && sessionModel) {
      if (saved?.provider === sessionProvider && saved.model === sessionModel) {
        setModelMode(modeForSavedPreference(saved));
        return;
      }
      const mode = `direct|${sessionProvider}|${sessionModel}`;
      setModelMode(mode);
      saveChatModelPreference(threadId, { mode: 'direct', provider: sessionProvider, model: sessionModel });
      return;
    }
    if (saved && (saved.mode !== 'last-used' || saved.provider && saved.model)) {
      setModelMode(modeForSavedPreference(saved));
      return;
    }
    const previousModel = referenceModel;
    const mode = previousModel?.provider && previousModel.modelId
      ? `direct|${previousModel.provider}|${previousModel.modelId}`
      : 'configured';
    setModelMode(mode);
    if (previousModel?.provider && previousModel.modelId) {
      saveChatModelPreference(threadId, { mode: 'direct', provider: previousModel.provider, model: previousModel.modelId });
    }
  }, [threadId, threadDetail.data]);
  useEffect(() => {
    const syncModel = () => changeModelMode('configured');
    window.addEventListener('forge:model-applied', syncModel);
    return () => window.removeEventListener('forge:model-applied', syncModel);
  }, [changeModelMode]);
  const displayModelMode = !isAutoRouteMode(modelMode) && threadId && !threadDetail.data && conv.currentModel
    ? `direct|${conv.currentModel.provider}|${conv.currentModel.modelId}`
    : modelMode;
  const actionTaskId = tasks.find((task) => task.requiresApproval || task.requiresModelConfirmation)?.id
    ?? tasks.find((task) => ['running', 'processing', 'queued', 'awaiting_confirmation', 'awaiting_approval'].includes(task.status))?.id
    ?? [...tasks].reverse().find((task) => task.recommendationKind === 'fallback')?.id ?? '';
  const actionTask = useGetAssistantTask(actionTaskId, { query: { enabled: !!actionTaskId, queryKey: getGetAssistantTaskQueryKey(actionTaskId), refetchInterval: (query) => {
    const task = query.state.data;
    return task && ['queued', 'running', 'processing', 'awaiting_approval', 'awaiting_confirmation'].includes(task.status) ? 2500 : false;
  } } });
  const localStop = (task?: AssistantTask | null) => !!task && (task.id === stopRequestedTaskId || task.id === stoppedTaskId);
  const liveTasks = [...tasks, details.data, actionTask.data];
  const activeExecution = liveTasks.some((task) => task && ['running', 'processing', 'queued'].includes(String(task.status)) && !localStop(task));
  const liveStreamTask = [...tasks].reverse().find((task) => ['running', 'processing', 'queued', 'awaiting_approval', 'awaiting_confirmation'].includes(String(task.status)));
  const streamTaskId = threadId
    ? [...tasks].reverse().find((task) => task.threadId === threadId && ['running', 'processing', 'queued'].includes(String(task.status)))?.id
    : undefined;
  useEffect(() => {
    if (!threadId || !streamTaskId) {
      setLiveText(undefined);
      return;
    }
    const taskId = streamTaskId;
    const activeThreadId = threadId;
    let disposed = false;
    const streamer = new SmoothStreamer((visibleText) => {
      if (!disposed) setLiveText({ taskId, text: visibleText });
    });
    liveStreamer.current = streamer;
    const stream = new EventSource(`/api/assistant/tasks/${encodeURIComponent(taskId)}/stream`);
    stream.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as { type?: string; text?: string; status?: string };
        if (event.type === 'snapshot') streamer.replace(event.text ?? '');
        else if (event.type === 'reset') streamer.replace('');
        else if (event.type === 'delta') streamer.push(event.text ?? '');
        else if (event.type === 'end') {
          streamer.complete(event.text);
          stream.close();
          void qc.invalidateQueries({ queryKey: getGetConversationThreadQueryKey(activeThreadId) });
          void qc.invalidateQueries({ queryKey: getGetAssistantTaskQueryKey(taskId) });
          void qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
        }
      } catch {
        // Ignore malformed event frames; EventSource reconnects if the connection drops.
      }
    };
    return () => {
      disposed = true;
      stream.close();
      streamer.dispose();
      if (liveStreamer.current === streamer) liveStreamer.current = null;
    };
  }, [threadId, streamTaskId, qc]);
  const streamTitle = activeExecution ? liveStreamTask?.objective ?? threadTitle : threadTitle;
  const isPending = createTask.isPending;
  const isGenerating = activeExecution || (isPending && !stopRequestedTaskId);
  const thinkingAura = cyberFxActive && isGenerating;
  useEffect(() => {
    const working = isGenerating;
    document.documentElement.dataset.agentWorking = String(working);
    window.dispatchEvent(new CustomEvent('forge:agent-state', { detail: { working } }));
  }, [isGenerating]);
  const threadBusy = !!threadId && (!threadDetail.data || (!!threadDetail.data.activeTaskId && threadDetail.data.activeTaskId !== stoppedTaskId));
  const stopTask = [...tasks].reverse().find((task) => ['running', 'processing', 'queued'].includes(String(task.status)) && !localStop(task))
    ?? [actionTask.data, details.data].find((task) => task && ['running', 'processing', 'queued'].includes(String(task.status)) && !localStop(task));
  const stopTargetId = stopRequestedTaskId ?? stopTask?.id;
  const requestStop = useCallback((taskId: string) => {
    if (abort.isPending || stopRequestedTaskId || taskId === stoppedTaskId) return;
    setSubmitError('');
    setStopRequestedTaskId(taskId);
    abort.mutate({ id: taskId }, {
      onSuccess: (stoppedTask) => {
        setStoppedTaskId(stoppedTask.id);
        setStopRequestedTaskId(undefined);
        qc.setQueryData(getGetAssistantTaskQueryKey(stoppedTask.id), stoppedTask);
        if (stoppedTask.threadId) {
          qc.invalidateQueries({ queryKey: getGetConversationThreadQueryKey(stoppedTask.threadId) });
        }
        qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
        qc.invalidateQueries({ queryKey: getListAssistantTasksQueryKey() });
      },
      onError: () => {
        setStopRequestedTaskId(undefined);
        setSubmitError('The task could not be stopped. Try again or open Task Activity.');
      },
    });
  }, [abort.isPending, abort.mutate, qc, stopRequestedTaskId, stoppedTaskId]);
  useEffect(() => {
    const stopTaskId = stopTask?.id;
    if (!stopTaskId || stopRequestedTaskId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.repeat || event.defaultPrevented) return;
      event.preventDefault();
      requestStop(stopTaskId);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [requestStop, stopRequestedTaskId, stopTask?.id]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = objective.trim();
    if (!text || createTask.isPending || uploadingAttachment || threadBusy) return;
    setSubmitError('');
    const selectedModel = resolveModelMode(displayModelMode);
    if (!selectedModel) {
      setSubmitError('The active model is still loading. Wait a moment and try again.');
      return;
    }
    createTask.mutate({ data: {
      objective: text,
      provider: selectedModel.provider as AssistantTask['provider'],
      ...(selectedModel.autoRouteMode
        ? { autoRouteMode: selectedModel.autoRouteMode }
        : { model: selectedModel.model, modelId: selectedModel.model }),
      ...(threadId ? { threadId } : {}),
      ...(attachments.length ? { fileIds: attachments.map((file) => file.id) } : {}),
    } }, {
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
      onError: (error) => {
        if (selectedThreadRef.current !== threadId) return;
        const apiError = error as { status?: number; data?: { detail?: unknown } };
        const detail = apiError.data?.detail;
        setSubmitError(
          apiError.status === 409
            ? 'This chat is still working. Wait for it to finish or stop the task.'
            : typeof detail === 'string' && detail.trim()
              ? detail
              : 'Your request could not be sent. Please try again.',
        );
      },
    });
  };
  const attachFiles = async (files: File[]) => {
    if (!files.length) return;
    setUploadingAttachment(true);
    setAttachmentError('');
    let uploadedCount = 0;
    try {
      for (const file of files) {
        try {
          const body = new FormData();
          body.append('file', file);
          const response = await fetch('/api/assistant/files', { method: 'POST', body, credentials: 'include' });
          if (!response.ok) throw new Error('Upload failed');
          const uploaded = await response.json() as AssistantFile;
          setAttachments((current) => [...current, uploaded]);
          uploadedCount += 1;
        } catch {
          setAttachmentError('One or more attachments could not be uploaded. Try again from Workspace Files.');
        }
      }
      if (uploadedCount) {
        await qc.invalidateQueries({ queryKey: getListAssistantFilesQueryKey() });
        await qc.invalidateQueries({ queryKey: getGetAssistantDashboardQueryKey() });
      }
    } finally {
      setUploadingAttachment(false);
      if (attachmentInput.current) attachmentInput.current.value = '';
    }
  };
  const selectedModelForDisplay = resolveModelMode(displayModelMode);
  const latestMatchingRouteTask = selectedModelForDisplay?.autoRouteMode
    ? [...tasks].reverse().find((task) => task.routingMode === selectedModelForDisplay.autoRouteMode)
    : undefined;
  const activeModelBadge = selectedModelForDisplay?.autoRouteMode
    ? latestMatchingRouteTask
      ? `${AUTO_ROUTE_LABELS[selectedModelForDisplay.autoRouteMode]} · ${modelDisplayName(latestMatchingRouteTask.provider, latestMatchingRouteTask.modelId)}`
      : AUTO_ROUTE_LABELS[selectedModelForDisplay.autoRouteMode]
    : selectedModelForDisplay
      ? modelDisplayName(selectedModelForDisplay.provider, selectedModelForDisplay.model)
      : 'Configured model';
  return <AppShell page="home"><div className="dashboard-page command-center enter" data-task-active={activeExecution ? 'true' : 'false'} data-testid="dashboard-command-center">
    {summary.isError && <QueryProblem retry={() => summary.refetch()} message="Your overview is temporarily unavailable." />}
    <section className={`activity-panel execution-panel${thinkingAura ? ' cyber-thinking-aura' : ''}`} data-task-active={isGenerating ? 'true' : 'false'}><div className="activity-panel-heading">
      <div className="stream-heading-main">{isGenerating && <span className="status-indicator live live-label" data-testid="status-streaming" aria-live="polite"><span className="online-pip working" />STREAMING</span>}<h2 className="thread-title" title={streamTitle} data-testid="text-thread-title">{streamTitle}</h2></div>
       <div className="stream-heading-right"><div className="command-status" data-testid="status-agent-state"><span className="stream-model-badge" data-testid="text-active-session-model">{activeModelBadge}</span>{latestMatchingRouteTask && <span className="stream-route-badge" data-testid="badge-routing-decision" title={latestMatchingRouteTask.routingReason ?? undefined}>{latestMatchingRouteTask.routingIntent?.replaceAll('_', ' ')}</span>}<span className="stream-status-badge"><span className={`online-pip ${isGenerating ? 'working' : ''}`} />{summary.isLoading ? 'Connecting' : isGenerating ? 'Running' : 'Idle'}</span></div><Link href="/tasks" className="text-link" data-testid="link-all-tasks">Task activity <ArrowRight size={14} /></Link></div>
    </div>
      {threadId && threadDetail.isError && !threadStale && !threadDetail.data ? <QueryProblem retry={() => threadDetail.refetch()} message="This chat could not be loaded." /> : <ActivityStream key={threadId ?? 'new'} tasks={tasks} messages={threadMessages} liveText={liveText} onUserScrollUp={flushLiveText} loading={!!threadId && threadDetail.isLoading} onOpen={(task) => setSelectedTaskId(task.id)} hasEarlier={threadDetail.hasNextPage} loadingEarlier={threadDetail.isFetchingNextPage} earlierError={threadDetail.isFetchNextPageError} onLoadEarlier={() => threadDetail.fetchNextPage()} />}
    </section>
    <TaskActionDock task={actionTask.data} />
    <section
      className={`composer-panel command-composer${draggingFiles ? ' is-drop-target' : ''}`}
      onDragEnter={(event: DragEvent<HTMLElement>) => {
        event.preventDefault();
        event.stopPropagation();
        if (Array.from(event.dataTransfer.types).includes('Files')) setDraggingFiles(true);
      }}
      onDragOver={(event: DragEvent<HTMLElement>) => {
        event.preventDefault();
        event.stopPropagation();
        if (Array.from(event.dataTransfer.types).includes('Files')) {
          event.dataTransfer.dropEffect = 'copy';
          setDraggingFiles(true);
        }
      }}
      onDragLeave={(event: DragEvent<HTMLElement>) => {
        event.preventDefault();
        event.stopPropagation();
        const nextTarget = event.relatedTarget;
        if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
          setDraggingFiles(false);
        }
      }}
      onDrop={(event: DragEvent<HTMLElement>) => {
        event.preventDefault();
        event.stopPropagation();
        setDraggingFiles(false);
        void attachFiles(Array.from(event.dataTransfer.files));
      }}
    >
      {draggingFiles && <div className="composer-drop-overlay" aria-live="polite" data-testid="composer-drop-overlay"><Upload size={20} /><span>Drop files here to attach</span></div>}
      <div className="composer-heading"><span className="composer-icon"><Sparkles size={15} /></span><div><strong>Give Forge a task</strong><span>Specific requests produce better work.</span></div></div>
      <form onSubmit={submit}><div className="terminal-input-row"><span className="terminal-prompt" aria-hidden="true">USR@FORGE-6570:~$</span><textarea ref={objectiveInput} value={objective} onChange={(event) => setObjective(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!event.repeat) event.currentTarget.form?.requestSubmit(); } }} placeholder="Describe what you want done…" maxLength={12000} rows={1} spellCheck={true} autoCorrect="on" autoCapitalize="sentences" data-testid="input-objective" aria-label="Task objective" aria-keyshortcuts="Enter Shift+Enter" /></div>
        {attachments.length > 0 && <div className="task-attachments">{attachments.map((file) => <span className="attachment-chip" key={file.id}><FileText size={13} />{file.name}<button type="button" onClick={() => setAttachments((current) => current.filter((item) => item.id !== file.id))} aria-label={`Remove ${file.name}`} data-testid={`button-remove-attachment-${file.id}`}><X size={13} /></button></span>)}</div>}
        {attachmentError && <p className="field-error" role="alert">{attachmentError}</p>}
        {submitError && <p className="field-error" role="alert">{submitError}</p>}
        <div className="composer-bottom"><div className="composer-actions">
          <span className="composer-counter" data-testid="text-prompt-counter">{objective.length.toLocaleString()} / 12,000</span>
          <ChatModelPicker value={displayModelMode} onChange={changeModelMode} configuredLabel={settingsQuery.data ? modelDisplayName(settingsQuery.data.provider, settingsQuery.data.modelId) : 'Loading model…'} lastUsedLabel={lastUsedModel?.provider && lastUsedModel.modelId ? modelDisplayName(lastUsedModel.provider, lastUsedModel.modelId) : null} currentSessionLabel={selectedModelForDisplay ? modelDisplayName(selectedModelForDisplay.provider, selectedModelForDisplay.model) : undefined} groups={Object.entries(models).filter(([groupProvider]) => groupProvider !== 'ollama' || settingsQuery.data?.localSetupAllowed).map(([groupProvider, items]) => ({ id: groupProvider, label: groupProvider === 'gemini' ? 'Google Gemini' : groupProvider === 'anthropic' ? 'Anthropic Claude' : groupProvider === 'openrouter' ? 'OpenRouter' : groupProvider === 'ollama' ? 'Local · Ollama' : groupProvider === 'openai' ? 'OpenAI' : 'DeepSeek', items }))} />
          <input ref={attachmentInput} type="file" hidden multiple onChange={(event) => { void attachFiles(Array.from(event.currentTarget.files ?? [])); }} data-testid="input-task-attachment" />
          <button type="button" className="button button-quiet submit-button composer-attach" title="Attach a file" aria-label={uploadingAttachment ? 'Uploading attachment' : 'Attach a file'} onClick={() => attachmentInput.current?.click()} disabled={uploadingAttachment} data-testid="button-attach-task-file">{uploadingAttachment ? <LoaderCircle className="spin" size={12} /> : <Upload size={12} />}</button>
          {stopTargetId ? <button type="button" className="button submit-button button-stop-task" disabled={abort.isPending || stopRequestedTaskId === stopTargetId} title="Stop the active task (Escape)" aria-label="Stop active task" aria-keyshortcuts="Escape" onClick={() => requestStop(stopTargetId)} data-testid="button-stop-task"><StopCircle size={12} />{stopRequestedTaskId === stopTargetId ? 'Stopping…' : 'Stop task'}<kbd>Esc</kbd></button>
            : <button className="button button-primary submit-button" disabled={!objective.trim() || isPending || uploadingAttachment || threadBusy} title={threadBusy ? 'Wait for this chat to finish its current task, or stop it here.' : 'Send task'} data-testid="button-submit-task">{isPending ? <LoaderCircle className="spin" size={12} /> : <Send size={12} />}{isPending ? 'Sending…' : threadBusy ? 'Working' : 'Send'}</button>}
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
  const terminalCommandApproval = task?.pendingApprovalKind === 'terminal_command';
  const blenderApproval = task?.pendingApprovalKind === 'blender_automation';
  const engineRemoteApproval = task?.pendingApprovalKind === 'engine_remote_command';
  const engineApproval = blenderApproval || engineRemoteApproval;
  const elevationButtonLabel = typeof navigator !== 'undefined' && navigator.platform.toLowerCase().startsWith('win')
    ? 'Approve & Run with UAC'
    : 'Approve & Run with OS elevation';
  return <Modal title="Task details" onClose={close}>{loading ? <Skeleton rows={5} /> : error || !task ? <QueryProblem retry={retry} /> : <div className="detail-content"><div className="detail-objective"><StatusPill status={task.status} /><h3>{task.objective}</h3><p>Started {formatDate(task.createdAt)} <span>·</span> Updated {timeAgo(task.updatedAt)}</p></div>
    <p className="settings-footnote">Model used: <strong>{task.modelId}</strong></p>
    {task.requiresApproval && task.pendingApprovalId && <section className={`model-recommendation approval-recommendation ${elevatedApproval || terminalCommandApproval || engineApproval ? 'elevated-approval' : ''}`} aria-live="polite" data-testid={elevatedApproval ? 'task-elevated-approval' : terminalCommandApproval ? 'task-terminal-approval' : blenderApproval ? 'task-blender-approval' : engineRemoteApproval ? 'task-engine-approval' : 'task-workspace-approval'}>
      {elevatedApproval ? <>
        <strong>Administrative Privilege Requested</strong>
        <p>The agent is requesting permission to execute this command with elevated system permissions:</p>
        <code className="elevated-command" data-testid="text-elevated-command">{task.approvalSummary}</code>
        <p>Nothing runs until you approve. The invocation will be recorded in <code>logs/elevated_audit.log</code>.</p>
        <p>If pkexec is unavailable, the sudo fallback requires an already-authorized non-interactive sudo session and fails closed otherwise.</p>
      </> : terminalCommandApproval ? <>
        <strong>Local terminal command needs approval</strong>
        <p>The agent requests to run this exact command with your normal local-user permissions:</p>
        <code className="elevated-command" data-testid="text-terminal-command">{task.approvalSummary}</code>
        <p>It runs from workspace/ with a cleaned environment and a 30-second limit. It is not elevated, but can still change local files or data. Nothing has run yet.</p>
      </> : blenderApproval ? <>
        <strong>Blender automation needs approval</strong>
        <p>{task.approvalSummary}</p>
        <EngineApprovalReview task={task} />
      </> : engineRemoteApproval ? <>
        <strong>Local engine command needs approval</strong>
        <p>{task.approvalSummary}</p>
        <EngineApprovalReview task={task} />
      </> : <>
        <strong>Workspace action needs your approval</strong>
        <p>{task.approvalSummary} The agent is paused; no change has been made yet.</p>
      </>}
      <div className="model-recommendation-actions">
        <button className="button button-primary" onClick={() => decideApproval(true)} disabled={resolveApproval.isPending} data-testid="button-approve-workspace-action">{resolveApproval.isPending ? 'Applying…' : elevatedApproval ? elevationButtonLabel : terminalCommandApproval ? 'Approve & Run' : blenderApproval ? 'Approve & Run in Blender' : engineRemoteApproval ? 'Approve & Send to Engine' : 'Approve and continue'}</button>
        <button className="button button-quiet" onClick={() => decideApproval(false)} disabled={resolveApproval.isPending} data-testid="button-reject-workspace-action">{elevatedApproval ? 'Reject Action' : terminalCommandApproval ? 'Reject Command' : engineApproval ? 'Reject 3D action' : 'Reject and continue'}</button>
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
    <div className="modal-actions"><button className="button button-quiet" onClick={close}>Close</button>{['queued', 'running'].includes(task.status) && !['Running approved command; waiting for operating-system elevation', 'Running approved local command (normal user permissions)', 'Running approved Blender automation (normal local-user permissions)'].includes(task.currentStep ?? '') && <button className="button button-danger" onClick={() => abort(task.id)} disabled={aborting} data-testid="button-abort-task"><StopCircle size={15} />{aborting ? 'Stopping…' : 'Stop task'}</button>}</div>
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

function safePreviewUrl(value?: string | null, allowLocalPort = false, expectedPort?: number) {
  if (!value) return '';
  try {
    const parsed = new URL(value, window.location.origin);
    const previewPath = parsed.pathname.startsWith('/api/workspace/preview/static/')
      || parsed.pathname.startsWith('/api/workspace/preview/server/')
      || parsed.pathname.startsWith('/workspace-preview/');
    const localPortPath = parsed.pathname.startsWith('/api/workspace/preview/server/');
    const loopback = allowLocalPort
      && localPortPath
      && !!expectedPort
      && parsed.port === String(expectedPort)
      && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
    return (parsed.origin === window.location.origin || loopback)
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

function WorkspacePreview({ isMaximized, onToggleMaximized }: { isMaximized: boolean; onToggleMaximized: () => void }) {
  const qc = useQueryClient();
  const previewQuery = useGetWorkspacePreview({
    query: { queryKey: getGetWorkspacePreviewQueryKey(), staleTime: 0, refetchOnMount: 'always', refetchInterval: 2500 },
  });
  const stopApp = useStopWorkspacePreviewApp();
  const [selectedId, setSelectedId] = useState('static');
  const [selectedHtmlPath, setSelectedHtmlPath] = useState('');
  const [previewMode, setPreviewMode] = useState<'static' | 'server'>('static');
  const [refreshKey, setRefreshKey] = useState(0);
  const [navigatedUrl, setNavigatedUrl] = useState('');
  const [addressValue, setAddressValue] = useState('');
  const [addressError, setAddressError] = useState(false);
  const htmlVersionsRef = useRef<Record<string, string>>({});
  const htmlEntriesInitializedRef = useRef(false);
  const preview = previewQuery.data;
  const htmlEntries = preview?.htmlEntries ?? [];
  const htmlSignature = htmlEntries.map((entry) => `${entry.path}:${entry.projectModifiedAt}`).join('|');
  const apps = preview?.apps ?? [];
  const localPortPreviewsEnabled = preview?.localAppPreviewsEnabled ?? preview?.pythonPreviewsEnabled ?? false;
  const selectedApp = apps.find((app) => app.id === selectedId) ?? apps[0];
  const activeHtmlEntry = htmlEntries.find((entry) => entry.path === selectedHtmlPath) ?? htmlEntries[0];
  const activeId = previewMode === 'static' ? activeHtmlEntry?.path ?? '' : selectedApp?.id ?? '';
  const activeApp = apps.find((app) => app.id === activeId);
  const staticUrl = activeHtmlEntry
    ? `${activeHtmlEntry.previewUrl}?t=${encodeURIComponent(activeHtmlEntry.projectModifiedAt)}`
    : undefined;
  const rawUrl = previewMode === 'static'
    ? staticUrl
    : localPortPreviewsEnabled ? activeApp?.localUrl : activeApp?.previewUrl;
  const iframeUrl = safePreviewUrl(navigatedUrl || rawUrl, localPortPreviewsEnabled, activeApp?.port);
  const label = previewMode === 'static' ? activeHtmlEntry?.path ?? 'Workspace preview' : activeApp?.entryPath ?? 'Running app';
  useEffect(() => {
    if (!preview) return;
    const previousVersions = htmlVersionsRef.current;
    const changedEntry = htmlEntries.find((entry) => previousVersions[entry.path] !== entry.projectModifiedAt);
    if (!htmlEntriesInitializedRef.current) {
      htmlEntriesInitializedRef.current = true;
      setSelectedHtmlPath(preview.staticEntryPath ?? htmlEntries[0]?.path ?? '');
    } else if (changedEntry) {
      setSelectedHtmlPath(changedEntry.path);
      setNavigatedUrl('');
      setRefreshKey((current) => current + 1);
    } else if (htmlEntries.length && !htmlEntries.some((entry) => entry.path === selectedHtmlPath)) {
      setSelectedHtmlPath(htmlEntries[0].path);
      setNavigatedUrl('');
    }
    htmlVersionsRef.current = Object.fromEntries(htmlEntries.map((entry) => [entry.path, entry.projectModifiedAt]));
  }, [htmlSignature, preview?.staticEntryPath, selectedHtmlPath]);
  useEffect(() => {
    const nextUrl = safePreviewUrl(rawUrl, localPortPreviewsEnabled, activeApp?.port);
    setNavigatedUrl(nextUrl);
    setAddressValue(nextUrl);
    setAddressError(false);
  }, [activeId, rawUrl, localPortPreviewsEnabled, activeApp?.port]);
  useEffect(() => {
    if (!preview?.staticAvailable && apps.length > 0 && previewMode === 'static') {
      setPreviewMode('server');
      setSelectedId(apps[0].id);
    }
  }, [preview?.staticAvailable, apps, previewMode]);
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
    const nextUrl = safePreviewUrl(addressValue, localPortPreviewsEnabled, activeApp?.port);
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
        setSelectedId(status.apps[0]?.id ?? 'static');
        setPreviewMode(status.apps.length > 0 ? 'server' : 'static');
        await qc.invalidateQueries({ queryKey: getGetWorkspacePreviewQueryKey() });
      },
      onError: () => undefined,
    });
  };

  return <section className="preview-workspace" aria-label="Live app previews" data-testid="workspace-live-preview">
    <div className="preview-toolbar">
      <div className="preview-view-label"><span className="preview-status-dot" /><div><strong>Live preview</strong><span>Workspace HTML · auto-checks for edits</span></div></div>
      <div className="preview-toolbar-actions">
        {previewMode === 'static' && htmlEntries.length > 0 && <label className="preview-entry-label"><span>ENTRY</span><select className="preview-entry-select" aria-label="Choose HTML preview entry" value={activeHtmlEntry?.path ?? ''} onChange={(event) => { setSelectedHtmlPath(event.currentTarget.value); setNavigatedUrl(''); setRefreshKey((current) => current + 1); }} data-testid="select-html-preview-entry">{htmlEntries.map((entry) => <option key={entry.path} value={entry.path}>{entry.path}</option>)}</select></label>}
        {iframeUrl && <a className="button button-quiet button-small preview-open" href={iframeUrl} target="_blank" rel="noopener noreferrer" data-testid="link-open-preview"><ExternalLink size={14} /> Open in New Tab</a>}
        <button type="button" className="button button-quiet button-small" onClick={() => { setRefreshKey((n) => n + 1); void previewQuery.refetch(); }} disabled={previewQuery.isFetching} data-testid="button-refresh-preview"><RefreshCw size={14} className={previewQuery.isFetching ? 'preview-spinning' : ''} />{previewQuery.isFetching ? 'Refreshing' : 'Refresh'}</button>
        <button type="button" className={`button button-quiet button-small preview-maximize ${isMaximized ? 'is-maximized' : ''}`} onClick={onToggleMaximized} aria-pressed={isMaximized} aria-label={isMaximized ? 'Restore split view' : 'Expand live preview'} data-testid="button-toggle-preview-maximize"><span aria-hidden="true">{isMaximized ? '❐' : '⛶'}</span>{isMaximized ? 'RESTORE' : 'FULL VIEW'}</button>
      </div>
    </div>
    {previewQuery.isLoading ? <div className="preview-loading" aria-label="Loading previews"><div className="preview-loading-bar" /><div className="preview-loading-stage" /></div>
      : previewQuery.isError ? <div className="preview-state preview-error"><div className="preview-state-icon"><AlertCircle size={20} /></div><strong>Preview status is unavailable</strong><p>We couldn’t reach the workspace preview service.</p><button className="button button-primary button-small" onClick={() => void previewQuery.refetch()} data-testid="button-retry-preview"><RefreshCw size={14} /> Try again</button></div>
        : <>
          <div className="preview-mode-switcher" role="tablist" aria-label="Preview mode">
            <button role="tab" aria-selected={previewMode === 'static'} className={previewMode === 'static' ? 'selected' : ''} onClick={() => { setPreviewMode('static'); setSelectedId('static'); if (!selectedHtmlPath) setSelectedHtmlPath(preview?.staticEntryPath ?? ''); }} data-testid="tab-preview-static">STATIC FILE</button>
            <button role="tab" aria-selected={previewMode === 'server'} className={previewMode === 'server' ? 'selected' : ''} onClick={() => setPreviewMode('server')} data-testid="tab-preview-server">LOCALHOST PORT TUNNEL <span>{apps.length}</span></button>
            <small>{localPortPreviewsEnabled ? 'LOCAL RUNTIME ENABLED' : 'LOCAL RUNTIME DISABLED'}</small>
          </div>
          {previewMode === 'static' && preview?.staticAvailable && <div className="preview-controls">
            <div className="preview-choices" role="group" aria-label="Static preview source">
               <button className="preview-choice selected" onClick={() => { if (activeHtmlEntry) setSelectedHtmlPath(activeHtmlEntry.path); }} aria-pressed="true" data-testid="preview-choice-static"><span className="choice-symbol">S</span><span><strong>Workspace</strong><small>{activeHtmlEntry?.path || preview.staticEntryPath || 'Static site'}</small></span></button>
            </div>
             <div className="preview-app-meta"><span className="preview-status-dot" /> Serving {activeHtmlEntry?.path ?? preview.staticEntryPath}</div>
          </div>}
          {previewMode === 'server' && apps.length > 0 && <div className="preview-controls">
            <div className="preview-choices" role="group" aria-label="Choose a running local app">
              {apps.map((app) => <div className={`preview-choice-wrap ${activeId === app.id ? 'selected' : ''}`} key={app.id}>
                <button className={`preview-choice ${activeId === app.id ? 'selected' : ''}`} onClick={() => setSelectedId(app.id)} aria-pressed={activeId === app.id} data-testid={`preview-choice-app-${app.id}`}><span className="choice-symbol app-symbol">{app.framework.slice(0, 1).toUpperCase()}</span><span><strong>{app.framework}</strong><small>{app.entryPath}</small></span></button>
                <button className="preview-stop" aria-label={`Stop ${app.framework} preview`} title="Stop app" disabled={stopApp.isPending} onClick={() => onStop(app)} data-testid={`button-stop-preview-${app.id}`}><StopCircle size={15} /></button>
              </div>)}
            </div>
            {activeApp && <div className="preview-app-meta"><span className="preview-status-dot" /> Running on port {activeApp.port} <span className="preview-meta-divider" /> Started {timeAgo(activeApp.startedAt)}</div>}
          </div>}
          {previewMode === 'static' && !preview?.staticAvailable && <div className="preview-state preview-empty"><div className="preview-empty-art"><span /><span /><span /><div className="preview-holo-terminal" aria-hidden="true"><i /><i /><i /><i /></div></div><strong>No HTML entry found</strong><p>Create an HTML file anywhere inside workspace/. Nested project folders are scanned automatically.</p></div>}
          {previewMode === 'server' && apps.length === 0 && <div className="preview-state preview-empty"><div className="preview-empty-art"><span /><span /><span /><div className="preview-holo-terminal" aria-hidden="true"><i /><i /><i /><i /></div></div><strong>No local app is running</strong><p>{localPortPreviewsEnabled ? 'Ask Forge to build and launch a Python or Vite app. The process will appear here on an ephemeral localhost port.' : 'Enable Local App Previews in Preferences in an exported local copy. Dynamic process previews are always disabled in Replit Cloud.'}</p></div>}
          {((previewMode === 'static' && !!preview?.staticAvailable) || (previewMode === 'server' && !!activeApp)) && <>
            <div className="preview-address-row">
              <form className="preview-address" onSubmit={navigateToAddress} data-testid="form-preview-address">
                <span className="address-lock"><ShieldCheck size={14} /></span>
                <input aria-label="Preview address" aria-invalid={addressError} value={addressValue} onChange={(event) => { setAddressValue(event.target.value); setAddressError(false); }} spellCheck={false} data-testid="input-preview-address" />
                <button type="submit" data-testid="button-go-preview">Go</button>
              </form>
            </div>
            {addressError && <p className="preview-address-error" role="alert" data-testid="status-preview-address-error">Enter a workspace preview URL or an enabled localhost app URL.</p>}
            <div className="preview-frame-shell" data-testid="preview-frame-shell">
              {iframeUrl ? <iframe key={`${activeId}-${refreshKey}-${iframeUrl}`} title={`${label} live preview`} className="preview-frame" src={iframeUrl} sandbox={activeApp && localPortPreviewsEnabled ? 'allow-scripts allow-forms allow-same-origin' : 'allow-scripts allow-forms'} referrerPolicy="same-origin" data-testid="iframe-live-preview" />
                : <div className="preview-state preview-unavailable"><div className="preview-state-icon"><LockKeyhole size={19} /></div><strong>This preview address can’t be opened safely</strong><p>Only workspace previews and enabled localhost app ports can be loaded here.</p></div>}
            </div>
          </>}
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

function MarketRadar() {
  const symbols = [
    { id: 'comex-gold', label: 'COMEX GOLD ($/oz)', symbol: 'TVC:GOLD' },
    { id: 'wti-crude', label: 'WTI CRUDE ($/bbl)', symbol: 'TVC:USOIL' },
    { id: 'natural-gas', label: 'NATURAL GAS', symbol: 'TVC:NATGAS' },
    { id: 'mcx-gold-inr', label: 'MCX GOLD (INR)', symbol: 'MCX:GOLD1!' },
    { id: 'nifty-50', label: 'NIFTY 50', symbol: 'NSE:NIFTY' },
  ];
  const [symbol, setSymbol] = useState(symbols[0].symbol);
  return <section className="telemetry-section market-radar" data-testid="section-market-radar">
    <div className="telemetry-section-head"><span className="telemetry-section-mark"><CandlestickChart size={14} /></span><div><span className="telemetry-kicker">MARKET RADAR</span><h3>Live market chart</h3></div><span className="telemetry-live-tag">TV WIDGET</span></div>
    <div className="market-radar-symbol"><span>INSTRUMENT</span><strong data-testid="text-market-symbol">{symbol}</strong></div>
    <div className="market-radar-switches" role="group" aria-label="Quick market symbols">
      {symbols.map((item) => <button type="button" key={item.symbol} className={symbol === item.symbol ? 'selected' : ''} aria-pressed={symbol === item.symbol} onClick={() => setSymbol(item.symbol)} data-testid={`button-market-${item.id}`}>{item.label}</button>)}
    </div>
    <TradingViewChart symbol={symbol} />
    <p className="market-radar-note">External TradingView chart · no quote data stored by Forge.</p>
  </section>;
}

function SystemTelemetry() {
  const dashboard = useGetAssistantDashboard({ query: { queryKey: getGetAssistantDashboardQueryKey(), refetchInterval: 4000 } });
  const settings = useGetAssistantSettings();
  const files = useListAssistantFiles();
  const notes = useListAssistantNotes();
  const tasks = useListAssistantTasks({ query: { queryKey: getListAssistantTasksQueryKey(), refetchInterval: 4000 } });
  const { selectedId, currentModel } = useConversations();
  const thread = useThreadHistory(selectedId);
  const messages = thread.data?.messages ?? [];
  const messageChars = messages.reduce((total, message) => total + message.content.length, 0);
  const estimatedTokens = Math.ceil(messageChars / 4);
  const meterWidth = Math.min(100, Math.max(0, (estimatedTokens / 16000) * 100));
  const recentFiles = getRecentFiles(files.data);
  const recentNotes = getRecentNotes(notes.data);
  const recentLogs = getRecentTaskLogs(tasks.data);
  const latestThreadTask = selectedId
    ? (tasks.data ?? [])
      .filter((task) => task.threadId === selectedId)
      .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))[0]
    : undefined;
  const activeProvider = latestThreadTask?.provider ?? currentModel?.provider ?? settings.data?.provider;
  const activeModelId = latestThreadTask?.modelId ?? currentModel?.modelId ?? settings.data?.modelId;
  const searchEngines = settings.data ? [
    { id: 'tavily', label: 'TAVILY', configured: settings.data.hasTavilyKey, selected: settings.data.searchMode === 'api' && settings.data.searchApiProvider === 'tavily' },
    { id: 'serper', label: 'SERPER', configured: settings.data.hasSerperKey, selected: settings.data.searchMode === 'api' && settings.data.searchApiProvider === 'serper' },
    { id: 'google', label: 'GOOGLE', configured: settings.data.hasGeminiKey, selected: settings.data.searchMode === 'native' && settings.data.provider === 'gemini' },
    { id: 'brave', label: 'BRAVE', configured: settings.data.hasBraveKey, selected: settings.data.searchMode === 'api' && settings.data.searchApiProvider === 'brave' },
  ] : [];
  return <div className="telemetry-console" data-testid="panel-system-telemetry">
    <section className="telemetry-section system-readout">
      <div className="telemetry-section-head"><span className="telemetry-section-mark"><Cpu size={14} /></span><div><span className="telemetry-kicker">SYSTEM READOUT</span><h3>Runtime overview</h3></div><span className="telemetry-live-tag">LOCAL</span></div>
      {dashboard.isLoading ? <div className="telemetry-skeleton" aria-label="Loading system telemetry"><i /><i /><i /></div> : dashboard.isError ? <div className="telemetry-error"><span>Runtime summary unavailable.</span><button type="button" onClick={() => dashboard.refetch()} data-testid="button-retry-telemetry">Retry</button></div> : <div className="telemetry-stats">
        <div><span>Active tasks</span><strong data-testid="text-telemetry-active-tasks">{dashboard.data?.activeTasks ?? '—'}</strong></div>
        <div><span>Completed</span><strong>{dashboard.data?.completedTasks ?? '—'}</strong></div>
        <div><span>Active timers</span><strong>{dashboard.data?.activeTimers ?? '—'}</strong></div>
      </div>}
      <div className="telemetry-model">
        <span className="telemetry-kicker">ACTIVE MODEL · {currentModel ? 'SELECTED CHAT' : 'SETTINGS'}</span>
        {settings.isLoading && !currentModel ? <div className="telemetry-skeleton model-skeleton"><i /></div> : settings.isError && !currentModel ? <div className="telemetry-error"><span>Model configuration unavailable.</span><button type="button" onClick={() => settings.refetch()}>Retry</button></div> : activeProvider && activeModelId ? <strong data-testid="text-telemetry-model">{modelDisplayName(activeProvider, activeModelId)}</strong> : <strong data-testid="text-telemetry-model">No model selected</strong>}
        {activeProvider && activeModelId && <span className="telemetry-model-id" data-testid="text-telemetry-model-id">{activeProvider} / {activeModelId}</span>}
        {latestThreadTask?.routingMode && isAutoRouteMode(latestThreadTask.routingMode) && <div className="telemetry-route-decision" data-testid="status-auto-routing-decision">
          <span className="telemetry-live-tag">{AUTO_ROUTE_LABELS[latestThreadTask.routingMode]}</span>
          <span>{latestThreadTask.routingIntent?.replaceAll('_', ' ') ?? 'task intent'}</span>
          {latestThreadTask.routingReason && <small>{latestThreadTask.routingReason}</small>}
        </div>}
      </div>
      {settings.data && <div className="telemetry-search" data-testid="status-search-provider">
        <div className="telemetry-search-heading"><span className="telemetry-kicker">SEARCH FALLBACK ENGINES</span><span className="telemetry-search-mode">{settings.data.searchMode ?? 'not set'}</span></div>
        <div className="telemetry-provider-list">{searchEngines.map((engine) => <span key={engine.id} className={`telemetry-provider-chip ${engine.configured ? 'ready' : 'missing'} ${engine.selected ? 'selected' : ''}`} data-testid={`telemetry-provider-${engine.id}`} title={`${engine.label}: ${engine.configured ? 'key configured' : 'key not configured'}${engine.selected ? ', selected search mode' : ''}`}>
          <i aria-hidden="true" /><span>{engine.label}</span><strong>{engine.configured ? engine.selected ? 'ACTIVE' : 'READY' : 'NO KEY'}</strong>
        </span>)}</div>
        {settings.data.searchMode === 'chromium' && <span className={`telemetry-provider-chip ${settings.data.chromiumAvailable ? 'ready' : 'missing'}`} data-testid="telemetry-provider-chromium"><i aria-hidden="true" /><span>CHROMIUM</span><strong>{settings.data.chromiumAvailable ? 'AVAILABLE' : 'UNAVAILABLE'}</strong></span>}
        <p className="telemetry-search-disclaimer">Configuration status only; no live connectivity probe.</p>
      </div>}
    </section>

    <section className="telemetry-section context-meter">
      <div className="telemetry-section-head"><span className="telemetry-section-mark"><Activity size={14} /></span><div><span className="telemetry-kicker">SELECTED THREAD</span><h3>Conversation footprint</h3></div></div>
      {!selectedId ? <p className="telemetry-empty">Select a conversation to estimate its message text.</p> : thread.isLoading ? <div className="telemetry-skeleton"><i /><i /></div> : thread.isError ? <div className="telemetry-error"><span>Thread messages unavailable.</span><button type="button" onClick={() => thread.refetch()}>Retry</button></div> : <>
        <div className="context-meter-value"><strong data-testid="text-context-estimate">~{estimatedTokens.toLocaleString()}</strong><span>estimated tokens</span></div>
        <div className="context-meter-track" role="meter" aria-label="Estimated message text footprint" aria-valuemin={0} aria-valuemax={16000} aria-valuenow={Math.min(16000, estimatedTokens)}><i style={{ transform: `scaleX(${meterWidth / 100})` }} /></div>
        <div className="context-meter-caption"><span>{messages.length} messages · {messageChars.toLocaleString()} characters</span><span>visual scale only</span></div>
        <p className="telemetry-footnote">Approximation from selected-thread message characters (about 4 characters per token). Not provider-measured usage; excludes hidden instructions and provider-side context.</p>
      </>}
    </section>

    <section className="telemetry-section workspace-recents">
      <div className="telemetry-section-head"><span className="telemetry-section-mark"><HardDrive size={14} /></span><div><span className="telemetry-kicker">LOCAL WORKSPACE</span><h3>Memory &amp; recent files</h3></div></div>
      <div className="telemetry-resource-group"><div className="telemetry-subhead"><FileText size={13} /><span>FILES</span><span className="telemetry-count">{files.data?.length ?? (files.isLoading ? '…' : '—')}</span></div>
        {files.isLoading ? <div className="telemetry-skeleton"><i /><i /></div> : files.isError ? <div className="telemetry-error"><span>Files unavailable.</span><button type="button" onClick={() => files.refetch()}>Retry</button></div> : recentFiles.length ? <RecentFileRows files={recentFiles} /> : <p className="telemetry-empty">No workspace files yet.</p>}
      </div>
      <div className="telemetry-resource-group"><div className="telemetry-subhead"><BookOpen size={13} /><span>NOTES</span><span className="telemetry-count">{notes.data?.length ?? (notes.isLoading ? '…' : '—')}</span></div>
        {notes.isLoading ? <div className="telemetry-skeleton"><i /><i /></div> : notes.isError ? <div className="telemetry-error"><span>Notes unavailable.</span><button type="button" onClick={() => notes.refetch()}>Retry</button></div> : recentNotes.length ? <RecentNoteRows notes={recentNotes} /> : <p className="telemetry-empty">No workspace notes yet.</p>}
      </div>
    </section>

    <section className="telemetry-section execution-log">
      <div className="telemetry-section-head"><span className="telemetry-section-mark"><Clock3 size={14} /></span><div><span className="telemetry-kicker">TASK LOGS</span><h3>Recent execution events</h3></div></div>
      {tasks.isLoading ? <div className="telemetry-skeleton"><i /><i /><i /></div> : tasks.isError ? <div className="telemetry-error"><span>Task logs unavailable.</span><button type="button" onClick={() => tasks.refetch()}>Retry</button></div> : recentLogs.length ? <div className="telemetry-log-list"><RecentTaskLogRows logs={recentLogs} /></div> : <p className="telemetry-empty">No task log entries recorded yet.</p>}
    </section>
    <MarketRadar />
    <div className="telemetry-safety-note"><span className="telemetry-safety-indicator" /><span>Local-first operations · Python execution and preview behavior unchanged</span></div>
  </div>;
}

function InspectorPanel({ onClose, defaultTab, previewMaximized, onPreviewMaximizedChange }: {
  onClose: () => void;
  defaultTab: 'telemetry' | 'preview';
  previewMaximized: boolean;
  onPreviewMaximizedChange: (maximized: boolean) => void;
}) {
  const [tab, setTab] = useState<'telemetry' | 'preview' | 'files'>(defaultTab);
  useEffect(() => {
    const showPreview = () => setTab('preview');
    window.addEventListener('morrow:show-preview', showPreview);
    return () => window.removeEventListener('morrow:show-preview', showPreview);
  }, []);
  const selectTab = (next: 'telemetry' | 'preview' | 'files') => {
    setTab(next);
    if (next !== 'preview') onPreviewMaximizedChange(false);
  };
  return <aside className="right-inspector" aria-label="Telemetry and workspace console" data-testid="right-inspector">
    <div className="inspector-heading"><div><span className="eyebrow">// TELEMETRY &amp; ACTIVE SYSTEM RUNTIME</span><strong>Forge Console</strong></div><button className="icon-button" onClick={onClose} aria-label="Close inspector" data-testid="button-close-inspector"><X size={16} /></button></div>
    <div className="inspector-tabs" role="tablist" aria-label="Console views">
      <button type="button" role="tab" aria-selected={tab === 'telemetry'} className={tab === 'telemetry' ? 'active' : ''} onClick={() => selectTab('telemetry')} data-testid="tab-inspector-telemetry">Telemetry</button>
      <button type="button" role="tab" aria-selected={tab === 'preview'} className={tab === 'preview' ? 'active' : ''} onClick={() => selectTab('preview')} data-testid="tab-inspector-live-preview">Live Preview</button>
      <button type="button" role="tab" aria-label="Workspace Inspector" title="Workspace Inspector" aria-selected={tab === 'files'} className={tab === 'files' ? 'active' : ''} onClick={() => selectTab('files')} data-testid="tab-workspace-inspector">Workspace</button>
    </div>
    <div className="inspector-content">{tab === 'telemetry' ? <SystemTelemetry /> : tab === 'preview' ? <WorkspacePreview isMaximized={previewMaximized} onToggleMaximized={() => onPreviewMaximizedChange(!previewMaximized)} /> : <WorkspaceInspector />}</div>
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
  'gemini-4-argon',
  'gemini-3.8-live',
  'gemini-3.8-live-extended-thinking',
  'gemini-3.8-flash-tts',
  'gemini-3.8-flash-lite-tts',
  'gemini-3.6-flash',
  'gemini-3.5-flash-lite',
  'gemini-3.8-flash',
  'gemini-3.1-flash-lite',
  'gemini-nano-banana-2.1',
  'gemini-3.1-flash-image',
  'gemini-3.1-flash-lite-image',
  'gemini-3-pro-image',
  'gemini-3.1-pro-preview',
  'gemini-3-flash-preview',
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
    { id: 'deepseek-chat', name: 'DeepSeek Chat', detail: 'Default · Balanced V3/V4-Flash mode · Tool calling', descriptor: 'BALANCED', color: 'sage' },
    { id: 'deepseek-reasoner', name: 'DeepSeek Reasoner', detail: 'Thinking mode for complex logic and math', descriptor: 'DEEP FOCUS', color: 'gold' },
  ],
  gemini: [
    { id: 'gemini-4-argon', name: 'Gemini 4 Argon', detail: 'Google Gemini model', descriptor: 'NEW', color: 'gold' },
    { id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash', detail: 'High-capability Flash model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'gemini-3.8-live', name: 'Gemini 3.8 Live', detail: 'Live model · realtime API capability', descriptor: 'LIVE', color: 'blue' },
    { id: 'gemini-3.8-live-extended-thinking', name: 'Gemini 3.8 Live Extended Thinking', detail: 'Live model with extended thinking', descriptor: 'LIVE · THINKING', color: 'gold' },
    { id: 'gemini-3.8-flash-tts', name: 'Gemini 3.8 Flash TTS', detail: 'Speech generation · audio output', descriptor: 'TTS', color: 'blue' },
    { id: 'gemini-3.8-flash-lite-tts', name: 'Gemini 3.8 Flash-Lite TTS', detail: 'Lightweight speech generation', descriptor: 'TTS · LITE', color: 'blue' },
    { id: 'gemini-3.6-flash', name: 'Gemini 3.6 Flash', detail: 'Google Gemini Flash model', descriptor: 'BALANCED', color: 'sage' },
    { id: 'gemini-3.5-flash-lite', name: 'Gemini 3.5 Flash-Lite', detail: 'Default · Budget-first', descriptor: 'QUICK', color: 'blue' },
    { id: 'gemini-3.1-flash-lite', name: 'Gemini 3.1 Flash-Lite', detail: 'Efficient Flash-Lite model', descriptor: 'QUICK', color: 'blue' },
    { id: 'gemini-nano-banana-2.1', name: 'Nano Banana 2.1', detail: 'Google image generation model', descriptor: 'IMAGE', color: 'gold' },
    { id: 'gemini-3.1-flash-image', name: 'Nano Banana 2', detail: 'Flash image generation', descriptor: 'IMAGE', color: 'gold' },
    { id: 'gemini-3.1-flash-lite-image', name: 'Nano Banana 2 Lite', detail: 'Lightweight image generation', descriptor: 'IMAGE · LITE', color: 'gold' },
    { id: 'gemini-3-pro-image', name: 'Nano Banana Pro', detail: 'Pro image generation', descriptor: 'IMAGE · PRO', color: 'gold' },
    { id: 'gemini-3.1-pro-preview', name: 'Gemini 3.1 Pro', detail: 'Preview · advanced reasoning', descriptor: 'DEEP FOCUS', color: 'gold' },
    { id: 'gemini-3-flash-preview', name: 'Gemini 3 Flash', detail: 'Preview · fast general-purpose model', descriptor: 'QUICK', color: 'blue' },
    { id: 'gemma-4-31b-it', name: 'Gemma 4 31B', detail: 'Google open-weight model', descriptor: 'BALANCED', color: 'sage' },
  ],
  anthropic: [
    { id: 'claude-haiku-5-5', name: 'Claude Haiku 5.5', detail: 'Direct Anthropic API · fast everyday tasks', descriptor: 'QUICK', color: 'blue' },
    { id: 'claude-sonnet-5-5', name: 'Claude Sonnet 5.5', detail: 'Direct Anthropic API · balanced capability', descriptor: 'BALANCED', color: 'sage' },
    { id: 'claude-opus-5-5', name: 'Claude Opus 5.5', detail: 'Direct Anthropic API · highest capability', descriptor: 'DEEP FOCUS', color: 'gold' },
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

type VaultSecretName = Exclude<keyof VaultKeysInput, 'ollamaBaseUrl'>;

function VaultSecretField({ name, label, placeholder, statusName, value, disabled, onChange, statuses, loading }: {
  name: VaultSecretName;
  label: string;
  placeholder: string;
  statusName: keyof VaultKeyStatuses;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  statuses?: VaultKeyStatuses;
  loading: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const fieldStatus = statuses?.[statusName];
  const configured = fieldStatus === 'configured';
  const unavailable = fieldStatus === 'unavailable';
  return <div className="vault-field">
    <label className="form-label" htmlFor={`vault-${name}`}>{label}</label>
    <div className="vault-field-meta"><span className={`key-status ${configured ? 'active' : ''}`} role="status" data-testid={`status-vault-${name}`}>{loading ? 'CHECKING' : unavailable ? 'UNAVAILABLE' : configured ? 'CONFIGURED' : 'NOT SET'}</span><span className="optional-label">{unavailable ? 'Re-enter to restore access' : configured ? 'Blank keeps existing key' : 'Optional · not configured'}</span></div>
    <div className="vault-input-wrap">
      <input id={`vault-${name}`} type={visible ? 'text' : 'password'} autoComplete="new-password" spellCheck={false} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} disabled={disabled} data-testid={`input-${name}`} />
      <button className="vault-visibility" type="button" aria-label={`${visible ? 'Hide' : 'Show'} ${label}`} aria-pressed={visible} onClick={() => setVisible((current) => !current)} disabled={disabled} data-testid={`button-toggle-${name}-visibility`}>{visible ? <EyeOff size={14} /> : <Eye size={14} />}</button>
    </div>
  </div>;
}

function SettingsPage() {
  const qc = useQueryClient();
  const settingsQuery = useGetAssistantSettings();
  const systemPromptQuery = useGetAssistantSystemPrompt();
  const updateSettings = useUpdateAssistantSettings();
  const updateSystemPrompt = useUpdateAssistantSystemPrompt();
  const applyModel = useApplyAssistantModel();
  const vaultStatusQuery = useGetVaultKeys({ query: { queryKey: getGetVaultKeysQueryKey() } });
  const saveVault = useSaveVaultKeys();
  const [confirmVaultReset, setConfirmVaultReset] = useState(false);
  const [provider, setProvider] = useState<'openai' | 'deepseek' | 'gemini' | 'anthropic' | 'openrouter' | 'ollama'>('deepseek');
  const [modelId, setModelId] = useState('deepseek-chat');
  const [customModelId, setCustomModelId] = useState('');
  const [fallbackModelId, setFallbackModelId] = useState('');
  const initialized = useRef(false);
  const credentialStatus = settingsQuery.data;
  const vaultLocked = vaultStatusQuery.data?.vault_status === 'locked';
  const [apiKeys, setApiKeys] = useState<VaultKeysInput>({
    openaiApiKey: '', deepseekApiKey: '', geminiApiKey: '', anthropicApiKey: '', openrouterApiKey: '',
    tavilyApiKey: '', serperApiKey: '', braveApiKey: '', kiteApiKey: '',
    kiteApiSecret: '', kiteAccessToken: '', alphaVantageApiKey: '', finnhubApiKey: '',
    goldapiIoKey: '', oilpriceapiKey: '', commodityApiKey: '',
  });
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState('http://localhost:11434/v1');
  const [appPreviewsEnabled, setAppPreviewsEnabled] = useState(false);
  const [engineToolsEnabled, setEngineToolsEnabled] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [providerSaved, setProviderSaved] = useState(false);
  const [backupPassword, setBackupPassword] = useState('');
  const [backupPasswordConfirm, setBackupPasswordConfirm] = useState('');
  const [restorePassword, setRestorePassword] = useState('');
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreConfirmed, setRestoreConfirmed] = useState(false);
  const [vaultBackupBusy, setVaultBackupBusy] = useState(false);
  const [vaultBackupMessage, setVaultBackupMessage] = useState('');
  const [vaultBackupError, setVaultBackupError] = useState('');
  const [vaultExpanded, setVaultExpanded] = useState<Record<string, boolean>>({ core: true, search: false, market: false });
  const [modelApplied, setModelApplied] = useState('');
  const [confirmBeforeActions, setConfirmBeforeActions] = useState(true);
  const [allowExternalResearch, setAllowExternalResearch] = useState(true);
  const [includeFiles, setIncludeFiles] = useState(true);
  const [saved, setSaved] = useState(false);
  const [systemPromptDraft, setSystemPromptDraft] = useState('');
  const [systemPromptDirty, setSystemPromptDirty] = useState(false);
  const [systemPromptError, setSystemPromptError] = useState('');
  const [systemPromptSaved, setSystemPromptSaved] = useState(false);
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
    setAppPreviewsEnabled(data.appPreviewsEnabled);
    setEngineToolsEnabled(data.engineToolsEnabled);
  }, [settingsQuery.data]);
  useEffect(() => {
    if (systemPromptQuery.data && !systemPromptDirty) {
      setSystemPromptDraft(systemPromptQuery.data.systemPrompt);
    }
  }, [systemPromptQuery.data, systemPromptDirty]);
  useEffect(() => {
    if (vaultLocked) setVaultExpanded({ core: true, search: true, market: true });
    else setConfirmVaultReset(false);
  }, [vaultLocked]);
  const configured = provider === 'openai'
    ? credentialStatus?.hasOpenaiKey
    : provider === 'deepseek'
      ? credentialStatus?.hasDeepseekKey
    : provider === 'gemini'
      ? credentialStatus?.hasGeminiKey
      : provider === 'openrouter'
        ? credentialStatus?.hasOpenrouterKey
        : provider === 'anthropic'
          ? credentialStatus?.hasAnthropicKey
          : credentialStatus?.localSetupAllowed;
  const saveProviderSettings = () => {
    setProviderError('');
    if (!credentialStatus) return;
    const payload: AssistantSettingsInput = { provider: credentialStatus.provider, modelId: credentialStatus.modelId, codeRunnerEnabled: true, appPreviewsEnabled, engineToolsEnabled };
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
    const payload = Object.fromEntries([
      ...Object.entries(apiKeys).filter(([, value]) => typeof value === 'string' && value.trim()).map(([key, value]) => [key, value.trim()]),
      ['ollamaBaseUrl', ollamaBaseUrl.trim()],
    ]) as VaultKeysInput;
    if (vaultLocked && confirmVaultReset) payload.recoverLockedVault = true;
    saveVault.mutate({ data: payload }, {
      onSuccess: () => {
        void qc.invalidateQueries({ queryKey: getGetVaultKeysQueryKey() });
        void qc.invalidateQueries({ queryKey: getGetAssistantSettingsQueryKey() });
        setApiKeys({
          openaiApiKey: '', deepseekApiKey: '', geminiApiKey: '', anthropicApiKey: '', openrouterApiKey: '',
          tavilyApiKey: '', serperApiKey: '', braveApiKey: '', kiteApiKey: '',
          kiteApiSecret: '', kiteAccessToken: '', alphaVantageApiKey: '', finnhubApiKey: '',
          goldapiIoKey: '', oilpriceapiKey: '', commodityApiKey: '',
        });
        setConfirmVaultReset(false);
        setProviderSaved(true);
      },
      onError: () => setProviderError('Vault settings could not be saved. Check the connection and try again.'),
    });
  };
  const backupRequestError = async (response: Response) => {
    const result = await response.json().catch(() => null) as { detail?: unknown } | null;
    return typeof result?.detail === 'string' ? result.detail : 'The vault backup could not be processed.';
  };
  const exportVaultBackup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setVaultBackupError('');
    setVaultBackupMessage('');
    if (backupPassword !== backupPasswordConfirm) {
      setVaultBackupError('The backup passwords do not match.');
      return;
    }
    setVaultBackupBusy(true);
    try {
      const response = await fetch('/api/vault/backup', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: backupPassword }),
      });
      if (!response.ok) throw new Error(await backupRequestError(response));
      const fileUrl = URL.createObjectURL(await response.blob());
      const download = document.createElement('a');
      download.href = fileUrl;
      download.download = 'forge-vault-backup.forgevault';
      document.body.appendChild(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(fileUrl), 1000);
      setBackupPassword('');
      setBackupPasswordConfirm('');
      setVaultBackupMessage('Encrypted vault backup downloaded. Keep the file and its password somewhere safe.');
    } catch (error) {
      setVaultBackupError(error instanceof Error ? error.message : 'The vault backup could not be created.');
    } finally {
      setVaultBackupBusy(false);
    }
  };
  const importVaultBackup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setVaultBackupError('');
    setVaultBackupMessage('');
    if (!restoreFile || !restoreConfirmed) return;
    setVaultBackupBusy(true);
    try {
      const body = new FormData();
      body.append('backup_file', restoreFile);
      body.append('password', restorePassword);
      const response = await fetch('/api/vault/restore', {
        method: 'POST',
        credentials: 'include',
        body,
      });
      if (!response.ok) throw new Error(await backupRequestError(response));
      const result = await response.json() as { restored_entries?: number };
      await Promise.all([
        qc.invalidateQueries({ queryKey: getGetVaultKeysQueryKey() }),
        qc.invalidateQueries({ queryKey: getGetAssistantSettingsQueryKey() }),
      ]);
      setRestorePassword('');
      setRestoreFile(null);
      setRestoreConfirmed(false);
      setVaultBackupMessage(`Vault restored. ${result.restored_entries ?? 0} saved credential${result.restored_entries === 1 ? '' : 's'} are available.`);
    } catch (error) {
      setVaultBackupError(error instanceof Error ? error.message : 'The vault backup could not be restored.');
    } finally {
      setVaultBackupBusy(false);
    }
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
  const saveSystemPrompt = () => {
    setSystemPromptError('');
    setSystemPromptSaved(false);
    const data: SystemPromptUpdate = { systemPrompt: systemPromptDraft };
    updateSystemPrompt.mutate({ data }, {
      onSuccess: (result) => {
        setSystemPromptDraft(result.systemPrompt);
        setSystemPromptDirty(false);
        setSystemPromptSaved(true);
        qc.setQueryData(getGetAssistantSystemPromptQueryKey(), result);
        toast({ title: 'System prompt saved and applied.' });
      },
      onError: (error) => setSystemPromptError(settingsError(error)),
    });
  };
  const vaultField = (name: VaultSecretName, statusName: keyof VaultKeyStatuses, label: string, placeholder: string) =>
    <VaultSecretField key={name} name={name} statusName={statusName} label={label} placeholder={placeholder}
      value={String(apiKeys[name] ?? '')} disabled={!credentialStatus?.providerSettingsAllowed}
      onChange={(value) => { setApiKeys((current) => ({ ...current, [name]: value })); setProviderSaved(false); }}
      statuses={vaultStatusQuery.data} loading={vaultStatusQuery.isLoading} />;
  const vaultGroups = [
    { id: 'core', title: 'AI & Core Reasoning', fields: [
      ['openaiApiKey', 'openai_api_key', 'OpenAI API key', 'Enter API key'],
      ['deepseekApiKey', 'deepseek_api_key', 'DeepSeek API key', 'Enter API key'],
      ['geminiApiKey', 'gemini_api_key', 'Gemini API key', 'Enter API key'],
      ['anthropicApiKey', 'anthropic_api_key', 'Anthropic API key', 'Enter sk-ant-... key'],
      ['openrouterApiKey', 'openrouter_api_key', 'OpenRouter API key', 'Enter API key'],
    ] },
    { id: 'search', title: 'Web Search & Grounding', fields: [
      ['tavilyApiKey', 'tavily_api_key', 'Tavily API key', 'Enter API key'],
      ['serperApiKey', 'serper_api_key', 'Serper API key', 'Enter API key'],
      ['braveApiKey', 'brave_search_api_key', 'Brave Search API key', 'Enter API key'],
    ] },
    { id: 'market', title: 'Market & Broker', fields: [
      ['kiteApiKey', 'kite_api_key', 'Kite API key', 'Enter broker API key'],
      ['kiteApiSecret', 'kite_api_secret', 'Kite API secret', 'Enter broker API secret'],
      ['kiteAccessToken', 'kite_access_token', 'Kite access token', 'Enter access token'],
      ['alphaVantageApiKey', 'alpha_vantage_api_key', 'Alpha Vantage API key', 'Enter API key'],
      ['finnhubApiKey', 'finnhub_api_key', 'Finnhub API key', 'Enter API key'],
      ['goldapiIoKey', 'goldapi_io_key', 'GoldAPI.io backup key', 'Optional metals API key'],
      ['oilpriceapiKey', 'oilpriceapi_key', 'OilPriceAPI key', 'Optional real-time energy API key'],
      ['commodityApiKey', 'commodity_api_key', 'Commodity API key', 'Optional alternate energy API key'],
    ] },
  ] as const;
  return <AppShell page="settings"><div className="content-page settings-page enter">
    <section className="settings-section theme-settings"><div className="settings-section-heading"><div><h2>Appearance</h2><p>Choose the command center color system.</p></div><ThemeChooser /></div></section>
    <PageHeading eyebrow="AGENT CONFIGURATION" title="Preferences" description="Choose how your agent works and where it should pause for your approval." />
    <section className="settings-section system-prompt-section" data-testid="settings-system-prompt">
      <div className="settings-section-heading">
        <div className="section-symbol"><Sparkles size={17} /></div>
        <div><h2>SYSTEM PROMPT &amp; CORE PERSONA</h2><p>Set the voice and collaborative guidance Forge uses in every task.</p></div>
        {systemPromptQuery.data && <span className="connection-state connected" data-testid="status-system-prompt-mode">{systemPromptQuery.data.isCustomized ? 'CUSTOMIZED' : 'BUILT-IN'}</span>}
      </div>
      <p className="settings-footnote system-prompt-note">
        This editable prompt is saved locally and applied to active task sessions and future messages without a restart.
        Forge’s fixed safety, tool-use, and permission instructions remain enforced separately.
      </p>
      {systemPromptQuery.isLoading && <p className="settings-footnote" role="status">Loading active prompt…</p>}
      {systemPromptQuery.isError && <QueryProblem retry={() => { void systemPromptQuery.refetch(); }} message="The active system prompt could not be loaded." />}
      <label className="form-label system-prompt-label" htmlFor="forge-system-prompt">Editable persona and instructions</label>
      <textarea
        id="forge-system-prompt"
        className="system-prompt-editor"
        value={systemPromptDraft}
        onChange={(event) => { setSystemPromptDraft(event.target.value); setSystemPromptDirty(true); setSystemPromptSaved(false); }}
        rows={16}
        maxLength={20_000}
        spellCheck
        aria-describedby="forge-system-prompt-help"
        data-testid="input-system-prompt"
      />
      <div className="system-prompt-footer">
        <span id="forge-system-prompt-help" className="settings-footnote">{systemPromptDraft.length.toLocaleString()} / 20,000 characters · Empty text restores the built-in persona.</span>
        {systemPromptError && <span className="field-error" role="alert" data-testid="status-system-prompt-error">{systemPromptError}</span>}
        {systemPromptSaved && <span className="save-state" role="status" data-testid="status-system-prompt-saved"><CheckCircle2 size={15} /> Saved and applied to active tasks.</span>}
        <button
          type="button"
          className="button button-primary"
          disabled={systemPromptQuery.isLoading || systemPromptQuery.isError || updateSystemPrompt.isPending || (!systemPromptDirty && !systemPromptQuery.data?.isCustomized)}
          onClick={saveSystemPrompt}
          data-testid="button-save-system-prompt"
        >
          {updateSystemPrompt.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
          {updateSystemPrompt.isPending ? 'SAVING…' : 'SAVE SYSTEM PROMPT'}
        </button>
      </div>
    </section>
    {settingsQuery.isLoading && <div className="settings-section" aria-label="Loading provider preferences" data-testid="status-settings-loading"><Skeleton rows={3} /></div>}
    {settingsQuery.isError && <div data-testid="status-settings-connection-error"><QueryProblem retry={() => { void settingsQuery.refetch(); }} message="Provider preferences are disconnected. Your saved configuration remains untouched." /></div>}
    <section className="settings-section model-section"><div className="settings-section-heading"><div className="section-symbol"><Zap size={17} /></div><div><h2>ACTIVE WORKING MODEL</h2><p>Choose which provider and model will run new tasks.</p></div></div>
      <label className="form-label provider-select-label">ACTIVE AI PROVIDER<select className="provider-hud-select" value={provider} onChange={(event) => { const next = event.target.value as typeof provider; setProvider(next); setModelId(models[next][0].id); setCustomModelId(''); setProviderSaved(false); }} data-testid="select-model-provider"><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="gemini">Google Gemini</option><option value="anthropic">Anthropic Claude</option><option value="openrouter">OpenRouter</option><option value="ollama" disabled={!credentialStatus?.localSetupAllowed}>Ollama / Local{!credentialStatus?.localSetupAllowed ? ' (localhost only)' : ''}</option></select></label>
      <label className="form-label model-choice-label">WORKING MODEL<select className="provider-hud-select model-hud-select" value={`${provider}::${customModelId ? 'custom' : modelId}`} onChange={(event) => { const [nextProvider, nextModel] = event.target.value.split('::'); if (nextProvider in models && (nextProvider !== 'ollama' || credentialStatus?.localSetupAllowed)) { const next = nextProvider as typeof provider; setProvider(next); if (nextModel === 'custom') { setCustomModelId(customModelId || modelId); } else { setModelId(nextModel); setCustomModelId(''); } setProviderSaved(false); } }} data-testid="select-active-model">
        {Object.entries(models).map(([groupProvider, items]) => groupProvider === 'ollama' && !credentialStatus?.localSetupAllowed ? null : <optgroup key={groupProvider} label={groupProvider === 'gemini' ? 'Google Gemini' : groupProvider === 'anthropic' ? 'Anthropic Claude' : groupProvider === 'openrouter' ? 'OpenRouter' : groupProvider === 'ollama' ? 'Local · Ollama' : groupProvider === 'openai' ? 'OpenAI' : 'DeepSeek'}>{items.map((item) => <option key={item.id} value={`${groupProvider}::${item.id}`}>{item.name}</option>)}<option value={`${groupProvider}::custom`}>Custom model name…</option></optgroup>)}
      </select></label>
      <label className="form-label custom-model-control">Custom Model Name <span className="optional-label">Optional; overrides the model selected above.</span><input type="text" autoComplete="off" spellCheck={false} value={customModelId} onChange={(event) => { setCustomModelId(event.target.value); setProviderSaved(false); }} placeholder={provider === 'gemini' ? 'e.g. gemini-3.1-pro-preview' : 'Enter a provider model ID'} data-testid="input-custom-model-id" /></label>
      {provider === 'gemini' && <label className="form-label custom-model-control">Automatic fallback model <span className="optional-label">Optional; retry once after a Gemini 429 or 503. Leave blank to disable.</span><input type="text" autoComplete="off" spellCheck={false} value={fallbackModelId} onChange={(event) => { setFallbackModelId(event.target.value); setProviderSaved(false); }} placeholder="e.g. gemini-3.5-flash-lite" data-testid="input-gemini-fallback-model-id" /></label>}
      <p className="settings-footnote"><LockKeyhole size={13} /> {provider === 'ollama' ? 'Local Ollama endpoint selected.' : configured ? 'Provider key configured.' : 'Add a provider key to run tasks.'} Keys are never sent back to the browser.</p>
      <div className="settings-save-row model-apply-row"><span className="save-state" role="status">{modelApplied === (customModelId.trim() || modelId) && <><CheckCircle2 size={15} /> ACTIVE MODEL SET: {modelApplied}</>}</span><button type="button" className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || applyModel.isPending || saveVault.isPending || updateSettings.isPending} onClick={applyWorkingModel} data-testid="button-apply-model">{applyModel.isPending ? <LoaderCircle className="spin" size={15} /> : <Zap size={15} />}{applyModel.isPending ? 'APPLYING…' : 'APPLY MODEL'}</button></div>
    </section>
    <section className="settings-section key-vault" data-testid="settings-api-keys-vault">
      <div className="settings-section-heading"><div className="section-symbol"><KeyRound size={17} /></div><div><h2>API KEYS VAULT</h2><p>Credentials stay local. Saved values are never shown or prefilled.</p></div><span className={`connection-state ${credentialStatus?.providerSettingsAllowed && !vaultLocked ? 'connected' : 'disconnected'}`} data-testid="status-provider-settings-access">{vaultLocked ? 'VAULT LOCKED' : credentialStatus?.providerSettingsAllowed ? 'KEY STORAGE AVAILABLE' : 'KEY STORAGE RESTRICTED'}</span></div>
      {vaultStatusQuery.isError && <QueryProblem retry={() => { void vaultStatusQuery.refetch(); }} message="Key status is unavailable. Saved keys remain untouched." />}
      {vaultLocked && <div className="field-error" role="alert" data-testid="status-vault-locked">
        <strong>Saved credentials could not be unlocked.</strong>
        <p>Restore the original <code>VAULT_ENCRYPTION_KEY</code> in this copy’s local environment file to recover existing entries. If you no longer have it, re-enter the credentials you still need below, confirm the reset, and save. This permanently removes the inaccessible encrypted entries; only the credentials you re-enter will be kept. Key values are never shown or returned.</p>
      </div>}
      <form className="key-vault-form" onSubmit={(event) => { event.preventDefault(); saveKeys(); }}>
        {vaultGroups.map((group) => <details className="vault-group" key={group.id} open={vaultExpanded[group.id]} data-testid={`group-vault-${group.id}`}>
          <summary aria-expanded={vaultExpanded[group.id]} onClick={(event) => { event.preventDefault(); setVaultExpanded((current) => ({ ...current, [group.id]: !current[group.id] })); }} data-testid={`toggle-vault-${group.id}`}><span>{group.title}</span><ChevronDown size={15} /></summary>
          <div className="key-vault-grid">{group.fields.map(([name, statusName, label, placeholder]) => vaultField(name, statusName, label, placeholder))}</div>
        </details>)}
        <div className="vault-group vault-local-group">
          <div className="vault-local-heading"><strong>Ollama / Local Base URL</strong><span className="key-status local" data-testid="status-vault-ollama">LOCAL</span></div>
          <p className="optional-label">OpenAI-compatible local endpoint</p>
          <input className="settings-input" type="url" value={ollamaBaseUrl} onChange={(event) => { setOllamaBaseUrl(event.target.value); setProviderSaved(false); }} placeholder="http://localhost:11434/v1" disabled={!credentialStatus?.providerSettingsAllowed || !credentialStatus?.localSetupAllowed} data-testid="input-ollama-base-url" />
        </div>
        <p className="settings-footnote"><LockKeyhole size={13} /> Blank key fields mean “keep existing key”. Saved key values are never returned to this screen.</p>
        {vaultLocked && <label className="setting-row" data-testid="confirm-vault-reset-row">
          <input type="checkbox" checked={confirmVaultReset} onChange={(event) => setConfirmVaultReset(event.target.checked)} data-testid="checkbox-confirm-vault-reset" />
          <span className="setting-copy"><strong>Reset inaccessible saved credentials</strong><span>I understand old encrypted entries will be permanently discarded. I have entered at least one replacement credential above.</span></span>
        </label>}
        {providerError && <p className="field-error" role="alert" data-testid="status-provider-save-error">{providerError}</p>}
        {providerSaved && <p className="save-state" role="status" data-testid="status-provider-saved"><CheckCircle2 size={15} /> Vault settings saved. Key values remain hidden.</p>}
        <div className="settings-save-row"><span className="settings-footnote">Keys and local URL save independently. Use Apply Model to activate a model.</span><button type="submit" className="button button-primary" disabled={!credentialStatus?.providerSettingsAllowed || saveVault.isPending || applyModel.isPending || updateSettings.isPending || vaultStatusQuery.isLoading || (vaultLocked && (!confirmVaultReset || !Object.entries(apiKeys).some(([, value]) => typeof value === 'string' && value.trim())))} data-testid="button-save-provider">{saveVault.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {saveVault.isPending ? 'Saving…' : vaultLocked ? 'Reset & Save New Keys' : 'Save Vault'}</button></div>
      </form>
      <div id="vault-backup" className="vault-backup-panel" data-testid="panel-vault-backup">
        <div className="vault-backup-heading"><strong>Move or back up this vault</strong><span>Export creates a password-encrypted file containing the encrypted credentials and the local key needed to unlock them. The key is never sent back to this screen.</span></div>
        <form className="vault-backup-form" onSubmit={exportVaultBackup}>
          <label className="form-label">Backup password <span className="optional-label">At least 12 characters</span><input type="password" autoComplete="new-password" value={backupPassword} onChange={(event) => setBackupPassword(event.target.value)} minLength={12} required data-testid="input-vault-backup-password" /></label>
          <label className="form-label">Confirm backup password<input type="password" autoComplete="new-password" value={backupPasswordConfirm} onChange={(event) => setBackupPasswordConfirm(event.target.value)} minLength={12} required data-testid="input-vault-backup-password-confirm" /></label>
          <button type="submit" className="button button-quiet" disabled={!credentialStatus?.providerSettingsAllowed || vaultLocked || vaultBackupBusy} data-testid="button-export-vault-backup">{vaultBackupBusy ? <LoaderCircle className="spin" size={15} /> : <ArrowDownToLine size={15} />} Download encrypted backup</button>
        </form>
        <form className="vault-backup-form vault-restore-form" onSubmit={importVaultBackup}>
          <label className="form-label">Restore backup file<input type="file" accept=".forgevault,application/octet-stream" onChange={(event) => { setRestoreFile(event.currentTarget.files?.[0] ?? null); setRestoreConfirmed(false); }} required data-testid="input-vault-restore-file" /></label>
          <label className="form-label">Backup password<input type="password" autoComplete="current-password" value={restorePassword} onChange={(event) => setRestorePassword(event.target.value)} minLength={12} required data-testid="input-vault-restore-password" /></label>
          <label className="vault-restore-confirm"><input type="checkbox" checked={restoreConfirmed} onChange={(event) => setRestoreConfirmed(event.target.checked)} data-testid="checkbox-confirm-vault-restore" /><span>Replace the current saved credentials with the credentials in this backup. Other app data will stay unchanged.</span></label>
          <button type="submit" className="button button-quiet" disabled={!credentialStatus?.providerSettingsAllowed || !restoreFile || !restoreConfirmed || vaultBackupBusy} data-testid="button-restore-vault-backup">{vaultBackupBusy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />} Restore encrypted backup</button>
        </form>
        {vaultBackupError && <p className="field-error" role="alert" data-testid="status-vault-backup-error">{vaultBackupError}</p>}
        {vaultBackupMessage && <p className="save-state" role="status" data-testid="status-vault-backup-result"><CheckCircle2 size={15} /> {vaultBackupMessage}</p>}
        <p className="settings-footnote"><LockKeyhole size={13} /> Store the backup file and password separately. Losing either prevents recovery. Restoring replaces saved vault entries.</p>
      </div>
    </section>
    <SearchSettingsPanel settings={credentialStatus} loading={settingsQuery.isLoading} />
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Local execution</h2><p>Project file and shell access are enabled; app previews and engine tools remain opt-in.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><KeyRound size={16} /></div><div className="setting-copy"><strong>Project files &amp; shell commands</strong><span>Forge can immediately read, create, overwrite, append, or delete project files and run shell commands without per-action approval. Commands run with the server process's normal OS permissions and inherited environment.</span><p className="settings-footnote" role="note">This is not a filesystem sandbox: commands can affect data the server process can access outside the project, including environment secrets. Administrative elevation still has a separate approval gate.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><ShieldCheck size={16} /></div><div className="setting-copy"><strong>Enable Local App Previews (Unrestricted Workspace Execution)</strong><span>When enabled on localhost, generated Flask, Streamlit, FastAPI, and Vite apps can run from workspace/ with a cleaned environment, loopback binding, and a one-hour runtime limit. Closing the Live Preview tab stops the child processes.</span><p className="settings-footnote" role="note">Running generated Python apps executes code with standard local user permissions. Running generated Node apps also executes code with standard local user permissions.</p></div><button className={`switch ${appPreviewsEnabled ? 'on' : ''}`} role="switch" aria-checked={appPreviewsEnabled} disabled={!credentialStatus?.localSetupAllowed} onClick={() => { setAppPreviewsEnabled(!appPreviewsEnabled); setProviderSaved(false); }} aria-label="Enable Local App Previews (Unrestricted Workspace Execution)" data-testid="switch-local-app-previews"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><ShieldCheck size={16} /></div><div className="setting-copy"><strong>Enable local Blender &amp; Unreal engine tools</strong><span>Off by default and only available in an exported localhost copy. Every exact script or local endpoint and JSON payload is shown for approval before execution or sending.</span><p className="settings-footnote" role="note">Blender scripts run as your normal local user and are not sandboxed. They can read or modify files your account can access. Blender runs have a 10-minute limit; engine requests are restricted to localhost.</p></div><button className={`switch ${engineToolsEnabled ? 'on' : ''}`} role="switch" aria-checked={engineToolsEnabled} disabled={!credentialStatus?.localSetupAllowed} onClick={() => { setEngineToolsEnabled(!engineToolsEnabled); setProviderSaved(false); }} aria-label="Enable local Blender and Unreal engine tools" data-testid="switch-local-engine-tools"><span /></button></div>
      <div className="setting-row"><div className="setting-row-icon"><Bell size={16} /></div><div className="setting-copy"><strong>Desktop notifications</strong><span>Show browser notifications when a scheduled reminder fires.</span></div><button className="button button-quiet button-small" onClick={() => { if ('Notification' in window) void Notification.requestPermission(); }} data-testid="button-enable-notifications">Enable alerts</button></div>
      {!credentialStatus?.localSetupAllowed && <p className="settings-footnote"><LockKeyhole size={13} /> Dynamic app previews and 3D engine tools can only be enabled from a localhost copy of the app. Replit Cloud keeps those child-process and engine integrations disabled.</p>}
    </section>
    <section className="settings-section safety-section"><div className="settings-section-heading"><div className="section-symbol amber"><ShieldCheck size={18} /></div><div><h2>Safety &amp; permissions</h2><p>Make your boundaries explicit. Change these any time.</p></div></div>
      <div className="setting-row"><div className="setting-row-icon"><CheckCircle2 size={16} /></div><div className="setting-copy"><strong>Confirm external actions</strong><span>Ask before actions that send data or affect external services. Project file and shell operations run immediately without per-action approval.</span></div><button className={`switch ${confirmBeforeActions ? 'on' : ''}`} role="switch" aria-checked={confirmBeforeActions} onClick={() => onSetting(setConfirmBeforeActions, !confirmBeforeActions)} aria-label="Confirm external actions" data-testid="switch-confirm-actions"><span /></button></div>
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
