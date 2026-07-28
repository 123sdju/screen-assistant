import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.code_replay import (
    VK_ESCAPE,
    KeyDrivenReplayController,
    extract_replay_text,
    replay_interval,
)
from app.config import DEFAULT_SHORTCUTS
from app.global_hotkeys import GlobalHotkeyManager, parse_native_shortcut, validate_shortcuts
from app.shortcut_edit import ShortcutCaptureEdit


class FakeKeyboard:
    def __init__(self) -> None:
        self.output: list[str] = []
        self.released: list[str] = []

    def release(self, name: str) -> None:
        self.released.append(name)

    def write(self, value: str) -> None:
        self.output.append(value)

    def send(self, value: str) -> None:
        self.output.append(f"<{value}>")


class FakeHook:
    def __init__(self) -> None:
        self.callback = None
        self.stopped = False

    def start(self, callback) -> None:
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def key(self, vk_code: int, is_down: bool) -> None:
        assert self.callback is not None
        self.callback(vk_code, is_down)


def test_extracts_fenced_code_for_replay() -> None:
    assert extract_replay_text("before\n```python\nprint(1)\n```\nafter") == "print(1)"


def test_replay_ignores_natural_language_without_code_fences() -> None:
    assert extract_replay_text("下面是代码说明：请先安装依赖。") == ""
    assert extract_replay_text("说明\n```python\nprint('ok')\n```\n更多中文说明") == "print('ok')"


def test_replay_accepts_unclosed_code_fence_but_not_plain_text() -> None:
    assert extract_replay_text("```cpp\nint main() {}") == "int main() {}"
    assert extract_replay_text("print('not fenced')") == ""


def test_parses_native_shortcut() -> None:
    shortcut = parse_native_shortcut("capture", "Ctrl+Shift+K")
    assert shortcut is not None
    assert shortcut.modifiers == frozenset({"ctrl", "shift"})


def test_validates_and_canonicalizes_shortcuts() -> None:
    normalized, errors = validate_shortcuts(
        {"capture": "ctrl+shift+k", "submit": "F3", "disabled": ""}
    )
    assert errors == {}
    assert normalized == {
        "capture": "Ctrl+Shift+K",
        "submit": "F3",
        "disabled": "",
    }


def test_app_control_shortcuts_support_page_and_oem_plus_minus_keys() -> None:
    normalized, errors = validate_shortcuts(DEFAULT_SHORTCUTS)
    assert errors == {}
    assert normalized["scroll_apps_up"] == "Ctrl+Alt+PageUp"
    assert normalized["scroll_apps_down"] == "Ctrl+Alt+PageDown"
    assert normalized["increase_app_font"] == "Ctrl+Alt+Plus"
    assert normalized["decrease_app_font"] == "Ctrl+Alt+Minus"
    plus = parse_native_shortcut("font", "Ctrl+Alt+Plus")
    assert plus is not None
    assert plus.key_code == 0xBB
    assert plus.modifiers == frozenset({"ctrl", "alt", "shift"})


def test_rejects_duplicate_and_plain_typing_keys() -> None:
    _, duplicate_errors = validate_shortcuts({"capture": "F2", "submit": "f2"})
    assert set(duplicate_errors) == {"capture", "submit"}

    _, typing_errors = validate_shortcuts({"capture": "K"})
    assert "capture" in typing_errors


def test_shortcut_capture_edit_records_and_clears() -> None:
    app = QApplication.instance() or QApplication([])
    editor = ShortcutCaptureEdit()
    editor.show()
    editor.setFocus()
    QTest.keyClick(
        editor,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.text() == "Ctrl+Shift+S"
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.text() == ""
    editor.close()
    app.processEvents()


def test_shortcut_capture_edit_accepts_f3_when_it_is_not_duplicated() -> None:
    app = QApplication.instance() or QApplication([])
    editor = ShortcutCaptureEdit()
    editor.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_F3)
    assert editor.text() == "F3"
    normalized, errors = validate_shortcuts({"submit_buffer": editor.text()})
    assert errors == {}
    assert normalized["submit_buffer"] == "F3"
    editor.close()
    app.processEvents()


