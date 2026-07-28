from __future__ import annotations

import tempfile
from pathlib import Path

from app.history import HistoryStore


def test_empty_history_directory_creates_no_files() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        history = HistoryStore("")
        history.persist_task({"id": "one"}, [])
        assert list(Path(folder).iterdir()) == []


def test_history_persists_text_but_does_not_expose_image_paths() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        root = Path(folder)
        image = root / "shot.png"
        image.write_bytes(b"png")
        history = HistoryStore(str(root / "save"))
        task = {
            "id": "one", "status": "completed", "profile_name": "profile",
            "thinking_text": "think", "result_text": "answer", "error_message": "",
            "created_at": "now", "completed_at": "later",
        }
        history.persist_task(task, [image])
        loaded = history.get_task("one")
        assert loaded["result_text"] == "answer"
        assert "image_paths_json" not in loaded
        assert history.delete_task("one")
