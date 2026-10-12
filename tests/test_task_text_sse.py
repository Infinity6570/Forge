from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import httpx

import main
from task_text_stream import TaskTextStreamHub


class _RunningTask:
    def done(self) -> bool:
        return False


class TaskTextSSETests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_sends_unbuffered_headers_and_ordered_text_events(self) -> None:
        task_id = "sse-test-task"
        hub = TaskTextStreamHub()
        hub.begin(task_id)

        async def publish_response() -> None:
            await asyncio.sleep(0)
            hub.publish(task_id, None)
            await asyncio.sleep(0)
            hub.publish(task_id, "Fast")
            await asyncio.sleep(0)
            hub.publish(task_id, "Fast answer")
            await asyncio.sleep(0)
            hub.finish(task_id, "completed", "Fast answer")

        publisher: asyncio.Task[None] | None = None
        with (
            patch.object(
                main,
                "db_one",
                return_value={"status": "running", "result": None},
            ),
            patch.object(main, "ACTIVE_TASKS", {task_id: _RunningTask()}),
            patch.object(main, "TASK_TEXT_STREAMS", hub),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app),
                base_url="http://127.0.0.1",
            ) as client:
                publisher = asyncio.create_task(publish_response())
                response = await client.get(f"/api/assistant/tasks/{task_id}/stream")
                await publisher

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        body = response.text
        self.assertIn('"type":"reset"', body)
        self.assertIn('"type":"delta","text":"Fast"', body)
        self.assertIn('"type":"delta","text":" answer"', body)
        self.assertIn('"type":"end","status":"completed","text":"Fast answer"', body)
        self.assertLess(body.index('"type":"reset"'), body.index('"type":"delta"'))
        self.assertLess(body.index('"type":"delta"'), body.index('"type":"end"'))


if __name__ == "__main__":
    unittest.main()
