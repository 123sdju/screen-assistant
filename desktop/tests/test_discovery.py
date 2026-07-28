from __future__ import annotations

from unittest.mock import patch

import pytest
from zeroconf import ServiceInfo

from app.discovery import (
    SERVICE_TYPE,
    is_usable_lan_ipv4,
    local_ipv4,
    service_instance_name,
    service_server_name,
)


def test_rejects_loopback_and_unspecified_pairing_addresses() -> None:
    assert not is_usable_lan_ipv4("127.0.0.1")
    assert not is_usable_lan_ipv4("0.0.0.0")
    assert not is_usable_lan_ipv4("169.254.1.2")
    assert is_usable_lan_ipv4("192.168.1.20")


def test_prefers_manual_address_and_never_falls_back_to_loopback() -> None:
    assert local_ipv4("192.168.50.8") == "192.168.50.8"
    with pytest.raises(ValueError):
        local_ipv4("127.0.0.1")
    with patch("app.discovery.local_ipv4_candidates", return_value=[]):
        with pytest.raises(RuntimeError):
            local_ipv4()


def test_mdns_service_type_and_names_are_valid_and_bounded() -> None:
    assert SERVICE_TYPE == "_screenasst._tcp.local."
    assert len("screenasst".encode("utf-8")) <= 15
    for raw_name in ("", "电脑.阅读器", "超长名称" * 30):
        instance = service_instance_name(raw_name)
        assert instance
        assert "." not in instance
        assert len(instance.encode("utf-8")) <= 63
        info = ServiceInfo(
            SERVICE_TYPE,
            f"{instance}.{SERVICE_TYPE}",
            addresses=[b"\xc0\xa8\x01\x08"],
            port=18765,
            server=f"{service_server_name(raw_name)}.local.",
        )
        assert info.port == 18765


def test_mdns_server_name_removes_special_characters() -> None:
    server = service_server_name("电脑 name.with_symbols!" * 10)
    assert server
    assert len(server.encode("ascii")) <= 63
    assert all(character.isalnum() or character == "-" for character in server)
