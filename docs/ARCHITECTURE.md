# VB Player — Architecture

## System Overview

```
MainWindow (orchestrator)
  ├── PlaybackController
  │     ├── LocalBackend → AudioEngine (GStreamer pipeline)
  │     └── DLNABackend → DlnaRenderer + EmbeddedHttpServer
  ├── PlaylistManager (track list + shuffle/repeat)
  ├── LibraryManager (favorites, playlists, watch folders, album cache)
  ├── EqualizerManager (10-band parametric EQ)
  ├── AudioAnalyzer (QThread: decode → waveform + spectrum)
  ├── LyricsFetcher (online lyrics via LRCLIB)
  ├── DeviceRegistry (background SSDP discovery)
  ├── Controllers
  │     ├── PlaybackController (backend ↔ playlist bridge)
  │     ├── LibraryController (favorites/playlists CRUD)
  │     ├── SettingsController (theme/EQ/exclusive mode)
  │     ├── NetworkController (SMB scanning, stream history)
  │     └── CastController (DLNA device switching)
  ├── System Media Services
  │     ├── Mpris2Service (Linux D-Bus)
  │     ├── SmtcService (Windows)
  │     └── MacOSSMediaService (macOS)
  └── UI Widgets
        ├── TransportBar, SeekSlider, VolumeControl, PlaybackModeControl
        ├── DeviceButton, DevicePopup (output device switching)
        ├── PlaylistView, AlbumGridView, AlbumDetailPage
        ├── SpectrumWidget, WaveformWidget, LyricsOverlay
        ├── MetadataPanel, OutputSpecBar
        ├── Sidebar, NetworkPage (device management)
        └── FullscreenLyricsWindow
```

## Core Principles

1. **Single active backend** — one PlaybackBackend active at a time (Local or DLNA), never both
2. **Engine owns pipeline lifecycle** — build, teardown, state transitions are engine-internal
3. **Signals drive UI** — engine emits state/position/metadata signals; UI reacts, never polls
4. **Platform dispatch at import time** — `player/__init__.py` selects engine subclass based on `sys.platform`
5. **Template method pattern** — base engine implements all logic; subclasses override `_create_sink()`, `_default_exclusive_device()`, `_output_info_dict()`
6. **Controller pattern** — MainWindow orchestrates; controllers handle domain-specific wiring
7. **No async in core playback path** — GStreamer handles async internally; Python side is synchronous Qt event loop
8. **Renderer is source of truth** — in DLNA mode, renderer state/position overrides local model
9. **Control mode only for remote** — DLNA renderer plays from HTTP URI; VB Player sends commands, does not stream PCM

## Data Flow

```
User Input
    │
    ▼
MainWindow / Controller
    │
    ▼
AudioEngine.play(file)
    │
    ▼
_build_pipeline(file)  ──→  GStreamer pipeline
    │                           │
    │                           ▼
    │                    decodebin → queue → convert → resample → volume → EQ → sink
    │                           │
    ▼                           ▼
_stateChanged ←─────── bus messages (EOS, error, state-change)
    │
    ▼
UI Update (TransportBar, SpectrumWidget, LyricsOverlay, etc.)
```

## Engine Architecture

### Class Hierarchy

```
_BaseAudioEngine (QObject)          # engine_base.py — 878 lines
  ├── AudioEngine (Linux)           # engine_linux.py — ALSA/autoaudiosink
  ├── AudioEngine (Windows)         # engine_windows.py — WASAPI/ASIO/DSD
  └── AudioEngine (macOS)           # engine_macos.py — CoreAudio
```

### Pipeline Variants

| Variant | Use Case | Chain |
|---------|----------|-------|
| Standard PCM | Local files | filesrc → decodebin → queue → convert → resample → [rgvolume] → volume → EQ → convert → resample → sink |
| URL/Stream | HTTP/HLS/ICY | playbin (self-contained) |
| DSD Passthrough | Windows native DSD | filesrc → avdemux_dsf → dsdconvert → queue → sink |
| DSD-to-PCM | Windows DSD soft-decode | filesrc → avdemux_dsf → avdec_dsd_msbf → capsfilter → resample → convert → volume → EQ → convert → resample → sink |
| DSD FFmpeg Fallback | Windows DSD via ffmpeg | appsrc → queue → convert → resample → volume → EQ → convert → resample → sink |

### Gapless Playback

