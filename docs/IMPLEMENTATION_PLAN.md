# VB Player — Implementation Plan

## Overview

This plan covers the addition of DLNA/UPnP casting support to VB Player, enabling playback to network renderers (speakers, TVs, other DLNA devices) while maintaining the existing local playback architecture unchanged.

## Architecture Decisions

1. **Single active backend** — either local GStreamer pipeline OR remote DLNA renderer, never both simultaneously
2. **Control mode only** — DLNA renderer plays from its own source; VB Player sends play/pause/stop/seek commands
3. **Embedded HTTP server** — serves local files to DLNA renderers that require HTTP URI
4. **Renderer is source of truth** — in DLNA mode, renderer state overrides local state model
5. **No async rewrite** — DLNA operations use synchronous HTTP on QThread with timeouts
6. **upnpclient** — sync UPnP library, QThread-based, no asyncio bridge needed
7. **PlaybackBackend abstraction** — LocalBackend and DLNABackend share interface, single active at a time
8. **Local as device** — "Local Playback" appears as first item in device list, unifying UI
9. **Background discovery** — DeviceRegistry runs SSDP continuously, UI observes via signals

---

## Phase 0 — PlaybackBackend Abstraction

### Deliverables

- `PlaybackBackend` abstract base class (signals: stateChanged, positionChanged, durationChanged, trackChanged, errorOccurred)
- `LocalBackend` wrapping existing AudioEngine
- `CastController` that manages active backend switching
- Wire existing PlaybackController through backend abstraction

### Implementation

```
audio_player/player/backend.py  (new file)

class PlaybackBackend(QObject):
    stateChanged = pyqtSignal(int)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    trackChanged = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def activate(self): ...
    def deactivate(self): ...
    def play(self): ...
    def pause(self): ...
    def stop(self): ...
    def seek(self, ms): ...
    def load(self, path): ...

class LocalBackend(PlaybackBackend):
    # wraps existing AudioEngine, delegates all calls
```

### Acceptance Criteria

- [ ] LocalBackend delegates to AudioEngine correctly
- [ ] All existing playback functionality works through LocalBackend
- [ ] No behavioral change from user perspective
- [ ] PlaybackController uses backend abstraction instead of direct engine calls

### Dependencies

None — refactoring only, no new features.

---

## Phase 1 — Embedded HTTP Server (MVP)

### Deliverables

- `EmbeddedHttpServer` class using `ThreadingHTTPServer`
- UUID-based stream mapping (`/stream/{uuid}`)
- HEAD + GET + Range request support
- MIME type detection from file extension
- Auto-start on application launch, auto-shutdown on exit

### Implementation

```
audio_player/player/http_server.py  (new file)

class EmbeddedHttpServer:
    __init__(host, port)
    start()                          # background thread
    stop()
    add_stream(file_path) -> str     # returns UUID
    remove_stream(uuid)
    get_url(uuid) -> str             # returns http://host:port/stream/{uuid}
```

### Acceptance Criteria

- [ ] VLC can open `http://localhost:PORT/stream/{uuid}` and play audio
- [ ] Browser can open stream URL and play audio
- [ ] HTTP Range requests work (seek in VLC)
- [ ] HEAD returns correct Content-Length and Content-Type
- [ ] Multiple simultaneous streams work
- [ ] Server shuts down cleanly on app exit

### Dependencies

None — pure Python, no new packages.

---

## Phase 2 — DLNA Discovery

### Deliverables

- SSDP discovery via UDP multicast (239.255.255.250:1900)
- MediaRenderer device filtering
- Device XML description parsing
- `DeviceRegistry` with signal-based updates

### Implementation

```
audio_player/player/dlna/
  ├── __init__.py
  ├── ssdp.py              # SSDP discovery (M-SEARCH, notify)
  ├── device.py             # DeviceDescription, ServiceDescription
  ├── registry.py           # DeviceRegistry (QThread-based)
  └── upnp.py               # UPnP SOAP client

class DeviceRegistry(QObject):
    deviceFound = pyqtSignal(dict)     # {udn, name, type, icon_url, location}
    deviceLost = pyqtSignal(str)       # udn
    start_discovery()
    stop_discovery()
    devices() -> list[dict]
```

