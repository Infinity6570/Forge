import { useEffect, useRef, useState } from 'react';
import { createCyberBackground } from '@/lib/cyber-background-renderer';

const readEnabled = () => document.documentElement.dataset.theme === 'scifi'
  && document.documentElement.dataset.cyberFx !== 'off';

export function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [enabled, setEnabled] = useState(readEnabled);
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  useEffect(() => {
    const sync = () => setEnabled(readEnabled());
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReducedMotion(preference.matches);
    window.addEventListener('morrow:theme', sync);
    window.addEventListener('morrow:cyber-fx', sync);
    preference.addEventListener('change', motion);
    return () => {
      window.removeEventListener('morrow:theme', sync);
      window.removeEventListener('morrow:cyber-fx', sync);
      preference.removeEventListener('change', motion);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !enabled) return;
    const renderer = createCyberBackground(canvas);
    if (!renderer) return;
    let frame = 0;
    let previous = 0;
    const tick = (timestamp: number) => {
      frame = 0;
      if (document.hidden) return;
      renderer.draw(previous ? Math.min((timestamp - previous) / 16.667, 3) : 1);
      previous = timestamp;
      if (!reducedMotion) frame = requestAnimationFrame(tick);
    };
    const restart = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      previous = 0;
      if (document.hidden) return;
      if (reducedMotion) renderer.draw(0);
      else frame = requestAnimationFrame(tick);
    };
    const resize = () => { renderer.resize(); restart(); };
    const move = (event: MouseEvent) => renderer.pointer(event.clientX, event.clientY);
    const leave = (event: MouseEvent) => { if (!event.relatedTarget) renderer.pointer(-9999, -9999); };
    const click = (event: MouseEvent) => { if (!reducedMotion) renderer.ripple(event.clientX, event.clientY); };
    resize();
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('mousemove', move, { passive: true });
    window.addEventListener('mouseout', leave, { passive: true });
    window.addEventListener('click', click, { passive: true });
    document.addEventListener('visibilitychange', restart);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseout', leave);
      window.removeEventListener('click', click);
      document.removeEventListener('visibilitychange', restart);
      renderer.clear();
    };
  }, [enabled, reducedMotion]);

  return <canvas id="forge-cyber-bg" ref={canvasRef} className="ambient-background" aria-hidden="true" />;
}
