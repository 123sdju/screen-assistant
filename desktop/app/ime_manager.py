from __future__ import annotations

import ctypes
from ctypes import wintypes


WM_IME_CONTROL = 0x0283
WM_INPUTLANGCHANGEREQUEST = 0x0050
IMC_GETOPENSTATUS = 0x0005
IMC_SETOPENSTATUS = 0x0006
KLF_ACTIVATE = 0x00000001
ENGLISH_US_KLID = "00000409"


def force_english_input() -> bool:
    """Switch the foreground window to an English layout and close its IME."""
    try:
        user32 = ctypes.windll.user32
        imm32 = ctypes.windll.imm32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.LoadKeyboardLayoutW.argtypes = (wintypes.LPCWSTR, wintypes.UINT)
        user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
        user32.PostMessageW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.PostMessageW.restype = wintypes.BOOL
        imm32.ImmGetDefaultIMEWnd.argtypes = (wintypes.HWND,)
        imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
        window = user32.GetForegroundWindow()
        if not window:
            return False
        english_layout = user32.LoadKeyboardLayoutW(ENGLISH_US_KLID, KLF_ACTIVATE)
        if english_layout:
            user32.PostMessageW(
                window,
                WM_INPUTLANGCHANGEREQUEST,
                0,
                english_layout,
            )
        ime_window = imm32.ImmGetDefaultIMEWnd(window)
        if not ime_window:
            return True
        is_open = user32.SendMessageW(
            ime_window,
            WM_IME_CONTROL,
            IMC_GETOPENSTATUS,
            0,
        )
        if is_open:
            user32.SendMessageW(
                ime_window,
                WM_IME_CONTROL,
                IMC_SETOPENSTATUS,
                0,
            )
        return True
    except Exception:
        return False
