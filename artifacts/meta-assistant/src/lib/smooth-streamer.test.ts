import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SmoothStreamer } from './smooth-streamer';

function fakeScheduler() {
  let nextId = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const scheduler = {
    requestFrame(callback: FrameRequestCallback) { const id = ++nextId; frames.set(id, callback); return id; },
    cancelFrame(id: number) { frames.delete(id); },
  };
  return {
    scheduler,
    step(timestamp: number) {
      const frame = [...frames.entries()][0];
      assert.ok(frame, 'a frame was scheduled');
      frames.delete(frame[0]);
      frame[1](timestamp);
    },
    get size() { return frames.size; },
  };
}

test('queues variable network chunks and reveals Unicode text at a frame cadence', () => {
  const clock = fakeScheduler();
  const updates: string[] = [];
  const streamer = new SmoothStreamer((text) => updates.push(text), clock.scheduler);
  streamer.push('ab');
  streamer.push('😀cdef');
  assert.equal(updates.length, 0, 'network chunks do not update the view directly');
  clock.step(16.67);
  assert.equal(streamer.text, 'ab😀c');
  clock.step(33.34);
  assert.equal(streamer.text, 'ab😀cdef');
  streamer.flush();
  assert.equal(streamer.text, 'ab😀cdef');
  assert.equal(streamer.queuedCharacters, 0);
  assert.equal(clock.size, 0);
});

test('completion immediately flushes an incomplete response and stops scheduled frames', () => {
  const clock = fakeScheduler();
  const updates: string[] = [];
  const streamer = new SmoothStreamer((text) => updates.push(text), clock.scheduler);
  streamer.push('partially');
  streamer.complete('final answer');
  assert.equal(streamer.text, 'final answer');
  assert.equal(updates.at(-1), 'final answer');
  assert.equal(clock.size, 0);
  streamer.push('late');
  assert.equal(streamer.text, 'final answer');
});

test('an SSE snapshot replaces stale queued deltas before animating new text', () => {
  const clock = fakeScheduler();
  const streamer = new SmoothStreamer(() => {}, clock.scheduler);
  streamer.push('stale');
  streamer.replace('authoritative snapshot');
  assert.equal(streamer.text, 'authoritative snapshot');
  assert.equal(streamer.queuedCharacters, 0);
  assert.equal(clock.size, 0);
  streamer.push(' next');
  streamer.flush();
  assert.equal(streamer.text, 'authoritative snapshot next');
});
