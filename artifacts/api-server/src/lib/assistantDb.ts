import { createRequire } from "node:module";
import path from "node:path";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import initSqlJs, { type Database, type SqlValue } from "sql.js";

const require = createRequire(import.meta.url);
const workspaceRoot = path.join(process.cwd(), "workspace");
export const uploadsRoot = path.join(workspaceRoot, "uploads");
export const notesRoot = path.join(workspaceRoot, "notes");
const databasePath = path.join(workspaceRoot, "assistant.db");

let database: Database | undefined;
let writeQueue = Promise.resolve();

export async function initAssistantDb(): Promise<void> {
  await mkdir(uploadsRoot, { recursive: true });
  await mkdir(notesRoot, { recursive: true });

  const SQL = await initSqlJs({
    locateFile: (file) => path.join(path.dirname(require.resolve("sql.js")), file),
  });

  let initialData: Uint8Array | undefined;
  try {
    initialData = await readFile(databasePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  database = initialData ? new SQL.Database(initialData) : new SQL.Database();

  database.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY,
      objective TEXT NOT NULL,
      status TEXT NOT NULL,
      current_step TEXT,
      result TEXT,
      error TEXT,
      logs_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS timers (
      id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      kind TEXT NOT NULL,
      scheduled_for TEXT NOT NULL,
      recurrence TEXT NOT NULL DEFAULT 'none',
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notes (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      tags_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS files (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      extracted_text TEXT NOT NULL,
      disk_path TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS tasks_created_idx ON tasks(created_at DESC);
    CREATE INDEX IF NOT EXISTS timers_due_idx ON timers(status, scheduled_for);
  `);
  await persistAssistantDb();
}

export function db(): Database {
  if (!database) throw new Error("Assistant database has not been initialized");
  return database;
}

export function queryRows<T>(sql: string, params: SqlValue[] = []): T[] {
  const statement = db().prepare(sql);
  try {
    statement.bind(params);
    const rows: T[] = [];
    while (statement.step()) rows.push(statement.getAsObject() as T);
    return rows;
  } finally {
    statement.free();
  }
}

export function queryOne<T>(sql: string, params: SqlValue[] = []): T | undefined {
  return queryRows<T>(sql, params)[0];
}

export function execute(sql: string, params: SqlValue[] = []): void {
  db().run(sql, params);
}

export function persistAssistantDb(): Promise<void> {
  if (!database) throw new Error("Assistant database has not been initialized");
  const snapshot = Buffer.from(database.export());
  const temporaryPath = `${databasePath}.tmp`;
  writeQueue = writeQueue
    .catch(() => undefined)
    .then(async () => {
      await writeFile(temporaryPath, snapshot);
      await rename(temporaryPath, databasePath);
    });
  return writeQueue;
}
