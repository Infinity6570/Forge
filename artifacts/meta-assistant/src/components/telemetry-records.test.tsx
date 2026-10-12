import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RecentFileRows, RecentNoteRows, RecentTaskLogRows } from './telemetry-records';
import { formatClock, getRecentFiles, getRecentNotes, getRecentTaskLogs } from '../lib/telemetry';

test('recent files keep visible when their timestamps are missing or invalid', () => {
  const files = getRecentFiles([
    { id: 'missing', name: 'Missing date.txt' },
    { id: 'invalid', name: 'Invalid date.txt', createdAt: 'not-a-date' },
    { id: 'dated', name: 'Dated file.txt', createdAt: '2000-10-12T11:00:00Z' },
  ]);
  const markup = renderToStaticMarkup(createElement(RecentFileRows, { files }));

  assert.match(markup, /Dated file\.txt/);
  assert.match(markup, /Missing date\.txt/);
  assert.match(markup, /Invalid date\.txt/);
  assert.equal((markup.match(/Just now/g) ?? []).length, 2);
});

test('recent notes sort safely when created or updated timestamps are missing or invalid', () => {
  const notes = getRecentNotes([
    { id: 'missing', title: 'No dates' },
    { id: 'invalid', title: 'Invalid update', createdAt: '2000-10-10T11:00:00Z', updatedAt: 'invalid' },
    { id: 'dated', title: 'Recently updated', createdAt: '2000-10-01T11:00:00Z', updatedAt: '2000-10-12T11:00:00Z' },
  ]);
  const markup = renderToStaticMarkup(createElement(RecentNoteRows, { notes }));

  assert.match(markup, /Recently updated/);
  assert.match(markup, /Invalid update/);
  assert.match(markup, /No dates/);
  assert.equal((markup.match(/Just now/g) ?? []).length, 2);
});

test('recent task logs render available events when timestamps are missing or invalid', () => {
  const logs = getRecentTaskLogs([
    {
      id: 'missing',
      objective: 'Task with missing timestamp',
      logs: [{ id: 'missing-time', kind: 'info', message: 'Still visible without a date' }],
    },
    {
      id: 'invalid',
      objective: 'Task with invalid timestamp',
      logs: [{ id: 'invalid-time', kind: 'warning', message: 'Still visible with a bad date', createdAt: 'yesterday-ish' }],
    },
    {
      id: 'dated',
      objective: 'Task with valid timestamp',
      logs: [{ id: 'valid-time', kind: 'success', message: 'Valid event', createdAt: '2000-10-12T11:00:00Z' }],
    },
  ] as Parameters<typeof getRecentTaskLogs>[0]);
  const markup = renderToStaticMarkup(createElement(RecentTaskLogRows, { logs }));

  assert.match(markup, /Still visible without a date/);
  assert.match(markup, /Still visible with a bad date/);
  assert.match(markup, /Valid event/);
  assert.equal((markup.match(/TIME N\/A/g) ?? []).length, 2);
  assert.equal((markup.match(/<article/g) ?? []).length, 3);
});

test('invalid and absent clock timestamps use the safe display fallback', () => {
  assert.equal(formatClock(undefined), 'TIME N/A');
  assert.equal(formatClock('not-a-date'), 'TIME N/A');
});
