from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class HistoryStore:
    def __init__(self, history_dir: str) -> None:
        self._lock = threading.Lock()
        self.set_directory(history_dir)

    def set_directory(self, history_dir: str) -> None:
        clean = str(history_dir or "").strip()
        self.root = Path(clean).resolve() / "data" if clean else None
        self.database_path = self.root / "history.db" if self.root else None
        self.images_dir = self.root / "screenshots" if self.root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            self.images_dir.mkdir(parents=True, exist_ok=True)
            self._init_db()

    @property
    def enabled(self) -> bool:
        return self.database_path is not None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.database_path is None:
            raise RuntimeError("历史保存已关闭")
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    thinking_text TEXT NOT NULL DEFAULT '',
                    result_text TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    image_paths_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def persist_task(self, task: dict[str, Any], image_paths: list[Path]) -> None:
        if not self.enabled:
            return
        stored_paths: list[str] = []
        task_dir = self.images_dir / str(task["id"])
        task_dir.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(image_paths):
            if not source.exists():
                continue
            destination = task_dir / f"{index:02d}{source.suffix.lower() or '.png'}"
            shutil.copy2(source, destination)
            stored_paths.append(str(destination))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, status, profile_name, thinking_text, result_text, error_message,
                 image_paths_json, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["id"], task.get("status", ""), task.get("profile_name", ""),
                    task.get("thinking_text", ""), task.get("result_text", ""),
                    task.get("error_message", ""), json.dumps(stored_paths, ensure_ascii=False),
                    task.get("created_at", ""), task.get("completed_at", ""),
                ),
            )

    def list_tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id, status, profile_name, created_at, completed_at FROM tasks ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("image_paths_json", None)
        return result

    def delete_task(self, task_id: str) -> bool:
        if not self.enabled:
            return False
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        task_dir = self.images_dir / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)
        return bool(cursor.rowcount)

    def clear(self) -> None:
        if not self.enabled:
            return
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM tasks")
        if self.images_dir.exists():
            shutil.rmtree(self.images_dir, ignore_errors=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
