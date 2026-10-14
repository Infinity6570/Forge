import { useEffect, useRef, useState } from 'react';

function readEnabled() {
  const root = document.documentElement;
  return root.dataset.theme === 'scifi' && root.dataset.cyberFx !== 'off';
}

export function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [enabled, setEnabled] = useState(readEnabled);
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  useEffect(() => {
    const syncTheme = () => setEnabled(readEnabled());
    const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const syncMotion = () => setReducedMotion(motionPreference.matches);

    window.addEventListener('morrow:theme', syncTheme);
    window.addEventListener('morrow:cyber-fx', syncTheme);
    motionPreference.addEventListener('change', syncMotion);
    return () => {
      window.removeEventListener('morrow:theme', syncTheme);
      window.removeEventListener('morrow:cyber-fx', syncTheme);
      motionPreference.removeEventListener('change', syncMotion);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    if (!enabled) {
      context.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const ctx = context as CanvasRenderingContext2D;

    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let time = 0;
    let lastFrameAt = 0;
    let frameId = 0;
    let particles: Array<{ x: number; y: number; vx: number; vy: number; radius: number; hue: number }> = [];

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

      const count = Math.min(72, Math.max(26, Math.floor((width * height) / 26000)));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        radius: Math.random() * 1.1 + 0.45,
        hue: Math.random() < 0.7 ? 185 : 276,
      }));
      draw(0, true);
    };

    const drawWaves = () => {
      for (let wave = 0; wave < 3; wave += 1) {
        ctx.beginPath();
        for (let x = 0; x <= width; x += 16) {
          const y = height * (0.82 + wave * 0.045)
            + Math.sin(x * 0.006 + time * 0.012 + wave) * 17
            + Math.sin(x * 0.013 - time * 0.009) * 8;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = [
          'rgba(0,243,255,0.13)',
          'rgba(180,76,255,0.11)',
          'rgba(255,62,165,0.08)',
        ][wave];
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    };

    const drawOrbitalNetwork = () => {
      const radius = Math.min(width, height) * 0.26;
      const centerX = width * 0.73;
      const centerY = height * 0.48;
      const count = width < 700 ? 160 : 260;
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const rotation = time * 0.0014;
      const tilt = 0.32 + Math.sin(time * 0.0006) * 0.12;
      const cosRotation = Math.cos(rotation);
      const sinRotation = Math.sin(rotation);
      const cosTilt = Math.cos(tilt);
      const sinTilt = Math.sin(tilt);

      for (let index = 0; index < count; index += 1) {
        const y = 1 - (index / (count - 1)) * 2;
        const ringRadius = Math.sqrt(1 - y * y);
        const angle = goldenAngle * index;
        const x = Math.cos(angle) * ringRadius;
        const z = Math.sin(angle) * ringRadius;
        const rotatedX = x * cosRotation - z * sinRotation;
        const rotatedZ = x * sinRotation + z * cosRotation;
        const rotatedY = y * cosTilt - rotatedZ * sinTilt;
        const depth = (1 - (y * sinTilt + rotatedZ * cosTilt)) / 2;
        const perspective = 2.5 / (2.5 + 1 - depth);
        const px = centerX + rotatedX * radius * perspective;
        const py = centerY + rotatedY * radius * perspective;
        const size = 0.6 + depth * 1.2;
        ctx.fillStyle = `hsla(${186 + depth * 74},100%,${58 + depth * 14}%,${0.18 + depth * 0.56})`;
        ctx.fillRect(px - size / 2, py - size / 2, size, size);
      }

      ctx.lineWidth = 0.8;
      for (let ring = 0; ring < 2; ring += 1) {
        ctx.beginPath();
        ctx.ellipse(
          centerX,
          centerY,
          radius * (1.25 + ring * 0.2),
          radius * (0.31 + ring * 0.07),
          rotation * (ring === 0 ? 0.6 : -0.4) + ring,
          0,
          Math.PI * 2,
        );
        ctx.strokeStyle = ring === 0 ? 'rgba(0,243,255,0.12)' : 'rgba(180,76,255,0.12)';
        ctx.stroke();
      }
    };

    function draw(timestamp: number, immediate = false) {
      if (!immediate && timestamp - lastFrameAt < 32) {
        frameId = window.requestAnimationFrame((next) => draw(next));
        return;
      }
      lastFrameAt = timestamp;
      ctx.clearRect(0, 0, width, height);
      ctx.globalCompositeOperation = 'lighter';
      drawWaves();
      drawOrbitalNetwork();

      const linkDistance = 118;
      for (let index = 0; index < particles.length; index += 1) {
        const particle = particles[index];
        if (!reducedMotion) {
          particle.x += particle.vx;
          particle.y += particle.vy;
          if (particle.x < 0) particle.x = width;
          if (particle.x > width) particle.x = 0;
          if (particle.y < 0) particle.y = height;
          if (particle.y > height) particle.y = 0;
        }

        for (let otherIndex = index + 1; otherIndex < particles.length; otherIndex += 1) {
          const other = particles[otherIndex];
          const distance = Math.hypot(particle.x - other.x, particle.y - other.y);
          if (distance < linkDistance) {
            ctx.strokeStyle = `rgba(0,243,255,${(1 - distance / linkDistance) * 0.11})`;
            ctx.lineWidth = 0.65;
            ctx.beginPath();
            ctx.moveTo(particle.x, particle.y);
            ctx.lineTo(other.x, other.y);
            ctx.stroke();
          }
        }

        ctx.fillStyle = `hsla(${particle.hue},100%,74%,0.52)`;
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';

      if (!reducedMotion && document.visibilityState === 'visible') {
        time += 1;
        frameId = window.requestAnimationFrame((next) => draw(next));
      }
    }

    const onVisibilityChange = () => {
      window.cancelAnimationFrame(frameId);
      if (document.visibilityState === 'visible' && !reducedMotion) {
        frameId = window.requestAnimationFrame((timestamp) => draw(timestamp, true));
      }
    };

    resize();
    window.addEventListener('resize', resize, { passive: true });
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [enabled, reducedMotion]);

  return <canvas ref={canvasRef} className="ambient-background" aria-hidden="true" />;
}
