from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import ConfigStore
from app.events import EventHub
from app.gateway import GatewayApi
from app.history import HistoryStore
from app.pairing import PairingManager
from app.task_engine import TaskEngine


def _api(folder: Path, command_handler):
    config = ConfigStore(folder / "config.json")
    events = EventHub()
    history = HistoryStore("")
    tasks = TaskEngine(history, events)
    pairing = PairingManager(config)
    api = GatewayApi(
        pairing,
        events,
        tasks,
        history,
        lambda: {
            "desktop": {"id": "pc", "name": "PC"},
            "active_profile": {"id": "profile", "name": "Default"},
            "profiles": [{"id": "profile", "name": "Default"}],
            "buffer_count": 0,
            "busy": False,
            "current_task": None,
            "tasks": [],
        },
        command_handler,
        lambda: [{"id": "profile", "name": "Default"}],
        lambda: {"models": [], "profiles": [], "active_profile_id": ""},
        lambda settings, device: {
            "command_id": f"settings-{device}",
            "status": "accepted",
            "received": settings,
        },
    )
    return config, pairing, TestClient(api.app)


def test_pair_auth_bootstrap_and_command_do_not_expose_model_secret() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        commands = []
        config, pairing, client = _api(Path(folder), lambda command, profile, device: commands.append((command, profile, device)) or {"command_id": "c", "status": "accepted"})
        config.data["models"][0]["api_key"] = "test-key-must-not-leak"
        code, _ = pairing.issue_code()
        paired = client.post("/v1/pair", json={"code": code, "device_id": "app-one", "device_name": "Phone"})
        assert paired.status_code == 200
        token = paired.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        bootstrap = client.get("/v1/bootstrap", headers=headers)
        assert bootstrap.status_code == 200
        assert "test-key-must-not-leak" not in bootstrap.text
        response = client.post("/v1/commands", headers=headers, json={"command": "capture_fullscreen"})
        assert response.status_code == 202
        assert commands == [("capture_fullscreen", None, "app-one")]
        assert client.get("/v1/bootstrap").status_code == 401


def test_authenticated_settings_can_be_read_and_updated() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        _config, pairing, client = _api(
            Path(folder),
            lambda _command, _profile, _device: {
                "command_id": "c",
                "status": "accepted",
            },
        )
        code, _ = pairing.issue_code()
        token = client.post(
            "/v1/pair",
            json={"code": code, "device_id": "settings-app", "device_name": "Phone"},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/v1/settings", headers=headers).status_code == 200
        response = client.put(
            "/v1/settings",
            headers=headers,
            json={"settings": {"models": [{"name": "M"}]}},
        )
        assert response.status_code == 202
        assert response.json()["command_id"] == "settings-settings-app"


def test_busy_command_maps_to_http_409() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
        def busy(_command, _profile, _device):
            raise RuntimeError("busy")

        _config, pairing, client = _api(Path(folder), busy)
        code, _ = pairing.issue_code()
        token = client.post("/v1/pair", json={"code": code, "device_id": "app", "device_name": "Phone"}).json()["token"]
        response = client.post(
            "/v1/commands",
            headers={"Authorization": f"Bearer {token}"},
            json={"command": "submit_buffer"},
        )
        assert response.status_code == 409
