"""DeviceRegistry — background DLNA renderer discovery.

Runs SSDP discovery periodically and maintains a list of available
MediaRenderer devices. Emits signals when devices appear/disappear.
"""

from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from audio_player.player.dlna.ssdp import discover_renderers, SSDPListener
from audio_player.player.dlna.device import DeviceDescription, fetch_description


class DeviceRegistry(QObject):
    """Background DLNA renderer discovery registry.

    Signals:
        deviceFound(dict) — {id, name, manufacturer, model, icon_url, avtransport_url, base_url, udn}
        deviceLost(str)   — device UDN
        devicesChanged()  — any change to device list
    """

    deviceFound = pyqtSignal(dict)
    deviceLost = pyqtSignal(str)
    devicesChanged = pyqtSignal()

    FAIL_COOLDOWN = 120  # seconds to skip a failing location

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: dict[str, dict] = {}  # udn -> device_info
        self._failed: dict[str, float] = {}  # location -> last_fail_time
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._listener: SSDPListener | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start background discovery."""
        if self._thread is not None:
            return

        # SSDP multicast socket crashes on MSYS2 Python 3.14 / Windows — skip
        import sys as _sys2
        if _sys2.platform == "win32":
            return

        self._stop_event.clear()

        # Start SSDP NOTIFY listener
        self._listener = SSDPListener()
        self._listener.on_alive(self._on_notify_alive)
        self._listener.on_byebye(self._on_notify_byebye)
        self._listener.start()

        # Start periodic M-SEARCH polling
        self._thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop discovery."""
        self._stop_event.set()
        if self._listener:
            self._listener.stop()
            self._listener = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def devices(self) -> list[dict]:
        """Return list of discovered devices."""
        with self._lock:
            return list(self._devices.values())

    def get_device(self, udn: str) -> dict | None:
        """Get device info by UDN."""
        with self._lock:
            return self._devices.get(udn)

    def _discovery_loop(self) -> None:
        """Periodically send M-SEARCH requests."""
        # Initial discovery
        self._do_discovery()

        while not self._stop_event.is_set():
            # Wait 30 seconds between discoveries
            self._stop_event.wait(30)
            if self._stop_event.is_set():
                break
            self._do_discovery()

    def _do_discovery(self) -> None:
        """Send M-SEARCH and process responses."""
        try:
            results = discover_renderers(timeout=3)
        except Exception as e:
            import sys
            print(f"[dlna] SSDP discovery failed: {e}", file=sys.stderr)
            return

        seen_udns = set()

        now = time.monotonic()
        # Purge expired failure entries
        self._failed = {loc: t for loc, t in self._failed.items()
                        if now - t < self.FAIL_COOLDOWN}

        for entry in results:
            location = entry.get("location", "")
            if not location:
                continue

            # Skip recently-failing locations
            if location in self._failed:
                continue

            # Fetch device description
            desc = fetch_description(location, timeout=5)
            if desc is None:
                self._failed[location] = now
                continue

            # Must have UDN and friendly name
            if not desc.udn or not desc.friendly_name:
                continue

            # Must have AVTransport service
            if not desc.avtransport_url:
                continue

            seen_udns.add(desc.udn)

            device_info = self._make_device_info(desc)

            with self._lock:
                existing = self._devices.get(desc.udn)
                if existing is None:
                    self._devices[desc.udn] = device_info
                    self.deviceFound.emit(device_info)
                    self.devicesChanged.emit()
                elif existing.get("name") != device_info.get("name"):
                    # Update if name changed
                    self._devices[desc.udn] = device_info
                    self.devicesChanged.emit()

    def _on_notify_alive(self, info: dict) -> None:
        """Handle SSDP NOTIFY alive message."""
        location = info.get("location", "")
        nt = info.get("nt", "")

        # Only process MediaRenderer notifications
        if "MediaRenderer" not in nt and nt != "ssdp:all":
            return

        if not location:
            return

        # Skip recently-failing locations
        now = time.monotonic()
        if location in self._failed and now - self._failed[location] < self.FAIL_COOLDOWN:
            return

        desc = fetch_description(location, timeout=5)
        if desc is None:
            self._failed[location] = now
            return
        if not desc.udn or not desc.avtransport_url:
            return

        device_info = self._make_device_info(desc)

        with self._lock:
            existing = self._devices.get(desc.udn)
            if existing is None:
                self._devices[desc.udn] = device_info
                self.deviceFound.emit(device_info)
                self.devicesChanged.emit()

    def _on_notify_byebye(self, info: dict) -> None:
        """Handle SSDP NOTIFY byebye message."""
        usn = info.get("usn", "")
        if not usn:
            return

        # Extract UDN from USN (format: uuid::urn:...)
        udn = usn.split("::")[0] if "::" in usn else usn

        with self._lock:
            if udn in self._devices:
                del self._devices[udn]
                self.deviceLost.emit(udn)
                self.devicesChanged.emit()

    @staticmethod
    def _make_device_info(desc: DeviceDescription) -> dict:
        """Convert DeviceDescription to device info dict."""
        # Resolve AVTransport URL
        av_url = desc.avtransport_url
        if av_url.startswith("/") and desc.base_url:
            av_url = desc.base_url + av_url
        elif not av_url.startswith("http") and desc.base_url:
            av_url = f"{desc.base_url}/{av_url}"

        return {
            "id": desc.udn,
            "udn": desc.udn,
            "name": desc.friendly_name,
            "manufacturer": desc.manufacturer,
            "model": desc.model_name,
            "icon_url": desc.icon_url,
            "avtransport_url": av_url,
            "base_url": desc.base_url,
            "location": desc.location,
        }
