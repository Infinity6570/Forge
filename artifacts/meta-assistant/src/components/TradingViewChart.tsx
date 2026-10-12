import { useEffect, useRef, useState } from 'react';

declare global {
  interface Window {
    TradingView?: {
      widget: new (options: Record<string, unknown>) => { remove?: () => void };
    };
  }
}

const SCRIPT_URL = 'https://s3.tradingview.com/tv.js';
let scriptPromise: Promise<void> | undefined;

function loadTradingView(): Promise<void> {
  if (window.TradingView) return Promise.resolve();
  if (!scriptPromise) {
    scriptPromise = new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_URL}"]`);
      const script = existing ?? document.createElement('script');
      const onLoad = () => window.TradingView ? resolve() : reject(new Error('TradingView script unavailable'));
      const onError = () => reject(new Error('TradingView script failed to load'));
      script.addEventListener('load', onLoad, { once: true });
      script.addEventListener('error', onError, { once: true });
      if (!existing) {
        script.src = SCRIPT_URL;
        script.async = true;
        script.dataset.tradingview = 'true';
        document.head.appendChild(script);
      }
    }).catch((error: unknown) => {
      scriptPromise = undefined;
      throw error;
    });
  }
  return scriptPromise!;
}

export function TradingViewChart({ symbol }: { symbol: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let widget: { remove?: () => void } | undefined;
    setState('loading');
    if (mountRef.current) mountRef.current.replaceChildren();

    const timeout = window.setTimeout(() => {
      if (!cancelled) setState((current) => current === 'ready' ? current : 'error');
    }, 12000);
    void loadTradingView().then(() => {
      if (cancelled || !mountRef.current || !window.TradingView) return;
      widget = new window.TradingView.widget({
        autosize: true,
        symbol,
        interval: 'D',
        timezone: 'Asia/Kolkata',
        theme: 'dark',
        style: '1',
        locale: 'en',
        enable_publishing: false,
        allow_symbol_change: true,
        hide_top_toolbar: false,
        hide_legend: false,
        save_image: false,
        withdateranges: true,
        studies: ['Volume@tv-basicstudies'],
        backgroundColor: '#070a0f',
        gridColor: 'rgba(35, 55, 68, 0.55)',
        container_id: mountRef.current.id,
      });
      window.setTimeout(() => {
        if (!cancelled) {
          window.clearTimeout(timeout);
          setState('ready');
        }
      }, 900);
    }).catch(() => {
      if (!cancelled) {
        window.clearTimeout(timeout);
        setState('error');
      }
    });
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      try {
        widget?.remove?.();
      } catch {
        // TradingView may detach its iframe itself before React cleans up the widget.
      }
      if (mountRef.current) mountRef.current.replaceChildren();
    };
  }, [symbol, retryCount]);

  return <div className="tv-chart-frame" data-testid="market-chart-frame">
    <div className="tv-chart-mount" id={`tv-chart-${symbol.replace(/[^a-z0-9]/gi, '-')}`} ref={mountRef} aria-label={`TradingView interactive candlestick chart for ${symbol}`} />
    {state === 'loading' && <div className="tv-chart-status" role="status" data-testid="status-market-chart-loading"><span className="tv-chart-pulse" />Connecting to TradingView…</div>}
    {state === 'error' && <div className="tv-chart-status tv-chart-error" role="alert" data-testid="status-market-chart-error"><strong>Chart unavailable</strong><span>TradingView could not be reached. Check your connection and switch symbols to retry.</span><button type="button" onClick={() => { setState('loading'); setRetryCount((count) => count + 1); }} data-testid="button-market-chart-retry">Retry chart</button></div>}
    <span className="sr-only" aria-live="polite" data-testid="status-market-chart">{state === 'ready' ? `Chart loaded for ${symbol}` : state === 'loading' ? 'Chart loading' : 'Chart unavailable'}</span>
  </div>;
}
