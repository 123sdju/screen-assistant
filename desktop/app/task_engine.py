from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.ai_provider import OpenAICompatibleProvider
from app.events import EventHub
from app.history import HistoryStore


class BusyError(RuntimeError):
    pass


class TaskSuperseded(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskEngine:
    def __init__(
        self,
        history: HistoryStore,
        events: EventHub,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.history = history
        self.events = events
        self.on_update = on_update
        self._lock = threading.Lock()
        self._busy = False
        self._cancel = threading.Event()
        self._provider: OpenAICompatibleProvider | None = None
        self._active_task_id = ""
        self.current_task: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(
        self,
        profile: dict[str, Any],
        model_config: dict[str, Any],
        image_paths: list[Path],
        ephemeral: bool,
        replace_running: bool = False,
    ) -> str:
        previous_provider: OpenAICompatibleProvider | None = None
        with self._lock:
            if self._busy and not replace_running:
                raise BusyError("已有截图或模型任务正在执行")
            if not image_paths:
                raise ValueError("截图缓冲区为空")
            if self._busy:
                self._cancel.set()
                previous_provider = self._provider
            self._busy = True
        task_id = uuid.uuid4().hex
        cancel = threading.Event()
        task = {
            "id": task_id,
            "status": "running",
            "profile_name": str(profile.get("name") or "配置"),
            "thinking_text": "",
            "result_text": "",
            "error_message": "",
            "created_at": now_iso(),
            "completed_at": "",
        }
        with self._lock:
            self._cancel = cancel
            self._provider = None
            self._active_task_id = task_id
            self.current_task = task
        if previous_provider is not None:
            try:
                previous_provider.close()
            except Exception:
                pass
        self._emit_for(task_id, "task_snapshot", task=dict(task))
        thread = threading.Thread(
            target=self._run,
            args=(
                task,
                cancel,
                dict(profile),
                dict(model_config),
                list(image_paths),
                ephemeral,
            ),
            daemon=True,
            name=f"ai-task-{task_id[:8]}",
        )
        thread.start()
        return task_id

    def _run(
        self,
        task: dict[str, Any],
        cancel: threading.Event,
        profile: dict[str, Any],
        model_config: dict[str, Any],
        image_paths: list[Path],
        ephemeral: bool,
    ) -> None:
        provider: OpenAICompatibleProvider | None = None
        try:
            if not self._is_active(task["id"], cancel):
                raise TaskSuperseded()
            provider = OpenAICompatibleProvider(model_config)
            with self._lock:
                if self._active_task_id != task["id"] or cancel.is_set():
                    raise TaskSuperseded()
                self._provider = provider
            for text, thinking in provider.stream_screenshot(profile, image_paths):
                if not self._is_active(task["id"], cancel):
                    raise TaskSuperseded()
                if thinking:
                    task["thinking_text"] += thinking
                    self._emit_for(task["id"], "thinking_delta", task_id=task["id"], delta=thinking)
                if text:
                    task["result_text"] += text
                    self._emit_for(task["id"], "result_delta", task_id=task["id"], delta=text)
                self._notify_for(task["id"], task)
            if not self._is_active(task["id"], cancel):
                raise TaskSuperseded()
            task["status"] = "completed"
            task["completed_at"] = now_iso()
            self.history.persist_task(task, image_paths)
            self._emit_for(task["id"], "completed", task=dict(task))
        except TaskSuperseded:
            # Superseded tasks are intentionally discarded: no failure event,
            # no history row, and no late UI update.
            pass
        except Exception as exc:
            if self._is_active(task["id"], cancel):
                task["status"] = "failed"
                task["error_message"] = str(exc)
                task["completed_at"] = now_iso()
                self.history.persist_task(task, image_paths)
                self._emit_for(task["id"], "failed", task=dict(task), message=str(exc))
        finally:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    pass
            if ephemeral:
                for path in image_paths:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            is_active = False
            with self._lock:
                if self._active_task_id == task["id"]:
                    self._busy = False
                    self._provider = None
                    is_active = True
            if is_active:
                self._notify_for(task["id"], task)

    def cancel(self) -> None:
        with self._lock:
            self._cancel.set()
            provider = self._provider
        if provider is not None:
            try:
                provider.close()
            except Exception:
                pass

    def snapshot(self) -> dict[str, Any] | None:
        return dict(self.current_task) if self.current_task else None

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks = self.history.list_tasks()
        if self.current_task and not any(item.get("id") == self.current_task["id"] for item in tasks):
            tasks.insert(0, {key: self.current_task.get(key, "") for key in ("id", "status", "profile_name", "created_at", "completed_at")})
        return tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        if self.current_task and self.current_task.get("id") == task_id:
            return dict(self.current_task)
        return self.history.get_task(task_id)

    def _is_active(self, task_id: str, cancel: threading.Event) -> bool:
        with self._lock:
            return self._active_task_id == task_id and not cancel.is_set()

    def _emit_for(self, active_task_id: str, event: str, **payload: Any) -> None:
        if not self._is_active(active_task_id, self._cancel):
            raise TaskSuperseded()
        self.events.publish(event, **payload)
        task = self.current_task
        if task is not None:
            self._notify_for(active_task_id, task)

    def _notify_for(self, task_id: str, task: dict[str, Any]) -> None:
        if self.on_update and self._is_active(task_id, self._cancel):
            self.on_update(dict(task))
