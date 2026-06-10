# VB Player — State Machine

## Playback States

```
┌─────────────────────────────────────────────────────────────┐
│                      PlaybackState                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌───────┐    load()    ┌─────────┐    play()   ┌───────┐ │
│   │ IDLE  │─────────────→│ LOADING │────────────→│PLAYING│ │
│   │(Stop) │              │         │             │       │ │
│   └───────┘              └─────────┘             └───────┘ │
│       ↑                      │                      │      │
│       │                      │ error                │      │
│       │                      ▼                      │      │
│       │                 ┌─────────┐                  │      │
│       │                 │  ERROR  │                  │      │
│       │                 └─────────┘                  │      │
│       │                                              │      │
│       │            pause()  │      pause()           │      │
│       │                     ▼                        │      │
│       │               ┌─────────┐                    │      │
│       │               │ PAUSED  │←───────────────────┘      │
│       │               └─────────┘                           │
│       │                     │                               │
│       │                     │ stop() / EOS                  │
│       │                     ▼                               │
│       └─────────────────────┘                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## State Definitions

| State | GStreamer State | Description |
|-------|---------------|-------------|
| `IDLE` (Stopped) | `NULL` | No pipeline, no file loaded |
| `LOADING` | `PAUSED` (transient) | Pipeline building, waiting for pad link |
| `PLAYING` | `PLAYING` | Audio output active |
| `PAUSED` | `PAUSED` | Pipeline ready, no audio output |
| `ERROR` | `NULL` | Pipeline torn down after error |

## State Transitions

### IDLE → LOADING

```
Trigger:  engine.play(file)
Actions:
  1. _teardown_pipeline() if exists
  2. _build_pipeline(file) or _build_url_pipeline(url)
  3. pipeline.set_state(PAUSED)
  4. _app_state = Loading (transient)
Signals:  none (internal)
```

### LOADING → PLAYING

```
Trigger:  GStreamer ASYNC_DONE message (pipeline ready)
Actions:
  1. pipeline.set_state(PLAYING)
  2. _app_state = Playing
  3. _poll_timer.start()
Signals:  stateChanged(Playing), trackChanged(filepath)
```

### LOADING → ERROR

```
Trigger:  GStreamer error message or pipeline build failure
Actions:
  1. _teardown_pipeline()
  2. _app_state = Stopped
Signals:  errorOccurred(message), stateChanged(Stopped)
```

### PLAYING → PAUSED

```
Trigger:  engine.pause() or user action
Actions:
  1. pipeline.set_state(PAUSED)
  2. _app_state = Paused
  3. _poll_timer.stop()
Signals:  stateChanged(Paused)
```

### PAUSED → PLAYING

```
Trigger:  engine.play() or engine.toggle()
Actions:
  1. pipeline.set_state(PLAYING)
  2. _app_state = Playing
  3. _poll_timer.start()
Signals:  stateChanged(Playing)
```

### PLAYING/PAUSED → IDLE

```
Trigger:  engine.stop() or EOS (end of stream)
Actions:
  1. _teardown_pipeline()
  2. _app_state = Stopped
  3. position = 0
Signals:  stateChanged(Stopped), positionChanged(0)
          trackFinished() [EOS only]
```

## Gapless Playback State

```
┌─────────────────────────────────────────────────────────────┐
│                    Gapless Preload                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Track N (PLAYING)         Track N+1 (preloaded)           │
│       │                          │                          │
│       │  position > duration-2s  │                          │
│       ├─────────────────────────→│                          │
│       │                          │                          │
│       │  _build_preload_pipeline │                          │
│       │  pipeline.set_state(     │                          │
│       │    PAUSED)               │                          │
│       │                          │                          │
│       │  EOS                     │                          │
│       ├─────────────────────────→│                          │
│       │                          │                          │
│       │  _gapless_transition()   │                          │
│       │  swap all refs           │                          │
│       │  pipeline.set_state(     │                          │
│       │    PLAYING)              │                          │
│       │                          │                          │
└─────────────────────────────────────────────────────────────┘
```

### Preload Trigger Condition

```python
if (self._duration_ms > 0
    and self._position_ms > 0
    and self._duration_ms - self._position_ms < 2000
    and not self._preload_pipeline
    and next_track_available):
    self._build_preload_pipeline(next_file)
