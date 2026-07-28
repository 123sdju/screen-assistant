from __future__ import annotations

import sys

from fastapi import FastAPI

from app.gateway import GatewayServer


class _ApiStub:
    app = FastAPI()


def test_gateway_server_configures_without_console_streams(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    gateway = GatewayServer(_ApiStub(), "127.0.0.1", 18765)

    assert gateway.config.log_config is None
    assert gateway.config.access_log is False
