import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QMessageBox,
    QLabel, QFrame, QPushButton, QApplication, QStyle, QSizePolicy,
    QSplitter
)
from PyQt6.QtCore import Qt, QSize, QTimer, QPoint, QSettings, QEvent
from PyQt6.QtGui import (QKeySequence, QShortcut, QFont,
                         QDragEnterEvent, QDropEvent, QMouseEvent, QColor,
                         QRegion, QPixmap,
                         QPainterPath, QPainter, QPen, QBrush, QPalette)
from PyQt6.QtCore import QRectF

from audio_player.app import apply_theme, current_accent, current_theme_mode
from audio_player.player.engine import AudioEngine, PlaybackState
from audio_player.player.playlist import PlaylistManager
from audio_player.player.metadata import read_metadata
from audio_player.player.audio_analyzer import AudioAnalyzer
from audio_player.player.equalizer import EqualizerManager

from audio_player.ui.widgets.transport_bar import TransportBar
from audio_player.ui.widgets.seek_slider import SeekSlider
from audio_player.ui.widgets.output_spec_bar import OutputSpecBar
from audio_player.ui.widgets.volume_control import VolumeControl
from audio_player.ui.widgets.playlist_view import PlaylistView
from audio_player.ui.widgets.spectrum import SpectrumWidget, SpectrumMode
from audio_player.ui.widgets.waveform import WaveformWidget
from audio_player.ui.widgets.metadata_panel import MetadataPanel
from audio_player.ui.widgets.sidebar import Sidebar
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _, set_language, languageChanged
from audio_player.ui.widgets.album_view import AlbumGridView, AlbumDetailPage
from audio_player.ui.widgets.fullscreen_lyrics import FullscreenLyricsWindow
from audio_player.ui.settings_dialog import SettingsDialog, _CloseButton

EDGE_MARGIN = 6


