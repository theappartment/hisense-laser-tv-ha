"""Wake-on-network helpers for Hisense VIDAA TVs."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST

from .const import CONF_MAC_ADDRESS

_LOGGER = logging.getLogger(__name__)
VIDAA_WAKE_PORT = 33129
VIDAA_WAKE_REPEAT = 5
VIDAA_WAKE_DELAY = 0.1


def configured_mac_address(entry: ConfigEntry) -> str:
    """Return the Wi-Fi MAC, preferring the value changed in options."""
    return entry.options.get(
        CONF_MAC_ADDRESS,
        entry.data.get(CONF_MAC_ADDRESS, ""),
    ).strip()


def can_wake_from_standby(entry: ConfigEntry) -> bool:
    """Return whether this entry has a valid MAC for network wake."""
    mac_address = configured_mac_address(entry)
    if not mac_address:
        return False
    try:
        _mac_address_bytes(mac_address)
    except ValueError:
        return False
    return True


def send_wake_packets_for_entry(entry: ConfigEntry) -> None:
    """Wake the configured TV using its Wi-Fi MAC and network address."""
    send_wake_packets(
        configured_mac_address(entry),
        entry.data.get(CONF_HOST),
    )


def send_wake_packets(mac_address: str, host: str | None = None) -> None:
    """Send standard WOL plus the VIDAA Android app wake packet."""
    broadcast_addresses = _wake_broadcast_addresses(host)
    last_error: Exception | None = None

    try:
        from wakeonlan import send_magic_packet
    except ImportError as err:
        last_error = err
        _LOGGER.debug("Wake-on-LAN library is not available: %s", err)
    else:
        for address in broadcast_addresses:
            for port in (9, 7):
                try:
                    send_magic_packet(mac_address, ip_address=address, port=port)
                except Exception as err:
                    last_error = err
                    _LOGGER.debug(
                        "Wake-on-LAN packet to %s:%s failed: %s",
                        address,
                        port,
                        err,
                    )

    try:
        _send_vidaa_wake_packets(mac_address, broadcast_addresses)
    except Exception as err:
        last_error = err
        _LOGGER.debug("VIDAA wake packet failed: %s", err)

    if last_error is not None:
        _LOGGER.debug("One or more wake packets failed; continuing after retries")


def _wake_broadcast_addresses(host: str | None) -> tuple[str, ...]:
    """Return broadcast targets likely to reach a sleeping VIDAA device."""
    addresses = ["255.255.255.255"]
    if host:
        try:
            ip_address = ipaddress.ip_address(host)
        except ValueError:
            ip_address = None
        if isinstance(ip_address, ipaddress.IPv4Address):
            addresses.append(str(ip_address))
            network = ipaddress.ip_network(f"{ip_address}/24", strict=False)
            addresses.append(str(network.broadcast_address))
    return tuple(dict.fromkeys(addresses))


def _send_vidaa_wake_packets(
    mac_address: str,
    broadcast_addresses: tuple[str, ...],
) -> None:
    """Send the wake packet used by the legacy VIDAA Android app."""
    mac_bytes = _mac_address_bytes(mac_address)
    payload = (b"\xff" * 6) + (mac_bytes * 16) + (b"\x00" * 6)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for address in broadcast_addresses:
            for _ in range(VIDAA_WAKE_REPEAT):
                sock.sendto(payload, (address, VIDAA_WAKE_PORT))
                time.sleep(VIDAA_WAKE_DELAY)


def _mac_address_bytes(mac_address: str) -> bytes:
    hex_digits = re.sub(r"[^0-9A-Fa-f]", "", mac_address)
    if len(hex_digits) != 12:
        raise ValueError("MAC address must contain 12 hex digits")
    return bytes.fromhex(hex_digits)
