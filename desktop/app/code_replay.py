from __future__ import annotations

import ctypes
import random
import re
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

import keyboard
from PySide6.QtCore import QObject, Signal, Slot

from app.ime_manager import force_english_input


FENCED_CODE = re.compile(r"```(?:[\w#+.-]+)?[ \t]*\n(.*?)```", re.DOTALL)
UNCLOSED_FENCED_CODE = re.compile(r"```(?:[\w#+.-]+)?[ \t]*\n(.*)\Z", re.DOTALL)

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
VK_ESCAPE = 0x1B
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
HHOOK = getattr(wintypes, "HHOOK", wintypes.HANDLE)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


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


HookProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def extract_replay_text(markdown: str) -> str:
    blocks = [match.strip("\n") for match in FENCED_CODE.findall(markdown or "")]
    if blocks:
        return "\n\n".join(blocks)
    unclosed = UNCLOSED_FENCED_CODE.search(markdown or "")
    return unclosed.group(1).strip("\n") if unclosed else ""


def replay_interval(chars_per_second: float, jitter_ratio: float, random_value: float | None = None) -> float:
    base = 1.0 / max(1.0, float(chars_per_second))
    jitter = max(0.0, min(float(jitter_ratio), 0.8))
    sample = random.uniform(-1.0, 1.0) if random_value is None else max(-1.0, min(random_value, 1.0))
    return max(0.01, base * (1.0 + sample * jitter))


class NativeReplayHook:
    """Suppress physical keyboard input while allowing injected input through."""

    def __init__(self) -> None:
        self._callback: Callable[[int, bool], None] | None = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error = ""

    def start(self, callback: Callable[[int, bool], None]) -> None:
        self.stop()
        self._callback = callback
        self._ready.clear()
        self._error = ""
        self._thread = threading.Thread(target=self._run, daemon=True, name="replay_keyboard_hook")
        self._thread.start()
        if not self._ready.wait(1.5):
            raise RuntimeError("键盘钩子启动超时")
        if self._error:
            raise RuntimeError(self._error)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None
        self._thread_id = 0
        self._callback = None

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
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._thread_id = int(kernel32.GetCurrentThreadId())

        @HookProc
        def keyboard_proc(code: int, w_param: int, l_param: int) -> int:
            if code != HC_ACTION:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if int(info.flags) & LLKHF_INJECTED:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            if w_param in {WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP}:
                callback = self._callback
                if callback is not None:
                    callback(int(info.vkCode), w_param in {WM_KEYDOWN, WM_SYSKEYDOWN})
                return 1
            return user32.CallNextHookEx(None, code, w_param, l_param)

        hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            keyboard_proc,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not hook:
            self._error = f"无法安装键盘钩子（Windows错误 {ctypes.get_last_error()}）"
            self._ready.set()
            self._thread_id = 0
            return
        self._ready.set()
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hook)
        self._thread_id = 0


