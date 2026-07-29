from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


_MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "meta",
    "windows": "meta",
    "meta": "meta",
}
_NAMED_KEYS = {
    "space",
    "tab",
    "enter",
    "esc",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "pageup",
    "pagedown",
    "up",
    "down",
    "left",
    "right",
    "plus",
    "equal",
    "minus",
}
_DISPLAY = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "meta": "Win",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "esc": "Esc",
    "plus": "Plus",
    "equal": "Equal",
    "minus": "Minus",
}


@dataclass(frozen=True)
class LinuxShortcutSpec:
    action: str
    sequence: str
    key: str
    modifiers: frozenset[str]


def _parse_shortcut(action: str, sequence: str) -> LinuxShortcutSpec | None:
    parts = [part.strip().lower() for part in str(sequence or "").split("+") if part.strip()]
    modifiers: set[str] = set()
    key = ""
    for part in parts:
        modifier = _MODIFIERS.get(part)
        if modifier:
            modifiers.add(modifier)
        elif not key and (
            part in _NAMED_KEYS
            or (part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24)
            or (len(part) == 1 and part.isalnum())
        ):
            key = part
        else:
            return None
    if not key:
        return None
    if key == "plus":
        modifiers.add("shift")
    return LinuxShortcutSpec(action, sequence, key, frozenset(modifiers))


def _format_shortcut(spec: LinuxShortcutSpec) -> str:
    modifiers = set(spec.modifiers)
    if spec.key == "plus":
        modifiers.discard("shift")
    parts = [_DISPLAY[name] for name in ("ctrl", "alt", "shift", "meta") if name in modifiers]
    key = _DISPLAY.get(spec.key, spec.key.upper() if len(spec.key) == 1 or spec.key.startswith("f") else spec.key.title())
    return "+".join([*parts, key])


def validate_shortcuts(shortcuts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    normalized: dict[str, str] = {}
    errors: dict[str, str] = {}
    signatures: dict[tuple[str, frozenset[str]], str] = {}
    for action, raw in shortcuts.items():
        sequence = str(raw or "").strip()
        if not sequence:
            normalized[action] = ""
            continue
        if "mouse" in sequence.lower():
            errors[action] = "Linux 版暂不支持鼠标侧键快捷键"
            continue
        spec = _parse_shortcut(action, sequence)
        if spec is None:
            errors[action] = "无法识别该快捷键"
            continue
        if not spec.modifiers and len(spec.key) == 1 and spec.key.isalnum():
            errors[action] = "字母或数字必须配合 Ctrl、Alt、Shift 或 Win"
            continue
        signature = (spec.key, spec.modifiers)
        previous = signatures.get(signature)
        if previous:
            errors[action] = "与其他功能重复"
            errors[previous] = "与其他功能重复"
            continue
        signatures[signature] = action
        normalized[action] = _format_shortcut(spec)
    return normalized, errors


class GlobalHotkeyManager(QObject):
    activated = Signal(str)
    registered = Signal(str, str)
    conflict = Signal(str, str)
    _activation_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._listener: Any = None
        self._specs: list[LinuxShortcutSpec] = []
        self._pressed: set[str] = set()
        self._active_actions: set[str] = set()
        self._suspended = threading.Event()
        self._activation_requested.connect(self._emit_activated)

    def register(self, shortcuts: dict[str, str]) -> None:
        self.stop()
        normalized, errors = validate_shortcuts(shortcuts)
        for action in errors:
            self.conflict.emit(action, str(shortcuts.get(action) or ""))
        self._specs = [
            spec
            for action, sequence in normalized.items()
            if sequence and (spec := _parse_shortcut(action, sequence)) is not None
        ]
        if not self._specs:
            return
        try:
            from pynput import keyboard

            self._keyboard_module = keyboard
            self._suspended.clear()
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.start()
            for spec in self._specs:
                self.registered.emit(spec.action, spec.sequence)
        except Exception:
            self._listener = None
            for spec in self._specs:
                self.conflict.emit(spec.action, spec.sequence)

    def suspend(self) -> None:
        self._suspended.set()

    @property
    def suspended(self) -> bool:
        return self._suspended.is_set()

    def stop(self) -> bool:
        self.suspend()
        listener = self._listener
        if listener is not None:
            try:
                listener.stop()
                listener.join(timeout=1)
            except Exception:
                pass
        self._listener = None
        self._pressed.clear()
        self._active_actions.clear()
        return True

    def _on_press(self, key: Any) -> None:
        if self.suspended:
            return
        name = self._key_name(key)
        if not name:
            return
        self._pressed.add(name)
        for spec in self._specs:
            if spec.action in self._active_actions:
                continue
            if name == spec.key and set(spec.modifiers).issubset(self._pressed):
                self._active_actions.add(spec.action)
                self._activation_requested.emit(spec.action)

    def _on_release(self, key: Any) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.discard(name)
        self._active_actions = {
            action
            for action in self._active_actions
            if any(spec.action == action and spec.key in self._pressed for spec in self._specs)
        }

    def _key_name(self, key: Any) -> str:
        keyboard = getattr(self, "_keyboard_module", None)
        if keyboard is None:
            return ""
        if isinstance(key, keyboard.KeyCode):
            char = str(key.char or "").lower()
            if char == "+":
                return "plus"
            if char == "=":
                return "equal"
            if char == "-":
                return "minus"
            return char
        value = str(key).removeprefix("Key.").lower()
        return {
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt_gr": "alt",
            "shift_l": "shift",
            "shift_r": "shift",
            "cmd": "meta",
            "cmd_l": "meta",
            "cmd_r": "meta",
            "page_up": "pageup",
            "page_down": "pagedown",
        }.get(value, value)

    @Slot(str)
    def _emit_activated(self, action: str) -> None:
        self.activated.emit(action)
