"""CastController — manages output device switching (Local ↔ DLNA).

Bridges DeviceRegistry, PlaybackBackend, and EmbeddedHttpServer.
Local playback is treated as a virtual device (always first in list).
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from audio_player.i18n import _

from audio_player.player.backend import PlaybackBackend, LocalBackend, DLNABackend
from audio_player.player.dlna.avtransport import AVTransport
from audio_player.player.dlna.state_sync import StateSyncThread


class CastController(QObject):
    """Manages output device discovery and backend switching."""

    deviceListChanged = pyqtSignal()           # device list updated
    activeDeviceChanged = pyqtSignal(str)      # device name
    switchingStarted = pyqtSignal(str)         # target device name
    switchingFinished = pyqtSignal(str)        # new device name
    switchError = pyqtSignal(str)              # error message
    backendChanged = pyqtSignal()              # active backend changed, reconnect signals

    LOCAL_DEVICE = "local"

    def __init__(self, local_backend: LocalBackend, parent=None):
        super().__init__(parent)
        self._local_backend = local_backend
        self._active_backend: PlaybackBackend = local_backend
        self._active_device_id = self.LOCAL_DEVICE
        self._devices: list[dict] = []  # [{id, name, avtransport_url, ...}]
        self._http_server = None  # set externally
        self._stream_uuid: str | None = None
        self._dlna_backend: DLNABackend | None = None
        self._state_sync: StateSyncThread | None = None

    @property
    def active_backend(self) -> PlaybackBackend:
        return self._active_backend

    @property
    def active_device_id(self) -> str:
        return self._active_device_id

    @property
    def active_device_name(self) -> str:
        if self._active_device_id == self.LOCAL_DEVICE:
            return _("device.local")
        for d in self._devices:
            if d["id"] == self._active_device_id:
                return d["name"]
        return _("device.unknown")

    @property
    def is_casting(self) -> bool:
        return self._active_device_id != self.LOCAL_DEVICE

    def devices(self) -> list[dict]:
        """Return all available devices (local + discovered renderers)."""
        local = {"id": self.LOCAL_DEVICE, "name": _("device.local"), "type": "local"}
        return [local] + list(self._devices)

    def set_http_server(self, server) -> None:
        """Set the EmbeddedHttpServer instance (from Phase 1)."""
        self._http_server = server

    def add_renderer(self, device_info: dict) -> None:
        """Add a discovered renderer to the device list."""
        if not any(d["id"] == device_info["id"] for d in self._devices):
            self._devices.append(device_info)
            self.deviceListChanged.emit()

    def remove_renderer(self, device_id: str) -> None:
        """Remove a renderer that went offline."""
        self._devices = [d for d in self._devices if d["id"] != device_id]
        if self._active_device_id == device_id:
            self.switch_to_local()
        self.deviceListChanged.emit()

    def switch_to_device(self, device_id: str, current_file: str = "") -> None:
        """Switch output to a specific device."""
        if device_id == self._active_device_id:
            return

        if device_id == self.LOCAL_DEVICE:
            self.switch_to_local()
            return

        # Find renderer
        device = next((d for d in self._devices if d["id"] == device_id), None)
        if device is None:
            self.switchError.emit(_("device.not_found", device_id=device_id))
            return

        self.switchingStarted.emit(device["name"])

        try:
            # Deactivate local backend
            self._local_backend.deactivate()

            # Create AVTransport client
            av_url = device.get("avtransport_url", "")
            if not av_url:
                raise ValueError(_("device.no_avtransport"))

            avtransport = AVTransport(av_url)

            # Create DLNA backend
            self._dlna_backend = DLNABackend(self)
            self._dlna_backend.set_avtransport(avtransport)
            self._dlna_backend.activate()

            # Start state sync polling
            self._state_sync = StateSyncThread(avtransport, poll_interval=1000, parent=self)
            self._state_sync.stateChanged.connect(self._dlna_backend.update_state)
            self._state_sync.positionChanged.connect(self._dlna_backend.update_position_pos)
            self._state_sync.durationChanged.connect(self._dlna_backend.update_position_dur)
            self._state_sync.start()

            self._active_backend = self._dlna_backend
            self._active_device_id = device_id
            self.backendChanged.emit()

            # If there's a current file, register and play it
            if current_file and self._http_server:
                self._stream_uuid = self._http_server.add_stream(current_file)
                url = self._http_server.get_url(self._stream_uuid)
                self._dlna_backend.load(url)
                self._dlna_backend.play()

            self.activeDeviceChanged.emit(device["name"])
            self.switchingFinished.emit(device["name"])

        except Exception as e:
            self.switchError.emit(str(e))
            self.switch_to_local()

    def switch_to_local(self) -> None:
        """Switch back to local playback."""
        if self._active_device_id == self.LOCAL_DEVICE:
            return

        self.switchingStarted.emit(_("device.local"))

        try:
            # Stop state sync
            if self._state_sync is not None:
                self._state_sync.stop()
                self._state_sync = None

            # Deactivate DLNA backend
            if self._dlna_backend is not None:
                self._dlna_backend.deactivate()
                self._dlna_backend = None

            # Clean up HTTP stream
            if self._stream_uuid and self._http_server:
                self._http_server.remove_stream(self._stream_uuid)
                self._stream_uuid = None

            self._active_backend = self._local_backend
            self._active_device_id = self.LOCAL_DEVICE
            self.backendChanged.emit()
            self.activeDeviceChanged.emit(_("device.local"))
            self.switchingFinished.emit(_("device.local"))

        except Exception as e:
            self.switchError.emit(str(e))
