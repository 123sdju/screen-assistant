from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.events import EventHub, encode_sse
from app.history import HistoryStore
from app.pairing import PairingError, PairingManager
from app.task_engine import TaskEngine


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    device_id: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="Android App", max_length=128)


class CommandRequest(BaseModel):
    command: str
    profile_id: str | None = None


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


class GatewayApi:
    def __init__(
        self,
        pairing: PairingManager,
        events: EventHub,
        tasks: TaskEngine,
        history: HistoryStore,
        bootstrap: Callable[[], dict[str, Any]],
        command_handler: Callable[[str, str | None, str], dict[str, Any]],
        public_profiles: Callable[[], list[dict[str, str]]],
        settings_snapshot: Callable[[], dict[str, Any]],
        settings_handler: Callable[[dict[str, Any], str], dict[str, Any]],
    ) -> None:
        self.pairing = pairing
        self.events = events
        self.tasks = tasks
        self.history = history
        self.bootstrap = bootstrap
        self.command_handler = command_handler
        self.public_profiles = public_profiles
        self.settings_snapshot = settings_snapshot
        self.settings_handler = settings_handler
        self.app = FastAPI(title="Screen Assistant LAN Gateway", version="1.0.0", docs_url=None, redoc_url=None)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/health")
        def health() -> dict[str, str]:
            return {"status": "ok", "protocol": "1"}

        @app.post("/v1/pair")
        def pair(request: PairRequest) -> dict[str, str]:
            try:
                return self.pairing.pair(request.code, request.device_id, request.device_name)
            except PairingError as exc:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

        def authenticated_device(authorization: str | None = Header(default=None)) -> dict[str, Any]:
            scheme, _, token = str(authorization or "").partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
            device = self.pairing.authenticate(token)
            if device is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token")
            return device

        @app.get("/v1/bootstrap")
        def bootstrap(_device: dict[str, Any] = Depends(authenticated_device)) -> dict[str, Any]:
            return self.bootstrap()

        @app.get("/v1/status")
        def get_status(_device: dict[str, Any] = Depends(authenticated_device)) -> dict[str, Any]:
            payload = self.bootstrap()
            return {
                "desktop": payload["desktop"],
                "active_profile": payload["active_profile"],
                "buffer_count": payload["buffer_count"],
                "busy": payload["busy"],
            }

        @app.get("/v1/profiles")
        def profiles(_device: dict[str, Any] = Depends(authenticated_device)) -> list[dict[str, str]]:
            return self.public_profiles()

        @app.get("/v1/settings")
        def settings(_device: dict[str, Any] = Depends(authenticated_device)) -> dict[str, Any]:
            return self.settings_snapshot()

        @app.put("/v1/settings", status_code=status.HTTP_202_ACCEPTED)
        def update_settings(
            request: SettingsRequest,
            device: dict[str, Any] = Depends(authenticated_device),
        ) -> dict[str, Any]:
            try:
                return self.settings_handler(
                    request.settings,
                    str(device.get("device_id") or ""),
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        @app.get("/v1/tasks")
        def tasks(_device: dict[str, Any] = Depends(authenticated_device)) -> list[dict[str, Any]]:
            return self.tasks.list_tasks()

        @app.get("/v1/tasks/{task_id}")
        def task(task_id: str, _device: dict[str, Any] = Depends(authenticated_device)) -> dict[str, Any]:
            result = self.tasks.get_task(task_id)
            if result is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            return result

        @app.post("/v1/commands", status_code=status.HTTP_202_ACCEPTED)
        def command(request: CommandRequest, device: dict[str, Any] = Depends(authenticated_device)) -> dict[str, Any]:
            try:
                return self.command_handler(
                    request.command,
                    request.profile_id,
                    str(device.get("device_id") or ""),
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        @app.get("/v1/events")
        def event_stream(_device: dict[str, Any] = Depends(authenticated_device)) -> StreamingResponse:
            return StreamingResponse(
                self._stream_events(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    def _stream_events(self) -> Iterator[str]:
        with self.events.subscribe() as subscriber:
            # Subscribe before yielding the first frame so controls triggered
            # immediately after the App reports "connected" cannot be lost.
            yield encode_sse({"id": 0, "event": "connected"})
            while True:
                try:
                    item = subscriber.get(timeout=15)
                    yield encode_sse(item)
                except queue.Empty:
                    yield ": keep-alive\n\n"


class GatewayServer:
    def __init__(self, api: GatewayApi, host: str, port: int) -> None:
        # A PyInstaller windowed executable has no console, so sys.stdout and
        # sys.stderr are None. Uvicorn's default logging formatter calls
        # stream.isatty() while Config is constructed and crashes in that
        # environment. The desktop app owns logging, so disable Uvicorn's
        # dictConfig setup entirely.
        self.config = uvicorn.Config(
            api.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            log_config=None,
        )
        self.server = uvicorn.Server(self.config)
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="lan-gateway")
        self.thread.start()

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
