from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.capture import _grab_platform_image
from app.code_replay_linux import KeyDrivenReplayController
from app.global_hotkeys_linux import validate_shortcuts


def test_linux_shortcut_validation_canonicalizes_and_detects_conflicts() -> None:
    normalized, errors = validate_shortcuts(
        {
            "capture": "ctrl+alt+pageup",
            "duplicate": "Ctrl+Alt+PageUp",
            "function": "f3",
            "typing": "k",
        }
    )
    assert errors["capture"] == "与其他功能重复"
    assert errors["duplicate"] == "与其他功能重复"
    assert normalized["function"] == "F3"
    assert "typing" in errors


def test_linux_capture_backend_uses_pillow_image_grab() -> None:
    expected = Image.new("RGB", (20, 10), "white")
    with (
        patch("app.capture.sys.platform", "linux"),
        patch("app.capture.ImageGrab.grab", return_value=expected) as grab,
    ):
        assert _grab_platform_image((1, 2, 10, 8)) is expected
    grab.assert_called_once_with(bbox=(1, 2, 10, 8), all_screens=True)


def test_linux_code_replay_reports_unsupported_without_input_hooks() -> None:
    controller = KeyDrivenReplayController()
    assert controller.active is False
    with pytest.raises(RuntimeError, match="Linux 首版暂不提供代码回放"):
        controller.start("```python\nprint('x')\n```")