```

### Gapless Transition

```
Trigger:  EOS message while preload exists
Actions:
  1. old_pipeline.set_state(NULL)
  2. Swap refs: _pipeline = _preload_pipeline
  3. Swap all element refs (volume, eq, sink, etc.)
  4. Update _current_file, _source_is_dsd, etc.
  5. Clear preload refs
  6. Emit trackChanged, positionChanged(0), durationChanged(new_dur)
```

## Exclusive Mode Transition

```
┌─────────────────────────────────────────────────────────────┐
│                 Exclusive Mode Toggle                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   shared (autoaudiosink)    exclusive (alsink/wasapi/asiosink)│
│         │                          │                        │
│         │  engine.exclusive_mode = True                     │
│         ├─────────────────────────→│                        │
│         │                          │                        │
│         │  1. Save position        │                        │
│         │  2. _teardown_pipeline() │                        │
│         │  3. _exclusive_mode = True                        │
│         │  4. _build_pipeline()    │                        │
│         │  5. Restore position     │                        │
│         │  6. Resume state         │                        │
│         │                          │                        │
│         │  engine.exclusive_mode = False                    │
│         │←─────────────────────────┤                        │
│         │                          │                        │
└─────────────────────────────────────────────────────────────┘
```

## ReplayGain Toggle

```
Trigger:  engine.replaygain_enabled = True/False
Actions:
  1. Save position + playback state
  2. _build_pipeline() (with/without rgvolume element)
  3. Restore state (PLAYING or PAUSED)
  4. Restore position
```

## DSD Mode Transition (Windows only)

```
Trigger:  engine.dsd_mode = "pcm" | "native" | "dop"
Condition: _source_is_dsd == True
Actions:
  1. Save position
  2. _build_pipeline() selects DSD pipeline variant
  3. Restore position
```

## UI State Synchronization

```
Engine Signal              UI Target                    Action
─────────────────────────────────────────────────────────────────
stateChanged(Playing)  → TransportBar                   set_playing(True)
                       → SpectrumWidget                  start_animation()
                       → Mpris2Service                   update_state("Playing")
                       → SystemTray                      update_icon(playing)

stateChanged(Paused)   → TransportBar                   set_playing(False)
                       → SpectrumWidget                  stop_animation()
                       → Mpris2Service                   update_state("Paused")

stateChanged(Stopped)  → TransportBar                   set_playing(False)
                       → SeekSlider                      set_position(0)
                       → SpectrumWidget                  clear()
                       → Mpris2Service                   update_state("Stopped")

positionChanged(ms)    → SeekSlider                      set_position(ms)
                       → Mpris2Service                   update_position(ms)
                       → GaplessCheck                    check_preload()

durationChanged(ms)    → SeekSlider                      set_duration(ms)
                       → Mpris2Service                   update_duration(ms)

trackChanged(file)     → MetadataPanel                   update(tags)
                       → LyricsFetcher                   fetch(file)
                       → AlbumView                       highlight(track)
                       → Mpris2Service                   update_metadata()

volumeChanged(v)       → VolumeControl                   set_value(v)
                       → Mpris2Service                   update_volume(v)

errorOccurred(msg)     → Sidebar                         append_log(msg)
                       → QMessageBox                     show_error(msg)
