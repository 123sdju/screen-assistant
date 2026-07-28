from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
XBUTTON1 = 1
XBUTTON2 = 2
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
HHOOK = getattr(wintypes, "HHOOK", wintypes.HANDLE)

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "meta": "win",
}
_NAMED_KEYS = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "plus": 0xBB,
    "equal": 0xBB,
    "equals": 0xBB,
    "minus": 0xBD,
}
_MOUSE_BUTTONS = {
    "mouse4": XBUTTON1,
    "mouse5": XBUTTON2,
}
for index in range(1, 25):
    _NAMED_KEYS[f"f{index}"] = 0x6F + index


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HookProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


@dataclass(frozen=True)
class NativeShortcutSpec:
    action: str
    sequence: str
    trigger: str
    key_code: int
    modifiers: frozenset[str]


_DISPLAY_KEY_NAMES = {
    0x20: "Space",
    0x09: "Tab",
    0x0D: "Enter",
    0x1B: "Esc",
    0x08: "Backspace",
    0x2E: "Delete",
    0x2D: "Insert",
    0x24: "Home",
    0x23: "End",
    0x21: "PageUp",
    0x22: "PageDown",
    0x26: "Up",
    0x28: "Down",
    0x25: "Left",
    0x27: "Right",
    0xBB: "Equal",
    0xBD: "Minus",
}
_DISPLAY_MODIFIERS = (("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("win", "Win"))


def parse_native_shortcut(action: str, sequence: str) -> NativeShortcutSpec | None:
    normalized = str(sequence or "").strip()
    if not normalized:
        return None
    parts = [part.strip().lower() for part in normalized.split("+") if part.strip()]
    if not parts:
        return None
    modifiers: set[str] = set()
    key_vk = 0
    key_part = ""
    for part in parts:
        modifier = _MODIFIER_ALIASES.get(part)
        if modifier is not None:
            modifiers.add(modifier)
            continue
        if key_vk:
            return None
        key_vk = _resolve_key_code(part)
        key_part = part
    if not key_vk:
        return None
    # On the main keyboard "+" is Shift + the OEM equals key. Keep a readable
    # canonical name while matching the actual low-level Windows modifier state.
    if key_part == "plus":
        modifiers.add("shift")
    trigger = "mouse" if key_part in _MOUSE_BUTTONS else "keyboard"
    return NativeShortcutSpec(
        action=action,
        sequence=normalized,
        trigger=trigger,
        key_code=key_vk,
        modifiers=frozenset(modifiers),
    )


def _resolve_key_code(name: str) -> int:
    if name in _MOUSE_BUTTONS:
        return _MOUSE_BUTTONS[name]
    if len(name) == 1:
        char = name.upper()
        if "A" <= char <= "Z" or "0" <= char <= "9":
            return ord(char)
    return _NAMED_KEYS.get(name, 0)


def format_native_shortcut(spec: NativeShortcutSpec) -> str:
    display_modifiers = set(spec.modifiers)
    if spec.key_code == 0xBB and "shift" in display_modifiers:
        display_modifiers.remove("shift")
        key_name = "Plus"
    elif spec.key_code == 0xBB:
        key_name = "Equal"
    else:
        key_name = ""
    parts = [label for name, label in _DISPLAY_MODIFIERS if name in display_modifiers]
    if spec.trigger == "mouse":
        key_name = "Mouse4" if spec.key_code == XBUTTON1 else "Mouse5"
    elif 0x70 <= spec.key_code <= 0x87:
        key_name = f"F{spec.key_code - 0x6F}"
    elif 0x30 <= spec.key_code <= 0x39 or 0x41 <= spec.key_code <= 0x5A:
        key_name = chr(spec.key_code)
    elif not key_name:
        key_name = _DISPLAY_KEY_NAMES.get(spec.key_code, "")
    return "+".join([*parts, key_name])


def validate_shortcuts(shortcuts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return canonical shortcuts and per-action validation messages."""
    normalized: dict[str, str] = {}
    errors: dict[str, str] = {}
    signatures: dict[tuple[str, int, frozenset[str]], str] = {}

    for action, raw_sequence in shortcuts.items():
        sequence = str(raw_sequence or "").strip()
        if not sequence:
            normalized[action] = ""
            continue
        spec = parse_native_shortcut(action, sequence)
        if spec is None:
            errors[action] = "无法识别该快捷键"
            continue
        if not spec.modifiers and (
            0x30 <= spec.key_code <= 0x39 or 0x41 <= spec.key_code <= 0x5A
        ):
            errors[action] = "字母或数字必须配合 Ctrl、Alt、Shift 或 Win，避免影响正常输入"
            continue
        canonical = format_native_shortcut(spec)
        if not canonical:
            errors[action] = "该按键暂不支持"
            continue
        signature = (spec.trigger, spec.key_code, spec.modifiers)
        previous = signatures.get(signature)
        if previous is not None:
            errors[action] = "与其他功能重复"
            errors[previous] = "与其他功能重复"
            continue
        signatures[signature] = action
        normalized[action] = canonical

    return normalized, errors


def current_modifier_state(user32: ctypes.WinDLL) -> set[str]:
    state: set[str] = set()
    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        state.add("ctrl")
    if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
        state.add("alt")
    if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        state.add("shift")
    if (user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000):
        state.add("win")
    return state


def should_trigger_shortcut(
    spec: NativeShortcutSpec,
    *,
    trigger: str,
    key_code: int,
    modifiers: set[str],
    active_actions: set[str],
) -> bool:
    if trigger != spec.trigger:
        return False
    if key_code != spec.key_code:
        return False
    if modifiers != set(spec.modifiers):
        return False
    if spec.action in active_actions:
        return False
    return True


class GlobalHotkeyManager(QObject):
    activated = Signal(str)
    registered = Signal(str, str)
    conflict = Signal(str, str)

    _activation_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop_event = threading.Event()
        # This flag is checked inside the native hook callbacks.  It lets the
        # UI stop swallowing keys immediately, without waiting for the hook
        # thread and its Windows message loop to finish.
        self._suspended = threading.Event()
        self._specs: list[NativeShortcutSpec] = []
        self._active_actions: set[str] = set()
        self._active_keyboard_keys: set[int] = set()
        self._active_mouse_buttons: set[int] = set()
        self._active_modifier_keys: set[int] = set()
        self._activation_requested.connect(self._emit_activated)

    def register(self, shortcuts: dict[str, str]) -> None:
        stopped = self.stop()
        normalized, errors = validate_shortcuts(shortcuts)
        specs: list[NativeShortcutSpec] = []
        for action, sequence in normalized.items():
            if not sequence:
                continue
            spec = parse_native_shortcut(action, sequence)
            if spec is not None:
                specs.append(spec)
        for action in errors:
            self.conflict.emit(action, str(shortcuts.get(action) or "").strip())
        self._specs = specs
        if not specs:
            return
        if not stopped:
            for spec in specs:
                self.conflict.emit(spec.action, spec.sequence)
            return
        self._start_listener_thread()

    def _start_listener_thread(self) -> None:
        self._stop_event.clear()
        self._suspended.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="global_hotkeys")
        self._thread.start()

    def suspend(self) -> None:
        """Immediately pass all native input through to the focused window."""
        self._suspended.set()

    @property
    def suspended(self) -> bool:
        return self._suspended.is_set()

    def stop(self) -> bool:
        # Set this first: PostThreadMessage/Join may take time, while a shortcut
        # recorder needs the very next key (including a currently registered
        # bare F-key) to reach its Qt widget.
        self.suspend()
        self._stop_event.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if thread is not None and thread.is_alive():
            return False
        self._thread = None
        self._thread_id = 0
        self._active_actions = set()
        self._active_keyboard_keys = set()
        self._active_mouse_buttons = set()
        self._active_modifier_keys = set()
        return True

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HookProc, wintypes.HINSTANCE, wintypes.DWORD)
        user32.SetWindowsHookExW.restype = HHOOK
        user32.UnhookWindowsHookEx.argtypes = (HHOOK,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.CallNextHookEx.argtypes = (HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.restype = LRESULT
        user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
        kernel32.GetCurrentThreadId.argtypes = ()
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._thread_id = kernel32.GetCurrentThreadId()

        @HookProc
        def keyboard_proc(code: int, w_param: int, l_param: int) -> int:
            if code != HC_ACTION:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            if self._suspended.is_set():
                return user32.CallNextHookEx(None, code, w_param, l_param)

            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk_code = int(info.vkCode)
            if int(info.flags) & LLKHF_INJECTED:
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if w_param in {WM_KEYUP, WM_SYSKEYUP}:
                if self._clear_active_keyboard_actions_for_vk(vk_code):
                    return 1
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if w_param not in {WM_KEYDOWN, WM_SYSKEYDOWN}:
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if self._is_suppressed_keyboard_event(vk_code):
                return 1

            modifiers = current_modifier_state(user32)
            for spec in self._specs:
                if not should_trigger_shortcut(
                    spec,
                    trigger="keyboard",
                    key_code=vk_code,
                    modifiers=modifiers,
                    active_actions=self._active_actions,
                ):
                    continue
                self._activate_spec(spec)
                self._activation_requested.emit(spec.action)
                return 1

            return user32.CallNextHookEx(None, code, w_param, l_param)

        @HookProc
        def mouse_proc(code: int, w_param: int, l_param: int) -> int:
            if code != HC_ACTION:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            if self._suspended.is_set():
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if w_param not in {WM_XBUTTONDOWN, WM_XBUTTONUP}:
                return user32.CallNextHookEx(None, code, w_param, l_param)

            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if int(info.flags) & LLMHF_INJECTED:
                return user32.CallNextHookEx(None, code, w_param, l_param)

            button_code = int(info.mouseData >> 16)
            if button_code not in {XBUTTON1, XBUTTON2}:
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if w_param == WM_XBUTTONUP:
                handled = self._clear_active_mouse_actions_for_button(button_code)
                if handled:
                    return 1
                return user32.CallNextHookEx(None, code, w_param, l_param)

            if button_code in self._active_mouse_buttons:
                return 1

            modifiers = current_modifier_state(user32)
            for spec in self._specs:
                if not should_trigger_shortcut(
                    spec,
                    trigger="mouse",
                    key_code=button_code,
                    modifiers=modifiers,
                    active_actions=self._active_actions,
                ):
                    continue
                self._activate_spec(spec)
                self._activation_requested.emit(spec.action)
                return 1

            return user32.CallNextHookEx(None, code, w_param, l_param)

        module_handle = kernel32.GetModuleHandleW(None)
        keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, module_handle, 0)
        mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, module_handle, 0)
        if not keyboard_hook or not mouse_hook:
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            for spec in self._specs:
                self.conflict.emit(spec.action, spec.sequence)
            self._thread = None
            self._thread_id = 0
            return

        for spec in self._specs:
            self.registered.emit(spec.action, spec.sequence)

        msg = MSG()
        while not self._stop_event.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break

        user32.UnhookWindowsHookEx(keyboard_hook)
        user32.UnhookWindowsHookEx(mouse_hook)
        self._thread = None
        self._thread_id = 0
        self._active_actions = set()
        self._active_keyboard_keys = set()
        self._active_mouse_buttons = set()
        self._active_modifier_keys = set()

    @staticmethod
    def _modifier_virtual_keys(modifiers: set[str] | frozenset[str]) -> set[int]:
        virtual_keys: set[int] = set()
        if "ctrl" in modifiers:
            virtual_keys.add(VK_CONTROL)
        if "alt" in modifiers:
            virtual_keys.add(VK_MENU)
        if "shift" in modifiers:
            virtual_keys.add(VK_SHIFT)
        if "win" in modifiers:
            virtual_keys.update({VK_LWIN, VK_RWIN})
        return virtual_keys

    def _activate_spec(self, spec: NativeShortcutSpec) -> None:
        self._active_actions.add(spec.action)
        if spec.trigger == "keyboard":
            self._active_keyboard_keys.add(spec.key_code)
        else:
            self._active_mouse_buttons.add(spec.key_code)
        self._active_modifier_keys.update(self._modifier_virtual_keys(spec.modifiers))

    def _is_suppressed_keyboard_event(self, vk_code: int) -> bool:
        return vk_code in self._active_keyboard_keys or vk_code in self._active_modifier_keys

    def _clear_active_keyboard_actions_for_vk(self, vk_code: int) -> bool:
        previous = set(self._active_actions)
        self._active_actions = {
            action
            for action in self._active_actions
            if not any(
                spec.action == action
                and (
                    (spec.trigger == "keyboard" and spec.key_code == vk_code)
                    or vk_code in self._modifier_virtual_keys(spec.modifiers)
                )
                for spec in self._specs
            )
        }
        self._rebuild_active_suppression_sets()
        return previous != self._active_actions

    def _clear_active_mouse_actions_for_button(self, button_code: int) -> bool:
        previous = set(self._active_actions)
        self._active_actions = {
            action
            for action in self._active_actions
            if not any(
                spec.action == action and spec.trigger == "mouse" and spec.key_code == button_code
                for spec in self._specs
            )
        }
        self._rebuild_active_suppression_sets()
        return previous != self._active_actions

    def _rebuild_active_suppression_sets(self) -> None:
        self._active_keyboard_keys = set()
        self._active_mouse_buttons = set()
        self._active_modifier_keys = set()
        for spec in self._specs:
            if spec.action not in self._active_actions:
                continue
            if spec.trigger == "keyboard":
                self._active_keyboard_keys.add(spec.key_code)
            else:
                self._active_mouse_buttons.add(spec.key_code)
            self._active_modifier_keys.update(self._modifier_virtual_keys(spec.modifiers))

    @Slot(str)
    def _emit_activated(self, action: str) -> None:
        self.activated.emit(action)
