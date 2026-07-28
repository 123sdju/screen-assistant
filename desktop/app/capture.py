from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import TypeAlias
from types import SimpleNamespace

from PIL import Image

try:
    import dxcam  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised via runtime dependency checks
    dxcam = SimpleNamespace(create=None)

Point: TypeAlias = tuple[int, int]
BBox: TypeAlias = tuple[int, int, int, int]
DXGI_BACKEND = "dxgi"
DXGI_OUTPUT_COLOR = "RGB"
DXGI_PROCESSOR_BACKEND = "numpy"
DXGI_GRAB_ATTEMPTS = 3
MAX_CAPTURE_FILES = 200
MAX_CAPTURE_AGE_DAYS = 30


def capture_fullscreen(output_dir: Path) -> Path:
    image = _grab_dxgi_image()
    return _save_capture(output_dir, image)


def normalize_bbox(first_point: Point, second_point: Point) -> BBox | None:
    left = min(first_point[0], second_point[0])
    top = min(first_point[1], second_point[1])
    right = max(first_point[0], second_point[0])
    bottom = max(first_point[1], second_point[1])
    if left == right or top == bottom:
        return None
    return (left, top, right, bottom)


def capture_region(output_dir: Path, bbox: BBox) -> Path:
    image = _grab_dxgi_image(bbox)
    return _save_capture(output_dir, image)


def _save_capture(output_dir: Path, image: Image.Image) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("screenshot_%Y%m%d_%H%M%S_%f.png")
    path = output_dir / filename
    image.save(path, "PNG")
    _prune_old_captures(output_dir)
    return path


def _prune_old_captures(output_dir: Path) -> None:
    try:
        entries = sorted(
            output_dir.glob("screenshot_*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    cutoff_time = time.time() - MAX_CAPTURE_AGE_DAYS * 86400
    for entry in entries[MAX_CAPTURE_FILES:]:
        _remove_capture_file(entry)
    for entry in entries[:MAX_CAPTURE_FILES]:
        try:
            if entry.stat().st_mtime < cutoff_time:
                _remove_capture_file(entry)
        except OSError:
            pass


def _remove_capture_file(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _grab_dxgi_image(region: BBox | None = None) -> Image.Image:
    create_camera = getattr(dxcam, "create", None)
    if create_camera is None:
        raise RuntimeError("DXGI capture backend is unavailable. Install dxcam to enable screenshot capture.")
    with create_camera(
        backend=DXGI_BACKEND,
        output_color=DXGI_OUTPUT_COLOR,
        processor_backend=DXGI_PROCESSOR_BACKEND,
    ) as camera:
        frame = None
        for _ in range(DXGI_GRAB_ATTEMPTS):
            frame = camera.grab(region=region, new_frame_only=False)
            if frame is not None:
                break
        if frame is None:
            raise RuntimeError("DXGI capture did not return a frame.")
    return Image.fromarray(frame)
