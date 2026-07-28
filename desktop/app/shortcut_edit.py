from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent
from PySide6.QtWidgets import QLineEdit, QWidget


class ShortcutCaptureEdit(QLineEdit):
    """A compact shortcut recorder that also understands mouse side buttons."""

    recording_started = Signal()
    recording_finished = Signal()
    recording_cancelled = Signal()
    candidate_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按快捷键；留空表示禁用")
        self._default_tooltip = "支持 F1-F24、Ctrl/Alt/Shift/Win 组合及 Mouse4/Mouse5；Backspace 清空；Esc 取消"
        self.setToolTip(self._default_tooltip)
        self._recording = False
        self._original_text = ""

    def focusInEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().focusInEvent(event)
        if self._recording:
            return
        self._recording = True
        self._original_text = self.text()
        self.selectAll()
        self.recording_started.emit()
        self.grabKeyboard()

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().focusOutEvent(event)
        if self._recording:
            self.setText(self._original_text)
            self._recording = False
            self._release_keyboard_grab()
            self.recording_cancelled.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            self._recording = True
            self._original_text = self.text()
            self.recording_started.emit()
            self.grabKeyboard()
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.setText(self._original_text)
            self._recording = False
            self._release_keyboard_grab()
            self.recording_cancelled.emit()
            self.clearFocus()
            event.accept()
            return
        if key in {
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }:
            event.accept()
            return
        if key in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete} and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._commit("")
            event.accept()
            return
        if key == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.focusNextChild()
            event.accept()
            return

        special_key = {
            Qt.Key.Key_Plus: "Plus",
            Qt.Key.Key_Equal: "Equal",
            Qt.Key.Key_Minus: "Minus",
        }.get(key)
        if special_key:
            modifiers = event.modifiers()
            parts: list[str] = []
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                parts.append("Ctrl")
            if modifiers & Qt.KeyboardModifier.AltModifier:
                parts.append("Alt")
            # Shift is implicit in the portable "Plus" name on the main
            # keyboard; retaining it would make the displayed shortcut noisy.
            if (
                modifiers & Qt.KeyboardModifier.ShiftModifier
                and special_key != "Plus"
            ):
                parts.append("Shift")
            if modifiers & Qt.KeyboardModifier.MetaModifier:
                parts.append("Win")
            sequence = "+".join([*parts, special_key])
        else:
            sequence = QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        if sequence:
            self._commit(sequence)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.XButton1:
            self._commit("Mouse4")
            event.accept()
            return
        if event.button() == Qt.MouseButton.XButton2:
            self._commit("Mouse5")
            event.accept()
            return
        super().mousePressEvent(event)

    def _commit(self, sequence: str) -> None:
        self.setText(sequence)
        self._recording = False
        self._release_keyboard_grab()
        self.candidate_changed.emit(sequence)
        self.recording_finished.emit()
        self.clearFocus()

    def _release_keyboard_grab(self) -> None:
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()

    def set_validation_error(self, message: str = "") -> None:
        if message:
            self.setStyleSheet("QLineEdit { border: 2px solid #c62828; border-radius: 3px; }")
            self.setToolTip(message)
        else:
            self.setStyleSheet("")
            self.setToolTip(self._default_tooltip)
