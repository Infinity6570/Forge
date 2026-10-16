import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import main
from conversation_threads import balanced_turns, title_from_prompt
from llm_protocol import prepare_history


def completion(text, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        role="assistant", content=text, tool_calls=calls))])


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        workspace = root / "workspace"
        self.paths = patch.multiple(main, ROOT=root, PROJECT_DIR=root.resolve(), BASE_DIR=workspace.resolve(), WORKSPACE=workspace,
                                    DATABASE=workspace / "assistant.db", UPLOADS=workspace / "uploads",
                                    NOTES=workspace / "notes", ENV_FILE=root / ".env")
        self.paths.start()
        self.environment = patch.dict(os.environ, {"GEMINI_API_KEY": "test-personal-key",
            "OPENAI_API_KEY": "test-openai-key", "AGENT_PROVIDER": "gemini",
            "AGENT_MODEL": "gemini-3.5-flash-lite"}, clear=True)
        self.environment.start()
        main.init_db()

    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost")

    async def asyncTearDown(self):
        await self.client.aclose()
        for task in list(main.ACTIVE_TASKS.values()):
            if not task.done():
                task.cancel()
        self.environment.stop()
        self.paths.stop()
        self.directory.cleanup()

    async def send(self, objective, thread=None, files=None):
        body = {"objective": objective}
        if thread:
            body["threadId"] = thread
        if files:
            body["fileIds"] = files
        response = await self.client.post("/api/assistant/tasks", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        task = response.json()
        for _ in range(100):
            await asyncio.sleep(.01)
            row = main.db_one("SELECT * FROM tasks WHERE id=?", (task["id"],))
            if row["status"] not in {"running", "queued"}:
                self.assertEqual(row["status"], "completed", row["error"])
                return task
        self.fail("Task did not settle")

    async def test_followup_replays_signed_tool_history_in_order_without_duplicate_messages(self):
        call = SimpleNamespace(id="signed-call", type="function",
            function=SimpleNamespace(name="web_search", arguments='{"query":"weather"}'),
            extra_content={"google": {"thought_signature": "opaque-signature", "unknown": {"keep": True}}})
        create = AsyncMock(side_effect=[completion(None, [call]), completion("A cloudy forecast."),
                                       completion("The prior forecast was cloudy.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client), patch.object(
                main, "execute_tool", new=AsyncMock(return_value='{"forecast":"cloudy"}')):
            first = await self.send("Search for a forecast")
            second = await self.send("What was the forecast?", first["threadId"])
        sent = create.call_args.kwargs["messages"]
        self.assertEqual([turn["role"] for turn in sent], ["system", "user", "assistant", "tool", "assistant", "user"])
        self.assertEqual(sent[2]["tool_calls"][0]["extra_content"], call.extra_content)
        self.assertEqual(sent[3]["tool_call_id"], "signed-call")
        self.assertIn("cloudy", sent[3]["content"])
        detail = (await self.client.get("/api/assistant/threads/" + first["threadId"])).json()
        self.assertEqual([message["role"] for message in detail["messages"]],
                         ["user", "assistant", "tool", "assistant", "user", "assistant"])
        self.assertEqual(len(detail["tasks"]), 2)
        self.assertEqual(detail["tasks"][1]["id"], second["id"])
        self.assertNotIn("opaque-signature", json.dumps(detail))
        self.assertTrue(any(message["thoughtSteps"] for message in detail["messages"] if message["role"] == "assistant"))
        foreign = main.THREADS.history(first["threadId"], "next", "openai")
        self.assertNotIn("extra_content", foreign[1]["tool_calls"][0])
        self.assertEqual(main.THREADS.history(first["threadId"], "next")[1]["tool_calls"][0]["extra_content"], call.extra_content)
        before = [message["id"] for message in detail["messages"]]
        main.init_db()
        after = (await self.client.get("/api/assistant/threads/" + first["threadId"])).json()
        self.assertEqual(before, [message["id"] for message in after["messages"]])

    async def test_attachment_context_survives_followup_but_never_enters_new_chat(self):
        main.db_run("INSERT INTO files VALUES(?,?,?,?,?,?,?)",
                    ("doc", "notes.txt", "text/plain", 22, "attachment-only-blue", "/unused", main.utc_now()))
        create = AsyncMock(side_effect=[completion("Noted blue."), completion("Blue."), completion("Clean chat.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            first = await self.send("Remember my attached note", files=["doc"])
            await self.send("What was in my note?", first["threadId"])
            previous = create.call_args.kwargs["messages"]
            self.assertIn("attachment-only-blue", previous[1]["content"])
            self.assertNotIn("attachment-only-blue", previous[-1]["content"])
            fresh = await self.send("Start fresh")
            clean = create.call_args.kwargs["messages"]
        self.assertNotEqual(first["threadId"], fresh["threadId"])
        self.assertNotIn("attachment-only-blue", json.dumps(clean))
        detail = (await self.client.get("/api/assistant/threads/" + first["threadId"])).json()
        self.assertEqual(detail["messages"][0]["content"], "Remember my attached note")

    async def test_pin_rename_delete_and_busy_guards_preserve_task_activity(self):
        thread = (await self.client.post("/api/assistant/threads", json={})).json()
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=completion("Saved.")))))
        with patch.object(main, "create_llm_client", return_value=client):
            task = await self.send("Create a budget forecast", thread["id"])
        renamed = await self.client.patch("/api/assistant/threads/" + thread["id"], json={"title": "Budget Forecast Chat", "pinned": True})
        self.assertEqual(renamed.json()["title"], "Budget Forecast Chat")
        self.assertTrue(renamed.json()["pinned"])
        main.db_run("UPDATE tasks SET status='running' WHERE id=?", (task["id"],))
        blocked = await self.client.post("/api/assistant/tasks", json={"objective": "Follow up", "threadId": thread["id"]})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual((await self.client.delete("/api/assistant/threads/" + thread["id"])).status_code, 409)
        self.assertEqual(len((await self.client.get("/api/assistant/threads/" + thread["id"])).json()["messages"]), 2)
        main.db_run("UPDATE tasks SET status='completed' WHERE id=?", (task["id"],))
        self.assertEqual((await self.client.delete("/api/assistant/threads/" + thread["id"])).status_code, 204)
        self.assertEqual((await self.client.get("/api/assistant/tasks/" + task["id"])).status_code, 200)
        self.assertIsNone(main.db_one("SELECT thread_id FROM tasks WHERE id=?", (task["id"],))["thread_id"])
        main.init_db()
        self.assertEqual((await self.client.get("/api/assistant/threads")).json(), [])
        self.assertEqual((await self.client.get("/api/assistant/threads/" + thread["id"])).status_code, 404)

    async def test_short_session_routes_preserve_history_and_delete_only_selected_chat(self):
        created = await self.client.post("/api/threads")
        self.assertEqual(created.status_code, 201, created.text)
        first_id = created.json()["id"]
        timestamp = "2020-01-01T00:00:00Z"
        with main.THREADS.transaction() as connection:
            main.THREADS.append_user(connection, first_id, "saved-session-task", "Remember this chat", timestamp)
            main.THREADS.save(connection, first_id, "saved-session-task", [
                {"role": "user", "content": "Remember this chat"},
                {"role": "assistant", "content": "This chat remains saved."},
            ], [], timestamp)

        other = await self.client.post("/api/assistant/threads", json={"title": "Other session"})
        self.assertEqual(other.status_code, 201)
        sessions = await self.client.get("/api/threads")
        self.assertEqual(sessions.status_code, 200)
        self.assertEqual({item["id"] for item in sessions.json()}, {first_id, other.json()["id"]})
        self.assertEqual([item["id"] for item in sessions.json()], [other.json()["id"], first_id])

        history = await self.client.get(f"/api/threads/{first_id}/messages")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([message["content"] for message in history.json()],
                         ["Remember this chat", "This chat remains saved."])

        removed = await self.client.delete(f"/api/threads/{other.json()['id']}")
        self.assertEqual(removed.status_code, 204)
        remaining = await self.client.get("/api/threads")
        self.assertEqual([item["id"] for item in remaining.json()], [first_id])
        retained = await self.client.get(f"/api/threads/{first_id}/messages")
        self.assertEqual([message["content"] for message in retained.json()],
                         ["Remember this chat", "This chat remains saved."])

    async def test_missing_thread_and_invalid_provider_do_not_create_orphan_messages(self):
        missing = await self.client.post("/api/assistant/tasks", json={"objective": "Hello", "threadId": "missing"})
        self.assertEqual(missing.status_code, 404)
        invalid = await self.client.post("/api/assistant/tasks", json={"objective": "Hello", "provider": "bad"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(main.db_all("SELECT * FROM conversation_threads"), [])
        self.assertEqual(main.db_all("SELECT * FROM conversation_messages"), [])

    async def test_legacy_completed_task_migrates_once_with_saved_answer(self):
        main.db_run("INSERT INTO tasks(id,objective,status,result,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("legacy", "Plan a mountain holiday", "completed", "A saved itinerary.", main.utc_now(), main.utc_now()))
        main.db_run("DELETE FROM conversation_meta WHERE name='legacy_backfill'")
        main.init_db()
        thread = (await self.client.get("/api/assistant/threads")).json()[0]
        self.assertTrue(3 <= len(thread["title"].split()) <= 5)
        messages = (await self.client.get("/api/assistant/threads/" + thread["id"])).json()["messages"]
        self.assertEqual([message["content"] for message in messages], ["Plan a mountain holiday", "A saved itinerary."])
        main.init_db()
        self.assertEqual(len((await self.client.get("/api/assistant/threads")).json()), 1)

    async def test_legacy_empty_final_error_is_removed_and_task_is_not_left_completed(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=completion("A real answer."))
        )))
        with patch.object(main, "create_llm_client", return_value=client):
            task = await self.send("Create a normal answer")

        bad_text = "The model returned no final text."
        timestamp = main.utc_now()
        main.db_run(
            "INSERT INTO conversation_messages(id,thread_id,task_id,sequence,role,content,protocol_json,thought_steps,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("legacy-empty-final", task["threadId"], task["id"], 99, "assistant", bad_text,
             json.dumps({"role": "assistant", "content": bad_text}), "[]", timestamp),
        )
        main.db_run(
            "UPDATE tasks SET status='completed',result=? WHERE id=?",
            (bad_text, task["id"]),
        )
        main.db_run("DELETE FROM conversation_meta WHERE name='empty_final_response_cleanup'")
        main.init_db()

        stored_task = main.db_one("SELECT status,result,error FROM tasks WHERE id=?", (task["id"],))
        self.assertEqual(stored_task["status"], "failed")
        self.assertIsNone(stored_task["result"])
        self.assertIn("No final response", stored_task["error"])
        visible = (await self.client.get(f"/api/assistant/threads/{task['threadId']}")).json()["messages"]
        self.assertNotIn(bad_text, [message["content"] for message in visible])
        history = main.THREADS.history(task["threadId"], "future-task", "gemini")
        self.assertNotIn(bad_text, [turn.get("content") for turn in history])

    async def test_restart_recovers_interrupted_runs_but_keeps_approval_gates(self):
        threads = {}
        with main.THREADS.transaction() as connection:
            for task_id, status in (("interrupted", "running"), ("paused", "awaiting_approval")):
                thread = main.THREADS.create(connection)
                threads[task_id] = thread
                connection.execute(
                    "INSERT INTO tasks(id,objective,status,thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (task_id, "Search", status, thread, main.utc_now(), main.utc_now()))
                main.THREADS.save(connection, thread, task_id, [{"role": "user", "content": "Search"}], [])
        main.THREADS.recover_interrupted()
        self.assertEqual(main.db_one("SELECT status FROM tasks WHERE id='interrupted'")["status"], "cancelled")
        self.assertEqual(main.db_one("SELECT status FROM tasks WHERE id='paused'")["status"], "awaiting_approval")
        history = main.THREADS.history(threads["interrupted"], "next")
        self.assertTrue(any("local server stopped" in turn.get("content", "") for turn in history))

    async def test_abort_waits_for_agent_cleanup_and_returns_cancelled_task(self):
        started = asyncio.Event()

        async def waiting_runner(task_id, _file_ids, resume_messages=None):
            main.db_run(
                "UPDATE tasks SET status='running',current_step='Searching' WHERE id=?",
                (task_id,),
            )
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                main.db_run(
                    "UPDATE tasks SET status='cancelled',result=NULL,current_step='Stopped by user',updated_at=? WHERE id=?",
                    (main.utc_now(), task_id),
                )
                main.log_task(task_id, "TASK ABORTED BY USER", "warning")
                raise

        with patch.object(main, "run_agent_task", new=waiting_runner):
            created = await self.client.post("/api/assistant/tasks", json={"objective": "Stop this search"})
            self.assertEqual(created.status_code, 201, created.text)
            task_id = created.json()["id"]
            await asyncio.wait_for(started.wait(), timeout=1)
            running_task = main.ACTIVE_TASKS[task_id]

            stopped = await self.client.post(f"/api/assistant/tasks/{task_id}/abort")

        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertEqual(stopped.json()["status"], "cancelled")
        self.assertTrue(running_task.done())
        self.assertTrue(any(log["message"] == "TASK ABORTED BY USER" for log in stopped.json()["logs"]))

    async def test_workspace_overwrite_completes_without_approval_and_keeps_tool_pair(self):
        (main.WORKSPACE / "index.html").write_text("original", encoding="utf8")
        call = SimpleNamespace(id="approval-call", type="function",
            function=SimpleNamespace(name="write_workspace_preview_file", arguments='{"path":"index.html","content":"replacement"}'),
            extra_content={"google": {"thought_signature": "approval-signature"}})
        create = AsyncMock(side_effect=[completion(None, [call]), completion("Homepage updated.")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(main, "create_llm_client", return_value=client):
            task = await self.send("Update the current homepage")
        sent = create.call_args.kwargs["messages"]
        self.assertEqual(sent[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "approval-signature")
        self.assertEqual(sent[3]["tool_call_id"], "approval-call")
        self.assertIn("saved", sent[3]["content"].lower())
        self.assertEqual(main.db_one("SELECT result FROM tasks WHERE id=?", (task["id"],))["result"], "Homepage updated.")
        self.assertEqual((main.WORKSPACE / "index.html").read_text(encoding="utf8"), "replacement")
        detail = (await self.client.get("/api/assistant/threads/" + task["threadId"])).json()
        self.assertEqual([message["role"] for message in detail["messages"]],
                         ["user", "assistant", "tool", "assistant"])


    async def test_display_history_is_paged_without_changing_model_context(self):
        timestamp = main.utc_now()
        with main.THREADS.transaction() as db:
            thread_id = main.THREADS.create(db)
            db.execute("INSERT INTO tasks(id,thread_id,objective,status,created_at,updated_at) VALUES(?,?,?,'completed',?,?)",
                       ("paged-task", thread_id, "History", timestamp, timestamp))
            main.THREADS.save(db, thread_id, "paged-task",
                             [{"role": "user" if n % 2 == 0 else "assistant", "content": str(n)} for n in range(60)], [])
        url = "/api/assistant/threads/" + thread_id
        latest = (await self.client.get(url)).json()
        self.assertEqual([m["content"] for m in latest["messages"]], [str(n) for n in range(35, 60)])
        earlier = (await self.client.get(url, params={"before": latest["nextBefore"]})).json()
        oldest = (await self.client.get(url, params={"before": earlier["nextBefore"]})).json()
        self.assertEqual([m["content"] for m in oldest["messages"] + earlier["messages"] + latest["messages"]],
                         [str(n) for n in range(60)])
        self.assertIsNone(oldest["nextBefore"])
        self.assertEqual(len(main.THREADS.history(thread_id, "next")), 60)
        self.assertEqual((await self.client.get(url, params={"limit": 1000})).status_code, 422)

    async def test_large_tool_payload_is_display_only_and_startup_is_metadata(self):
        timestamp = main.utc_now()
        calls = [{"id": "big-call", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "large.html", "content": "Z" * 1_000_000})},
            "extra_content": {"google": {"thought_signature": "preserve-exactly"}}}]
        turns = [{"role": "user", "content": "Build a page"},
                 {"role": "assistant", "content": "", "tool_calls": calls},
                 {"role": "tool", "tool_call_id": "big-call", "content": "R" * 1_000_000},
                 {"role": "assistant", "content": "Page saved."}]
        logs = [{"id": "big-log", "kind": "tool", "message": json.dumps({"path": "large.html", "content": "Z" * 1_000_000}), "createdAt": timestamp}]
        with main.THREADS.transaction() as db:
            thread_id = main.THREADS.create(db)
            db.execute("INSERT INTO tasks(id,thread_id,objective,status,result,logs_json,created_at,updated_at) VALUES(?,?,?,'completed',?,?,?,?)",
                       ("big-task", thread_id, "Build page", "Page saved.", json.dumps(logs), timestamp, timestamp))
            main.THREADS.save(db, thread_id, "big-task", turns, logs)
        listing = (await self.client.get("/api/assistant/threads")).json()
        self.assertGreater(listing[0]["historyBytes"], 500 * 1024)
        self.assertNotIn("messages", listing[0])
        response = await self.client.get("/api/assistant/threads/" + thread_id)
        self.assertLess(len(response.content), 25_000)
        self.assertIn("payload", response.text)
        self.assertNotIn("Z" * 10_000, response.text)
        self.assertNotIn("preserve-exactly", response.text)
        self.assertEqual(main.THREADS.history(thread_id, "next"), turns)
        for endpoint in ["/api/assistant/dashboard", "/api/assistant/tasks"]:
            self.assertLess(len((await self.client.get(endpoint)).content), 25_000)

    async def test_archive_preserves_context_and_tasks_and_can_restore(self):
        thread = (await self.client.post("/api/assistant/threads", json={})).json()
        url = "/api/assistant/threads/" + thread["id"]
        self.assertEqual((await self.client.patch(url, json={"archived": True})).status_code, 200)
        self.assertEqual((await self.client.get("/api/assistant/threads")).json(), [])
        archived = (await self.client.get("/api/assistant/threads?includeArchived=true")).json()
        self.assertTrue(archived[0]["archived"])
        self.assertEqual((await self.client.get(url)).status_code, 200)
        await self.client.patch(url, json={"archived": False})
        self.assertEqual(len((await self.client.get("/api/assistant/threads")).json()), 1)
        timestamp = main.utc_now()
        with main.THREADS.transaction() as db:
            db.execute("INSERT INTO tasks(id,thread_id,objective,status,created_at,updated_at) VALUES(?,?,?,'awaiting_approval',?,?)",
                       ("active-archive", thread["id"], "Pending approval", timestamp, timestamp))
        self.assertEqual((await self.client.patch(url, json={"archived": True})).status_code, 409)


class ProtocolBoundaryTests(unittest.TestCase):
    def test_interrupted_parallel_calls_are_closed_before_followup(self):
        calls = [{"id": "one", "type": "function", "function": {"name": "search", "arguments": "{}"}},
                 {"id": "two", "type": "function", "function": {"name": "search", "arguments": "{}"}}]
        result = balanced_turns([{"role": "assistant", "tool_calls": calls},
            {"role": "tool", "tool_call_id": "one", "content": "real"},
            {"role": "assistant", "content": "Stopped."}])
        self.assertEqual([turn["role"] for turn in result], ["assistant", "tool", "tool", "assistant"])
        self.assertEqual(result[2]["tool_call_id"], "two")
        self.assertIn("stopped", result[2]["content"])

    def test_switching_provider_normalizes_wire_copy_not_stored_metadata(self):
        history = [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "one", "type": "function", "function": {"name": "search", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "preserve"}}}]}]
        openai = prepare_history(history, "openai")
        self.assertNotIn("extra_content", openai[0]["tool_calls"][0])
        self.assertEqual(history[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "preserve")
        gemini = prepare_history(history, "gemini")
        self.assertEqual(gemini[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "preserve")

    def test_titles_are_local_concise_and_deterministic(self):
        self.assertEqual(title_from_prompt("Please create a budget forecast for Q4"), "Budget Forecast Q4")
        self.assertEqual(title_from_prompt("Hello"), "Hello Chat Session")
