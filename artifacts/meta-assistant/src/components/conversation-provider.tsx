import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'wouter';
import {
  getListConversationThreadsQueryKey,
  getGetConversationThreadQueryKey,
  useCreateConversationThread,
  useDeleteConversationThread,
  useListConversationThreads,
  useUpdateConversationThread,
} from '@workspace/api-client-react';
import type { ConversationThread } from '@workspace/api-client-react';
import { newestThreadFirst } from '@/lib/thread-order';

const STORAGE_KEY = 'forge:selected-thread';

type Ctx = {
  threads: ConversationThread[];
  loading: boolean;
  error: boolean;
  retry: () => void;
  selectedId: string | undefined;
  select: (id: string | undefined) => void;
  adopt: (id: string) => Promise<boolean>;
  newChat: () => void;
  creating: boolean;
  rename: (id: string, title: string) => Promise<void>;
  setPinned: (id: string, pinned: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
  actionError: string;
  clearActionError: () => void;
  resetSignal: number;
  showArchived: boolean;
  toggleArchived: () => void;
  archiveOld: () => Promise<void>;
  restore: (id: string) => Promise<void>;
};

const ConversationContext = createContext<Ctx | null>(null);

export function useConversations() {
  const ctx = useContext(ConversationContext);
  if (!ctx) throw new Error('useConversations must be used inside ConversationProvider');
  return ctx;
}

const statusOf = (error: unknown) => (error as { status?: number } | null)?.status;

export function ConversationProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [, navigate] = useLocation();
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [showArchived, setShowArchived] = useState(false);
  const [actionError, setActionError] = useState('');
  const [resetSignal, setResetSignal] = useState(0);
  const selectionVersion = useRef(0);
  const initialSelectionDone = useRef(false);
  const list = useListConversationThreads({ includeArchived: showArchived }, { query: { queryKey: getListConversationThreadsQueryKey({ includeArchived: showArchived }), refetchInterval: 10_000 } });
  const create = useCreateConversationThread();
  const update = useUpdateConversationThread();
  const del = useDeleteConversationThread();
  const threads = useMemo(() => list.data ?? [], [list.data]);

  const select = useCallback((id: string | undefined) => {
    initialSelectionDone.current = true;
    selectionVersion.current += 1;
    setSelectedId(id);
    try { if (id) window.localStorage.setItem(STORAGE_KEY, id); else window.localStorage.removeItem(STORAGE_KEY); } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    if (initialSelectionDone.current || !list.isSuccess) return;
    initialSelectionDone.current = true;
    const newest = [...(list.data ?? [])].filter((thread) => !thread.archived).sort(newestThreadFirst)[0];
    if (newest) select(newest.id);
  }, [list.isSuccess, list.data, select]);

  // Drop a stale selection once the list has loaded without it.
  useEffect(() => {
    if (selectedId && list.isSuccess && list.data && !list.isFetching && !list.data.some((t) => t.id === selectedId)) select(undefined);
  }, [selectedId, list.data, list.isSuccess, list.isFetching, select]);

  const adopt = useCallback(async (id: string) => {
    const version = selectionVersion.current;
    await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
    if (selectionVersion.current !== version) return false;
    select(id);
    return true;
  }, [qc, select]);

  const newChat = useCallback(() => {
    // An explicit fresh-chat request wins even if the sidebar is still loading.
    initialSelectionDone.current = true;
    setActionError('');
    const version = selectionVersion.current;
    create.mutate({ data: {} }, {
      onSuccess: async (thread) => {
        if (selectionVersion.current !== version) { await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() }); return; }
        if (await adopt(thread.id)) { setResetSignal((n) => n + 1); navigate('/'); }
      },
      onError: () => setActionError('A new chat could not be created. Try again.'),
    });
  }, [create, adopt, navigate, qc]);

  const rename = useCallback(async (id: string, title: string) => {
    setActionError('');
    try {
      await update.mutateAsync({ id, data: { title } });
      await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
      await qc.invalidateQueries({ queryKey: getGetConversationThreadQueryKey(id) });
    } catch (error) { setActionError('The chat could not be renamed.'); throw error; }
  }, [update, qc]);

  const setPinned = useCallback(async (id: string, pinned: boolean) => {
    setActionError('');
    try {
      await update.mutateAsync({ id, data: { pinned } });
      await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
    } catch { setActionError('The pin could not be changed.'); }
  }, [update, qc]);

  const remove = useCallback(async (id: string) => {
    setActionError('');
    try {
      await del.mutateAsync({ id });
      if (selectedId === id) { select(undefined); setResetSignal((n) => n + 1); }
      await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
    } catch (error) {
      setActionError(statusOf(error) === 409 ? 'This chat is still running. Stop the task before deleting it.' : 'The chat could not be deleted.');
      throw error;
    }
  }, [del, qc, selectedId, select]);

  const restore = async (id: string) => {
    try {
      await update.mutateAsync({ id, data: { archived: false } });
      await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() });
    } catch { setActionError('The chat could not be restored.'); }
  };
  const archiveOld = async () => {
    setActionError('');
    try {
      // Pinned chats and runs awaiting approval are never archived.
      for (const thread of threads.filter((t) => !t.archived && !t.pinned && !t.activeTaskId)) {
        await update.mutateAsync({ id: thread.id, data: { archived: true } });
        if (thread.id === selectedId) select(undefined);
      }
      setResetSignal((n) => n + 1);
    } catch { setActionError('Some chats could not be archived. No history was deleted.'); }
    finally { await qc.invalidateQueries({ queryKey: getListConversationThreadsQueryKey() }); }
  };
  const value: Ctx = {
    threads, loading: list.isLoading, error: list.isError, retry: () => { void list.refetch(); },
    selectedId, select, adopt, newChat, creating: create.isPending, rename, setPinned, remove,
    actionError, clearActionError: () => setActionError(''), resetSignal,
    showArchived, toggleArchived: () => setShowArchived((v) => !v), archiveOld, restore,
  };
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}
