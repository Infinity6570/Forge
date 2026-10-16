import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  loadChatModelPreference,
  modeForSavedPreference,
  newestThreadModel,
  saveChatModelPreference,
} from './chat-model-preference';

function memoryStorage() {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
  });
  return () => Reflect.deleteProperty(globalThis, 'localStorage');
}

test('stores a model by chat, restores it, and ignores malformed selections', () => {
  const cleanup = memoryStorage();
  try {
    saveChatModelPreference('thread-1', { mode: 'direct', provider: 'anthropic', model: 'claude-opus-5-5' });
    saveChatModelPreference('thread-2', { mode: 'direct', provider: 'deepseek', model: 'deepseek-reasoner' });
    assert.deepEqual(loadChatModelPreference('thread-1'), {
      mode: 'direct', provider: 'anthropic', model: 'claude-opus-5-5',
    });
    assert.equal(modeForSavedPreference(loadChatModelPreference('thread-1')!), 'direct|anthropic|claude-opus-5-5');
    assert.equal(loadChatModelPreference('thread-2')?.model, 'deepseek-reasoner');
    assert.equal(loadChatModelPreference('thread-3'), null);
    localStorage.setItem('forge:chat-model:bad', JSON.stringify({ mode: 'direct', provider: 'anthropic', model: '../bad' }));
    assert.equal(loadChatModelPreference('bad'), null);
  } finally {
    cleanup();
  }
});

test('persists provider-scoped auto routing independently for each chat', () => {
  const cleanup = memoryStorage();
  try {
    saveChatModelPreference('thread-auto', { mode: 'auto', autoRouteMode: 'auto-gemini' });
    assert.deepEqual(loadChatModelPreference('thread-auto'), {
      mode: 'auto',
      autoRouteMode: 'auto-gemini',
    });
    assert.equal(modeForSavedPreference(loadChatModelPreference('thread-auto')!), 'auto-gemini');
    localStorage.setItem('forge:chat-model:bad-auto', JSON.stringify({
      mode: 'auto',
      autoRouteMode: 'auto-ollama',
    }));
    assert.equal(loadChatModelPreference('bad-auto'), null);
  } finally {
    cleanup();
  }
});

test('restores the most recently used model in the selected thread', () => {
  const latest = newestThreadModel([
    { provider: 'deepseek', modelId: 'deepseek-chat', createdAt: '2026-01-01T00:00:00Z' },
    { provider: 'anthropic', modelId: 'claude-sonnet-5-5', createdAt: '2026-02-01T00:00:00Z' },
    { provider: null, modelId: null, createdAt: '2026-03-01T00:00:00Z' },
  ]);
  assert.equal(latest?.provider, 'anthropic');
  assert.equal(latest?.modelId, 'claude-sonnet-5-5');
});