### Acceptance Criteria

- [ ] Discovery finds renderers on local network within 5 seconds
- [ ] Device name, type, and icon URL are parsed from description XML
- [ ] Device lost events fire when renderer goes offline
- [ ] Registry survives network interruptions (retry logic)
- [ ] Only MediaRenderer devices are listed (not MediaServer)

### Dependencies

`upnpclient` — sync UPnP SOAP client (`pip install upnpclient`). SSDP discovery is stdlib UDP.

---

## Phase 3 — Playback Control

### Deliverables

- UPnP AVTransport service client
- SetAVTransportURI, Play, Pause, Stop, Seek, GetTransportInfo
- Error handling with timeout and retry

### Implementation

```
audio_player/player/dlna/
  └── avtransport.py        # AVTransport service client

class AVTransport:
    __init__(control_url, service_type)
    set_av_transport_uri(uri, metadata)    # SetAVTransportURI
    play()                                 # Play
    pause()                                # Pause
    stop()                                 # Stop
    seek(position)                         # Seek (REL_TIME)
    get_transport_info() -> dict           # GetTransportInfo
    get_position_info() -> dict            # GetPositionInfo
```

### Acceptance Criteria

- [ ] SetAVTransportURI sets the URI on the renderer
- [ ] Play/Pause/Stop commands work on real DLNA renderers
- [ ] Seek works with HH:MM:SS format
- [ ] Timeout handling (5s default) does not freeze UI
- [ ] Error responses are parsed and reported

### Dependencies

`upnpclient` (SOAP transport).

---

## Phase 4 — State Synchronization

### Deliverables

- Polling-based state sync (GetTransportInfo, GetPositionInfo)
- State reconciliation between renderer and local model
- Position tracking for seek slider

### Implementation

```
audio_player/player/dlna/
  └── state_sync.py         # StateSyncThread (QThread)

class StateSyncThread(QThread):
    stateChanged = pyqtSignal(str)       # PLAYING, PAUSED, STOPPED, etc.
    positionChanged = pyqtSignal(int)    # ms
    durationChanged = pyqtSignal(int)    # ms
    
    __init__(avtransport, poll_interval=1000)
    run()                                # polling loop
    stop()
```

### State Mapping

| DLNA TransportState | VB Player PlaybackState |
|---------------------|------------------------|
| PLAYING | Playing |
| PAUSED_PLAYBACK | Paused |
| STOPPED | Stopped |
| TRANSITIONING | (ignore, keep previous) |
| NO_MEDIA_PRESENT | Stopped |

### Acceptance Criteria

- [ ] Seek slider tracks renderer position accurately
- [ ] Play/pause state reflects renderer state in UI
- [ ] Position updates at ~1 second interval
- [ ] State changes from renderer (e.g., remote control) are reflected in UI
- [ ] No UI freezing during polling

### Dependencies

Phase 3 (AVTransport client).

---

## Phase 5 — UI Integration

### Deliverables

- Device button in transport bar
- Minimal device picker popup
- Local device always available
- Visual indicator of active output device

### Implementation

```
audio_player/ui/widgets/
  ├── device_button.py      # QPushButton with device icon + current name
  └── device_popup.py       # Minimal popup: local + discovered renderers

audio_player/ui/controllers/
  └── cast_controller.py    # CastController (PlaybackBackend ↔ DLNA bridge)
```

### CastController Responsibilities

- switch_device(renderer | None) — triggers backend switch
- Manages EmbeddedHttpServer lifecycle
- Bridges DeviceRegistry → UI
- Handles "local as device" virtual entry

### UI Behavior

```
Transport Bar:
  [prev] [play] [next] [seek slider] [volume] [mode] [📡 device]

Device Popup:
  ┌─────────────────────────────┐
  │ 🔊 Local Playback      ✓   │
  │ ─────────────────────────── │
  │ 📡 Living Room Speaker      │
  │ 📡 Bedroom TV               │
  │ 📡 Kitchen Speaker          │
  └─────────────────────────────┘
```

