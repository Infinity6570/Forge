import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createCyberBackground } from './cyber-background-renderer';

test('clinic sphere, orbits, waves, links and ripples use finite 2D geometry', () => {
  let rectangles = 0, orbits = 0, sprites = 0, strokes = 0;
  const finite = (...args: unknown[]) => args.filter((v) => typeof v === 'number').forEach((v) => assert.ok(Number.isFinite(v)));
  const ctx = {
    setTransform: finite, clearRect: finite, beginPath() {}, moveTo: finite, lineTo: finite,
    fillRect(...args: number[]) { finite(...args); rectangles++; },
    ellipse(...args: number[]) { finite(...args); orbits++; },
    arc: finite, fill() {}, stroke() { strokes++; },
    drawImage(_image: unknown, ...args: number[]) { finite(...args); sprites++; },
    createRadialGradient() { return { addColorStop() {} }; },
  };
  const canvas = {
    width: 0, height: 0,
    getContext(kind: string, options: unknown) {
      assert.equal(kind, '2d');
      assert.deepEqual(options, { alpha: true, desynchronized: true });
      return ctx;
    },
  } as unknown as HTMLCanvasElement;
  const oldWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const oldDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { innerWidth: 1440, innerHeight: 900, devicePixelRatio: 2 } });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => ({ getContext: () => ctx }) } });
  try {
    const renderer = createCyberBackground(canvas)!;
    renderer.resize();
    assert.equal(canvas.width, 2160);
    renderer.pointer(700, 400);
    renderer.ripple(700, 400);
    for (let frame = 0; frame < 5; frame++) renderer.draw(1);
    assert.ok(rectangles >= 420 * 5);
    assert.equal(orbits, 15);
    assert.equal(sprites, 15);
    assert.ok(strokes >= 35);
    renderer.clear();
  } finally {
    if (oldWindow) Object.defineProperty(globalThis, 'window', oldWindow); else Reflect.deleteProperty(globalThis, 'window');
    if (oldDocument) Object.defineProperty(globalThis, 'document', oldDocument); else Reflect.deleteProperty(globalThis, 'document');
  }
});
