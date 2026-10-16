import { useLayoutEffect, useRef, useState } from 'react';
import { Check, MessageSquare, Pencil, Pin, PinOff, Plus, Trash2, X } from 'lucide-react';
import type { ConversationThread } from '@workspace/api-client-react';
import { useConversations } from '@/components/conversation-provider';
import { newestThreadFirst } from '@/lib/thread-order';

function Row({ thread, onPicked, collapsed = false }: { thread: ConversationThread; onPicked?: () => void; collapsed?: boolean }) {
  const { selectedId, select, rename, setPinned, remove, restore } = useConversations();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(thread.title);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = selectedId === thread.id;
  const save = async () => {
    const next = title.trim();
    if (!next || next === thread.title) { setEditing(false); return; }
    setBusy(true);
    try { await rename(thread.id, next.slice(0, 100)); setEditing(false); } catch { /* error shown by list */ } finally { setBusy(false); }
  };
  if (editing) return <li className="chat-row editing">
    <input className="chat-title-input" value={title} maxLength={100} autoFocus aria-label="Chat title" data-testid="input-chat-title"
      onChange={(e) => setTitle(e.target.value)}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void save(); } if (e.key === 'Escape') { setTitle(thread.title); setEditing(false); } }} />
    <button type="button" className="chat-act" onClick={() => void save()} disabled={busy || !title.trim()} aria-label="Save title" data-testid="button-save-chat-title"><Check size={13} /></button>
    <button type="button" className="chat-act" onClick={() => { setTitle(thread.title); setEditing(false); }} aria-label="Cancel rename" data-testid="button-cancel-chat-title"><X size={13} /></button>
  </li>;
  if (confirming) return <li className="chat-row confirming" role="alertdialog" aria-label={`Delete ${thread.title}`}>
    <p>Delete this chat? Task activity records stay available in Task Activity.</p>
    <div>
      <button type="button" className="chat-confirm danger" disabled={busy} onClick={async () => { setBusy(true); try { await remove(thread.id); } catch { setConfirming(false); } finally { setBusy(false); } }} data-testid={`button-confirm-delete-chat-${thread.id}`}>Delete</button>
      <button type="button" className="chat-confirm" onClick={() => setConfirming(false)} data-testid={`button-cancel-delete-chat-${thread.id}`}>Keep</button>
    </div>
  </li>;
  return <li className={`chat-row ${active ? 'active' : ''}`} data-testid={`chat-thread-${thread.id}`}>
    <button type="button" className="chat-pick" onClick={() => { select(thread.id); onPicked?.(); }} aria-current={active ? 'true' : undefined} aria-label={thread.title} title={thread.title} data-testid={`button-select-chat-${thread.id}`}>
      {thread.activeTaskId ? <span className="exec-dot live" aria-label="Running" /> : thread.pinned ? <Pin size={12} /> : <MessageSquare size={12} />}
      <span>{thread.title}</span>
    </button>
    {!collapsed && <span className="chat-acts">
      {thread.archived && <button type="button" className="chat-act" onClick={() => void restore(thread.id)} aria-label="Restore archived chat" title="Restore chat">↩</button>}
      <button type="button" className="chat-act" onClick={() => void setPinned(thread.id, !thread.pinned)} aria-label={thread.pinned ? 'Unpin chat' : 'Pin chat'} aria-pressed={thread.pinned} data-testid={`button-pin-chat-${thread.id}`}>{thread.pinned ? <PinOff size={12} /> : <Pin size={12} />}</button>
      <button type="button" className="chat-act" onClick={() => { setTitle(thread.title); setEditing(true); }} aria-label="Rename chat" data-testid={`button-rename-chat-${thread.id}`}><Pencil size={12} /></button>
      <button type="button" className="chat-act" onClick={() => setConfirming(true)} aria-label="Delete chat" data-testid={`button-delete-chat-${thread.id}`}><Trash2 size={12} /></button>
    </span>}
  </li>;
}

export function NewChatAction({ onPicked, collapsed = false }: { onPicked?: () => void; collapsed?: boolean }) {
  const { newChat, creating } = useConversations();
  return <button
    type="button"
    className="new-chat-button"
    onClick={() => { newChat(); onPicked?.(); }}
    disabled={creating}
    aria-label="New Task / Chat"
    title={collapsed ? 'New Task / Chat' : undefined}
    data-testid="button-new-chat"
  ><Plus size={14} /><span>New Task / Chat</span></button>;
}

export function RecentSessions({ onPicked, collapsed = false }: { onPicked?: () => void; collapsed?: boolean }) {
  const { threads, loading, error, retry, actionError, archiveOld, showArchived, toggleArchived, selectedId } = useConversations();
  const listRef = useRef<HTMLUListElement>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const ordered = [...threads].sort(newestThreadFirst);
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list || !selectedId) return;
    if (ordered[0]?.id === selectedId) { list.scrollTop = 0; return; }
    const active = list.querySelector('[aria-current="true"]');
    if (!active) return;
    const row = active.getBoundingClientRect();
    const box = list.getBoundingClientRect();
    if (row.top < box.top) list.scrollTop += row.top - box.top;
    else if (row.bottom > box.bottom) list.scrollTop += row.bottom - box.bottom;
  }, [selectedId, ordered[0]?.id]);
  return <section className="chat-sidebar chat-sidebar-nested" aria-label="Recent sessions">
    <div className="sidebar-section-title chat-sidebar-title" role="heading" aria-level={2}>RECENT SESSIONS</div>
    {!collapsed && <div className="chat-archive-controls">
      <button type="button" onClick={() => setConfirmArchive(true)} disabled={archiving}>Archive old sessions</button>
      <button type="button" onClick={toggleArchived} aria-pressed={showArchived}>{showArchived ? 'Hide archived' : 'Show archived'}</button>
      {confirmArchive && <div role="alertdialog" aria-label="Archive old sessions"><p>Archive inactive, unpinned chats and open a clean view? History and Task Activity are preserved. Use Show archived to restore them.</p><button type="button" disabled={archiving} onClick={async () => { setArchiving(true); await archiveOld(); setArchiving(false); setConfirmArchive(false); }}>Archive</button><button type="button" onClick={() => setConfirmArchive(false)}>Cancel</button></div>}
    </div>}
    {actionError && <p className="chat-error" role="alert" data-testid="text-chat-error">{actionError}</p>}
    {loading ? <div className="chat-skeleton" aria-busy="true"><i /><i /><i /></div>
      : error && !threads.length ? <p className="chat-error" role="alert">Chats could not load. <button type="button" onClick={retry} data-testid="button-retry-chats">Retry</button></p>
      : !ordered.length ? <p className="chat-empty">No chats yet. Send a request to start one.</p>
      : <ul className="chat-list" ref={listRef}>{ordered.map((t) => <Row key={t.id} thread={t} onPicked={onPicked} collapsed={collapsed} />)}</ul>}
  </section>;
}