### Acceptance Criteria

- [ ] Device button shows current output device icon
- [ ] Popup lists all discovered DLNA renderers + local device
- [ ] Selecting local device switches back to GStreamer pipeline
- [ ] Selecting DLNA device initiates cast with current track
- [ ] Active device is highlighted in popup
- [ ] Device button pulses/animates when casting

### Dependencies

Phase 2 (discovery), Phase 3 (control), Phase 4 (state sync).

---

## Phase 6 — Settings & Device Management

### Deliverables

- Network page device manager
- Device rename
- Default device setting
- Auto-connect option

### Implementation

```
audio_player/ui/widgets/network_page.py  (extend existing)

New sections:
  - Device list with status indicators
  - Device rename dialog
  - Default device dropdown
  - Auto-connect toggle
```

### Settings Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dlna_enabled` | bool | true | Enable DLNA discovery |
| `dlna_default_device` | str | "" | UDN of default device |
| `dlna_auto_connect` | bool | false | Auto-connect to default on startup |
| `dlna_device_names` | dict | {} | Custom names {udn: name} |

### Acceptance Criteria

- [ ] Device list shows all discovered devices with status
- [ ] Devices can be renamed (persisted in settings)
- [ ] Default device can be selected
- [ ] Auto-connect triggers on app startup if default is set
- [ ] Discovery can be toggled on/off

### Dependencies

Phase 2 (discovery).

---

## Non-Goals (v1)

- ❌ No async DLNA rewrite — synchronous HTTP on QThread with timeouts
- ❌ No real-time audio streaming — control mode only, renderer plays from HTTP URI
- ❌ No AirPlay implementation (future extension)
- ❌ No Chromecast implementation (future extension)
- ❌ No transcoding — files must be in format renderer supports
- ❌ No visualizer sync in DLNA mode — no local PCM data available
- ❌ No DMR (Digital Media Renderer) — VB Player does not appear as a renderer
- ❌ No DMS (Digital Media Server) — no UPnP content directory service
- ❌ No multi-room sync — single renderer at a time
- ❌ No DLNA volume control — use renderer's own volume
- ❌ No mirror mode (local + remote simultaneous playback)
- ❌ No GENA event subscription — polling only for state sync
- ❌ No artwork/metadata XML in v1 — future `/artwork/<uuid>` endpoint

---

## File Structure (Target)

```
audio_player/
  ├── player/
  │     ├── backend.py               # Phase 0: PlaybackBackend abstraction
  │     ├── http_server.py           # Phase 1: Embedded HTTP server
  │     ├── dlna/
  │     │     ├── __init__.py
  │     │     ├── ssdp.py            # Phase 2: SSDP discovery
  │     │     ├── device.py          # Phase 2: Device description
  │     │     ├── registry.py        # Phase 2: Device registry
  │     │     ├── upnp.py            # Phase 2: UPnP SOAP client
  │     │     ├── avtransport.py     # Phase 3: AVTransport service
  │     │     └── state_sync.py      # Phase 4: State synchronization
  │     └── ... (existing files)
  ├── ui/
  │     ├── controllers/
  │     │     ├── cast_controller.py # Phase 5: Cast controller
  │     │     └── ... (existing files)
  │     ├── widgets/
  │     │     ├── device_button.py   # Phase 5: Device button
  │     │     ├── device_popup.py    # Phase 5: Device picker
  │     │     └── ... (existing files)
  │     └── ... (existing files)
  └── ... (existing files)
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| DLNA devices have inconsistent SOAP implementations | Test with multiple real devices; fallback to error messages |
| SSDP discovery unreliable on some networks | Retry logic; manual IP entry as fallback |
| HTTP server port conflicts | Auto-select available port; configurable in settings |
| Renderer state drift | Polling-based sync; renderer is source of truth |
| UI freeze during DLNA operations | Timeout on all HTTP calls (5s default); non-blocking UI |
| Large file serving performance | Streaming via file.read() chunks; no full file load |
