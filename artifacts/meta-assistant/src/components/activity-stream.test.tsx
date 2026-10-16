import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AssistantTask, ConversationMessage, ConversationThreadDetail } from '@workspace/api-client-react';
import { ActivityStream } from './activity-stream';
import { mergeLatestPage } from '../hooks/use-thread-history';

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
  assert.match(html, /Thinking \(2 steps\)/);
  assert.match(html, /Final <strong>answer<\/strong>/);
  assert.doesNotMatch(html, /HIDDEN_THINKING_TRACE|HIDDEN_TOOL_OUTPUT|class="exec-raw"/);
  assert.doesNotMatch(html, /<details[^>]* open/);
});

test('earlier history has an explicit load control', () => {
  const html = renderToStaticMarkup(createElement(ActivityStream, {
    tasks: [task], loading: false, onOpen: () => {}, hasEarlier: true, onLoadEarlier: () => {},
  }));
  assert.match(html, /Load earlier messages/);
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
