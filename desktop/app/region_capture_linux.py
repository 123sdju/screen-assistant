from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class _SelectionOverlay(QWidget):
    finished = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        geometry = QRect()
        for screen in QApplication.screens():
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        first = self.mapToGlobal(self._origin)
        second = self.mapToGlobal(self._current)
        self.hide()
        QTimer.singleShot(
            120,
            lambda: self.finished.emit(((first.x(), first.y()), (second.x(), second.y()))),
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._origin is not None and self._current is not None:
            selection = QRect(self._origin, self._current).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(selection, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#4f6fdc"), 2))
            painter.drawRect(selection)


class RegionCaptureManager(QObject):
    selection_started = Signal()
    selection_finished = Signal(object)
    selection_cancelled = Signal()
    selection_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._overlay: _SelectionOverlay | None = None

    def is_active(self) -> bool:
        return self._overlay is not None

    def start(self) -> bool:
        if self._overlay is not None:
            return False
        try:
            overlay = _SelectionOverlay()
            overlay.finished.connect(self._finish)
            overlay.cancelled.connect(self._cancel)
            self._overlay = overlay
            overlay.show()
            overlay.raise_()
            overlay.activateWindow()
            overlay.setFocus()
            self.selection_started.emit()
            return True
        except Exception as exc:
            self._overlay = None
            self.selection_error.emit(f"无法启动 Linux 区域选择：{exc}")
            return False

    def stop(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay.deleteLater()
            self._overlay = None

    def _finish(self, points: object) -> None:
        self.stop()
        self.selection_finished.emit(points)

    def _cancel(self) -> None:
        self.stop()
        self.selection_cancelled.emit()
