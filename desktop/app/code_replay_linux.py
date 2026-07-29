from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class KeyDrivenReplayController(QObject):
    started = Signal(int)
    stopped = Signal(int, int)
    finished = Signal(int)
    progress_updated = Signal(int, int)
    error_occurred = Signal(str)

    @property
    def active(self) -> bool:
        return False

    @property
    def completed(self) -> bool:
        return False

    @property
    def progress(self) -> tuple[int, int]:
        return (0, 0)

    def start(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError(
            "Linux 首版暂不提供代码回放：Wayland/X11 无法可靠、免 root 地拦截并替换全局键盘输入。"
        )

    def stop(self) -> None:
        return