```
Track N playing          Track N+1 preloaded
    │                         │
    ▼                         ▼
_pipeline (PLAYING)      _preload_pipeline (PAUSED)
    │                         │
    └──── EOS ───────────────►│
                              ▼
                     _gapless_transition()
                     swap refs, start PLAYING
```

## Playback Backend Abstraction

```
PlaybackBackend (abstract)
  ├── LocalBackend (GStreamer engine)
  └── DLNABackend (UPnP control + HTTP serving)

PlaybackController
  └── _active_backend: PlaybackBackend   # single source of truth
```

### Backend Lifecycle

```
Local → DLNA:
  1. LocalBackend.deactivate() → engine.stop(), pipeline teardown
  2. DLNABackend.activate() → register HTTP stream, SetAVTransportURI, Play

DLNA → Local:
  1. DLNABackend.deactivate() → Stop renderer, unregister stream
  2. LocalBackend.activate() → engine.load(file), engine.play()
```

### Backend Signals (shared interface)

| Signal | Description |
|--------|-------------|
| `stateChanged(int)` | PlaybackState (Playing/Paused/Stopped) |
| `positionChanged(int)` | Position in ms |
| `durationChanged(int)` | Duration in ms |
| `trackChanged(str)` | Current track path/URI |
| `errorOccurred(str)` | Error message |

## DLNA Output Subsystem

### Architecture

```
DeviceRegistry (QThread, background SSDP discovery)
  └── devices: list[RemoteOutputDevice]
        └── DlnaRenderer (UPnP AVTransport control)

EmbeddedHttpServer (ThreadingHTTPServer, background thread)
  └── /stream/<uuid> → file bytes (HEAD + GET + Range)

CastController (bridges PlaybackController ↔ DLNA)
  └── switch_device(renderer | None)
```

### Data Flow (DLNA mode)

```
User selects renderer in device popup
    │
    ▼
CastController.switch_device(renderer)
    │
    ├─ LocalBackend.deactivate() → engine.stop()
    │
    ├─ EmbeddedHttpServer.add_stream(file) → uuid → url
    │
    ├─ DlnaRenderer.play(url)
    │     └─ SetAVTransportURI(url) → Play()
    │
    └─ StateSyncThread.start() → polling GetPositionInfo/GetTransportInfo
           │
           ├─ stateChanged → UI updates
           ├─ positionChanged → seek slider
           └─ durationChanged → duration display
```

### HTTP Server Design

- `ThreadingHTTPServer` on random port, auto-select LAN IPv4
- UUID-based stream mapping (no real file paths exposed)
- HEAD + GET + Range (206 Partial Content)
- MIME from extension (audio/mpeg, audio/flac, audio/wav, audio/mp4, audio/aac)
- File direct output (no transcoding)
- Future: `/artwork/<uuid>` endpoint

### Device Registry

- Background SSDP discovery (M-SEARCH + NOTIFY)
- MediaRenderer filter only (`urn:schemas-upnp-org:device:MediaRenderer:1`)
- Signal-based: `deviceFound(dict)`, `deviceLost(str)`
- Survives network interruptions (retry logic)
- Local playback treated as a virtual device (always first in list)

## Device System

### Platform Device Enumeration

| Platform | Method | Returns |
|----------|--------|---------|
| Linux | `/proc/asound/cards` + `/sys/class/sound/` | ALSA hardware devices |
| Windows | `Gst.DeviceMonitor` | WASAPI + ASIO devices |
| macOS | `Gst.DeviceMonitor` | CoreAudio devices |

### Exclusive Mode

```
shared (autoaudiosink)  ←→  exclusive (alsasink/wasapi2sink/asiosink/osxaudiosink)
         │                              │
         └──── toggle triggers ─────────┘
              pipeline rebuild
              position preserved
```

## UI Architecture

### Page System

```
_content_stack (QStackedWidget)
  ├── 0: All Songs (PlaylistView + search/filter)
  ├── 1: Albums (AlbumGridView, grid/list toggle)
  ├── 2: Audio Management (import, stats)
  ├── 3: Album Detail (inline)
  ├── 4: Favorites
  ├── 5: Playlists (PlaylistGridView)
  ├── 6: Playlist Detail (inline)
  └── 7: Network (stream URL + SMB browser)
```

### Output Device UI

| Location | Purpose | Content |
|----------|---------|---------|
| Transport bar | Quick switch | Device button (📡 + current name), minimal popup |
| Network page | Device management | Default device, auto-connect, rename, diagnostics |
| Settings | Local audio config | ALSA/PipeWire/exclusive — not DLNA |

