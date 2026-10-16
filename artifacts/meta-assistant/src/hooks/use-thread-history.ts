import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import type { InfiniteData } from '@tanstack/react-query';
import { useMemo } from 'react';
import { getConversationThread, getGetConversationThreadQueryKey } from '@workspace/api-client-react';
import type { ConversationThreadDetail } from '@workspace/api-client-react';

export function mergeLatestPage(latest: ConversationThreadDetail, previous?: InfiniteData<ConversationThreadDetail>) {
  if (!previous || previous.pages.length < 2) return latest;
  const old = previous.pages[0];
  // Once earlier history is loaded, hold its boundary steady during streaming.
  // Otherwise a moving newest-page cursor could skip messages between pages.
  return {
    ...latest,
    nextBefore: old.nextBefore,
    messages: [...new Map([...old.messages, ...latest.messages].map((message) => [message.id, message])).values()],
    tasks: [...new Map([...old.tasks, ...latest.tasks].map((task) => [task.id, task])).values()],
  };
}

/** Poll only the newest page while work is active; older pages stay cached. */
export function useThreadHistory(id: string | undefined) {
  const qc = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: [...getGetConversationThreadQueryKey(id ?? ''), 'paged'],
    enabled: !!id,
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam, signal }) => {
      if (pageParam) return qc.fetchQuery({
        queryKey: [...getGetConversationThreadQueryKey(id!), 'older', pageParam],
        queryFn: () => getConversationThread(id!, { before: pageParam }, { signal }),
        staleTime: Infinity,
      });
      const latest = await getConversationThread(id!, undefined, { signal });
      return mergeLatestPage(latest, qc.getQueryData<InfiniteData<ConversationThreadDetail>>(
        [...getGetConversationThreadQueryKey(id!), 'paged'],
      ));
    },
    getNextPageParam: (page) => page.nextBefore ?? undefined,
    staleTime: 30_000,
    refetchInterval: (q) => q.state.data?.pages[0]?.activeTaskId ? 2000 : false,
  });
  const data = useMemo(() => {
    const pages = query.data?.pages;
    if (!pages?.length) return undefined;
    // Newer data wins if a task spans adjacent pages.
    const chronological = [...pages].reverse();
    const tasks = new Map(chronological.flatMap((page) => page.tasks).map((task) => [task.id, task]));
    const messages = new Map(chronological.flatMap((page) => page.messages).map((message) => [message.id, message]));
    return { ...pages[0], tasks: [...tasks.values()], messages: [...messages.values()] };
  }, [query.data]);
  return { ...query, data };
}