```

## State Invariants

1. **Only one pipeline active** — `_pipeline` is either `None` or a single live pipeline
2. **State matches GStreamer** — `_app_state` always reflects actual GStreamer pipeline state
3. **Position valid only in PLAYING/PAUSED** — position is 0 in IDLE/ERROR
4. **Duration valid only after metadata parsed** — duration is 0 until `durationChanged` emitted
5. **Preload exists only in PLAYING** — preload pipeline is cleaned up on pause/stop
6. **Exclusive mode triggers rebuild** — no hot-swap; full pipeline reconstruction
7. **ReplayGain triggers rebuild** — no hot-swap; full pipeline reconstruction

---

## Backend Switching (Local ↔ DLNA)

### State Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Backend Switching                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────┐                    ┌─────────────┐             │
│   │ Local Active │                    │ DLNA Active  │             │
│   │ (GStreamer)  │                    │ (Renderer)   │             │
│   └──────┬──────┘                    └──────┬──────┘             │
│          │                                   │                   │
│          │ switch_to_dlna(renderer)          │                   │
│          │  1. local.deactivate()            │                   │
│          │  2. engine.stop()                 │                   │
│          │  3. http_server.add_stream()      │                   │
│          │  4. renderer.play(url)            │                   │
│          │  5. state_sync.start()            │                   │
│          ├──────────────────────────────────→│                   │
│          │                                   │                   │
│          │                                   │ switch_to_local() │
│          │                                   │  1. renderer.stop()│
│          │                                   │  2. state_sync.stop()│
│          │                                   │  3. http_server.remove()│
│          │                                   │  4. local.activate()│
│          │←──────────────────────────────────┤                   │
│          │                                   │                   │
│   ┌──────┴──────┐                    ┌──────┴──────┐             │
│   │ Switching   │                    │ Switching   │             │
│   │ (Local→DLNA)│                    │ (DLNA→Local)│             │
│   └─────────────┘                    └─────────────┘             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Local → DLNA Switch

```
Trigger:  user selects renderer in device popup
Condition: renderer is online
Actions:
  1. LocalBackend.deactivate()
     - engine.stop()
     - pipeline teardown (NULL state)
  2. EmbeddedHttpServer.add_stream(current_file) → uuid
  3. url = http_server.get_url(uuid)
  4. DlnaRenderer.play(url)
     - SetAVTransportURI(url, metadata_xml)
     - Play()
  5. StateSyncThread.start(renderer, poll_interval=1000ms)
  6. _active_backend = dlna_backend
Signals:  outputDeviceChanged(renderer_name)
          stateChanged → UI follows renderer state
```

### DLNA → Local Switch

```
Trigger:  user selects "Local Playback" in device popup
Actions:
  1. DlnaRenderer.stop()
  2. StateSyncThread.stop()
  3. EmbeddedHttpServer.remove_stream(uuid)
  4. LocalBackend.activate()
     - engine.load(previous_file)
     - engine.play() [if was playing]
  5. _active_backend = local_backend
Signals:  outputDeviceChanged("local")
          stateChanged → UI follows engine state
```

### DLNA Renderer State Sync

```
Source:  StateSyncThread polling GetTransportInfo + GetPositionInfo
Interval: 1000ms (configurable)

DLNA TransportState → PlaybackState:
  PLAYING           → Playing
  PAUSED_PLAYBACK   → Paused
  STOPPED           → Stopped
  TRANSITIONING     → (ignore, keep previous)
  NO_MEDIA_PRESENT  → Stopped

Position: renderer track position (ms)
Duration: renderer track duration (ms)
```

### Backend Invariants

1. **Only one backend active** — `_active_backend` is either local or DLNA, never both
2. **Renderer is state source in DLNA mode** — local engine state is irrelevant
3. **Local engine fully stopped in DLNA mode** — no paused pipeline, no resource hold
4. **HTTP stream lifecycle tied to DLNA session** — add on switch to DLNA, remove on switch back
5. **Visualizer disabled in DLNA mode** — no local PCM data available
6. **Switching is blocking** — UI shows "Switching..." indicator during transition
