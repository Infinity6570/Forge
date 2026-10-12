import { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Globe, LoaderCircle } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { getGetAssistantSettingsQueryKey, useUpdateAssistantSearchSettings } from '@workspace/api-client-react';
import type { AssistantSettings, SearchSettingsInput } from '@workspace/api-client-react';

type Mode = SearchSettingsInput['searchMode'];
type Engine = SearchSettingsInput['searchApiProvider'];

const MODES: { id: Mode; label: string; note: string }[] = [
  { id: 'native', label: 'Native / provider default', note: 'Gemini uses Google grounding. Other providers use the selected API engine when its key is saved, else Chromium. For Gemma, choose Search API or Chromium.' },
  { id: 'api', label: 'Search API', note: 'Query the selected API with your personal key.' },
  { id: 'chromium', label: 'Headless Chromium', note: 'Run searches in a local Chromium browser.' },
];
const ENGINES: { id: Engine; label: string; key: 'hasTavilyKey' | 'hasSerperKey' | 'hasBraveKey' }[] = [
  { id: 'tavily', label: 'Tavily', key: 'hasTavilyKey' },
  { id: 'serper', label: 'Serper', key: 'hasSerperKey' },
  { id: 'brave', label: 'Brave', key: 'hasBraveKey' },
];

export function SearchSettingsPanel({ settings, loading }: { settings?: AssistantSettings; loading: boolean }) {
  const qc = useQueryClient();
  const update = useUpdateAssistantSearchSettings();
  const [mode, setMode] = useState<Mode>('native');
  const [engine, setEngine] = useState<Engine>('tavily');
  const [fallback, setFallback] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const dirty = useRef(false);
  const serverMode = settings?.searchMode ?? 'native';
  const serverEngine = settings?.searchApiProvider ?? 'tavily';
  const serverFallback = settings?.searchChromiumFallback ?? false;

  // Rehydrate from the server, but never overwrite unsaved edits.
  useEffect(() => {
    if (!settings || dirty.current) return;
    setMode(serverMode); setEngine(serverEngine); setFallback(serverFallback);
  }, [settings, serverMode, serverEngine, serverFallback]);

  const touch = () => { dirty.current = true; setSaved(false); setError(''); };
  const engineMeta = ENGINES.find((e) => e.id === engine)!;
  const hasKey = !!settings?.[engineMeta.key];
  const chromium = settings?.chromiumAvailable;

  const save = () => {
    setError(''); setSaved(false);
    update.mutate({ data: { searchMode: mode, searchApiProvider: engine, searchChromiumFallback: fallback } }, {
      onSuccess: async () => {
        dirty.current = false;
        await qc.invalidateQueries({ queryKey: getGetAssistantSettingsQueryKey() });
        setSaved(true);
      },
      onError: (e) => {
        const detail = (e as { data?: { detail?: unknown } })?.data?.detail;
        setError(typeof detail === 'string' ? detail : 'Search settings could not be saved. Try again.');
      },
    });
  };

  return <section className="settings-section search-settings" data-testid="section-search-settings">
    <div className="settings-section-heading"><div className="section-symbol"><Globe size={18} /></div><div><h2>WEB SEARCH ENGINE CONFIGURATION</h2><p>Searches use your personal keys and a locally run Chromium, never a managed service.</p></div></div>
    {loading && !settings ? <div className="exec-skeleton" aria-busy="true"><i /><i /></div> : <>
      <div className="search-modes" role="radiogroup" aria-label="Search mode">
        {MODES.map((m) => <label key={m.id} className={`search-mode ${mode === m.id ? 'on' : ''}`}>
          <input type="radio" name="search-mode" value={m.id} checked={mode === m.id} disabled={update.isPending} onChange={() => { setMode(m.id); touch(); }} data-testid={`radio-search-mode-${m.id}`} />
          <span><strong>{m.label}</strong><small>{m.note}</small></span>
        </label>)}
      </div>
      {(mode === 'api' || (mode === 'native' && settings?.provider !== 'gemini')) && <div className="search-engine-pick">
        <span className="form-label" id="search-engine-label">API engine</span>
        <div className="search-engines" role="radiogroup" aria-labelledby="search-engine-label">
          {ENGINES.map((e) => <label key={e.id} className={`search-engine ${engine === e.id ? 'on' : ''}`}>
            <input type="radio" name="search-engine" value={e.id} checked={engine === e.id} disabled={update.isPending} onChange={() => { setEngine(e.id); touch(); }} data-testid={`radio-search-engine-${e.id}`} />
            {e.label}<span className={`key-status ${settings?.[e.key] ? 'active' : ''}`}>{settings?.[e.key] ? 'ACTIVE KEY' : 'NO KEY'}</span>
          </label>)}
        </div>
        {!hasKey && <p className="settings-footnote" role="note">No {engineMeta.label} key saved. Add one in API KEYS VAULT.</p>}
      </div>}
      <div className="setting-row"><div className="setting-copy"><strong>Auto-fallback to Chromium if API quota is exhausted</strong><span>Used only for quota or rate-limit errors. Invalid keys are reported, not retried.</span></div>
        <button type="button" className={`switch ${fallback ? 'on' : ''}`} role="switch" aria-checked={fallback} disabled={update.isPending} aria-label="Auto-fallback to Chromium" onClick={() => { setFallback(!fallback); touch(); }} data-testid="switch-search-fallback"><span /></button></div>
      <p className="settings-footnote" role="note" data-testid="text-chromium-status">{chromium === undefined ? 'Chromium availability is unknown.' : chromium ? 'Chromium is available on this machine.' : <>Chromium is not installed. Run <code>python -m playwright install chromium</code>.</>}</p>
      {error && <p className="field-error" role="alert" data-testid="status-search-save-error"><AlertCircle size={13} /> {error}</p>}
      {saved && <p className="save-state" role="status" data-testid="status-search-saved"><CheckCircle2 size={15} /> Search settings saved.</p>}
      <div className="settings-save-row"><span className="settings-footnote">Search mode saves separately from keys.</span>
        <button type="button" className="button button-primary" disabled={update.isPending} onClick={save} data-testid="button-save-search">{update.isPending ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}{update.isPending ? 'Saving…' : 'Save Search'}</button></div>
    </>}
  </section>;
}
