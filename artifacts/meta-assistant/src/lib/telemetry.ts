import type { AssistantFile, AssistantNote, AssistantTask, TaskLog } from '@workspace/api-client-react';

type TelemetryFile = Pick<AssistantFile, 'id' | 'name'> & Partial<Pick<AssistantFile, 'createdAt'>>;
type TelemetryNote = Pick<AssistantNote, 'id' | 'title'> & Partial<Pick<AssistantNote, 'createdAt' | 'updatedAt'>>;
type TelemetryTask = Pick<AssistantTask, 'id' | 'objective' | 'logs'>;
export type TelemetryTaskLog = Pick<TaskLog, 'id' | 'kind' | 'message'> & {
  createdAt?: string | null;
  objective: string;
  taskId: string;
};

function timestampValue(value?: string | null) {
  const parsed = Date.parse(value ?? '');
  return Number.isFinite(parsed) ? parsed : 0;
}

export function getRecentFiles(files: TelemetryFile[] = []) {
  return [...files]
    .sort((a, b) => timestampValue(b.createdAt) - timestampValue(a.createdAt))
    .slice(0, 4);
}

export function getRecentNotes(notes: TelemetryNote[] = []) {
  return [...notes]
    .sort((a, b) => timestampValue(b.updatedAt ?? b.createdAt) - timestampValue(a.updatedAt ?? a.createdAt))
    .slice(0, 4);
}

export function getRecentTaskLogs(tasks: TelemetryTask[] = []): TelemetryTaskLog[] {
  return tasks.flatMap((task) => task.logs.map((log) => ({
    ...log,
    objective: task.objective,
    taskId: task.id,
  })))
    .sort((a, b) => timestampValue(b.createdAt) - timestampValue(a.createdAt))
    .slice(0, 10);
}

export function timeAgo(value?: string | null) {
  if (!value) return 'Just now';
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return 'Just now';
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function formatClock(value?: string | null) {
  if (!value) return 'TIME N/A';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return 'TIME N/A';
  return new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}
