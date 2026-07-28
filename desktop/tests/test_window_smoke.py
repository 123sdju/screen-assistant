from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.config import ConfigStore
from app.main_window import MainWindow


def test_main_window_starts_without_remote_server_or_database() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        config = ConfigStore(Path(folder) / "config.json")
        config.data["lan"]["enabled"] = False
        config.data["storage"]["history_dir"] = ""
        with patch("app.main_window.GlobalHotkeyManager.register"):
            window = MainWindow(config)
            assert window.windowTitle() == "Screen Assistant"
            assert window.history.enabled is False
            assert window._gateway is None
            assert set(window.shortcut_edits) == set(config.data["shortcuts"])
            window.shortcut_edits["capture_fullscreen"].setText("Ctrl+Shift+S")
            window.save_settings()
            assert config.data["shortcuts"]["capture_fullscreen"] == "Ctrl+Shift+S"
            window.shortcut_edits["capture_fullscreen"].setText("F3")
            window._preview_shortcut_candidate("capture_fullscreen", "F3")
            assert "冲突" in window.shortcut_status.text()
            first = Path(folder) / "first.png"
            second = Path(folder) / "second.png"
            Image.new("RGB", (320, 180), "red").save(first)
            Image.new("RGB", (180, 320), "blue").save(second)
            window.buffer = [first, second]
            window._update_buffer_ui()
            assert window.buffer_list.count() == 2
            assert window.buffer_list.currentRow() == 1
            assert window.buffer_preview.pixmap() is not None
            with window.events.subscribe() as first_app, window.events.subscribe() as second_app:
                window._execute_remote_command(
                    "scroll_apps_down",
                    None,
                    "scroll-test",
                    "controller-app",
                )
                first_event = first_app.get_nowait()
                assert first_event["direction"] == "down"
                assert first_event["source_device_id"] == "controller-app"
                assert second_app.get_nowait()["event"] == "app_scroll"
                assert first_app.get_nowait()["event"] == "command_completed"
                assert second_app.get_nowait()["event"] == "command_completed"
                window._hotkey_activated("scroll_apps_up")
                desktop_scroll = first_app.get_nowait()
                assert desktop_scroll == second_app.get_nowait()
                assert desktop_scroll["event"] == "app_scroll"
                assert desktop_scroll["direction"] == "up"
                assert desktop_scroll["source_device_id"] == "desktop"
                assert "2 个在线 App" in window.statusBar().currentMessage()
                window._hotkey_activated("increase_app_font")
                font_event = first_app.get_nowait()
                assert font_event == second_app.get_nowait()
                assert font_event["event"] == "app_font_scale"
                assert font_event["delta"] == 0.1
            window._quitting = True
            window.close()
    app.processEvents()
