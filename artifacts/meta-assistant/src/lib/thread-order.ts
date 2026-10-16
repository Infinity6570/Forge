import type { ConversationThread } from '@workspace/api-client-react';

const timestamp = (value: string) => Date.parse(value) || 0;

/** Pinning is a marker, not an override of most-recent activity ordering. */
export function newestThreadFirst(a: ConversationThread, b: ConversationThread) {
  return timestamp(b.updatedAt) - timestamp(a.updatedAt)
    || timestamp(b.createdAt) - timestamp(a.createdAt)
    || b.id.localeCompare(a.id);
}
