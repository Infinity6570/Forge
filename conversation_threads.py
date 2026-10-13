"""Local SQLite conversations and public thread APIs, independent of any host."""
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm_protocol import to_wire

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


def sanitize_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        turn for turn in (to_wire(item) for item in turns)
        if isinstance(turn, dict) and not malformed_empty_assistant(turn)
    ]


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
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
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
        """)
        if not connection.execute("SELECT 1 FROM conversation_meta WHERE name='legacy_backfill'").fetchone():
            for task in connection.execute("SELECT * FROM tasks WHERE thread_id IS NULL ORDER BY created_at,id").fetchall():
                thread_id = self.create(connection, title_from_prompt(task["objective"]), task["created_at"])
                connection.execute("UPDATE tasks SET thread_id=? WHERE id=?", (thread_id, task["id"]))
                turns = [{"role": "user", "content": task["objective"]}]
                if task["result"]:
                    turns.append({"role": "assistant", "content": task["result"]})
                self.save(connection, thread_id, task["id"], turns, json.loads(task["logs_json"]), task["created_at"])
            connection.execute("INSERT INTO conversation_meta(name) VALUES('legacy_backfill')")
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
        connection.execute("INSERT INTO conversation_threads VALUES(?,?,0,?,?)",
                           (thread_id, title, timestamp, timestamp))
        return thread_id

    def require(self, connection, thread_id: str):
        row = connection.execute("SELECT * FROM conversation_threads WHERE id=?", (thread_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Chat not found.")
        return row

    def active(self, connection, thread_id: str):
        return connection.execute(
            "SELECT id FROM tasks WHERE thread_id=? AND status IN (?,?,?,?) ORDER BY created_at LIMIT 1",
            (thread_id, *BUSY),
        ).fetchone()

    def describe(self, connection, row) -> dict[str, Any]:
        active = self.active(connection, row["id"])
        count = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE thread_id=?", (row["id"],)).fetchone()[0]
        return {"id": row["id"], "title": row["title"], "pinned": bool(row["pinned"]),
                "createdAt": row["created_at"], "updatedAt": row["updated_at"],
                "activeTaskId": active["id"] if active else None, "messageCount": count}

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
                        "role", "content", "name", "tool_calls", "tool_call_id", "function_call"}}
                    if turn.get("tool_calls"):
                        turn["tool_calls"] = [{key: value for key, value in call.items()
                                              if key in {"id", "type", "function"}} for call in turn["tool_calls"]]
                turns.append(turn)
            return turns

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


def thread_routers(store: ThreadStore, serialize_task, redact=lambda value: value) -> tuple[APIRouter, APIRouter]:
    router = APIRouter(prefix="/api/assistant/threads")
    sessions = APIRouter(prefix="/api/threads")

    def read_messages(connection, thread_id: str) -> list[dict[str, Any]]:
        messages = []
        for row in connection.execute(
            "SELECT * FROM conversation_messages WHERE thread_id=? ORDER BY ordering", (thread_id,)
        ):
            protocol = json.loads(row["protocol_json"])
            if malformed_empty_assistant(protocol):
                continue
            messages.append(
                {"id": row["id"], "threadId": row["thread_id"], "taskId": row["task_id"], "role": row["role"],
                 "content": redact(row["content"]), "thoughtSteps": json.loads(row["thought_steps"]),
                 "isToolCall": bool(protocol.get("tool_calls")), "createdAt": row["created_at"]}
            )
        return messages

    @router.get("")
    async def list_threads():
        with store.transaction() as connection:
            return [store.describe(connection, row) for row in connection.execute(
                "SELECT * FROM conversation_threads ORDER BY pinned DESC,updated_at DESC")]

    @router.post("", status_code=201)
    async def create_thread(body: ThreadInput):
        if not body.title.strip():
            raise HTTPException(422, "Enter a chat title.")
        with store.transaction() as connection:
            thread_id = store.create(connection, body.title.strip())
            return store.describe(connection, store.require(connection, thread_id))

    @router.get("/{thread_id}")
    async def get_thread(thread_id: str):
        with store.transaction() as connection:
            result = store.describe(connection, store.require(connection, thread_id))
            result["messages"] = read_messages(connection, thread_id)
            result["tasks"] = [serialize_task(row) for row in connection.execute(
                "SELECT * FROM tasks WHERE thread_id=? ORDER BY created_at,id", (thread_id,))]
            return result

    @sessions.get("")
    async def list_sessions():
        with store.transaction() as connection:
            return [store.describe(connection, row) for row in connection.execute(
                "SELECT * FROM conversation_threads ORDER BY updated_at DESC,id")]

    @sessions.post("", status_code=201)
    async def create_session(body: ThreadInput | None = None):
        return await create_thread(body or ThreadInput())

    @sessions.get("/{thread_id}/messages")
    async def get_session_messages(thread_id: str):
        with store.transaction() as connection:
            store.require(connection, thread_id)
            return read_messages(connection, thread_id)

    @router.patch("/{thread_id}")
    async def update_thread(thread_id: str, body: ThreadUpdate):
        with store.transaction() as connection:
            store.require(connection, thread_id)
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