def test_global_hotkey_suspend_is_immediate_and_survives_stop() -> None:
    manager = GlobalHotkeyManager()
    assert not manager.suspended
    manager.suspend()
    assert manager.suspended
    assert manager.stop()
    assert manager.suspended


def test_shortcut_capture_edit_escape_restores_original_value() -> None:
    app = QApplication.instance() or QApplication([])
    editor = ShortcutCaptureEdit()
    editor.setText("F2")
    editor.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert editor.text() == "F2"
    editor.close()
    app.processEvents()


def test_shortcut_capture_edit_records_portable_plus_and_minus_names() -> None:
    app = QApplication.instance() or QApplication([])
    editor = ShortcutCaptureEdit()
    editor.show()
    editor.setFocus()
    QTest.keyClick(
        editor,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.text() == "Ctrl+Alt+Plus"
    editor.setFocus()
    QTest.keyClick(
        editor,
        Qt.Key.Key_Minus,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert editor.text() == "Ctrl+Alt+Minus"
    editor.close()
    app.processEvents()


def test_key_driven_replay_advances_one_character_per_release_and_stays_locked() -> None:
    backend = FakeKeyboard()
    hook = FakeHook()
    replay = KeyDrivenReplayController(backend, hook)
    replay.start("```text\nab\n```")

    hook.key(ord("X"), True)
    assert backend.output == []
    hook.key(ord("X"), False)
    assert backend.output == ["a"]

    hook.key(ord("Y"), True)
    hook.key(ord("Y"), False)
    assert backend.output == ["a", "b"]
    assert replay.active
    assert replay.completed

    hook.key(ord("Z"), True)
    hook.key(ord("Z"), False)
    assert backend.output == ["a", "b"]
    assert replay.active

    replay.stop()
    assert not replay.active
    assert hook.stopped


def test_key_driven_replay_escape_cancels_without_output() -> None:
    backend = FakeKeyboard()
    hook = FakeHook()
    replay = KeyDrivenReplayController(backend, hook)
    replay.start("```text\nabc\n```")
    hook.key(VK_ESCAPE, True)
    assert not replay.active
    assert replay.progress == (0, 3)
    assert backend.output == []


def test_newline_selects_editor_autoindent_before_source_indentation(monkeypatch) -> None:
    english_calls: list[bool] = []
    monkeypatch.setattr(
        "app.code_replay.force_english_input",
        lambda: english_calls.append(True) or True,
    )
    monkeypatch.setattr("app.code_replay.time.sleep", lambda _seconds: None)
    backend = FakeKeyboard()
    replay = KeyDrivenReplayController(backend, FakeHook())
    replay.start("```python\nif x:\n    y()\n```")

    for _ in range(len("if x:\n    y()")):
        replay._request_step()

    newline = backend.output.index("<enter>")
    assert backend.output[newline - 1] == "<esc>"
    assert backend.output[newline : newline + 4] == [
        "<enter>",
        "<home>",
        "<home>",
        "<shift+end>",
    ]
    assert backend.output[newline + 4 : newline + 8] == [" ", " ", " ", " "]
    assert len(english_calls) == len("if x:\n    y()") + 1


def test_fast_replay_interval_has_bounded_random_jitter() -> None:
    assert replay_interval(10, 0.2, -1.0) == pytest.approx(0.08)
    assert replay_interval(10, 0.2, 0.0) == pytest.approx(0.1)
    assert replay_interval(10, 0.2, 1.0) == pytest.approx(0.12)


def test_fast_mode_emits_on_initial_keydown_and_ignores_os_repeat() -> None:
    backend = FakeKeyboard()
    hook = FakeHook()
    replay = KeyDrivenReplayController(backend, hook)
    replay.start("```text\nab\n```", fast_mode=True)

    hook.key(ord("X"), True)
    hook.key(ord("X"), True)
    assert backend.output == ["a"]
    hook.key(ord("X"), False)
    replay.stop()
