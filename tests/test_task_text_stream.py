from __future__ import annotations

import unittest

from task_text_stream import TaskTextStreamHub


class TaskTextStreamHubTests(unittest.TestCase):
    def test_publishes_each_delta_and_reconnects_from_latest_snapshot(self):
        hub = TaskTextStreamHub()
        hub.begin("task-1")
        queue, snapshot, terminal = hub.subscribe("task-1")

        self.assertEqual(snapshot, {"type": "snapshot", "text": ""})
        self.assertIsNone(terminal)
        hub.publish("task-1", None)
        self.assertEqual(queue.get_nowait(), {"type": "reset"})
        hub.publish("task-1", "Hello")
        hub.publish("task-1", "Hello world")
        self.assertEqual(queue.get_nowait(), {"type": "delta", "text": "Hello"})
        self.assertEqual(queue.get_nowait(), {"type": "delta", "text": " world"})

        reconnect, snapshot, terminal = hub.subscribe("task-1")
        self.assertEqual(snapshot, {"type": "snapshot", "text": "Hello world"})
        self.assertIsNone(terminal)
        hub.unsubscribe("task-1", queue)
        hub.finish("task-1", "completed", "Hello world")
        self.assertEqual(
            reconnect.get_nowait(),
            {"type": "end", "status": "completed", "text": "Hello world"},
        )

    def test_backpressure_replaces_old_deltas_with_a_current_snapshot(self):
        hub = TaskTextStreamHub(queue_size=2)
        hub.begin("task-2")
        queue, _, _ = hub.subscribe("task-2")

        hub.publish("task-2", "a")
        hub.publish("task-2", "ab")
        hub.publish("task-2", "abc")

        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get_nowait(), {"type": "snapshot", "text": "abc"})

    def test_rewrite_and_terminal_status_are_explicit(self):
        hub = TaskTextStreamHub()
        hub.begin("task-3")
        queue, _, _ = hub.subscribe("task-3")
        hub.publish("task-3", "partial answer")
        queue.get_nowait()
        hub.publish("task-3", "replacement answer")
        self.assertEqual(
            queue.get_nowait(),
            {"type": "snapshot", "text": "replacement answer"},
        )
        hub.finish("task-3", "cancelled", "")
        self.assertEqual(
            queue.get_nowait(),
            {"type": "end", "status": "cancelled", "text": ""},
        )


if __name__ == "__main__":
    unittest.main()
