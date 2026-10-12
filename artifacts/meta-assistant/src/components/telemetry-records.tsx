import React from 'react';
import { BookOpen, FileText } from 'lucide-react';
import type { AssistantFile, AssistantNote } from '@workspace/api-client-react';
import type { TelemetryTaskLog } from '@/lib/telemetry';
import { formatClock, timeAgo } from '@/lib/telemetry';

type TelemetryFile = Pick<AssistantFile, 'id' | 'name'> & Partial<Pick<AssistantFile, 'createdAt'>>;
type TelemetryNote = Pick<AssistantNote, 'id' | 'title'> & Partial<Pick<AssistantNote, 'updatedAt'>>;

export function RecentFileRows({ files }: { files: TelemetryFile[] }) {
  return files.map((file) => <div className="telemetry-resource" key={file.id} data-testid={`telemetry-file-${file.id}`}>
    <FileText size={13} /><span title={file.name}>{file.name}</span><time>{timeAgo(file.createdAt)}</time>
  </div>);
}

export function RecentNoteRows({ notes }: { notes: TelemetryNote[] }) {
  return notes.map((note) => <div className="telemetry-resource" key={note.id} data-testid={`telemetry-note-${note.id}`}>
    <BookOpen size={13} /><span title={note.title}>{note.title}</span><time>{timeAgo(note.updatedAt)}</time>
  </div>);
}

export function RecentTaskLogRows({ logs }: { logs: TelemetryTaskLog[] }) {
  return logs.map((log) => <article className="telemetry-log-entry" key={`${log.taskId}-${log.id}`} data-testid={`telemetry-log-${log.id}`}>
    <i className={`telemetry-log-dot ${log.kind}`} />
    <div>
      <div className="telemetry-log-meta"><strong>{log.kind}</strong><time dateTime={log.createdAt ?? undefined}>{formatClock(log.createdAt)}</time></div>
      <span className="telemetry-log-task">{log.objective}</span>
      <p>{log.message}</p>
    </div>
  </article>);
}
