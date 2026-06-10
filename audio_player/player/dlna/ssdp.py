"""SSDP (Simple Service Discovery Protocol) discovery.

Sends M-SEARCH requests and listens for NOTIFY messages on UDP multicast.
Discovers UPnP MediaRenderer devices on the local network.
"""

from __future__ import annotations

import socket
import struct
import threading
import time

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_MX = 3  # max wait seconds for M-SEARCH response

# Search target for UPnP root devices
SSDP_ST_ALL = "ssdp:all"
SSDP_ST_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"

MSEARCH_TEMPLATE = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: {addr}:{port}\r\n"
    "MAN: \"ssdp:discover\"\r\n"
    "MX: {mx}\r\n"
    "ST: {st}\r\n"
    "\r\n"
)


def _parse_headers(data: str) -> dict[str, str]:
    """Parse HTTP-like headers from SSDP message."""
    headers = {}
    for line in data.split("\r\n"):
        if ":" in line and not line.startswith("HTTP/"):
            key, _, value = line.partition(":")
            headers[key.strip().upper()] = value.strip()
    return headers


def _send_msearch(st: str, mx: int = SSDP_MX) -> list[dict]:
    """Send M-SEARCH and collect responses within MX seconds."""
    results = []
    msg = MSEARCH_TEMPLATE.format(addr=SSDP_ADDR, port=SSDP_PORT, mx=mx, st=st)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(mx + 1)

    try:
        sock.sendto(msg.encode(), (SSDP_ADDR, SSDP_PORT))
        deadline = time.monotonic() + mx + 0.5

        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
                text = data.decode("utf-8", errors="replace")
                headers = _parse_headers(text)

                location = headers.get("LOCATION", "")
                if location:
                    results.append({
                        "location": location,
                        "st": headers.get("ST", ""),
                        "usn": headers.get("USN", ""),
                        "server": headers.get("SERVER", ""),
                        "from_addr": addr[0],
                    })
            except socket.timeout:
                break
    finally:
        sock.close()

    return results


def discover_renderers(timeout: int = 3) -> list[dict]:
    """Discover UPnP MediaRenderer devices on the network.

    Returns list of {location, st, usn, server, from_addr}.
    """
    return _send_msearch(SSDP_ST_RENDERER, mx=timeout)


def discover_all(timeout: int = 3) -> list[dict]:
    """Discover all UPnP devices on the network."""
    return _send_msearch(SSDP_ST_ALL, mx=timeout)


class SSDPListener:
    """Listens for SSDP NOTIFY messages (device alive/byebye).

    Runs in a background thread. Calls callbacks on device events.
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_alive: list = []
        self._on_byebye: list = []

    def on_alive(self, callback) -> None:
        self._on_alive.append(callback)

    def on_byebye(self, callback) -> None:
        self._on_byebye.append(callback)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Join SSDP multicast group
        mreq = struct.pack(
            "4sl",
            socket.inet_aton(SSDP_ADDR),
            socket.INADDR_ANY,
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.bind(("", SSDP_PORT))
        sock.settimeout(2)

        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(4096)
                text = data.decode("utf-8", errors="replace")
                headers = _parse_headers(text)

                location = headers.get("LOCATION", "")
                if not location:
                    continue

                nts = headers.get("NTS", "")
                info = {
                    "location": location,
                    "nt": headers.get("NT", ""),
                    "usn": headers.get("USN", ""),
                    "server": headers.get("SERVER", ""),
                    "from_addr": addr[0],
                }

                if nts == "ssdp:alive":
                    for cb in self._on_alive:
                        try:
                            cb(info)
                        except Exception as _e:
                            import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
                elif nts == "ssdp:byebye":
                    for cb in self._on_byebye:
                        try:
                            cb(info)
                        except Exception as _e:
                            import sys; print(f"[{__name__}] {_e}", file=sys.stderr)

            except socket.timeout:
                continue
            except Exception as e:
                import sys; print(f"[ssdp] SSDP 接收跳过: {e}", file=sys.stderr)
                continue

        sock.close()
