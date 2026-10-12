import { useState } from 'react';
import { Check, MessageSquare, Pencil, Pin, PinOff, Plus, Trash2, X } from 'lucide-react';
import type { ConversationThread } from '@workspace/api-client-react';
import { useConversations } from '@/components/conversation-provider';

function Row({ thread, onPicked }: { thread: ConversationThread; onPicked?: () => void }) {
  const { selectedId, select, rename, setPinned, remove } = useConversations();
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
    <button type="button" className="chat-pick" onClick={() => { select(thread.id); onPicked?.(); }} aria-current={active ? 'true' : undefined} title={thread.title} data-testid={`button-select-chat-${thread.id}`}>
      {thread.activeTaskId ? <span className="exec-dot live" aria-label="Running" /> : thread.pinned ? <Pin size={12} /> : <MessageSquare size={12} />}
      <span>{thread.title}</span>
    </button>
    <span className="chat-acts">
      <button type="button" className="chat-act" onClick={() => void setPinned(thread.id, !thread.pinned)} aria-label={thread.pinned ? 'Unpin chat' : 'Pin chat'} aria-pressed={thread.pinned} data-testid={`button-pin-chat-${thread.id}`}>{thread.pinned ? <PinOff size={12} /> : <Pin size={12} />}</button>
      <button type="button" className="chat-act" onClick={() => { setTitle(thread.title); setEditing(true); }} aria-label="Rename chat" data-testid={`button-rename-chat-${thread.id}`}><Pencil size={12} /></button>
      <button type="button" className="chat-act" onClick={() => setConfirming(true)} aria-label="Delete chat" data-testid={`button-delete-chat-${thread.id}`}><Trash2 size={12} /></button>
    </span>
  </li>;
}

export function ChatSidebar({ onPicked }: { onPicked?: () => void }) {
  const { threads, loading, error, retry, newChat, creating, actionError } = useConversations();
  const ordered = [...threads].sort((a, b) => Number(b.pinned) - Number(a.pinned) || (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0));
  return <section className="chat-sidebar" aria-label="Chats">
    <button type="button" className="new-chat-button" onClick={() => { newChat(); onPicked?.(); }} disabled={creating} data-testid="button-new-chat"><Plus size={14} />New Task / Chat</button>
    <div className="sidebar-section-title chat-sidebar-title" role="heading" aria-level={2}>RECENT SESSIONS</div>
    {actionError && <p className="chat-error" role="alert" data-testid="text-chat-error">{actionError}</p>}
    {loading ? <div className="chat-skeleton" aria-busy="true"><i /><i /><i /></div>
      : error && !threads.length ? <p className="chat-error" role="alert">Chats could not load. <button type="button" onClick={retry} data-testid="button-retry-chats">Retry</button></p>
      : !ordered.length ? <p className="chat-empty">No chats yet. Send a request to start one.</p>
      : <ul className="chat-list">{ordered.map((t) => <Row key={t.id} thread={t} onPicked={onPicked} />)}</ul>}
  </section>;
}
