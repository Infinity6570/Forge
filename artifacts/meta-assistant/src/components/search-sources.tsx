import { AlertCircle, ExternalLink, Globe } from 'lucide-react';

export type SearchResult = { title?: string; url?: string; text?: string };
export type SearchPayload = {
  engine: string;
  results: SearchResult[];
  answer?: string;
  groundingMetadata?: Record<string, unknown>;
  fallbackFrom?: string;
  fallbackReason?: string;
  warning?: string;
  error?: string;
};

const ENGINES = ['google-grounding', 'tavily', 'serper', 'brave', 'chromium'];

export function parseSearchPayload(content: string): SearchPayload | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith('{')) return null;
  try {
    const raw = JSON.parse(trimmed) as Record<string, unknown>;
    if (typeof raw.engine !== 'string' || !ENGINES.includes(raw.engine) || !Array.isArray(raw.results)) return null;
    return { ...raw, engine: raw.engine, results: raw.results as SearchResult[] } as SearchPayload;
  } catch { return null; }
}

/** Only public http(s) URLs are ever made clickable. */
export function safeUrl(value?: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (url.username || url.password) return null;
    const host = url.hostname.toLowerCase();
    if (host === 'localhost' || host.endsWith('.local') || host.endsWith('.internal') || /^(127\.|10\.|0\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || host === '[::1]' || host.startsWith('[fc') || host.startsWith('[fd') || host.startsWith('[fe80')) return null;
    return url.toString();
  } catch { return null; }
}

const hostOf = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; } };
export const engineLabel = (engine: string) => engine === 'google-grounding' ? 'Google grounding' : engine.charAt(0).toUpperCase() + engine.slice(1);

export function SourceList({ results, limit }: { results: SearchResult[]; limit?: number }) {
  const items = results.map((r) => ({ ...r, href: safeUrl(r.url) })).slice(0, limit ?? results.length);
  if (!items.length) return null;
  return <ul className="source-list">{items.map((r, i) => <li key={`${r.url ?? r.title}-${i}`} className="source-card">
    {r.href ? <a href={r.href} target="_blank" rel="noopener noreferrer nofollow" data-testid={`link-source-${i}`}><Globe size={12} /><span className="source-title">{r.title || hostOf(r.href)}</span><span className="source-host">{hostOf(r.href)}</span><ExternalLink size={11} /></a>
      : <span className="source-plain"><Globe size={12} /><span className="source-title">{r.title || 'Source'}</span></span>}
    {r.text && <p>{r.text.length > 240 ? `${r.text.slice(0, 239)}…` : r.text}</p>}
  </li>)}</ul>;
}

function suggestionsHtml(meta?: Record<string, unknown>): string | null {
  const entry = meta?.searchEntryPoint as { renderedContent?: unknown } | undefined;
  return typeof entry?.renderedContent === 'string' ? entry.renderedContent : null;
}

export function SearchPayloadView({ payload }: { payload: SearchPayload }) {
  const html = suggestionsHtml(payload.groundingMetadata);
  const googleFallback = payload.fallbackFrom === 'google-grounding' && Boolean(payload.fallbackReason);
  return <div className="search-payload" data-testid="search-payload">
    <div className="search-engine-line"><span className="search-engine-badge">{engineLabel(payload.engine)}</span>
      {googleFallback && <span className="search-fallback-badge" data-testid="badge-search-fallback">Fallback from Google grounding · {payload.fallbackReason}</span>}
      {payload.fallbackFrom && payload.fallbackFrom !== 'google-grounding' && <span className="search-note">Fallback from {engineLabel(payload.fallbackFrom)}</span>}
    </div>
    {payload.error && <p className="search-error"><AlertCircle size={12} />{payload.error}</p>}
    {payload.warning && <p className="search-note">{payload.warning}</p>}
    {payload.answer && <p className="search-answer">{payload.answer}</p>}
    <SourceList results={payload.results} />
    {html && <iframe className="search-suggestions" title="Search suggestions" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={html} data-testid="frame-search-suggestions" />}
    <details className="search-raw"><summary>Raw search data</summary><pre>{JSON.stringify(payload, null, 2)}</pre></details>
  </div>;
}
