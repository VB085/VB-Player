# VB Player — Domain Context

## What this is

VB Player is a PyQt6 desktop audio player with immersive visualization, frameless window, and album management. Built on GStreamer (via Qt Multimedia) for audio playback.

## Architecture

```
audio_player/
├── app.py              — QApplication setup, theme injection, accent system
├── main_window.py      — MainWindow orchestrator, _TitleBar, all signal wiring
├── player/
│   ├── engine.py       — AudioEngine: QMediaPlayer wrapper, play/pause/seek/toggle
│   ├── engine_linux.py — Linux-specific engine (GStreamer pipeline)
│   ├── engine_windows.py — Windows-specific engine (WASAPI/DSound)
│   ├── engine_macos.py   — macOS-specific engine (CoreAudio)
│   ├── engine_base.py    — Shared engine interface
│   ├── playlist.py     — PlaylistManager: QAbstractListModel, file/folder loading
│   ├── metadata.py     — read_metadata() → TrackMetadata, mutagen + WAV fallback
│   ├── album_manager.py — AlbumManager.group_by_album(), AlbumInfo dataclass
│   ├── audio_analyzer.py — QThread worker: waveform FFT, spectrum, LRC/embedded lyrics
│   └── equalizer.py    — EqualizerManager: 10-band parametric EQ
├── ui/
│   ├── settings_dialog.py — SettingsDialog: QListWidget+QStackedWidget nav
│   ├── animations.py     — Animation helpers
│   └── widgets/
│       ├── transport_bar.py — TransportBar: play/pause/prev/next buttons
│       ├── seek_slider.py   — SeekSlider with accent coloring
│       ├── volume_control.py — VolumeControl with mute toggle
│       ├── playlist_view.py  — PlaylistView: QListView on PlaylistManager model
│       ├── spectrum.py       — SpectrumWidget: bars/line/circular viz + lyrics overlay
│       ├── waveform.py       — WaveformWidget: waveform display with seek
│       ├── lyrics_overlay.py — LyricsOverlay: LRC scrolling + untimed text
│       ├── sidebar.py        — Sidebar: collapsible left nav panel
│       ├── slide_panel.py    — DEPRECATED, replaced by sidebar.py
│       ├── album_view.py     — AlbumGridView, AlbumCardWidget, AlbumDetailDialog
│       ├── metadata_panel.py — MetadataPanel: track info display
│       ├── equalizer_widget.py — EqualizerWidget: 10-band EQ sliders
│       └── fullscreen_lyrics.py — Fullscreen lyrics display
└── ui/themes/
    ├── dark_purple.qss  — Dark theme (pure black + accent)
    └── light.qss        — Light theme (pure white + accent)
```

## Glossary

| Term | Meaning |
|------|---------|
| **Accent** | User-chosen highlight color (purple/blue/green/orange/pink/red), injected into QSS at runtime |
| **Engine** | `AudioEngine` — wraps QMediaPlayer, owns playback state, emits signals |
| **Playlist** | `PlaylistManager` — ordered list of file paths, drives the QListView |
| **TrackMetadata** | Dataclass from `read_metadata()`: title, artist, album, cover, duration, etc. |
| **AlbumInfo** | Grouped album: name, artist, cover, tracks list, year, disc_count |
| **Spectrum** | `SpectrumWidget` — FFT visualization, also hosts lyrics overlay |
| **LyricsOverlay** | `LyricsOverlay` — renders scrolling LRC or static text over spectrum |
| **TransportBar** | Bottom play/pause/prev/next control bar |
| **Sidebar** | Left collapsible nav: songs/albums/manage/settings |
| **SlidePanel** | DEPRECATED — right-side overlay panel, replaced by Sidebar |
| **Analyzer** | `AudioAnalyzer` — QThread that decodes audio via gst-launch, computes waveform+spectrum, loads lyrics |
| **EQ** | `EqualizerManager` — parametric equalizer with presets |
| **QSS** | Qt Style Sheets — theme files, accent hex codes replaced at runtime |
| **Frameless** | `Qt.WindowType.FramelessWindowHint` — custom title bar + edge resize via `windowHandle().startSystemResize()` |
| **Mutagen** | Python library for reading audio metadata (ID3, Vorbis, MP4 tags) |
| **LRC** | Lyrics file format with `[mm:ss.xx]` timestamps per line |

## Key signals

- `AudioEngine.stateChanged(int)` → `TransportBar.set_playing(bool)`
- `AudioEngine.positionChanged(int)` → `SeekSlider`, `WaveformWidget`, `LyricsOverlay`
- `AudioEngine.trackChanged(str)` → `MetadataPanel.show_metadata()`, `AudioAnalyzer.analyze()`
- `AudioAnalyzer.lyricsReady(list)` → `SpectrumWidget.set_lyrics()`
- `Sidebar.navChanged(str)` → `QStackedWidget.setCurrentIndex()`
- `AlbumGridView.albumClicked(AlbumInfo)` → `AlbumDetailDialog.exec()`

## Theme system

QSS files use hardcoded accent hex `#7c3aed` (dark) / `#007AFF` (light). At runtime, `apply_theme()` replaces these with the user's chosen accent. All widgets also read accent from `QSettings` for inline styles.

## Settings persistence

`QSettings("VBPlayer", "VB Player")` — keys: `theme_mode`, `accent`, `viz_mode`, `lyrics_enabled`, `default_volume`, `border_radius`
