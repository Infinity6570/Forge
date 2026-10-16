/**
 * Forge port of workspace/dental-clinic/js/background.js.
 * Retains its Fibonacci sphere, three satellite orbits, repulsion, waves and
 * click pulses; buffers and glow sprites are allocated outside the frame loop.
 * Canvas 2D raster acceleration is ultimately controlled by the browser/driver.
 */
export function createCyberBackground(canvas: HTMLCanvasElement) {
  const ctx = canvas.getContext('2d', { alpha: true, desynchronized: true });
  if (!ctx) return null;
  const floaters = new Float32Array(104 * 6); // x,y,vx,vy,radius,palette
  const sphere = new Float32Array(420 * 3);
  const ripples = new Float32Array(12 * 4); // x,y,radius,alpha
  const sphereColors = Array.from({ length: 32 }, (_, i) =>
    `hsl(${280 - i * 95 / 31} 100% ${62 + i * 16 / 31}%)`);
  const glow = document.createElement('canvas');
  glow.width = glow.height = 40;
  const glowCtx = glow.getContext('2d');
  if (glowCtx) {
    const gradient = glowCtx.createRadialGradient(20, 20, 0, 20, 20, 20);
    gradient.addColorStop(0, 'rgba(235,255,255,1)');
    gradient.addColorStop(0.2, 'rgba(0,240,255,.9)');
    gradient.addColorStop(1, 'rgba(0,240,255,0)');
    glowCtx.fillStyle = gradient;
    glowCtx.fillRect(0, 0, 40, 40);
  }
  let width = 0, height = 0, count = 0, sphereCount = 420, t = 140;
  let mouseX = -9999, mouseY = -9999, parallaxX = 0, parallaxY = 0, rippleIndex = 0;
  let workTarget = 0, workEnergy = 0;
  const tau = Math.PI * 2;

  const resize = () => {
    width = window.innerWidth;
    height = window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    count = Math.min(104, Math.max(28, Math.floor(width * height / 16000)));
    for (let i = 0; i < count * 6; i += 6) {
      floaters[i] = Math.random() * width; floaters[i + 1] = Math.random() * height;
      floaters[i + 2] = (Math.random() - 0.5) * 0.5;
      floaters[i + 3] = (Math.random() - 0.5) * 0.5;
      floaters[i + 4] = 1 + Math.random() * 1.6;
      floaters[i + 5] = Math.random() < 0.7 ? 0 : 1;
    }
    sphereCount = width < 700 ? 220 : 420;
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < sphereCount; i++) {
      const y = 1 - i / (sphereCount - 1) * 2;
      const r = Math.sqrt(1 - y * y);
      sphere[i * 3] = Math.cos(golden * i) * r;
      sphere[i * 3 + 1] = y;
      sphere[i * 3 + 2] = Math.sin(golden * i) * r;
    }
    ripples.fill(0);
  };

  const draw = (dt: number) => {
    t += dt;
    workEnergy += (workTarget - workEnergy) * Math.min(1, 0.045 * dt);
    const beat = 0.5 + 0.5 * Math.sin(t * 0.055);
    const workPulse = workEnergy * beat;
    const targetX = mouseX < 0 ? 0 : mouseX / width - 0.5;
    const targetY = mouseY < 0 ? 0 : mouseY / height - 0.5;
    parallaxX += (targetX - parallaxX) * Math.min(1, 0.045 * dt);
    parallaxY += (targetY - parallaxY) * Math.min(1, 0.045 * dt);
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = 'lighter';
    // Bottom data-stream waves from the clinic background.
    for (let wave = 0; wave < 3; wave++) {
      ctx.beginPath();
      for (let x = 0; x <= width + 12; x += 12) {
        const y = height * (0.80 + wave * 0.055)
          + Math.sin(x * 0.006 + t * 0.02 + wave) * 26 + Math.sin(x * 0.013 - t * 0.013) * 12;
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = wave === 1 ? '#b44cff' : wave === 2 ? '#ff3ea5' : '#00f0ff';
      ctx.globalAlpha = 0.65; ctx.lineWidth = 1.8; ctx.stroke();
    }
    const radius = Math.min(width, height) * 0.31 * (1 + workPulse * 0.045);
    const cx = width * 0.72 + parallaxX * 42, cy = height * 0.48 + parallaxY * 42;
    const ay = t * (0.0025 + workEnergy * 0.0018) + parallaxX * 0.4;
    const ax = 0.35 + Math.sin(t * 0.001 + workPulse * 0.6) * (0.2 + workEnergy * 0.06) + parallaxY * 0.3;
    const cosY = Math.cos(ay), sinY = Math.sin(ay), cosX = Math.cos(ax), sinX = Math.sin(ax);
    for (let i = 0; i < sphereCount * 3; i += 3) {
      const x = sphere[i], y = sphere[i + 1], z = sphere[i + 2];
      const wobble = 1 + 0.06 * Math.sin(t * 0.02 + y * 6 + x * 4);
      const x1 = (x * cosY - z * sinY) * wobble;
      const z1 = (x * sinY + z * cosY) * wobble;
      const y1 = y * wobble * cosX - z1 * sinX;
      const z2 = y * wobble * sinX + z1 * cosX;
      const scale = 2.6 / (2.6 + z2);
      const depth = Math.max(0, Math.min(1, (1 - z2) / 2));
      const size = 1.6 + depth * 3.2;
      ctx.fillStyle = sphereColors[Math.min(31, Math.floor(depth * 31))];
      ctx.globalAlpha = Math.min(1, 0.28 + depth * 0.72 + workPulse * (0.12 + depth * 0.16));
      ctx.fillRect(cx + x1 * radius * scale - size / 2, cy + y1 * radius * scale - size / 2, size, size);
    }
    for (let orbit = 0; orbit < 3; orbit++) {
      const rx = radius * (1.25 + orbit * 0.18), ry = radius * (0.28 + orbit * 0.05);
      const rotation = t * 0.0015 * (orbit % 2 ? -1 : 1) + orbit;
      ctx.beginPath(); ctx.strokeStyle = orbit === 1 ? '#b44cff' : '#00f0ff';
      ctx.globalAlpha = Math.min(1, 0.75 + workPulse * 0.22); ctx.lineWidth = 2 + workPulse * 1.1;
      ctx.ellipse(cx, cy, rx, ry, rotation, 0, tau); ctx.stroke();
      const angle = t * (0.01 + orbit * 0.004 + workEnergy * 0.005), ex = Math.cos(angle) * rx, ey = Math.sin(angle) * ry;
      ctx.globalAlpha = 1;
      ctx.drawImage(glow, cx + ex * Math.cos(rotation) - ey * Math.sin(rotation) - 20,
        cy + ex * Math.sin(rotation) + ey * Math.cos(rotation) - 20);
    }
    // Squared-distance checks avoid sqrt/hypot in the O(n²) network loop.
      const damping = Math.pow(0.995 - workEnergy * 0.002, dt);
    for (let i = 0; i < count * 6; i += 6) {
      const dx = floaters[i] - mouseX, dy = floaters[i + 1] - mouseY, d2 = dx * dx + dy * dy;
      if (d2 < 26000) {
        const force = (1 - d2 / 26000) * 0.24 * dt / (Math.abs(dx) + Math.abs(dy) + 1);
        floaters[i + 2] += dx * force; floaters[i + 3] += dy * force;
      }
      floaters[i + 2] *= damping; floaters[i + 3] *= damping;
      floaters[i + 2] += Math.sin(t * (0.01 + workEnergy * 0.01) + i) * (0.002 + workEnergy * 0.003) * dt;
      floaters[i + 3] += Math.cos(t * (0.01 + workEnergy * 0.01) + i) * (0.002 + workEnergy * 0.003) * dt;
      floaters[i] = (floaters[i] + floaters[i + 2] * dt + width) % width;
      floaters[i + 1] = (floaters[i + 1] + floaters[i + 3] * dt + height) % height;
      ctx.strokeStyle = '#00f0ff'; ctx.lineWidth = 0.85;
      for (let j = i + 6; j < count * 6; j += 6) {
        const lx = floaters[i] - floaters[j], ly = floaters[i + 1] - floaters[j + 1], distance2 = lx * lx + ly * ly;
        if (distance2 >= 21025) continue;
        ctx.globalAlpha = (1 - distance2 / 21025) * (0.45 + workPulse * 0.3);
        ctx.beginPath(); ctx.moveTo(floaters[i], floaters[i + 1]); ctx.lineTo(floaters[j], floaters[j + 1]); ctx.stroke();
      }
      if (d2 < 32400) {
        ctx.globalAlpha = (1 - d2 / 32400) * 0.8;
        ctx.beginPath(); ctx.moveTo(floaters[i], floaters[i + 1]); ctx.lineTo(mouseX, mouseY); ctx.stroke();
      }
      ctx.globalAlpha = Math.min(1, 0.9 + workPulse * 0.1); ctx.fillStyle = floaters[i + 5] ? '#b44cff' : '#00f0ff';
      ctx.beginPath(); ctx.arc(floaters[i], floaters[i + 1], floaters[i + 4] * (1 + workPulse * 0.55), 0, tau); ctx.fill();
    }
    for (let i = 0; i < ripples.length; i += 4) {
      if (ripples[i + 3] < 0.02) continue;
      ripples[i + 2] += 5 * dt; ripples[i + 3] *= Math.pow(0.96, dt);
      ctx.globalAlpha = ripples[i + 3]; ctx.strokeStyle = '#00f0ff'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(ripples[i], ripples[i + 1], ripples[i + 2], 0, tau); ctx.stroke();
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  };
  return {
    resize, draw,
    setWorking(working: boolean, snap = false) {
      workTarget = working ? 1 : 0;
      if (snap) workEnergy = workTarget;
    },
    pointer(x: number, y: number) { mouseX = x; mouseY = y; },
    ripple(x: number, y: number) {
      const i = rippleIndex * 4; rippleIndex = (rippleIndex + 1) % 12;
      ripples[i] = x; ripples[i + 1] = y; ripples[i + 2] = 0; ripples[i + 3] = 0.85;
    },
    clear() { ctx.clearRect(0, 0, width, height); },
  };
}
