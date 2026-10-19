import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AssistantTask, ConversationMessage, ConversationThreadDetail, ConversationThread } from '@workspace/api-client-react';
import { ActivityStream } from './activity-stream';
import { mergeLatestPage } from '../hooks/use-thread-history';
import { newestThreadFirst } from '../lib/thread-order';
import { distanceFromBottom, prependedScrollTop } from '../lib/chat-scroll';

const task = {
  id: 'history-task', objective: 'Read saved history', status: 'completed',
  createdAt: '2026-10-01T12:00:00Z', updatedAt: '2026-10-01T12:00:00Z',
  logs: [{ id: 'log-1', kind: 'agent', message: 'HIDDEN_THINKING_TRACE', createdAt: '2026-10-01T12:00:00Z' }],
  result: 'Final **answer**.', error: null,
} as AssistantTask;
const message = {
  id: 'tool-1', threadId: 'thread-1', taskId: task.id, role: 'tool', content: 'HIDDEN_TOOL_OUTPUT',
  createdAt: task.createdAt, thoughtSteps: [], isToolCall: false,
} as ConversationMessage;

test('historical thinking and tool contents are not mounted while collapsed', () => {
  const html = renderToStaticMarkup(createElement(ActivityStream, {
    tasks: [task], messages: [message], loading: false, onOpen: () => {},
  }));
  assert.match(html, /Execution activity \(2 steps\)/);
  assert.match(html, /Final <strong>answer<\/strong>/);
  assert.doesNotMatch(html, /HIDDEN_THINKING_TRACE|HIDDEN_TOOL_OUTPUT|class="exec-raw"/);
  assert.doesNotMatch(html, /<details[^>]* open/);
});

test('provider-authored Claude summaries are visible without exposing raw thought traces', () => {
  const summaryTask = {
    ...task,
    logs: [{
      id: 'summary-1', kind: 'agent',
      message: 'Claude thinking summary:\nThe evidence supports checking the primary source next.',
      createdAt: '2026-10-01T12:00:01Z',
    }],
  } as AssistantTask;
  const html = renderToStaticMarkup(createElement(ActivityStream, {
    tasks: [summaryTask], loading: false, onOpen: () => {},
  }));
  assert.match(html, /<details[^>]* open/);
  assert.match(html, /class="exec-provider-summary"/);
  assert.match(html, /The evidence supports checking the primary source next/);
  assert.match(html, /private model reasoning is not displayed/);
  assert.doesNotMatch(html, /Claude thinking summary:/);
});

test('earlier history has an explicit load control', () => {
  const html = renderToStaticMarkup(createElement(ActivityStream, {
    tasks: [task], loading: false, onOpen: () => {}, hasEarlier: true, onLoadEarlier: () => {},
  }));
  assert.match(html, /Load earlier messages/);
  assert.ok(html.indexOf('Load earlier messages') < html.indexOf('Read saved history'));
});

test('sidebar orders by activity then creation, regardless of pinned status', () => {
  const thread = (id: string, updatedAt: string, createdAt: string, pinned = false) =>
    ({ id, updatedAt, createdAt, pinned }) as ConversationThread;
  const sorted = [
    thread('pinned-old', '2026-01-01', '2026-01-01', true),
    thread('newer-creation', '2026-02-02', '2026-02-01'),
    thread('older-creation', '2026-02-02', '2026-01-31'),
    thread('most-active', '2026-03-01', '2025-01-01'),
  ].sort(newestThreadFirst);
  assert.deepEqual(sorted.map((t) => t.id), ['most-active', 'newer-creation', 'older-creation', 'pinned-old']);
});

test('prepending keeps the reading offset including nonzero previous scroll position', () => {
  assert.equal(prependedScrollTop({ height: 2000, top: 0 }, 3200), 1200);
  assert.equal(prependedScrollTop({ height: 2000, top: 85 }, 3200), 1285);
  assert.equal(prependedScrollTop({ height: 2000, top: 85 }, 2000), 85);
  assert.equal(prependedScrollTop({ height: 2000, top: 0 }, 1800), 0);
});

test('jump-to-latest threshold is strictly more than 200 pixels from bottom', () => {
  const el = { scrollHeight: 2000, clientHeight: 600, scrollTop: 1199 };
  assert.ok(distanceFromBottom(el) > 200);
  assert.equal(distanceFromBottom({ ...el, scrollTop: 1200 }), 200);
  assert.equal(distanceFromBottom({ ...el, scrollTop: 1400 }), 0);
  assert.equal(distanceFromBottom({ ...el, scrollTop: 1500 }), 0);
});

test('streaming newest history preserves loaded-page boundary and updated tasks', () => {
  const old = { messages: [{ ...message, id: 'old' }], tasks: [task], nextBefore: 10 } as ConversationThreadDetail;
  const latest = { ...old, messages: [{ ...message, id: 'new' }], tasks: [{ ...task, result: 'Updated' }], nextBefore: 11 };
  const merged = mergeLatestPage(latest, { pages: [old, old], pageParams: [undefined, 10] });
  assert.equal(merged.nextBefore, 10);
  assert.deepEqual(merged.messages.map((m) => m.id), ['old', 'new']);
  assert.equal(merged.tasks[0].result, 'Updated');
  assert.equal(mergeLatestPage(latest, { pages: [old], pageParams: [undefined] }), latest);
});
