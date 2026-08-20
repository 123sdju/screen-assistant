import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

platform_hiddenimports = (
    collect_submodules("dxcam")
    if sys.platform == "win32"
    else ["pynput.keyboard._xorg", "pynput._util.xorg"]
)
hiddenimports = platform_hiddenimports + [
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "qrcode.image.pil",
]


def collect_runtime_dlls() -> list[tuple[str, str]]:
    """Bundle DLLs kept outside Python's DLL directory by Conda builds."""
    if sys.platform != "win32":
        return []
    roots = {
        Path(sys.prefix) / "Library" / "bin",
        Path(getattr(sys, "base_prefix", sys.prefix)) / "Library" / "bin",
        Path(sys.prefix) / "DLLs",
        Path(getattr(sys, "base_prefix", sys.prefix)) / "DLLs",
    }
    names = {
        "LIBBZ2.dll",
        "libmpdec-4.dll",
        "libcrypto-3-x64.dll",
        "libssl-3-x64.dll",
        "ffi.dll",
        "sqlite3.dll",
    }
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        for name in names:
            candidate = root / name
            key = str(candidate).lower()
            if candidate.is_file() and key not in seen:
                result.append((str(candidate), "."))
                seen.add(key)
    return result


runtime_dlls = collect_runtime_dlls()

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=runtime_dlls,
    datas=[("web", "web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["psycopg", "sqlalchemy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ScreenAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