class _TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(0)

        title = QLabel("VB Player")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        for name, icon, obj in [("minBtn", "─", "minBtn"),
                                ("maxBtn", "□", "maxBtn")]:
            btn = QPushButton(icon)
            btn.setObjectName(obj)
            btn.setFixedSize(36, 24)
            btn.clicked.connect(
                lambda checked, n=name: self._on_btn(n))
            layout.addWidget(btn)

        close_btn = _CloseButton()
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(lambda: self.window().close())
        layout.addWidget(close_btn)

    def _on_btn(self, name):
        w = self.window()
        if name == "minBtn":
            w.showMinimized()
        elif name == "maxBtn":
            if w.isMaximized():
                w.showNormal()
            else:
                w.showMaximized()
        elif name == "closeBtn":
            w.close()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            wh = self.window().windowHandle()
            if wh:
                wh.startSystemMove()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VB Player")
        self.setMinimumSize(900, 580)
        self.resize(1200, 720)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)

        self._border_radius = 12
        self._ui_radius = 12
        self._mask_dirty = True
        self._engine = AudioEngine(self)
        self._playlist = PlaylistManager(self)
        self._equalizer_mgr = EqualizerManager(self)
        self._analyzer = AudioAnalyzer(self)
        self._album_view = AlbumGridView(self._playlist)

        self._setup_ui()
        self._connect_signals()
        self._connect_analyzer()

        # Fullscreen lyrics window
        self._fullscreen_lyrics = FullscreenLyricsWindow()
        self._spectrum.lyrics_overlay.fullscreenRequested.connect(self._show_fullscreen_lyrics)
        self._setup_shortcuts()
        self._restore_settings()

        # Set initial theme state on widgets that track it explicitly
        is_light = current_theme_mode() == "light"
        self._sidebar.refresh_theme_mode(is_light)
        self._album_view.refresh_theme_mode(is_light)
        self._output_spec_bar.refresh_theme_mode(is_light)

        # React to language changes
        languageChanged.connect(self._refresh_language)

    # ================================================================
    #  UI Setup
    # ================================================================

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Custom title bar
        self._title_bar = _TitleBar(self)
        root.addWidget(self._title_bar)

        # --- Main content ---
        self._body = QWidget()
        root.addWidget(self._body, 1)

        # ===== LEFT SIDEBAR =====
        self._sidebar = Sidebar()
        self._sidebar.navChanged.connect(self._on_sidebar_nav)
        self._sidebar.reloadAlbums.connect(self._reload_albums)
        self._sidebar.widthToggled.connect(self._on_sidebar_width_toggled)

        # ===== CENTER: stacked content pages =====
        self._content_stack = AnimatedStackedWidget()
        self._content_stack.setMinimumWidth(260)

        # Page 0: Playlist view
        playlist_page = QWidget()
        playlist_page.setObjectName("playlistPage")
        pl_layout = QVBoxLayout(playlist_page)
        pl_layout.setContentsMargins(0, 0, 0, 0)
        pl_layout.setSpacing(0)
        pl_header = QHBoxLayout()
        pl_header.setContentsMargins(8, 8, 8, 4)
        self._pl_label = QLabel(_("page.all_songs"))
        self._pl_label.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:bold;letter-spacing:2px;")
        pl_header.addWidget(self._pl_label)
        pl_header.addStretch()
        pl_layout.addLayout(pl_header)
        self._playlist_view = PlaylistView()
        self._playlist_view.setModel(self._playlist)
        self._playlist_view.trackDoubleClicked.connect(self._play_track_at)
        self._playlist_view.tracksDropped.connect(self._load_paths)
        pl_layout.addWidget(self._playlist_view, 1)
        self._content_stack.addWidget(playlist_page)  # index 0

        # Page 1: Album grid
        album_page = QWidget()
        album_page.setObjectName("albumPage")
        album_layout = QVBoxLayout(album_page)
        album_layout.setContentsMargins(0, 0, 0, 0)
        album_layout.setSpacing(0)
        album_header = QHBoxLayout()
        album_header.setContentsMargins(8, 8, 8, 4)
        self._album_lbl = QLabel(_("page.albums"))
        self._album_lbl.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:bold;letter-spacing:2px;")
        album_header.addWidget(self._album_lbl)
        album_header.addSpacing(8)
        # Grid/list toggle
        self._album_view_btn = QPushButton("◧")
        self._album_view_btn.setFixedSize(28, 22)
        self._album_view_btn.setToolTip(_("album.view_toggle_grid"))
        self._album_view_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.06);color:#94a3b8;border:none;"
            "border-radius:3px;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);color:#e2e8f0;}"
        )
        self._album_view_btn.clicked.connect(self._toggle_album_view_mode)
        album_header.addWidget(self._album_view_btn)
        album_header.addStretch()
        album_layout.addLayout(album_header)
        album_layout.addWidget(self._album_view, 1)
        self._content_stack.addWidget(album_page)  # index 1

        # Page 2: Audio management
        manage_page = self._build_manage_page()
        self._content_stack.addWidget(manage_page)  # index 2

        # Page 3: Album detail (inline)
        self._album_detail_page = AlbumDetailPage()
        self._album_detail_page.backRequested.connect(lambda: self._content_stack.setCurrentIndex(1))
        self._album_detail_page.trackDoubleClicked.connect(self._play_track_at)
        self._content_stack.addWidget(self._album_detail_page)  # index 3

        # ===== RIGHT: viz + controls (splitter) =====
        center_panel = QWidget()
        center_panel.setObjectName("centerPanel")
        center_panel.setMinimumWidth(220)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 4, 0, 0)
        center_layout.setSpacing(0)

        # Vertical splitter: viz area | controls area
        self._center_splitter = QSplitter(Qt.Orientation.Vertical)
        self._center_splitter.setHandleWidth(3)
        self._center_splitter.setChildrenCollapsible(False)

        # Top: viz container
        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.setContentsMargins(0, 0, 0, 4)
        viz_layout.setSpacing(0)

        self._spectrum = SpectrumWidget()
        self._waveform = WaveformWidget()
        self._waveform.seekRequested.connect(self._engine.seek_ratio)

        viz_layout.addWidget(self._spectrum, 1)
        viz_layout.addWidget(self._waveform, 0)
        self._center_splitter.addWidget(viz_container)

        # Bottom: controls container
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)

        self._seek_slider = SeekSlider()
        self._seek_slider.seekRequested.connect(self._engine.seek)
        controls_layout.addWidget(self._seek_slider)

        self._output_spec_bar = OutputSpecBar()
        controls_layout.addWidget(self._output_spec_bar)

        # Transport row — vertical volume on left, play controls centered
        transport_layout = QHBoxLayout()
        transport_layout.setContentsMargins(8, 4, 8, 6)
        self._volume_control = VolumeControl()
        self._volume_control.valueChanged.connect(lambda v: setattr(self._engine, 'volume', v))
        transport_layout.addWidget(self._volume_control, 0, Qt.AlignmentFlag.AlignVCenter)
        transport_layout.addStretch(1)
        self._transport_bar = TransportBar()
        self._transport_bar.playPauseClicked.connect(self._engine.toggle)
        self._transport_bar.nextClicked.connect(self._next_track)
        self._transport_bar.prevClicked.connect(self._prev_track)
        transport_layout.addWidget(self._transport_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        transport_layout.addStretch(1)
        # Right spacer matching volume control width to keep transport centered
        self._transport_right_spacer = QWidget()
        self._transport_right_spacer.setFixedWidth(52)
        transport_layout.addWidget(self._transport_right_spacer, 0)
        controls_layout.addLayout(transport_layout)
        self._center_splitter.addWidget(controls_container)

        self._center_splitter.setSizes([400, 200])
        center_layout.addWidget(self._center_splitter)

        # Hidden metadata panel
        self._metadata_panel = MetadataPanel()
        self._metadata_panel.hide()

        # ===== Layout: sidebar | content stack | viz =====
        body_layout = QHBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.setHandleWidth(3)
        self._body_splitter.addWidget(self._sidebar)
        self._body_splitter.addWidget(self._content_stack)
        self._body_splitter.addWidget(center_panel)
        self._body_splitter.setSizes([200, 500, 400])
        self._body_splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self._body_splitter)

    def _build_manage_page(self) -> QWidget:
        from audio_player.app import current_accent as _accent, current_theme_mode
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        is_light = current_theme_mode() == "light"
        accent = _accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        title_color = "#333" if is_light else "#e2e8f0"
        muted = "#555" if is_light else "#94a3b8"

        self._manage_title = QLabel(_("page.manage"))
        self._manage_title.setStyleSheet(f"color:{title_color};font-size:15px;font-weight:bold;")
        layout.addWidget(self._manage_title)

        self._manage_btn_style_template = (
            f"QPushButton{{background:rgba({r},{g},{b},0.12);color:{accent.lighter(130).name()};border:none;"
            "border-radius:6px;padding:12px;font-size:13px;text-align:left;}"
            f"QPushButton:hover{{background:rgba({r},{g},{b},0.22);}}"
        )

        self._manage_import_folder_btn = QPushButton(_("manage.import_folder"))
        self._manage_import_folder_btn.setStyleSheet(self._manage_btn_style_template)
        self._manage_import_folder_btn.clicked.connect(self._open_folder)
        layout.addWidget(self._manage_import_folder_btn)

        self._manage_import_files_btn = QPushButton(_("manage.import_files"))
        self._manage_import_files_btn.setStyleSheet(self._manage_btn_style_template)
        self._manage_import_files_btn.clicked.connect(self._open_files)
        layout.addWidget(self._manage_import_files_btn)

        layout.addSpacing(8)

        self._manage_track_label = QLabel(_("manage.tracks_loaded", count=0))
        self._manage_track_label.setStyleSheet(f"color:{muted};font-size:12px;")
        layout.addWidget(self._manage_track_label)

        self._manage_album_label = QLabel(_("manage.albums_found", count=0))
        self._manage_album_label.setStyleSheet(f"color:{muted};font-size:12px;")
        layout.addWidget(self._manage_album_label)

        layout.addSpacing(8)

        reload_btn = QPushButton(_("manage.reload_albums"))
        reload_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:6px;"
            "padding:12px;font-size:13px;}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        reload_btn.clicked.connect(self._reload_albums)
        self._manage_reload_btn = reload_btn
        layout.addWidget(reload_btn)

        layout.addStretch()
        return w

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self, self._engine.toggle)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_files)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self._open_folder)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_playlist)
        QShortcut(QKeySequence("Ctrl+L"), self, self._load_playlist)
        QShortcut(QKeySequence("V"), self, self._spectrum.cycle_mode)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, self._toggle_lyrics)
        QShortcut(QKeySequence("Left"), self, lambda: self._engine.seek(self._engine.position - 5000))
        QShortcut(QKeySequence("Right"), self, lambda: self._engine.seek(self._engine.position + 5000))
        QShortcut(QKeySequence("Up"), self,
                  lambda: setattr(self._engine, 'volume', min(1.0, self._engine.volume + 0.05)))
        QShortcut(QKeySequence("Down"), self,
                  lambda: setattr(self._engine, 'volume', max(0.0, self._engine.volume - 0.05)))
        QShortcut(QKeySequence("Ctrl+Right"), self, self._next_track)
        QShortcut(QKeySequence("Ctrl+Left"), self, self._prev_track)
        QShortcut(QKeySequence("Delete"), self, self._remove_selected)

    def _restore_settings(self):
        s = QSettings("VBPlayer", "VB Player")
        vol = float(s.value("default_volume", 80) or 80) / 100.0
        self._engine.volume = vol
        self._volume_control.set_value(vol)

        lyrics_on = str(s.value("lyrics_enabled", "true") or "true").lower() == "true"
        self._lyrics_enabled = lyrics_on

        br = int(s.value("border_radius", 0) or 0)
        if br > 0:
            self._border_radius = br
        ui_r = int(s.value("ui_radius", 12) or 12)
        self._ui_radius = ui_r
        self._mask_dirty = True
        self.update()

        lh = int(s.value("lyrics_line_height", 40) or 40)
        self._spectrum.lyrics_overlay.set_line_height(lh)

        sidebar_log = str(s.value("sidebar_log", "false")).lower() == "true"
        self._sidebar.set_log_visible(sidebar_log)

        # Exclusive mode
        exclusive = str(s.value("exclusive_mode", "false")).lower() == "true"
        exclusive_dev = str(s.value("exclusive_device", "hw:0,0") or "hw:0,0")
        self._engine._exclusive_mode = exclusive
        self._engine._exclusive_device = exclusive_dev

        # Propagate loaded UI radius to sliders
        if self._ui_radius != 12:
            self._seek_slider._apply_sizing(self._ui_radius)
            self._volume_control._refresh_style(self._ui_radius)

    # ================================================================
    #  Signal Connections
    # ================================================================

    def _connect_signals(self):
        self._engine.stateChanged.connect(self._on_state_changed)
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)
        self._engine.trackChanged.connect(self._on_track_changed)
        self._engine.trackFinished.connect(self._on_track_finished)
        self._engine.errorOccurred.connect(self._on_error)
        self._engine.volumeChanged.connect(lambda v: self._volume_control.set_value(v))
        self._engine.exclusiveModeChanged.connect(self._on_exclusive_mode_changed)
        self._playlist.currentIndexChanged.connect(self._on_playlist_index_changed)
        self._album_view.albumClicked.connect(self._on_album_clicked)
        self._album_view.trackDoubleClicked.connect(self._play_track_at)

    def _connect_analyzer(self):
        self._analyzer.waveformReady.connect(self._waveform.set_waveform_data)
        self._analyzer.spectrumReady.connect(self._spectrum.set_audio_data)
        self._analyzer.lyricsReady.connect(self._on_lyrics_loaded)

    def _log_message(self, msg: str):
        self._sidebar.append_log(msg)

    def _on_sidebar_nav(self, key: str):
        page_map = {"songs": 0, "albums": 1, "manage": 2}
        if key in page_map:
            self._content_stack.setCurrentIndex(page_map[key])
            if key == "albums":
                self._album_view.refresh_from_playlist()
        elif key == "settings":
            self._open_settings()

    def _on_sidebar_width_toggled(self, target_w: int):
        sizes = self._body_splitter.sizes()
        if len(sizes) >= 2:
            delta = target_w - sizes[0]
            sizes[0] = target_w
            sizes[1] = max(50, sizes[1] - delta)
            self._body_splitter.setSizes(sizes)

    def _reload_albums(self):
        paths = [t["path"] for t in self._playlist._tracks]
        self._playlist.blockSignals(True)
        self._playlist.clear()
        self._playlist.add_files(sorted(paths))
        if self._playlist.count > 0:
            self._playlist.current_index = 0
        self._playlist.blockSignals(False)
        self._album_view.refresh_from_playlist()
        # Pre-load first track without playing
        path = self._playlist.current_track_path
        if path:
            self._engine.load(path)
        album_count = len(self._album_view._albums)
        self._sidebar.update_stats(self._playlist.count, album_count)
        self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
        self._manage_album_label.setText(_("manage.albums_found", count=album_count))
        self._log_message(_("log.reloaded", tracks=self._playlist.count, albums=album_count))

    def _on_album_clicked(self, album_info):
        self._album_detail_page.show_album(album_info)
        self._content_stack.setCurrentIndex(3)

    def _toggle_album_view_mode(self):
        if self._album_view.view_mode() == "grid":
            self._album_view.set_view_mode("list")
            self._album_view_btn.setText("⊞")
        else:
            self._album_view.set_view_mode("grid")
            self._album_view_btn.setText("◧")

    def _on_lyrics_loaded(self, lines):
        self._spectrum.set_lyrics(lines)
        self._fullscreen_lyrics.set_lyrics(lines)
        s = QSettings("VBPlayer", "VB Player")
        lyrics_on = str(s.value("lyrics_enabled", "true") or "true").lower() == "true"
        if lines:
            if lyrics_on:
                self._spectrum.show_lyrics()
            self._log_message(_("log.lyrics_loaded", count=len(lines)))
        else:
            self._log_message(_("log.lyrics_not_found"))

    def _show_fullscreen_lyrics(self):
        """Show the fullscreen lyrics window on the primary screen."""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self._fullscreen_lyrics.setGeometry(geo)
        self._fullscreen_lyrics.showFullScreen()
        self._fullscreen_lyrics.setFocus()

    # ================================================================
    #  Engine Callbacks
    # ================================================================

    def _on_state_changed(self, state):
        self._transport_bar.set_playing(state == PlaybackState.Playing)

    def _on_position_changed(self, ms):
        self._seek_slider.set_position(ms)
        dur = self._engine.duration
        if dur > 0:
            ratio = ms / dur
            self._waveform.set_position(ratio)
            self._spectrum.set_position_ratio(ratio)
            self._spectrum.lyrics_overlay.set_position(ms)
        self._fullscreen_lyrics.set_position(ms)

    def _on_duration_changed(self, ms):
        self._seek_slider.set_duration(ms)
        self._spectrum.lyrics_overlay.set_duration(ms)
        self._fullscreen_lyrics.set_duration(ms)

    def _on_track_changed(self, filepath):
        meta = read_metadata(filepath)
        self._metadata_panel.show_metadata(meta, filepath)
        title = meta.title or os.path.basename(filepath)
        artist = meta.artist or ""
        if artist:
            self._log_message(_("log.now_playing", artist=artist, title=title))
        else:
            self._log_message(_("log.now_playing_no_artist", title=title))
        self._output_spec_bar.set_meta(meta)
        self._output_spec_bar.set_audio_device(self._engine.output_info)
        self._fullscreen_lyrics.set_meta(meta)
        self._analyzer.analyze(filepath)

    def _on_track_finished(self):
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()
        else:
            self._engine.stop()

    def _on_error(self, msg):
        self._log_message(_("log.error", msg=msg))
        self._transport_bar.set_playing(False)

    def _on_playlist_index_changed(self, idx):
        path = self._playlist.current_track_path
        if path:
            self._engine.load(path)
            self._engine.play()
        self._playlist_view.scrollTo(
            self._playlist.index(idx, 0),
            self._playlist_view.ScrollHint.EnsureVisible
        )

    # ================================================================
    #  Playlist Actions
    # ================================================================

    def _play_track_at(self, idx):
        self._playlist.current_index = idx

    def _next_track(self):
        if self._playlist.advance():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()

    def _prev_track(self):
        if self._engine.position > 3000:
            self._engine.seek(0)
        elif self._playlist.previous():
            path = self._playlist.current_track_path
            if path:
                self._engine.load(path)
                self._engine.play()

    def _remove_selected(self):
        indices = [idx.row() for idx in self._playlist_view.selectedIndexes()]
        if indices:
            self._playlist.remove_indices(indices)

    # ================================================================
    #  File Operations
    # ================================================================

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, _("manage.select_folder"))
        if not folder:
            return
        self._playlist.clear()
        self._playlist.add_folder(folder)
        self._sidebar.update_stats(self._playlist.count, 0)
        self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
        self._log_message(_("log.loaded_folder", count=self._playlist.count, folder=folder))

    def _open_files(self):
        files, __ = QFileDialog.getOpenFileNames(
            self, _("manage.import_files").replace("📁  ", ""), "",
            _("manage.audio_files_filter")
        )
        if files:
            self._playlist.add_files(files)
            self._sidebar.update_stats(self._playlist.count, 0)
            self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
            self._log_message(_("log.added_files", count=len(files)))

    def _load_paths(self, paths: list[str]):
        self._playlist.clear()
        audio_paths = []
        for p in paths:
            if os.path.isdir(p):
                audio_paths.extend(
                    os.path.join(p, f) for f in os.listdir(p)
                    if os.path.splitext(f)[1].lower() in {
                        ".mp3", ".flac", ".wav", ".ogg", ".opus",
                        ".m4a", ".aac", ".wma", ".aiff", ".ape", ".wv",
                        ".dsf", ".dff"
                    }
                )
            else:
                audio_paths.append(p)
        if audio_paths:
            self._playlist.add_files(sorted(audio_paths))
            if self._playlist.current_index < 0:
                self._playlist.current_index = 0
            self._sidebar.update_stats(self._playlist.count, 0)
            self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))

    def _save_playlist(self):
        path, __ = QFileDialog.getSaveFileName(
            self, "保存播放列表", "", "M3U (*.m3u);;所有文件 (*)"
        )
        if path:
            self._playlist.save_m3u(path)
            self._log_message(_("log.playlist_saved", path=path))

    def _load_playlist(self):
        path, __ = QFileDialog.getOpenFileName(
            self, "加载播放列表", "", "M3U (*.m3u);;所有文件 (*)"
        )
        if path:
            self._playlist.load_m3u(path)
            if self._playlist.current_index < 0 and self._playlist.count > 0:
                self._playlist.current_index = 0
            self._log_message(_("log.playlist_loaded", count=self._playlist.count))

    # ================================================================
    #  Settings
    # ================================================================

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.themeChanged.connect(self._on_theme_changed)
        dlg.vizModeChanged.connect(lambda m: self._spectrum.set_mode(SpectrumMode(m)))
        dlg.defaultVolumeChanged.connect(lambda v: setattr(self._engine, 'volume', v))
        dlg.borderRadiusChanged.connect(self._apply_border_radius)
        dlg.uiRadiusChanged.connect(self._apply_ui_radius)
        dlg.lyricsToggled.connect(self._on_lyrics_toggled)
        dlg.lyricsLineHeightChanged.connect(self._on_lyrics_line_height)
        dlg.lyricsFullscreenLineHeightChanged.connect(self._on_lyrics_fullscreen_line_height)
        dlg.lyricsFontSizeChanged.connect(self._on_lyrics_font_size)
        dlg.lyricsLetterSpacingChanged.connect(self._on_lyrics_letter_spacing)
        dlg.lyricsShowSpecToggled.connect(self._on_lyrics_show_spec_toggled)
        dlg.sidebarLogToggled.connect(self._on_sidebar_log_toggled)
        dlg.albumCoverRadiusToggled.connect(self._on_album_cover_radius_toggled)

        # Equalizer state → settings dialog
        dlg.set_eq_state(
            self._equalizer_mgr.enabled,
            self._equalizer_mgr.current_preset,
            self._equalizer_mgr.all_gains()
        )
        dlg.eqBandChanged.connect(self._equalizer_mgr.set_band_gain)
        dlg.eqBandChanged.connect(self._engine.set_eq_band_gain)
        dlg.eqPresetSelected.connect(self._on_eq_preset_from_settings)
        dlg.eqResetRequested.connect(self._on_eq_reset_from_settings)
        dlg.eqEnabledToggled.connect(self._on_eq_enabled_from_settings)
        dlg.reloadRequested.connect(self._reload_albums)

        # Exclusive mode
        dlg.set_exclusive_state(self._engine.exclusive_mode, self._engine.exclusive_device)
        dlg.exclusiveModeToggled.connect(lambda v: setattr(self._engine, 'exclusive_mode', v))
        dlg.exclusiveDeviceChanged.connect(lambda v: setattr(self._engine, 'exclusive_device', v))
        # Language
        dlg.languageChanged.connect(lambda lang: set_language(lang))

        if dlg.exec():
            self._log_message(_("log.settings_saved"))

    def _on_theme_changed(self, mode: str, accent_name: str):
        apply_theme(QApplication.instance(), mode, accent_name)
        is_light = mode == "light"
        self._sidebar.refresh_theme_mode(is_light)
        self._album_view.refresh_theme_mode(is_light)
        self._output_spec_bar.refresh_theme_mode(is_light)
        self._refresh_accent_colors()
        # Album header label + toggle
        hdr_color = "#666666" if is_light else "#94a3b8"
        self._album_lbl.setStyleSheet(f"color:{hdr_color};font-size:10px;font-weight:bold;letter-spacing:2px;")
        btn_color = "#888888" if is_light else "#94a3b8"
        btn_hover_color = "#333333" if is_light else "#e2e8f0"
        self._album_view_btn.setStyleSheet(
            f"QPushButton{{background:rgba(0,0,0,0.06);color:{btn_color};border:none;"
            f"border-radius:3px;font-size:12px;}}"
            f"QPushButton:hover{{background:rgba(0,0,0,0.10);color:{btn_hover_color};}}"
        )

    def _refresh_accent_colors(self):
        """Re-apply inline accent-dependent styles across all widgets."""
        self._sidebar.refresh_accent()
        self._refresh_manage_accent()
        self._seek_slider._apply_sizing()
        self._volume_control._refresh_style()
        self._transport_bar._apply_sizing()

    def _refresh_language(self, _code: str = ""):
        """Refresh all translatable UI text after language change."""
        # Page labels
        self._pl_label.setText(_("page.all_songs"))
        self._album_lbl.setText(_("page.albums"))
        self._album_view_btn.setToolTip(_("album.view_toggle_grid"))
        # Manage page
        self._manage_title.setText(_("page.manage"))
        self._manage_import_folder_btn.setText(_("manage.import_folder"))
        self._manage_import_files_btn.setText(_("manage.import_files"))
        self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
        album_count = len(self._album_view._albums)
        self._manage_album_label.setText(_("manage.albums_found", count=album_count))
        reload_btn = self._manage_reload_btn
        if hasattr(self, '_manage_reload_btn'):
            reload_btn.setText(_("manage.reload_albums"))
        # Sidebar
        self._sidebar.refresh_language()
        # Album view
        self._album_view.refresh_language()
        self._album_detail_page.refresh_language()
        self._metadata_panel.refresh_accent()
        self._output_spec_bar.refresh_accent()
        self._waveform.update()
        self._spectrum.update()
        self._playlist_view.viewport().update()

    def _refresh_manage_accent(self):
        """Re-apply accent color and theme colors to manage page."""
        from audio_player.app import current_accent as _accent, current_theme_mode
        accent = _accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        is_light = current_theme_mode() == "light"
        title_color = "#333" if is_light else "#e2e8f0"
        muted = "#555" if is_light else "#94a3b8"

        if hasattr(self, '_manage_import_folder_btn'):
            self._manage_btn_style_template = (
                f"QPushButton{{background:rgba({r},{g},{b},0.12);color:{accent.lighter(130).name()};border:none;"
                "border-radius:6px;padding:12px;font-size:13px;text-align:left;}"
                f"QPushButton:hover{{background:rgba({r},{g},{b},0.22);}}"
            )
            self._manage_import_folder_btn.setStyleSheet(self._manage_btn_style_template)
            self._manage_import_files_btn.setStyleSheet(self._manage_btn_style_template)
            self._manage_reload_btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:6px;"
                "padding:12px;font-size:13px;}"
                f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
            )
            self._manage_title.setStyleSheet(f"color:{title_color};font-size:15px;font-weight:bold;")
            self._manage_track_label.setStyleSheet(f"color:{muted};font-size:12px;")
            self._manage_album_label.setStyleSheet(f"color:{muted};font-size:12px;")

    # ================================================================
    #  Toggles
    # ================================================================

    def _toggle_lyrics(self):
        visible = self._spectrum.toggle_lyrics()
        self._log_message(_("log.lyrics_on") if visible else _("log.lyrics_off"))

    def _on_lyrics_toggled(self, enabled: bool):
        if enabled:
            self._spectrum.show_lyrics()
        else:
            self._spectrum.hide_lyrics()

    def _on_lyrics_line_height(self, px: int):
        self._spectrum.lyrics_overlay.set_line_height(px)
        QSettings("VBPlayer", "VB Player").setValue("lyrics_line_height", px)

    def _on_lyrics_fullscreen_line_height(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_fullscreen_line_height", px)
        self._fullscreen_lyrics.update()

    def _on_lyrics_font_size(self, pt: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_font_size", pt)
        self._fullscreen_lyrics.update()

    def _on_lyrics_letter_spacing(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_letter_spacing", px)
        self._fullscreen_lyrics.update()

    def _on_lyrics_show_spec_toggled(self, show: bool):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_show_spec", show)
        self._fullscreen_lyrics._update_spec_bar()

    def _on_sidebar_log_toggled(self, visible: bool):
        self._sidebar.set_log_visible(visible)
        QSettings("VBPlayer", "VB Player").setValue("sidebar_log", visible)

    def _on_exclusive_mode_changed(self, enabled: bool):
        self._output_spec_bar.set_audio_device(self._engine.output_info)
        self._log_message(_("log.exclusive_mode",
            mode=_("log.exclusive_alsa") if enabled else _("log.exclusive_shared")))

    def _on_album_cover_radius_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("album_cover_radius", enabled)
        self._album_view.refresh_from_playlist()
        if hasattr(self, '_album_detail_page'):
            self._album_detail_page._album = None

    # ================================================================
    #  Equalizer (controlled from Settings > Playback)
    # ================================================================

    def _on_eq_preset_from_settings(self, name: str):
        self._equalizer_mgr.apply_preset(name)
        self._engine.set_eq_all_gains(self._equalizer_mgr.all_gains())

    def _on_eq_reset_from_settings(self):
        self._equalizer_mgr.reset_flat()
        self._engine.set_eq_all_gains([0.0] * 10)

    def _on_eq_enabled_from_settings(self, enabled: bool):
        self._equalizer_mgr.enabled = enabled
        self._engine.set_eq_enabled(enabled)

    # ================================================================
    #  Border Radius
    # ================================================================

    def _apply_border_radius(self, radius: int):
        QSettings("VBPlayer", "VB Player").setValue("border_radius", radius)
        self._border_radius = radius
        self._mask_dirty = True
        self.update()

    def _apply_ui_radius(self, radius: int):
        QSettings("VBPlayer", "VB Player").setValue("ui_radius", radius)
        self._ui_radius = radius
        self._seek_slider._apply_sizing(radius)
        self._volume_control._refresh_style(radius)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._mask_dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        self._mask_dirty = True

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._mask_dirty = True
            if self.isMaximized():
                self.clearMask()

    def _apply_mask(self):
        r = self._border_radius
        w, h = self.width(), self.height()
        if r > 0 and not self.isMaximized() and w > 0 and h > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, w, h), r, r)
            pixmap = QPixmap(w, h)
            pixmap.fill(Qt.GlobalColor.transparent)
            pp = QPainter(pixmap)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            pp.fillPath(path, Qt.GlobalColor.black)
            pp.end()
            self.setMask(pixmap.mask())
        else:
            self.clearMask()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._border_radius > 0 and not self.isMaximized():
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._border_radius, self._border_radius)
            painter.fillPath(path, self.palette().color(QPalette.ColorRole.Window))
        else:
            painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        painter.end()
        # Apply mask after painting — guarded by _mask_dirty to prevent recursion
        if self._mask_dirty:
            self._mask_dirty = False
            self._apply_mask()

    # ================================================================
    #  Drag & Drop on MainWindow
    # ================================================================

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._load_paths(paths)
        event.acceptProposedAction()

    # ================================================================
    #  Frameless window edge resize
    # ================================================================

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton and self._is_on_edge(e.pos()):
            wh = self.windowHandle()
            if wh:
                wh.startSystemResize(self._edge_at(e.pos()))
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        edge = self._edge_at(e.pos())
        if edge == Qt.Edge.TopEdge or edge == Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge == Qt.Edge.LeftEdge or edge == Qt.Edge.RightEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or \
             edge == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == (Qt.Edge.TopEdge | Qt.Edge.RightEdge) or \
             edge == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def _is_on_edge(self, pos: QPoint) -> bool:
        return self._edge_at(pos) is not None

    def _edge_at(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        edge = None
        if y <= EDGE_MARGIN:
            edge = Qt.Edge.TopEdge
        elif y >= h - EDGE_MARGIN:
            edge = Qt.Edge.BottomEdge
        if x <= EDGE_MARGIN:
            edge = edge | Qt.Edge.LeftEdge if edge else Qt.Edge.LeftEdge
        elif x >= w - EDGE_MARGIN:
            edge = edge | Qt.Edge.RightEdge if edge else Qt.Edge.RightEdge
        return edge