class KeyDrivenReplayController(QObject):
    """Replay fenced code from physical key events, with optional hold repeat."""

    started = Signal(int)
    stopped = Signal(int, int)
    finished = Signal(int)
    progress_updated = Signal(int, int)
    error_occurred = Signal(str)

    _advance_requested = Signal()
    _stop_requested = Signal()

    def __init__(
        self,
        keyboard_backend: Any = keyboard,
        hook_backend: NativeReplayHook | None = None,
    ) -> None:
        super().__init__()
        self._keyboard = keyboard_backend
        self._hook = hook_backend or NativeReplayHook()
        self._text = ""
        self._index = 0
        self._active = False
        self._completed = False
        self._line_has_content = False
        self._fast_mode = False
        self._chars_per_second = 12.0
        self._jitter_ratio = 0.15
        self._pressed_keys: set[int] = set()
        self._repeat_key: int | None = None
        self._step_pending = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._advance_requested.connect(self._advance)
        self._stop_requested.connect(self.stop)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def progress(self) -> tuple[int, int]:
        return self._index, len(self._text)

    def start(
        self,
        markdown: str,
        *,
        fast_mode: bool = False,
        chars_per_second: float = 12.0,
        jitter_ratio: float = 0.15,
    ) -> None:
        text = extract_replay_text(markdown)
        if not text:
            raise ValueError("当前结果中没有检测到 Markdown 代码块，无法回放")
        if self._active:
            self.stop()
        self._text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._index = 0
        self._active = True
        self._completed = False
        self._line_has_content = False
        self._fast_mode = bool(fast_mode)
        self._chars_per_second = max(1.0, float(chars_per_second))
        self._jitter_ratio = max(0.0, min(float(jitter_ratio), 0.8))
        self._pressed_keys.clear()
        self._repeat_key = None
        self._step_pending = False
        self._stop_event.clear()
        force_english_input()
        try:
            self._hook.start(self._on_physical_key)
        except Exception as exc:
            self._active = False
            raise RuntimeError(f"无法启动按键回放：{exc}") from exc
        self.started.emit(len(self._text))
        self.progress_updated.emit(0, len(self._text))

    @Slot()
    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop_event.set()
        self._hook.stop()
        self._pressed_keys.clear()
        self._repeat_key = None
        self.stopped.emit(self._index, len(self._text))

    def _on_physical_key(self, vk_code: int, is_down: bool) -> None:
        if not self._active:
            return
        if vk_code == VK_ESCAPE:
            if is_down:
                self._stop_requested.emit()
            return
        if vk_code in MODIFIER_VKS:
            return
        if self._completed:
            return

        if is_down:
            if vk_code in self._pressed_keys:
                return
            self._pressed_keys.add(vk_code)
            if self._fast_mode:
                self._request_step()
                if self._repeat_key is None:
                    self._repeat_key = vk_code
                    threading.Thread(
                        target=self._repeat_while_held,
                        args=(vk_code,),
                        daemon=True,
                        name="replay_hold_repeat",
                    ).start()
            return

        if vk_code not in self._pressed_keys:
            return
        self._pressed_keys.discard(vk_code)
        if self._repeat_key == vk_code:
            self._repeat_key = None
        if not self._fast_mode:
            self._request_step()

    def _repeat_while_held(self, vk_code: int) -> None:
        if self._stop_event.wait(0.32):
            return
        while (
            self._active
            and not self._completed
            and self._repeat_key == vk_code
            and vk_code in self._pressed_keys
        ):
            self._request_step()
            if self._stop_event.wait(
                replay_interval(self._chars_per_second, self._jitter_ratio)
            ):
                return

    def _request_step(self) -> None:
        with self._lock:
            if not self._active or self._completed or self._step_pending:
                return
            self._step_pending = True
        self._advance_requested.emit()

    @Slot()
    def _advance(self) -> None:
        try:
            if not self._active or self._completed or self._index >= len(self._text):
                return
            force_english_input()
            for modifier in ("shift", "ctrl", "alt", "windows"):
                try:
                    self._keyboard.release(modifier)
                except Exception:
                    pass

            character = self._text[self._index]
            if character == "\n":
                if self._line_has_content:
                    self._keyboard.send("esc")
                self._keyboard.send("enter")
                time.sleep(0.025)
                # Select any indentation inserted automatically by the target
                # editor. The first source character on the new line replaces
                # that selection, rebuilding the exact source indentation.
                self._keyboard.send("home")
                self._keyboard.send("home")
                self._keyboard.send("shift+end")
                self._line_has_content = False
            elif character == "\t":
                self._keyboard.send("tab")
            elif character == "\b":
                self._keyboard.send("backspace")
            else:
                self._keyboard.write(character)
                if not character.isspace():
                    self._line_has_content = True

            self._index += 1
            self.progress_updated.emit(self._index, len(self._text))
            if self._index >= len(self._text):
                self._completed = True
                self.finished.emit(len(self._text))
        except Exception as exc:
            self._active = False
            self._completed = False
            self._stop_event.set()
            self._hook.stop()
            self.error_occurred.emit(f"代码回放失败：{exc}")
        finally:
            with self._lock:
                self._step_pending = False
