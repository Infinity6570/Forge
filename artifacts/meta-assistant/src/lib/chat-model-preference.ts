const STORAGE_PREFIX = 'forge:chat-model:';
const PROVIDERS = new Set(['openai', 'deepseek', 'gemini', 'anthropic', 'openrouter', 'ollama']);
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$/;

export type ChatModelPreference = {
  mode: 'configured' | 'last-used' | 'direct' | 'auto';
  provider?: string;
  model?: string;
  autoRouteMode?: 'auto-gemini' | 'auto-claude' | 'auto-openai' | 'auto-global';
};

const storageKey = (threadId?: string) => `${STORAGE_PREFIX}${threadId || 'new'}`;

export function loadChatModelPreference(threadId?: string): ChatModelPreference | null {
  try {
    const raw = localStorage.getItem(storageKey(threadId));
    if (!raw) return null;
    const saved = JSON.parse(raw) as Partial<ChatModelPreference>;
    if (!['configured', 'last-used', 'direct', 'auto'].includes(saved.mode ?? '')) return null;
    if (saved.mode === 'auto' && !['auto-gemini', 'auto-claude', 'auto-openai', 'auto-global'].includes(saved.autoRouteMode ?? '')) return null;
    if (saved.mode === 'direct' || saved.mode === 'last-used') {
      if (!saved.provider || !PROVIDERS.has(saved.provider)
        || !saved.model || !MODEL_ID.test(saved.model)) return null;
    }
    return saved as ChatModelPreference;
  } catch {
    return null;
  }
}

export function saveChatModelPreference(threadId: string | undefined, preference: ChatModelPreference) {
  try {
    localStorage.setItem(storageKey(threadId), JSON.stringify(preference));
  } catch {
    // Model selection still applies for the current session if storage is unavailable.
  }
}

export function modeForSavedPreference(preference: ChatModelPreference): string {
  if (preference.mode === 'direct' && preference.provider && preference.model) {
    return `direct|${preference.provider}|${preference.model}`;
  }
  if (preference.mode === 'auto' && preference.autoRouteMode) return preference.autoRouteMode;
  return preference.mode;
}

export function newestThreadModel(
  tasks: readonly { provider?: string | null; modelId?: string | null; createdAt?: string | null }[],
) {
  return tasks.reduce<(typeof tasks)[number] | undefined>((newest, task) => {
    if (!task.provider || !task.modelId) return newest;
    if (!newest) return task;
    const candidateTime = Date.parse(task.createdAt ?? '');
    const newestTime = Date.parse(newest.createdAt ?? '');
    return candidateTime > newestTime ? task : newest;
  }, undefined);
}
