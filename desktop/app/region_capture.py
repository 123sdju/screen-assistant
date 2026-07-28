from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_QUIT = 0x0012
VK_ESCAPE = 0x1B
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
STOP_JOIN_TIMEOUT_SECONDS = 0.15


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


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
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
HHOOK = getattr(wintypes, "HHOOK", wintypes.HANDLE)


def should_consume_region_click(
    *,
    code: int,
    w_param: int,
    now: float,
    arm_at: float,
    click_points: list[tuple[int, int]],
    point: tuple[int, int],
) -> bool:
    if code != HC_ACTION or w_param != WM_LBUTTONDOWN or now < arm_at:
        return False
    click_points.append(point)
    return True


class RegionCaptureManager(QObject):
    selection_started = Signal()
    selection_finished = Signal(object)
    selection_cancelled = Signal()
    selection_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._stop_event = threading.Event()
        self._active = False

    def is_active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._active = True
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_SECONDS)
        self._thread = None
        self._thread_id = 0
        self._active = False

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
        user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.PostThreadMessageW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = ()
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._thread_id = kernel32.GetCurrentThreadId()
        click_points: list[tuple[int, int]] = []
        arm_at = time.monotonic() + 0.15

        def finish_selection(payload: tuple[tuple[int, int], tuple[int, int]]) -> None:
            self.selection_finished.emit(payload)
            self._stop_event.set()
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        def cancel_selection() -> None:
            self.selection_cancelled.emit()
            self._stop_event.set()
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        @HookProc
        def mouse_proc(code: int, w_param: int, l_param: int) -> int:
            if code != HC_ACTION:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if int(info.flags) & LLMHF_INJECTED:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            if w_param == WM_LBUTTONDOWN:
                consumed = should_consume_region_click(
                    code=code,
                    w_param=w_param,
                    now=time.monotonic(),
                    arm_at=arm_at,
                    click_points=click_points,
                    point=(int(info.pt.x), int(info.pt.y)),
                )
                if consumed:
                    if len(click_points) >= 2:
                        finish_selection((click_points[0], click_points[1]))
                    return 1
            return user32.CallNextHookEx(None, code, w_param, l_param)

        @HookProc
        def keyboard_proc(code: int, w_param: int, l_param: int) -> int:
            if code != HC_ACTION:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if int(info.flags) & LLKHF_INJECTED:
                return user32.CallNextHookEx(None, code, w_param, l_param)
            if w_param in {WM_KEYDOWN, WM_SYSKEYDOWN} and int(info.vkCode) == VK_ESCAPE:
                cancel_selection()
                return 1
            return user32.CallNextHookEx(None, code, w_param, l_param)

        module_handle = kernel32.GetModuleHandleW(None)
        mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, module_handle, 0)
        mouse_error = ctypes.get_last_error()
        keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyboard_proc, module_handle, 0)
        keyboard_error = ctypes.get_last_error()

        if not mouse_hook or not keyboard_hook:
            if mouse_hook:
                user32.UnhookWindowsHookEx(mouse_hook)
            if keyboard_hook:
                user32.UnhookWindowsHookEx(keyboard_hook)
            self.selection_error.emit(
                f"无法启动无感区域截图监听 (mouse={mouse_error}, keyboard={keyboard_error}, module={int(module_handle or 0)})"
            )
            self._active = False
            self._thread = None
            self._thread_id = 0
            return

        self.selection_started.emit()
        msg = MSG()
        while not self._stop_event.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break

        user32.UnhookWindowsHookEx(mouse_hook)
        user32.UnhookWindowsHookEx(keyboard_hook)
        self._active = False
        self._thread = None
        self._thread_id = 0
