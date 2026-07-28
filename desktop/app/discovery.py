from __future__ import annotations

import ipaddress
import re
import socket

import psutil
from zeroconf import IPVersion, ServiceInfo, Zeroconf


SERVICE_TYPE = "_screenasst._tcp.local."


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    encoded = encoded[:maximum_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def service_instance_name(value: str) -> str:
    cleaned = "".join(
        "-" if character == "." or ord(character) < 32 else character
        for character in str(value or "").strip()
    ).strip(" -")
    return _truncate_utf8(cleaned or "Screen Assistant", 63).strip(" -") or "Screen Assistant"


def service_server_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", str(value or "").strip()).strip("-")
    return (cleaned[:63].strip("-") or "screen-assistant").lower()


def is_usable_lan_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return (
        address.version == 4
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
        and not address.is_multicast
    )


def local_ipv4_candidates() -> list[str]:
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = str(value or "").strip()
        if is_usable_lan_ipv4(normalized) and normalized not in candidates:
            candidates.append(normalized)

    interface_addresses: list[tuple[int, str]] = []
    stats = psutil.net_if_stats()
    preferred_names = ("wlan", "wi-fi", "wifi", "wireless", "无线")
    wired_names = ("ethernet", "以太网")
    virtual_names = (
        "virtual",
        "vethernet",
        "vmware",
        "virtualbox",
        "hyper-v",
        "wsl",
        "tunnel",
        "vpn",
        "tap",
        "tun",
        "loopback",
        "yeshayun",
    )
    for interface_name, addresses in psutil.net_if_addrs().items():
        interface_stats = stats.get(interface_name)
        if interface_stats is not None and not interface_stats.isup:
            continue
        lowered = interface_name.lower()
        if any(token in lowered for token in virtual_names):
            rank = 100
        elif any(token in lowered for token in preferred_names):
            rank = 0
        elif any(token in lowered for token in wired_names):
            rank = 10
        else:
            rank = 20
        for address in addresses:
            if address.family == socket.AF_INET and is_usable_lan_ipv4(address.address):
                interface_addresses.append((rank, address.address))
    for _, address in sorted(interface_addresses, key=lambda item: item[0]):
        add(address)

    # UDP connect does not send a packet, but asks Windows which adapter would
    # route to the target. Multiple targets make this useful without requiring
    # public Internet connectivity.
    for target in ("8.8.8.8", "1.1.1.1", "192.168.0.1", "10.255.255.255"):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((target, 80))
            add(str(probe.getsockname()[0]))
        except OSError:
            pass
        finally:
            probe.close()

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            add(str(item[4][0]))
    except OSError:
        pass
    return candidates


def local_ipv4(preferred: str = "") -> str:
    requested = str(preferred or "").strip()
    if requested:
        if not is_usable_lan_ipv4(requested):
            raise ValueError("手动配对地址必须是非回环 IPv4 地址")
        return requested
    candidates = local_ipv4_candidates()
    if not candidates:
        raise RuntimeError("未检测到可用的局域网 IPv4 地址")
    return candidates[0]


class DiscoveryPublisher:
    def __init__(self, device_name: str, device_id: str, port: int, address: str = "") -> None:
        self.address = local_ipv4(address)
        safe_name = service_instance_name(device_name)
        server_name = service_server_name(socket.gethostname())
        self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.info = ServiceInfo(
            SERVICE_TYPE,
            f"{safe_name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(self.address)],
            port=port,
            properties={"id": device_id, "version": "1"},
            server=f"{server_name}.local.",
        )
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.zeroconf.register_service(self.info, allow_name_change=True)
            self.started = True

    def stop(self) -> None:
        if self.started:
            self.zeroconf.unregister_service(self.info)
            self.started = False
        self.zeroconf.close()