Transport bar popup:
```
📡 客厅功放
─────────────
✓ 本地播放
  客厅功放
  卧室音箱
─────────────
管理设备…
```

### Signal Wiring Pattern

```
Engine.stateChanged ──→ PlaybackController ──→ TransportBar.set_playing()
                   ──→ Mpris2Service.update_state()
                   ──→ SpectrumWidget.on_state_changed()

Engine.positionChanged ──→ PlaybackController ──→ SeekSlider.set_position()
                       ──→ Mpris2Service.update_position()

Engine.trackChanged ──→ PlaybackController ──→ MetadataPanel.update()
                    ──→ LyricsFetcher.fetch()
                    ──→ Mpris2Service.update_metadata()
```

## Persistence

| Data | Storage | Format |
|------|---------|--------|
| Settings | QSettings | INI (`~/.config/VBPlayer/VB Player.conf`) |
| Favorites | `LibraryManager` | JSON (`~/.config/VBPlayer/favorites.json`) |
| Playlists | `LibraryManager` | JSON (`~/.config/VBPlayer/playlists.json`) |
| Album cache | `LibraryManager` | JSON (`~/.config/VBPlayer/album_cache.json`) |
| Watch folders | `LibraryManager` | JSON (`~/.config/VBPlayer/watch_folders.json`) |
| Stream history | `NetworkController` | JSON |
| DLNA settings | `QSettings` | INI (default_device, auto_connect, device_names) |

## File Structure

```
audio_player/
  ├── player/
  │     ├── _types.py              # PlaybackState enum
  │     ├── engine_base.py         # _BaseAudioEngine (pipeline lifecycle)
  │     ├── engine_linux.py        # Linux ALSA engine
  │     ├── engine_windows.py      # Windows WASAPI/ASIO/DSD engine
  │     ├── engine_macos.py        # macOS CoreAudio engine
  │     ├── engine.py              # Platform dispatch
  │     ├── playlist.py            # PlaylistManager
  │     ├── library.py             # LibraryManager (JSON persistence)
  │     ├── metadata.py            # Tag read/write (mutagen)
  │     ├── album_manager.py       # Album grouping
  │     ├── equalizer.py           # EqualizerManager
  │     ├── audio_analyzer.py      # Waveform/spectrum analysis
  │     ├── lyrics_fetcher.py      # Online lyrics
  │     ├── lrc_parser.py          # LRC file parser
  │     ├── smb_scanner.py         # SMB share scanning
  │     ├── http_server.py         # Embedded HTTP server (DLNA serving)
  │     ├── dlna/
  │     │     ├── __init__.py
  │     │     ├── ssdp.py          # SSDP discovery
  │     │     ├── device.py        # Device description parsing
  │     │     ├── registry.py      # DeviceRegistry (QThread)
  │     │     ├── upnp.py          # UPnP SOAP client
  │     │     ├── avtransport.py   # AVTransport service
  │     │     └── state_sync.py    # State synchronization polling
  │     ├── mpris2.py              # Linux MPRIS2
  │     ├── smtc.py                # Windows SMTC
  │     └── macos_media.py         # macOS Now Playing
  ├── ui/
  │     ├── controllers/
  │     │     ├── playback_controller.py
  │     │     ├── library_controller.py
  │     │     ├── settings_controller.py
  │     │     ├── network_controller.py
  │     │     └── cast_controller.py   # DLNA cast bridge
  │     ├── widgets/
  │     │     ├── transport_bar.py
  │     │     ├── seek_slider.py
  │     │     ├── volume_control.py
  │     │     ├── playback_mode.py
  │     │     ├── playlist_view.py
  │     │     ├── album_view.py
  │     │     ├── playlist_browse.py
  │     │     ├── spectrum.py
  │     │     ├── waveform.py
  │     │     ├── lyrics_overlay.py
  │     │     ├── fullscreen_lyrics.py
  │     │     ├── metadata_panel.py
  │     │     ├── output_spec_bar.py
  │     │     ├── sidebar.py
  │     │     ├── network_page.py
  │     │     ├── device_button.py     # Transport bar device button
  │     │     ├── device_popup.py      # Device picker popup
  │     │     ├── equalizer_widget.py
  │     │     ├── search_filter.py
  │     │     ├── tag_editor_dialog.py
  │     │     └── animated_stack.py
  │     └── settings_dialog.py
  ├── app.py                       # QApplication, theme system
  ├── i18n.py                      # 4-language translations
  └── main_window.py               # MainWindow (orchestrator)
```
