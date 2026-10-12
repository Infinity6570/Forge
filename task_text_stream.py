"""In-memory fan-out for live, user-visible assistant text deltas."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


StreamEvent = dict[str, str]


@dataclass
class _TaskStream:
    text: str = ""
    subscribers: set[asyncio.Queue[StreamEvent]] = field(default_factory=set)
    terminal: StreamEvent | None = None


class TaskTextStreamHub:
    """Fan out token deltas while allowing reconnecting clients to catch up."""

    def __init__(self, queue_size: int = 64) -> None:
        self._queue_size = queue_size
        self._streams: dict[str, _TaskStream] = {}

    def begin(self, task_id: str) -> None:
        stream = self._streams.setdefault(task_id, _TaskStream())
        stream.text = ""
        stream.terminal = None
        self._broadcast(stream, {"type": "reset"})

    def subscribe(
        self,
        task_id: str,
        *,
        fallback_text: str = "",
        terminal: StreamEvent | None = None,
    ) -> tuple[asyncio.Queue[StreamEvent], StreamEvent, StreamEvent | None]:
        stream = self._streams.get(task_id)
        if stream is None:
            stream = _TaskStream(text=fallback_text, terminal=terminal)
            self._streams[task_id] = stream
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=self._queue_size)
        stream.subscribers.add(queue)
        return queue, {"type": "snapshot", "text": stream.text}, stream.terminal

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[StreamEvent]) -> None:
        stream = self._streams.get(task_id)
        if stream is None:
            return
        stream.subscribers.discard(queue)
        if stream.terminal is not None and not stream.subscribers:
            self._streams.pop(task_id, None)

    def publish(self, task_id: str, text: str | None) -> None:
        stream = self._streams.setdefault(task_id, _TaskStream())
        stream.terminal = None
        if text is None:
            stream.text = ""
            self._broadcast(stream, {"type": "reset"})
            return
        if text == stream.text:
            return
        if text.startswith(stream.text):
            delta = text[len(stream.text):]
            stream.text = text
            if delta:
                self._broadcast(stream, {"type": "delta", "text": delta})
            return
        stream.text = text
        self._broadcast(stream, {"type": "snapshot", "text": text})

    def finish(self, task_id: str, status: str, text: str = "") -> None:
        stream = self._streams.setdefault(task_id, _TaskStream())
        stream.text = text
        stream.terminal = {"type": "end", "status": status, "text": text}
        self._broadcast(stream, stream.terminal)
        if not stream.subscribers:
            self._streams.pop(task_id, None)

    def _broadcast(self, stream: _TaskStream, event: StreamEvent) -> None:
        for queue in tuple(stream.subscribers):
            if queue.full():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait({"type": "snapshot", "text": stream.text})
                if event["type"] == "end" and not queue.full():
                    queue.put_nowait(event)
            else:
                queue.put_nowait(event)
