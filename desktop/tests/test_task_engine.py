from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.events import EventHub
from app.history import HistoryStore
from app.task_engine import BusyError, TaskEngine


MODEL = {"base_url": "http://local/v1", "api_key": "key", "model": "vision"}
PROFILE = {"name": "Profile", "prompt_template": "analyze"}


def _wait_until_idle(engine: TaskEngine) -> None:
    deadline = time.time() + 3
    while engine.busy and time.time() < deadline:
        time.sleep(0.01)
    assert not engine.busy


def test_task_streams_result_and_removes_ephemeral_capture() -> None:
    class FakeProvider:
        def __init__(self, _model) -> None: pass
        def stream_screenshot(self, _profile, _paths):
            yield "answer", "thinking"
        def close(self) -> None: pass

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        image = Path(folder) / "shot.png"
        image.write_bytes(b"image")
        events = EventHub()
        engine = TaskEngine(HistoryStore(""), events)
        with patch("app.task_engine.OpenAICompatibleProvider", FakeProvider):
            engine.start(PROFILE, MODEL, [image], ephemeral=True)
            _wait_until_idle(engine)
        assert engine.current_task["status"] == "completed", engine.current_task["error_message"]
        assert engine.current_task["thinking_text"] == "thinking"
        assert engine.current_task["result_text"] == "answer"
        assert not image.exists()


def test_second_task_is_rejected_while_first_is_running() -> None:
    release = threading.Event()

    class SlowProvider:
        def __init__(self, _model) -> None: pass
        def stream_screenshot(self, _profile, _paths):
            release.wait(timeout=2)
            yield "done", ""
        def close(self) -> None: release.set()

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        first = Path(folder) / "first.png"
        second = Path(folder) / "second.png"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        engine = TaskEngine(HistoryStore(""), EventHub())
        with patch("app.task_engine.OpenAICompatibleProvider", SlowProvider):
            engine.start(PROFILE, MODEL, [first], ephemeral=True)
            with pytest.raises(BusyError):
                engine.start(PROFILE, MODEL, [second], ephemeral=True)
            release.set()
            _wait_until_idle(engine)


def test_new_task_can_supersede_running_task_without_late_output_or_failure() -> None:
    first_started = threading.Event()
    first_released = threading.Event()

    class ReplaceableProvider:
        def __init__(self, model) -> None:
            self.name = model["model"]

        def stream_screenshot(self, _profile, _paths):
            if self.name == "first":
                first_started.set()
                yield "", "old-thinking"
                first_released.wait(timeout=2)
                yield "old-result", ""
            else:
                yield "new-result", "new-thinking"

        def close(self) -> None:
            if self.name == "first":
                first_released.set()

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        first = Path(folder) / "first.png"
        second = Path(folder) / "second.png"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        events = EventHub()
        engine = TaskEngine(HistoryStore(""), events)
        with patch("app.task_engine.OpenAICompatibleProvider", ReplaceableProvider):
            with events.subscribe() as subscriber:
                first_id = engine.start(
                    PROFILE,
                    {**MODEL, "model": "first"},
                    [first],
                    ephemeral=True,
                )
                assert first_started.wait(timeout=1)
                deadline = time.time() + 1
                while engine.current_task["thinking_text"] != "old-thinking" and time.time() < deadline:
                    time.sleep(0.01)
                second_id = engine.start(
                    PROFILE,
                    {**MODEL, "model": "second"},
                    [second],
                    ephemeral=True,
                    replace_running=True,
                )
                _wait_until_idle(engine)
                time.sleep(0.05)
                emitted = []
                while not subscriber.empty():
                    emitted.append(subscriber.get_nowait())

        assert first_id != second_id
        assert engine.current_task["id"] == second_id
        assert engine.current_task["status"] == "completed", engine.current_task["error_message"]
        assert engine.current_task["thinking_text"] == "new-thinking"
        assert engine.current_task["result_text"] == "new-result"
        assert not any(
            event["event"] == "failed"
            and event.get("task", {}).get("id") == first_id
            for event in emitted
        )
        assert not first.exists()
        assert not second.exists()
