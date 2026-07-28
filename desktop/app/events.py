from __future__ import annotations

import json
import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator


class EventHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._sequence = 0

    def publish(self, event: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            item = {"id": self._sequence, "event": event, **payload}
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(item)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(item)
                except queue.Empty:
                    pass
        return item

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @contextmanager
    def subscribe(self) -> Iterator[queue.Queue[dict[str, Any]]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)


def encode_sse(item: dict[str, Any]) -> str:
    return f"id: {item.get('id', '')}\nevent: {item.get('event', 'message')}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
