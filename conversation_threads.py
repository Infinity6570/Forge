"""Local SQLite conversations and public thread APIs, independent of any host."""
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from llm_protocol import to_wire
from history_display import display_task

BUSY = ("queued", "running", "awaiting_confirmation", "awaiting_approval")
LEGACY_EMPTY_RESPONSE = "The model returned no final text."


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def title_from_prompt(prompt: str) -> str:
    text = re.sub(r"(\d+)\s+days?\b", r"\1-Day", prompt, flags=re.I)
    words = re.findall(r"[\w]+(?:-[\w]+)*", text)
    if not words:
        return "New Chat Session"
    stop = set("please can could would you i me my a an the to for of in on with and this that make create build write help verification use".split())
    meaningful = [word for word in words if word.lower() not in stop][:5] or words[:5]
    if len(meaningful) < 3:
        meaningful += ["Chat", "Session"][:3-len(meaningful)]
    return " ".join(meaningful).title()[:100]


def balanced_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close interrupted tool turns without inventing successful tool results."""
    result: list[dict[str, Any]] = []
    pending: dict[str, bool] = {}

    def finish_pending() -> None:
        for call_id in pending:
            result.append({"role": "tool", "tool_call_id": call_id,
                           "content": '{"error":"Execution stopped before this tool returned a result."}'})
        pending.clear()

    for original in turns:
        turn = to_wire(original)
        if turn.get("role") != "tool":
            finish_pending()
        result.append(turn)
        if turn.get("role") == "assistant":
            pending.update({call["id"]: True for call in turn.get("tool_calls") or []})
        elif turn.get("role") == "tool":
            pending.pop(turn.get("tool_call_id"), None)
    finish_pending()
    return result


def malformed_empty_assistant(turn: dict[str, Any]) -> bool:
    """Exclude synthetic empty-final errors and assistant turns with no payload."""
    if turn.get("role") != "assistant" or turn.get("tool_calls"):
        return False
    if any(
        isinstance(part, dict) and ("functionCall" in part or "function_call" in part)
        for part in turn.get("parts") or []
    ):
        return False
    content = turn.get("content")
    return (
        content is None
        or (isinstance(content, str) and (not content.strip() or content.strip() == LEGACY_EMPTY_RESPONSE))
    )


def _history_tool_limit() -> int:
    """Max characters of one old tool result replayed into a new task (0 = no limit)."""
    try:
        return max(0, int(os.getenv("FORGE_HISTORY_TOOL_CHARS", "4000")))
    except ValueError:
        return 4000


def compact_history_turn(turn: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    """Shorten a large tool result from an earlier task before it is replayed.

    The assistant's own reply from that task already summarises the result, so
    replaying a 100k-character search dump on every later message only costs
    cache writes. Truncation is deterministic, which keeps the cached prefix
    stable between requests. The current task is never compacted.
    """
    limit = _history_tool_limit() if limit is None else limit
    content = turn.get("content")
    if limit <= 0 or turn.get("role") != "tool" or not isinstance(content, str) or len(content) <= limit:
        return turn
    omitted = len(content) - limit
    note = f"\n[... {omitted} characters omitted from an earlier turn to save context; re-run the tool if the detail is needed]"
    return {**turn, "content": content[:limit] + note}


def sanitize_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        turn for turn in (to_wire(item) for item in turns)
        if isinstance(turn, dict) and not malformed_empty_assistant(turn)
    ]


MEMORY_STOP_WORDS = frozenset({
    "about", "after", "also", "and", "are", "but", "can", "could", "for", "from",
    "have", "into", "its", "not", "our", "should", "that", "the", "their", "them",
    "then", "there", "these", "this", "those", "was", "were", "what", "when", "where",
    "which", "who", "will", "with", "would", "you", "your",
})
MEMORY_CONTEXT_LIMIT = 5
MEMORY_CONTEXT_CHARS = 3_100
MEMORY_CONTEXT_NOTE_CHARS = 1_000


def memory_terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\w-]{3,}", value)
        if token.casefold() not in MEMORY_STOP_WORDS
    }


class ThreadStore:
    def __init__(self, connect, lock):
        self.connect, self.lock = connect, lock

    @contextmanager
    def transaction(self):
        with self.lock:
            connection = self.connect()
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def initialize(self, connection) -> None:
        connection.executescript("""
          CREATE TABLE IF NOT EXISTS conversation_threads (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            model_provider TEXT, model_id TEXT);
          CREATE TABLE IF NOT EXISTS conversation_messages (
            ordering INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
            task_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
            content TEXT NOT NULL, protocol_json TEXT NOT NULL,
            thought_steps TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
            UNIQUE(task_id,sequence));
          CREATE INDEX IF NOT EXISTS conversation_messages_thread_idx ON conversation_messages(thread_id,ordering);
          CREATE INDEX IF NOT EXISTS tasks_thread_idx ON tasks(thread_id,created_at);
          CREATE TABLE IF NOT EXISTS conversation_meta (name TEXT PRIMARY KEY);
          CREATE TABLE IF NOT EXISTS project_memories (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, title_key TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS project_memories_updated_idx ON project_memories(updated_at DESC);
          CREATE TABLE IF NOT EXISTS project_memory_terms (
            memory_id TEXT NOT NULL, term TEXT NOT NULL, PRIMARY KEY(memory_id,term));
          CREATE INDEX IF NOT EXISTS project_memory_terms_term_idx
            ON project_memory_terms(term,memory_id);
        """)
        if not connection.execute(
            "SELECT 1 FROM conversation_meta WHERE name='project_memory_search_index_v1'"
        ).fetchone():
            for row in connection.execute("SELECT id,title,content,tags_json FROM project_memories").fetchall():
                try:
                    tags = json.loads(row["tags_json"])
                except (TypeError, json.JSONDecodeError):
                    tags = []
                if not isinstance(tags, list):
                    tags = []
                self._index_project_memory(connection, row["id"], row["title"], row["content"], tags)
            connection.execute(
                "INSERT INTO conversation_meta(name) VALUES('project_memory_search_index_v1')"
            )
        if "archived" not in {row[1] for row in connection.execute("PRAGMA table_info(conversation_threads)")}:
            connection.execute("ALTER TABLE conversation_threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        thread_columns = {row[1] for row in connection.execute("PRAGMA table_info(conversation_threads)")}
        if "model_provider" not in thread_columns:
            connection.execute("ALTER TABLE conversation_threads ADD COLUMN model_provider TEXT")
        if "model_id" not in thread_columns:
            connection.execute("ALTER TABLE conversation_threads ADD COLUMN model_id TEXT")
        connection.execute(
            "UPDATE conversation_threads SET "
            "model_provider=(SELECT provider FROM tasks WHERE tasks.thread_id=conversation_threads.id "
            "ORDER BY created_at DESC,id DESC LIMIT 1),"
            "model_id=(SELECT model_id FROM tasks WHERE tasks.thread_id=conversation_threads.id "
            "ORDER BY created_at DESC,id DESC LIMIT 1) "
            "WHERE model_id IS NULL AND EXISTS(SELECT 1 FROM tasks WHERE tasks.thread_id=conversation_threads.id)"
        )
        if not connection.execute("SELECT 1 FROM conversation_meta WHERE name='legacy_backfill'").fetchone():
            for task in connection.execute("SELECT * FROM tasks WHERE thread_id IS NULL ORDER BY created_at,id").fetchall():
                thread_id = self.create(connection, title_from_prompt(task["objective"]), task["created_at"])
                connection.execute("UPDATE tasks SET thread_id=? WHERE id=?", (thread_id, task["id"]))
                turns = [{"role": "user", "content": task["objective"]}]
                if task["result"]:
                    turns.append({"role": "assistant", "content": task["result"]})
                self.save(connection, thread_id, task["id"], turns, json.loads(task["logs_json"]), task["created_at"])
            connection.execute("INSERT INTO conversation_meta(name) VALUES('legacy_backfill')")
        connection.execute(
            "UPDATE conversation_threads SET "
            "model_provider=(SELECT provider FROM tasks WHERE tasks.thread_id=conversation_threads.id "
            "ORDER BY created_at DESC,id DESC LIMIT 1),"
            "model_id=(SELECT model_id FROM tasks WHERE tasks.thread_id=conversation_threads.id "
            "ORDER BY created_at DESC,id DESC LIMIT 1) "
            "WHERE model_id IS NULL AND EXISTS(SELECT 1 FROM tasks WHERE tasks.thread_id=conversation_threads.id)"
        )
        if not connection.execute("SELECT 1 FROM conversation_meta WHERE name='empty_final_response_cleanup'").fetchone():
            for row in connection.execute(
                "SELECT id,protocol_json FROM conversation_messages WHERE role='assistant'"
            ).fetchall():
                try:
                    turn = json.loads(row["protocol_json"])
                except (TypeError, json.JSONDecodeError):
                    turn = {"role": "assistant", "content": ""}
                if malformed_empty_assistant(turn):
                    connection.execute("DELETE FROM conversation_messages WHERE id=?", (row["id"],))
            for row in connection.execute("SELECT id,messages_json FROM tasks WHERE messages_json!='[]'").fetchall():
                try:
                    turns = json.loads(row["messages_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    continue
                cleaned = sanitize_turns(turns) if isinstance(turns, list) else []
                if cleaned != turns:
                    connection.execute(
                        "UPDATE tasks SET messages_json=? WHERE id=?",
                        (json.dumps(cleaned, ensure_ascii=False), row["id"]),
                    )
            connection.execute(
                "UPDATE tasks SET status='failed',result=NULL,error='No final response was generated by the provider.',"
                "current_step='Final response unavailable' WHERE result=?",
                (LEGACY_EMPTY_RESPONSE,),
            )
            connection.execute("INSERT INTO conversation_meta(name) VALUES('empty_final_response_cleanup')")

    def create(self, connection, title: str = "New Chat", timestamp: str | None = None) -> str:
        thread_id, timestamp = str(uuid.uuid4()), timestamp or now()
        connection.execute("INSERT INTO conversation_threads(id,title,pinned,created_at,updated_at) VALUES(?,?,0,?,?)",
                           (thread_id, title, timestamp, timestamp))
        return thread_id

    def require(self, connection, thread_id: str):
        row = connection.execute("SELECT * FROM conversation_threads WHERE id=?", (thread_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Chat not found.")
        return row

    def set_model(self, connection, thread_id: str, provider: str, model_id: str) -> None:
        self.require(connection, thread_id)
        connection.execute(
            "UPDATE conversation_threads SET model_provider=?,model_id=? WHERE id=?",
            (provider, model_id, thread_id),
        )

    def active(self, connection, thread_id: str):
        return connection.execute(
            "SELECT id FROM tasks WHERE thread_id=? AND status IN (?,?,?,?) ORDER BY created_at LIMIT 1",
            (thread_id, *BUSY),
        ).fetchone()

    def describe(self, connection, row) -> dict[str, Any]:
        active = self.active(connection, row["id"])
        count = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE thread_id=?", (row["id"],)).fetchone()[0]
        size = connection.execute(
            "SELECT COALESCE(SUM(length(CAST(protocol_json AS BLOB))+length(CAST(thought_steps AS BLOB))),0) "
            "FROM conversation_messages WHERE thread_id=?", (row["id"],)
        ).fetchone()[0]
        return {"id": row["id"], "title": row["title"], "pinned": bool(row["pinned"]),
                "provider": row["model_provider"], "modelId": row["model_id"],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"],
                "activeTaskId": active["id"] if active else None, "messageCount": count,
                "historyBytes": size, "archived": bool(row["archived"])}

    def append_user(self, connection, thread_id: str, task_id: str, objective: str, timestamp: str) -> None:
        row = self.require(connection, thread_id)
        if self.active(connection, thread_id):
            raise HTTPException(409, "This chat already has an active task. Stop or finish it before sending a follow-up.")
        count = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE thread_id=?", (thread_id,)).fetchone()[0]
        if count == 0 and row["title"] == "New Chat":
            connection.execute("UPDATE conversation_threads SET title=? WHERE id=?", (title_from_prompt(objective), thread_id))
        self.save(connection, thread_id, task_id, [{"role": "user", "content": objective}], [], timestamp)

    def save(self, connection, thread_id: str, task_id: str, turns: list[dict[str, Any]], steps: list, timestamp: str | None = None) -> None:
        timestamp = timestamp or now()
        for sequence, turn in enumerate(sanitize_turns(balanced_turns(turns))):
            if turn.get("role") not in {"user", "assistant", "tool"}:
                continue
            content = turn.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            # Keep attachment context internal; the visible user message is the original prompt.
            if turn["role"] == "user":
                existing = connection.execute("SELECT content FROM conversation_messages WHERE task_id=? AND sequence=?",
                                              (task_id, sequence)).fetchone()
                if existing:
                    content = existing["content"]
            connection.execute(
                "INSERT INTO conversation_messages(id,thread_id,task_id,sequence,role,content,protocol_json,thought_steps,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id,sequence) DO UPDATE SET "
                "role=excluded.role,content=excluded.content,protocol_json=excluded.protocol_json,thought_steps=excluded.thought_steps",
                (str(uuid.uuid4()), thread_id, task_id, sequence, turn["role"], content,
                 json.dumps(turn, ensure_ascii=False), json.dumps(steps if turn["role"] == "assistant" else []), timestamp),
            )
        connection.execute("UPDATE conversation_threads SET updated_at=? WHERE id=?", (timestamp, thread_id))

    def history(self, thread_id: str | None, task_id: str, provider: str | None = None) -> list[dict[str, Any]]:
        if not thread_id:
            return []
        with self.transaction() as connection:
            turns = []
            for row in connection.execute(
                "SELECT m.protocol_json,t.provider FROM conversation_messages m LEFT JOIN tasks t ON t.id=m.task_id "
                "WHERE m.thread_id=? AND (m.task_id IS NULL OR m.task_id!=?) ORDER BY m.ordering", (thread_id, task_id)):
                turn = json.loads(row["protocol_json"])
                if malformed_empty_assistant(turn):
                    continue
                if provider and row["provider"] != provider:
                    # Foreign provider metadata stays in SQLite, not an incompatible API request.
                    turn = {key: value for key, value in turn.items() if key in {
                        "role", "content", "name", "tool_calls", "tool_call_id", "function_call", "images"}}
                    if turn.get("tool_calls"):
                        turn["tool_calls"] = [{key: value for key, value in call.items()
                                              if key in {"id", "type", "function"}} for call in turn["tool_calls"]]
                turns.append(compact_history_turn(turn))
            return turns

    def remember_project_memory(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> dict[str, Any]:
        title = title.strip()
        content = content.strip()
        if not title or len(title) > 120:
            raise ValueError("A memory title must contain 1 to 120 characters.")
        if not content or len(content) > 2_000:
            raise ValueError("Memory content must contain 1 to 2,000 characters.")
        clean_tags = []
        for tag in tags or []:
            clean_tag = str(tag).strip()[:40]
            if clean_tag and clean_tag.casefold() not in {item.casefold() for item in clean_tags}:
                clean_tags.append(clean_tag)
            if len(clean_tags) >= 10:
                break
        title_key = " ".join(title.casefold().split())
        timestamp = now()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id,created_at FROM project_memories WHERE title_key=?", (title_key,)
            ).fetchone()
            memory_id = existing["id"] if existing else str(uuid.uuid4())
            created_at = existing["created_at"] if existing else timestamp
            connection.execute(
                "INSERT INTO project_memories(id,title,title_key,content,tags_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(title_key) DO UPDATE SET "
                "title=excluded.title,content=excluded.content,tags_json=excluded.tags_json,"
                "updated_at=excluded.updated_at",
                (
                    memory_id,
                    title,
                    title_key,
                    content,
                    json.dumps(clean_tags, ensure_ascii=False),
                    created_at,
                    timestamp,
                ),
            )
            self._index_project_memory(connection, memory_id, title, content, clean_tags)
            return {
                "id": memory_id,
                "title": title,
                "content": content,
                "tags": clean_tags,
                "createdAt": created_at,
                "updatedAt": timestamp,
            }

    @staticmethod
    def _memory_dict(row) -> dict[str, Any]:
        try:
            tags = json.loads(row["tags_json"])
        except (TypeError, json.JSONDecodeError):
            tags = []
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "tags": tags if isinstance(tags, list) else [],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _index_project_memory(connection, memory_id: str, title: str, content: str, tags: list[str]) -> None:
        searchable = " ".join([title, content, *(tag for tag in tags if isinstance(tag, str))])
        connection.execute("DELETE FROM project_memory_terms WHERE memory_id=?", (memory_id,))
        connection.executemany(
            "INSERT INTO project_memory_terms(memory_id,term) VALUES(?,?)",
            ((memory_id, term) for term in memory_terms(searchable)),
        )

    @staticmethod
    def _matching_project_memory_rows(connection, terms: set[str]):
        placeholders = ",".join("?" for _ in terms)
        return connection.execute(
            "SELECT memories.*, matches.match_count "
            "FROM project_memories AS memories "
            "JOIN (SELECT memory_id,COUNT(*) AS match_count FROM project_memory_terms "
            f"WHERE term IN ({placeholders}) GROUP BY memory_id) AS matches "
            "ON matches.memory_id=memories.id "
            "ORDER BY matches.match_count DESC,memories.updated_at DESC",
            tuple(sorted(terms)),
        )

    def recall_project_memories(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = memory_terms(query)
        if not terms:
            return []
        result_limit = max(1, min(int(limit), 10))
        with self.transaction() as connection:
            rows = self._matching_project_memory_rows(connection, terms).fetchmany(result_limit)
        return [self._memory_dict(row) for row in rows]

    def relevant_project_memories(
        self,
        objective: str,
        limit: int = MEMORY_CONTEXT_LIMIT,
        max_chars: int = MEMORY_CONTEXT_CHARS,
    ) -> list[dict[str, Any]]:
        terms = memory_terms(objective)
        if not terms:
            return []
        with self.transaction() as connection:
            selected: list[dict[str, Any]] = []
            used_chars = 0
            for row in self._matching_project_memory_rows(connection, terms):
                memory = self._memory_dict(row)
                clipped = {
                    **memory,
                    "content": memory["content"][:MEMORY_CONTEXT_NOTE_CHARS],
                }
                entry_chars = len(clipped["title"]) + len(clipped["content"])
                if len(selected) >= max(0, limit) or used_chars + entry_chars > max_chars:
                    continue
                selected.append(clipped)
                used_chars += entry_chars
            return selected

    def checkpoint(self, task_id: str, messages: list[dict[str, Any]], start: int) -> None:
        with self.transaction() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task and task["thread_id"]:
                safe_messages = sanitize_turns(messages)
                self.save(connection, task["thread_id"], task_id, safe_messages[start:], json.loads(task["logs_json"]))
                replay = json.dumps(safe_messages, ensure_ascii=False) if task["status"] in BUSY else "[]"
                connection.execute("UPDATE tasks SET messages_json=? WHERE id=?", (replay, task_id))

    def append_response(self, task_id: str, content: str) -> None:
        with self.transaction() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task and task["thread_id"]:
                turns = [json.loads(row["protocol_json"]) for row in connection.execute(
                    "SELECT protocol_json FROM conversation_messages WHERE task_id=? ORDER BY sequence", (task_id,))]
                turns.append({"role": "assistant", "content": content})
                self.save(connection, task["thread_id"], task_id, turns, json.loads(task["logs_json"]))

    def recover_interrupted(self) -> None:
        """Runs only on server startup; paused approval/model gates remain paused."""
        with self.transaction() as connection:
            for task in connection.execute("SELECT * FROM tasks WHERE status IN ('queued','running') AND thread_id IS NOT NULL").fetchall():
                saved = json.loads(task["messages_json"] or "[]")
                turns = saved[task["thread_context_start"]:] if saved else [
                    json.loads(row["protocol_json"]) for row in connection.execute(
                        "SELECT protocol_json FROM conversation_messages WHERE task_id=? ORDER BY sequence", (task["id"],))]
                notice = "The local server stopped before this task completed. Send a follow-up to continue."
                turns.append({"role": "assistant", "content": notice})
                timestamp = now()
                steps = json.loads(task["logs_json"])
                steps.append({"id": str(uuid.uuid4()), "kind": "warning", "message": notice, "createdAt": timestamp})
                self.save(connection, task["thread_id"], task["id"], turns, steps, timestamp)
                connection.execute(
                    "UPDATE tasks SET status='cancelled',result=NULL,error=NULL,current_step=?,logs_json=?,messages_json='[]',updated_at=? WHERE id=?",
                    (notice, json.dumps(steps), timestamp, task["id"]))


class ThreadInput(BaseModel):
    title: str = Field(default="New Chat", min_length=1, max_length=100)


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    pinned: bool | None = None
    archived: bool | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=32)
    modelId: str | None = Field(default=None, min_length=1, max_length=120)


def thread_routers(store: ThreadStore, serialize_task, redact=lambda value: value) -> tuple[APIRouter, APIRouter]:
    router = APIRouter(prefix="/api/assistant/threads")
    sessions = APIRouter(prefix="/api/threads")

    def read_messages(connection, thread_id: str, limit: int = 25, before: int | None = None) -> list[dict[str, Any]]:
        messages = []
        rows = connection.execute(
            "SELECT id,thread_id,task_id,role,created_at,ordering,"
            "COALESCE(json_array_length(protocol_json,'$.tool_calls'),0)>0 AS is_tool_call,"
            "CASE WHEN role='tool' OR COALESCE(json_array_length(protocol_json,'$.tool_calls'),0)>0 "
            "THEN substr(content,1,10240) ELSE substr(content,1,65536) END AS content,"
            "length(CAST(content AS BLOB)) AS content_bytes "
            ",substr(json_extract(thought_steps,'$[0].message'),1,2000) AS thought_summary "
            "FROM conversation_messages WHERE thread_id=? AND (? IS NULL OR ordering<?) "
            "ORDER BY ordering DESC LIMIT ?", (thread_id, before, before, limit)
        ).fetchall()
        for row in reversed(rows):
            content = row["content"]
            if row["content_bytes"] > 10240 and (row["role"] == "tool" or row["is_tool_call"]):
                content = f"[Tool/file payload: {row['content_bytes'] / 1024:.1f} KB — retained locally; inspect Workspace for saved files]"
            elif row["content_bytes"] > 65536 and len(content) == 65536:
                content += "\n[Display shortened; full message retained locally]"
            messages.append(
                {"id": row["id"], "threadId": row["thread_id"], "taskId": row["task_id"], "role": row["role"],
                 "content": redact(content), "thoughtSteps": [
                     {"id": row["id"] + "-summary", "kind": "info", "message": redact(row["thought_summary"]),
                      "createdAt": row["created_at"]}
                 ] if row["thought_summary"] else [],
                 "isToolCall": bool(row["is_tool_call"]), "createdAt": row["created_at"],
                 "ordering": row["ordering"]}
            )
        return messages

    @router.get("")
    async def list_threads(includeArchived: bool = False):
        with store.transaction() as connection:
            return [store.describe(connection, row) for row in connection.execute(
                "SELECT * FROM conversation_threads WHERE archived=0 OR ? ORDER BY updated_at DESC,created_at DESC,id DESC",
                (includeArchived,))]

    @router.post("", status_code=201)
    async def create_thread(body: ThreadInput):
        if not body.title.strip():
            raise HTTPException(422, "Enter a chat title.")
        with store.transaction() as connection:
            thread_id = store.create(connection, body.title.strip())
            return store.describe(connection, store.require(connection, thread_id))

    @router.get("/{thread_id}")
    async def get_thread(thread_id: str, limit: int = Query(25, ge=1, le=25), before: int | None = Query(None, ge=1)):
        with store.transaction() as connection:
            result = store.describe(connection, store.require(connection, thread_id))
            result["messages"] = read_messages(connection, thread_id, limit, before)
            oldest = result["messages"][0]["ordering"] if result["messages"] else before
            result["nextBefore"] = oldest if oldest and connection.execute(
                "SELECT 1 FROM conversation_messages WHERE thread_id=? AND ordering<? LIMIT 1",
                (thread_id, oldest)).fetchone() else None
            task_ids = list(dict.fromkeys(message["taskId"] for message in result["messages"]))
            active = result["activeTaskId"]
            if active and before is None and active not in task_ids:
                task_ids.append(active)
            result["tasks"] = [display_task(row, serialize_task, log_limit=10) for row in connection.execute(
                f"SELECT * FROM tasks WHERE thread_id=? AND id IN ({','.join('?' for _ in task_ids)}) ORDER BY created_at,id",
                (thread_id, *task_ids))] if task_ids else []
            return result

    @sessions.get("")
    async def list_sessions():
        with store.transaction() as connection:
            return [store.describe(connection, row) for row in connection.execute(
                "SELECT * FROM conversation_threads WHERE archived=0 ORDER BY updated_at DESC,created_at DESC,id DESC")]

    @sessions.post("", status_code=201)
    async def create_session(body: ThreadInput | None = None):
        return await create_thread(body or ThreadInput())

    @sessions.get("/{thread_id}/messages")
    async def get_session_messages(thread_id: str, limit: int = Query(25, ge=1, le=25), before: int | None = Query(None, ge=1)):
        with store.transaction() as connection:
            store.require(connection, thread_id)
            return read_messages(connection, thread_id, limit, before)

    @router.patch("/{thread_id}")
    async def update_thread(thread_id: str, body: ThreadUpdate):
        with store.transaction() as connection:
            store.require(connection, thread_id)
            if (body.provider is None) != (body.modelId is None):
                raise HTTPException(422, "Choose both a provider and model.")
            if body.provider is not None:
                if body.provider not in {"openai", "deepseek", "gemini", "anthropic", "openrouter", "ollama"}:
                    raise HTTPException(422, "Unsupported AI provider.")
                store.set_model(connection, thread_id, body.provider, body.modelId)
            if body.archived is not None:
                if body.archived and store.active(connection, thread_id):
                    raise HTTPException(409, "Stop or finish this chat before archiving it.")
                connection.execute("UPDATE conversation_threads SET archived=? WHERE id=?", (int(body.archived), thread_id))
            if body.title is not None:
                if not body.title.strip():
                    raise HTTPException(422, "Enter a chat title.")
                connection.execute("UPDATE conversation_threads SET title=? WHERE id=?", (body.title.strip(), thread_id))
            if body.pinned is not None:
                connection.execute("UPDATE conversation_threads SET pinned=? WHERE id=?", (int(body.pinned), thread_id))
            connection.execute("UPDATE conversation_threads SET updated_at=? WHERE id=?", (now(), thread_id))
            return store.describe(connection, store.require(connection, thread_id))

    @router.delete("/{thread_id}", status_code=204)
    async def delete_thread(thread_id: str):
        from fastapi import Response
        with store.transaction() as connection:
            store.require(connection, thread_id)
            if store.active(connection, thread_id):
                raise HTTPException(409, "Stop or finish this chat's active task before deleting it.")
            connection.execute("DELETE FROM conversation_messages WHERE thread_id=?", (thread_id,))
            connection.execute("UPDATE tasks SET thread_id=NULL,messages_json='[]' WHERE thread_id=?", (thread_id,))
            connection.execute("DELETE FROM conversation_threads WHERE id=?", (thread_id,))
        return Response(status_code=204)

    @sessions.delete("/{thread_id}", status_code=204)
    async def delete_session(thread_id: str):
        return await delete_thread(thread_id)

    return router, sessions
