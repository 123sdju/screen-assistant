import sys

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

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
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
