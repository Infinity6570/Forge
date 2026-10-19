import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import mermaid from 'mermaid';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetWorkspaceCanvasFileQueryKey,
  getGetWorkspacePreviewQueryKey,
  getListWorkspaceCanvasFilesQueryKey,
  useGetWorkspaceCanvasFile,
  useGetWorkspacePreview,
  useListWorkspaceCanvasFiles,
  useStopWorkspacePreviewApp,
} from '@workspace/api-client-react';
import type { WorkspaceCanvasFile } from '@workspace/api-client-react';
import {
  AlertCircle, Braces, ChevronRight, Code2, ExternalLink, FileImage, FileText,
  Maximize2, Network, RefreshCw, Square, X,
} from 'lucide-react';

type CanvasSelection = { type: 'file'; path: string } | { type: 'app'; id: string };

function safeCanvasUrl(value?: string, app?: { port: number }, allowLocal = false) {
  if (!value) return '';
  try {
    const url = new URL(value, window.location.origin);
    const allowedPath = url.pathname.startsWith('/api/workspace/preview/static/')
      || url.pathname.startsWith('/api/workspace/preview/server/')
      || url.pathname.startsWith('/workspace-preview/');
    const tunnel = allowLocal && url.pathname.startsWith('/api/workspace/preview/server/')
      && !!app?.port && url.port === String(app.port)
      && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    return (url.origin === window.location.origin || tunnel)
      && ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && allowedPath
      ? url.href : '';
  } catch { return ''; }
}

function formatBytes(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : bytes < 1_048_576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function MermaidDiagram({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'dark', themeVariables: { darkMode: true, background: '#07111d', primaryColor: '#102535', primaryTextColor: '#dffaff', primaryBorderColor: '#00d9ea', lineColor: '#57a9bd', secondaryColor: '#0b1b2b', tertiaryColor: '#142031' } });
    const render = async () => {
      try {
        const id = `forge-diagram-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, source);
        if (active && ref.current) { ref.current.innerHTML = svg; setError(false); }
      } catch { if (active) setError(true); }
    };
    void render();
    return () => { active = false; };
  }, [source]);
  return error ? <div className="canvas-diagram-error" role="status" data-testid="status-canvas-diagram-error"><AlertCircle size={15} /> Diagram syntax could not be rendered.</div> : <div ref={ref} className="canvas-diagram" data-testid="canvas-mermaid-diagram" />;
}

function SourceViewer({ content, language }: { content: string; language: string }) {
  const lines = useMemo(() => content.split('\n'), [content]);
  return <div className="canvas-source" data-testid="canvas-source-viewer" aria-label={`${language} source viewer`}>
    <div className="canvas-line-numbers" aria-hidden="true">{lines.map((_, index) => <span key={index}>{index + 1}</span>)}</div>
    <pre><code>{content}</code></pre>
  </div>;
}

function FileContent({ file, content, loading, error, retry }: {
  file: WorkspaceCanvasFile; content?: string; loading: boolean; error: boolean; retry: () => void;
}) {
  const url = safeCanvasUrl(file.previewUrl);
  if (file.kind === 'html') return url
    ? <iframe className="canvas-frame" title={`${file.name} static preview`} src={url} sandbox="allow-scripts allow-forms" referrerPolicy="same-origin" data-testid="iframe-canvas-static" />
    : <CanvasMessage icon={<AlertCircle size={20} />} title="Preview URL not available" text="This file cannot be safely opened in the canvas." />;
  if (file.kind === 'image') return url
    ? <div className="canvas-image-wrap"><img src={url} alt={file.name} data-testid="img-canvas-file" /></div>
    : <CanvasMessage icon={<FileImage size={20} />} title="Image unavailable" text="The workspace did not provide a safe preview URL." />;
  if (file.kind === 'pdf') return url
    ? <iframe className="canvas-frame" title={`${file.name} document`} src={url} sandbox="" referrerPolicy="same-origin" data-testid="iframe-canvas-pdf" />
    : <CanvasMessage icon={<FileText size={20} />} title="Document unavailable" text="The workspace did not provide a safe preview URL." />;
  if (loading) return <div className="canvas-loading" aria-busy="true" data-testid="status-canvas-file-loading"><i /><i /><i /><i /></div>;
  if (error) return <CanvasMessage icon={<AlertCircle size={20} />} title="Could not read this file" text="The workspace file service did not respond." action={<button type="button" onClick={retry} data-testid="button-retry-canvas-file"><RefreshCw size={13} /> Retry</button>} />;
  if (content === undefined) return <CanvasMessage icon={<FileText size={20} />} title="No document content" text="Select a workspace artifact to inspect it." />;
  if (file.kind === 'markdown') return <div className="canvas-markdown" data-testid="canvas-markdown-viewer"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    pre({ children }) {
      const child = Array.isArray(children) ? children[0] : children;
      if (child && typeof child === 'object' && 'props' in child) {
        const props = child.props as { className?: string; children?: unknown };
        if (/language-mermaid/.test(props.className ?? '')) return <MermaidDiagram source={String(props.children ?? '').replace(/\n$/, '')} />;
      }
      return <pre>{children}</pre>;
    },
  }}>{content}</ReactMarkdown></div>;
  if (file.kind === 'mermaid') return <div className="canvas-diagram-panel"><MermaidDiagram source={content} /></div>;
  return <SourceViewer content={content} language={file.kind === 'react' ? 'tsx source' : file.kind === 'code' ? 'source' : 'text document'} />;
}

function CanvasMessage({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="canvas-message" role="status" data-testid="status-canvas-message"><span>{icon}</span><strong>{title}</strong><p>{text}</p>{action}</div>;
}

export function WorkspaceCanvas({ onClose }: { onClose?: () => void }) {
  const queryClient = useQueryClient();
  const filesQuery = useListWorkspaceCanvasFiles({ query: { queryKey: getListWorkspaceCanvasFilesQueryKey(), refetchOnMount: 'always' } });
  const previewQuery = useGetWorkspacePreview({ query: { queryKey: getGetWorkspacePreviewQueryKey(), refetchInterval: 3000 } });
  const stopApp = useStopWorkspacePreviewApp();
  const files = filesQuery.data ?? [];
  const apps = previewQuery.data?.apps ?? [];
  const [selection, setSelection] = useState<CanvasSelection>();
  const [maximized, setMaximized] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [stopError, setStopError] = useState('');
  const selectedFile = selection?.type === 'file' ? files.find((file) => file.path === selection.path) : undefined;
  const selectedApp = selection?.type === 'app' ? apps.find((app) => app.id === selection.id) : undefined;
  const currentSelection = selectedFile
    ? { type: 'file' as const, path: selectedFile.path }
    : selectedApp ? { type: 'app' as const, id: selectedApp.id } : undefined;
  const firstRenderable = files[0];
  const filePath = selectedFile?.path ?? '';
  const fileQuery = useGetWorkspaceCanvasFile({ path: filePath }, {
    query: { enabled: !!selectedFile && !['html', 'image', 'pdf'].includes(selectedFile.kind), queryKey: getGetWorkspaceCanvasFileQueryKey({ path: filePath }) },
  });
  const active = !!selectedFile || !!selectedApp;
  const title = selectedApp?.entryPath ?? selectedFile?.path ?? 'Workspace canvas';
  const appUrl = safeCanvasUrl(selectedApp?.previewUrl, selectedApp, previewQuery.data?.localAppPreviewsEnabled ?? false);
  const fileUrl = selectedFile?.kind === 'html' ? safeCanvasUrl(selectedFile.previewUrl) : '';
  const iframeUrl = appUrl || fileUrl;
  const externalUrl = selectedApp?.localUrl && previewQuery.data?.localAppPreviewsEnabled
    ? safeCanvasUrl(selectedApp.localUrl, selectedApp, true) || appUrl
    : appUrl || fileUrl;
  const selectFile = (file: WorkspaceCanvasFile) => setSelection({ type: 'file', path: file.path });
  useEffect(() => {
    if (currentSelection || (!firstRenderable && !apps.length)) return;
    if (firstRenderable) setSelection({ type: 'file', path: firstRenderable.path });
    else if (apps[0]) setSelection({ type: 'app', id: apps[0].id });
  }, [currentSelection, firstRenderable, apps]);
  const refresh = async () => {
    setRefreshToken((value) => value + 1);
    await Promise.all([filesQuery.refetch(), previewQuery.refetch()]);
    if (selectedFile && !['html', 'image', 'pdf'].includes(selectedFile.kind)) await fileQuery.refetch();
  };
  const stopPreviewApp = (app: (typeof apps)[number]) => {
    if (!window.confirm(`Stop the ${app.framework} preview at ${app.entryPath}?`)) return;
    setStopError('');
    stopApp.mutate({ data: { appId: app.id } }, {
      onSuccess: async (status) => {
        queryClient.setQueryData(getGetWorkspacePreviewQueryKey(), status);
        setSelection((current) => current?.type === 'app' && current.id === app.id
          ? status.apps[0] ? { type: 'app', id: status.apps[0].id } : files[0] ? { type: 'file', path: files[0].path } : undefined
          : current);
        await queryClient.invalidateQueries({ queryKey: getGetWorkspacePreviewQueryKey() });
      },
      onError: () => setStopError('Preview could not be stopped. Retry from the running app list.'),
    });
  };
  const openInNewTab = () => { if (externalUrl) window.open(externalUrl, '_blank', 'noopener,noreferrer'); };
  const fileIcon = (file: WorkspaceCanvasFile) => file.kind === 'html' ? <Code2 size={14} /> : file.kind === 'mermaid' ? <Network size={14} /> : file.kind === 'image' || file.kind === 'pdf' ? <FileImage size={14} /> : file.kind === 'react' || file.kind === 'code' ? <Braces size={14} /> : <FileText size={14} />;
  return <section className={`workspace-canvas ${maximized ? 'canvas-maximized' : ''}`} aria-label="Workspace canvas" data-testid="workspace-canvas">
    <header className="canvas-header">
      <div className="canvas-heading-mark"><Network size={16} /></div>
      <div className="canvas-heading"><span>WORKSPACE / ARTIFACT SURFACE</span><strong>{title}</strong></div>
      <div className="canvas-header-actions">
        <span className="canvas-live-state" data-testid="status-canvas-live"><i />{selectedApp ? 'RUNNING' : selectedFile ? selectedFile.kind.toUpperCase() : 'IDLE'}</span>
        <button type="button" className="canvas-icon-action" onClick={() => void refresh()} aria-label="Refresh workspace canvas" title="Refresh workspace" data-testid="button-refresh-canvas"><RefreshCw size={14} className={filesQuery.isFetching || previewQuery.isFetching ? 'canvas-rotate' : ''} /></button>
        {iframeUrl && <button type="button" className="canvas-icon-action" onClick={openInNewTab} aria-label="Open preview in new tab" title="Pop out preview" data-testid="button-popout-canvas"><ExternalLink size={14} /></button>}
        <button type="button" className="canvas-icon-action" onClick={() => setMaximized((value) => !value)} aria-label={maximized ? 'Restore canvas split view' : 'Maximize canvas'} title={maximized ? 'Restore split view' : 'Maximize'} data-testid="button-maximize-canvas"><Maximize2 size={14} /></button>
        {onClose && <button type="button" className="canvas-icon-action" onClick={onClose} aria-label="Close canvas" data-testid="button-close-canvas"><X size={15} /></button>}
      </div>
    </header>
    <div className="canvas-workbench">
      <aside className="canvas-rail" aria-label="Workspace artifacts">
        <div className="canvas-rail-label"><span>FILES</span><span data-testid="status-canvas-file-count">{files.length.toString().padStart(2, '0')}</span></div>
        {filesQuery.isLoading ? <div className="canvas-file-skeleton" aria-label="Loading workspace files"><i /><i /><i /></div>
          : filesQuery.isError ? <div className="canvas-rail-error" role="status" data-testid="status-canvas-files-error"><span>File index unavailable</span><button type="button" onClick={() => void filesQuery.refetch()} data-testid="button-retry-canvas-list">Retry</button></div>
            : files.length ? <div className="canvas-file-list">{files.map((file) => <button type="button" key={file.path} className={`canvas-file-row ${selectedFile?.path === file.path ? 'selected' : ''}`} onClick={() => selectFile(file)} title={file.path} data-testid={`button-canvas-file-${encodeURIComponent(file.path)}`}><span className="canvas-file-icon">{fileIcon(file)}</span><span className="canvas-file-label"><strong>{file.name}</strong><small>{file.kind} · {formatBytes(file.sizeBytes)}</small></span>{selectedFile?.path === file.path && <ChevronRight size={13} />}</button>)}</div>
              : <div className="canvas-empty-files" data-testid="status-canvas-empty-files"><FileText size={17} /><span>No previewable workspace files</span></div>}
        <div className="canvas-rail-label canvas-running-label"><span>RUNNING APPS</span><span data-testid="status-canvas-app-count">{apps.length.toString().padStart(2, '0')}</span></div>
        {previewQuery.isError && <div className="canvas-rail-error" role="status" data-testid="status-canvas-preview-error"><span>Runtime list unavailable</span><button type="button" onClick={() => void previewQuery.refetch()} data-testid="button-retry-canvas-apps">Retry</button></div>}
        {apps.map((app) => <div className={`canvas-app-row ${selectedApp?.id === app.id ? 'selected' : ''}`} key={app.id}><button type="button" className="canvas-app-select" onClick={() => setSelection({ type: 'app', id: app.id })} title={app.entryPath} data-testid={`button-canvas-app-${app.id}`}><span className="canvas-app-pip" /><span><strong>{app.framework}</strong><small>{app.port} · {app.entryPath.split('/').at(-1)}</small></span></button><button type="button" className="canvas-stop-app" aria-label={`Stop ${app.framework} preview`} title="Stop app" onClick={() => stopPreviewApp(app)} disabled={stopApp.isPending} data-testid={`button-stop-canvas-app-${app.id}`}><Square size={12} /></button></div>)}
      </aside>
      <main className="canvas-stage">
        <div className="canvas-stage-topline"><div><span className="canvas-stage-path">{selectedApp ? `localhost:${selectedApp.port}` : selectedFile?.path ?? 'Awaiting selection'}</span><span className="canvas-stage-kind">{selectedApp ? `${selectedApp.framework} / live runtime` : selectedFile ? `${selectedFile.contentType} / ${formatBytes(selectedFile.sizeBytes)}` : 'Select a workspace artifact'}</span></div>{selectedFile && <span className="canvas-modified">MODIFIED {new Date(selectedFile.modifiedAt).toLocaleString()}</span>}</div>
        {stopError && <div className="canvas-stop-error" role="alert" data-testid="status-canvas-stop-error">{stopError}</div>}
        {!active ? filesQuery.isLoading || previewQuery.isLoading ? <div className="canvas-stage-loading" aria-busy="true"><i /><i /><i /></div>
          : <CanvasMessage icon={<Network size={21} />} title="Canvas standing by" text="Choose a file to inspect source, read docs, render diagrams, or open a live workspace preview." />
          : selectedApp ? iframeUrl ? <iframe key={`${selectedApp.id}-${refreshToken}`} className="canvas-frame" title={`${selectedApp.framework} running preview`} src={iframeUrl} sandbox={previewQuery.data?.localAppPreviewsEnabled ? 'allow-scripts allow-forms allow-same-origin' : 'allow-scripts allow-forms'} referrerPolicy="same-origin" data-testid="iframe-canvas-running-app" /> : <CanvasMessage icon={<AlertCircle size={20} />} title="Running preview is unavailable" text="The app URL failed the workspace preview safety check." />
            : selectedFile ? <FileContent key={`${selectedFile.path}-${refreshToken}`} file={selectedFile} content={fileQuery.data?.content} loading={fileQuery.isLoading} error={fileQuery.isError} retry={() => void fileQuery.refetch()} /> : null}
      </main>
    </div>
    {selectedFile && fileQuery.data?.truncated && <div className="canvas-truncation" role="status" data-testid="status-canvas-truncated"><AlertCircle size={14} /><span>Showing a truncated read-only excerpt. The source exceeds the canvas document limit.</span></div>}
    {stopApp.isPending && <div className="canvas-operation-status" role="status" data-testid="status-canvas-stopping">Stopping preview…</div>}
    <footer className="canvas-footer"><span><i /> LOCAL WORKSPACE</span><span>READ-ONLY ARTIFACT VIEWER</span></footer>
  </section>;
}
