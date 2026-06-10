import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QMessageBox, QMenu,
    QLabel, QFrame, QPushButton, QApplication, QStyle, QSizePolicy,
    QSplitter, QScrollArea, QInputDialog, QSystemTrayIcon, QLineEdit,
    QStackedWidget
)
from PyQt6.QtCore import Qt, QSize, QTimer, QPoint, QSettings, QEvent, QRectF
from PyQt6.QtGui import (QKeySequence, QShortcut, QFont,
                         QDragEnterEvent, QDropEvent, QMouseEvent, QColor,
                         QRegion, QPixmap,
                         QPainterPath, QPainter, QPen, QBrush, QPalette,
                         QAction, QIcon)

from audio_player.app import current_accent, current_theme_mode
from audio_player.player.engine import AudioEngine
from audio_player.player.playlist import PlaylistManager
from audio_player.player.metadata import read_metadata, write_tags
from audio_player.player.audio_analyzer import AudioAnalyzer
from audio_player.player.lyrics_fetcher import LyricsFetcher, LyricsState
from audio_player.player.lrc_parser import export_lrc
from audio_player.player.equalizer import EqualizerManager
from audio_player.player.library import LibraryManager

from audio_player.ui.widgets.transport_bar import TransportBar
from audio_player.ui.widgets.seek_slider import SeekSlider
from audio_player.ui.widgets.output_spec_bar import OutputSpecBar
from audio_player.ui.widgets.volume_control import VolumeControl
from audio_player.ui.widgets.playback_mode import PlaybackModeControl
from audio_player.ui.widgets.playlist_view import PlaylistView
from audio_player.ui.widgets.spectrum import SpectrumWidget
from audio_player.ui.widgets.waveform import WaveformWidget
from audio_player.ui.widgets.metadata_panel import MetadataPanel
from audio_player.ui.widgets.hifi_now_playing import HiFiNowPlayingPage, _format_duration, _format_size
from audio_player.ui.widgets.sidebar import Sidebar
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _, set_language, languageChanged
from audio_player.ui.pages import Page
from audio_player.ui.widgets.album_view import AlbumGridView, AlbumDetailPage
from audio_player.ui.widgets.search_filter import PlaylistFilterProxy
from audio_player.ui.icons import PANEL_COLLAPSE, PANEL_EXPAND, _icon
from audio_player.ui.widgets.playlist_browse import (
    PlaylistGridView, PlaylistDetailPage, PlaylistEditDialog, PlaylistInfo, build_playlist_info,
)
from audio_player.ui.widgets.fullscreen_lyrics import FullscreenLyricsWindow
from audio_player.ui.widgets.frameless_resize import FramelessResizeMixin
from audio_player.ui.widgets.tag_editor_dialog import TagEditorDialog
from audio_player.ui.widgets.network_page import NetworkPage
from audio_player.ui.settings_dialog import SettingsDialog, _CloseButton

from audio_player.ui.controllers.library_controller import LibraryController
from audio_player.ui.controllers.playback_controller import PlaybackController
from audio_player.ui.controllers.settings_controller import SettingsController
from audio_player.ui.controllers.cast_controller import CastController
from audio_player.player.backend import LocalBackend
from audio_player.player.http_server import EmbeddedHttpServer
from audio_player.player.dlna.registry import DeviceRegistry


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
        close_btn.clicked.connect(self._minimize_to_tray)
        layout.addWidget(close_btn)

    def _minimize_to_tray(self):
        w = self.window()
        if hasattr(w, '_tray') and w._tray.isVisible():
            from audio_player.i18n import _
            w.hide()
            w._tray.showMessage("VB Player", _("tray.minimized"),
                               QSystemTrayIcon.MessageIcon.Information, 1500)
        else:
            w.close()

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


class MainWindow(FramelessResizeMixin, QMainWindow):
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
        self._lyrics_fetcher = LyricsFetcher(self)
        self._album_view = AlbumGridView(self._playlist)

        self._library = LibraryManager(self)
        self._fav_playlist = PlaylistManager(self)
        self._pls_playlist = PlaylistManager(self)

        # Playback backend
        self._local_backend = LocalBackend(self._engine, self)
        self._http_server = EmbeddedHttpServer()
        self._http_server.start()
        self._cast_ctrl = CastController(self._local_backend, self)
        self._cast_ctrl.set_http_server(self._http_server)
        self._device_registry = DeviceRegistry(self)
        self._device_registry.deviceFound.connect(self._cast_ctrl.add_renderer)
        self._device_registry.deviceLost.connect(self._cast_ctrl.remove_renderer)
        self._cast_ctrl.backendChanged.connect(
            lambda: self._playback_ctrl.switch_backend(self._cast_ctrl.active_backend)
        )
        self._cast_ctrl.activeDeviceChanged.connect(self._on_active_device_changed)
        self._cast_ctrl.switchError.connect(lambda msg: self._sidebar.append_log(_("device.switch_error", msg=msg)))

        # Controllers
        self._playback_ctrl = PlaybackController(self._local_backend, self._playlist, self._analyzer, self)
        self._library_ctrl = LibraryController(self._library, self._fav_playlist, self._pls_playlist, self)
        self._settings_ctrl = SettingsController(self._equalizer_mgr, None, None, self._engine, self)

        self._setup_ui()

        # Fullscreen lyrics window
        self._fullscreen_lyrics = FullscreenLyricsWindow()

        # Wire settings controller refs that require UI to exist
        self._settings_ctrl._spectrum = self._spectrum
        self._settings_ctrl._fullscreen_lyrics = self._fullscreen_lyrics
        self._connect_signals()
        self._connect_analyzer()
        self._spectrum.lyrics_overlay.fullscreenRequested.connect(self._show_fullscreen_lyrics)
        self._setup_shortcuts()
        self._restore_settings()

        # System media controls (MPRIS2 on Linux, SMTC on Windows)
        self._system_media = None
        self._init_system_media()

        # Set initial theme state on widgets that track it explicitly
        is_light = current_theme_mode() == "light"
        self._sidebar.refresh_theme_mode(is_light)
        self._album_view.refresh_theme_mode(is_light)
        self._output_spec_bar.refresh_theme_mode(is_light)
        self._playback_mode.refresh_theme_mode(is_light)
        self._pls_grid_view.refresh_theme_mode(is_light)

        # React to language changes
        languageChanged.connect(self._refresh_language)

        # Auto-scan watch folders on startup
        self._auto_scan_library()

        # Start DLNA device discovery
        self._device_registry.start()

        # System tray
        self._setup_tray()

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
        # body is added to root later via _hifi_overlay stacked widget

        # ===== LEFT SIDEBAR =====
        self._sidebar = Sidebar()
        self._sidebar.navChanged.connect(self._on_sidebar_nav)
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
        self._pl_label.setObjectName("pageTitle")
        pl_header.addWidget(self._pl_label)
        pl_header.addStretch()
        # Search + Sort
        self._pl_search_btn, self._pl_search_bar = self._make_search_ui()
        self._pl_search_bar.textChanged.connect(lambda t: self._playlist_view.setFilterText(t))
        self._playlist_proxy = PlaylistFilterProxy()
        self._pl_sort_btn = self._make_sort_btn(self._playlist_proxy)
        pl_header.addWidget(self._pl_search_btn)
        pl_header.addWidget(self._pl_search_bar)
        pl_header.addSpacing(8)
        pl_header.addWidget(self._pl_sort_btn)
        pl_layout.addLayout(pl_header)
        self._playlist_proxy.setSourceModel(self._playlist)
        self._playlist_proxy.invalidate()
        self._playlist_view = PlaylistView()
        self._playlist_view.setModel(self._playlist_proxy)
        self._playlist_view.trackDoubleClicked.connect(self._playback_ctrl.play_track_at)
        self._playlist_view.tracksDropped.connect(self._load_paths)
        pl_layout.addWidget(self._playlist_view, 1)
        self._content_stack.addWidget(playlist_page)  # Page.SONGS

        # Page 1: Album grid
        album_page = QWidget()
        album_page.setObjectName("albumPage")
        album_layout = QVBoxLayout(album_page)
        album_layout.setContentsMargins(0, 0, 0, 0)
        album_layout.setSpacing(0)
        album_header = QHBoxLayout()
        album_header.setContentsMargins(8, 8, 8, 4)
        self._album_lbl = QLabel(_("page.albums"))
        self._album_lbl.setObjectName("pageTitle")
        album_header.addWidget(self._album_lbl)
        album_header.addStretch()
        # Search
        self._album_search_btn, self._album_search_bar = self._make_search_ui()
        self._album_search_bar.textChanged.connect(lambda t: self._album_view.set_filter(t))
        album_header.addWidget(self._album_search_btn)
        album_header.addWidget(self._album_search_bar)
        album_header.addSpacing(8)
        # Grid/list toggle
        self._album_view_btn = QPushButton("◧")
        self._album_view_btn.setObjectName("viewToggle")
        self._album_view_btn.setFixedSize(28, 28)
        self._album_view_btn.setToolTip(_("album.view_toggle_grid"))
        self._album_view_btn.clicked.connect(self._toggle_album_view_mode)
        album_header.addWidget(self._album_view_btn)
        album_layout.addLayout(album_header)
        album_layout.addWidget(self._album_view, 1)
        self._content_stack.addWidget(album_page)  # Page.ALBUMS

        # Page 2: Audio management
        manage_page = self._build_manage_page()
        self._content_stack.addWidget(manage_page)  # Page.MANAGE

        # Page 3: Album detail (inline)
        self._album_detail_page = AlbumDetailPage()
        self._album_detail_page.backRequested.connect(lambda: self._content_stack.setCurrentIndex(Page.ALBUMS))
        self._album_detail_page.trackDoubleClicked.connect(self._playback_ctrl.play_track_at)
        self._album_detail_page._is_favorite_fn = self._library.is_favorite
        self._album_detail_page._get_playlist_names_fn = self._library.get_playlist_names
        self._album_detail_page.addToFavorites.connect(self._library_ctrl.on_add_to_favorites)
        self._album_detail_page.removeFromFavorites.connect(self._library_ctrl.on_remove_from_favorites)
        self._album_detail_page.addToPlaylist.connect(self._library_ctrl.on_add_to_playlist)
        self._album_detail_page.editTags.connect(self._on_edit_tags)
        self._content_stack.addWidget(self._album_detail_page)  # Page.ALBUM_DETAIL

        # Page 4: Favorites
        fav_page = self._build_favorites_page()
        self._content_stack.addWidget(fav_page)  # Page.FAVORITES

        # Page 5: Playlists list
        pls_page = self._build_playlists_page()
        self._content_stack.addWidget(pls_page)  # Page.PLAYLISTS

        # Page 6: Playlist detail (inline)
        self._pls_detail_page = PlaylistDetailPage()
        self._pls_detail_page.backRequested.connect(lambda: self._content_stack.setCurrentIndex(Page.PLAYLISTS))
        self._pls_detail_page.trackDoubleClicked.connect(self._library_ctrl.play_pls_track)
        self._pls_detail_page._is_favorite_fn = self._library.is_favorite
        self._pls_detail_page._get_playlist_names_fn = self._library.get_playlist_names
        self._pls_detail_page.addToFavorites.connect(self._library_ctrl.on_add_to_favorites)
        self._pls_detail_page.removeFromFavorites.connect(self._library_ctrl.on_remove_from_favorites)
        self._pls_detail_page.addToPlaylist.connect(self._library_ctrl.on_add_to_playlist)
        self._pls_detail_page.removeFromPlaylist.connect(self._library_ctrl.on_remove_from_pls)
        self._pls_detail_page.editRequested.connect(self._on_edit_playlist)
        self._pls_detail_page.editTags.connect(self._on_edit_tags)
        self._content_stack.addWidget(self._pls_detail_page)  # Page.PLAYLIST_DETAIL

        # Page 7: Network
        self._network_page = NetworkPage()
        self._network_page.streamAdded.connect(self._play_stream_url)
        self._network_page.playRequested.connect(self._play_from_paths)
        self._network_page.smbBrowseRequested.connect(self._on_smb_browse)
        self._network_page.deviceSelected.connect(self._on_device_selected)
        self._cast_ctrl.deviceListChanged.connect(self._update_network_devices)
        self._update_network_devices()  # initial sync
        self._content_stack.addWidget(self._network_page)  # Page.NETWORK

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
        self._seek_slider.seekRequested.connect(
            lambda pos: self._cast_ctrl.active_backend.seek(pos)
        )
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
        self._transport_bar.playPauseClicked.connect(self._playback_ctrl.toggle)
        self._transport_bar.nextClicked.connect(self._playback_ctrl.next_track)
        self._transport_bar.prevClicked.connect(self._playback_ctrl.prev_track)
        transport_layout.addWidget(self._transport_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        transport_layout.addStretch(1)
        # Right side: playback mode control (symmetric with volume)
        self._playback_mode = PlaybackModeControl()
        self._playback_mode.repeatModeChanged.connect(self._on_repeat_mode_changed)
        self._playback_mode.shuffleChanged.connect(self._on_shuffle_changed)
        self._playback_mode.moreClicked.connect(
            lambda: self._library_ctrl.show_more_menu(self._playback_mode._more_btn, self._engine.current_file))
        self._playback_mode.expandRequested.connect(self._show_hifi)
        transport_layout.addWidget(self._playback_mode, 0, Qt.AlignmentFlag.AlignVCenter)
        controls_layout.addLayout(transport_layout)
        self._center_splitter.addWidget(controls_container)

        self._center_splitter.setSizes([400, 200])

        # Metadata panel (collapsed view)
        self._metadata_panel = MetadataPanel()

        # Panel toggle button (top-right corner)
        self._panel_toggle_btn = QPushButton(center_panel)
        self._panel_toggle_btn.setIcon(_icon(PANEL_COLLAPSE, color="#94a3b8"))
        self._panel_toggle_btn.setObjectName("panelToggleBtn")
        self._panel_toggle_btn.setFixedSize(28, 28)
        self._panel_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._panel_toggle_btn.setToolTip(_("panel.collapse"))
        self._panel_toggle_btn.clicked.connect(self._toggle_right_panel)
        self._panel_toggle_btn.raise_()
        self._refresh_panel_toggle_style()

        # Stacked: page 0 = full, page 1 = metadata-only
        self._panel_stack = AnimatedStackedWidget()
        self._panel_stack.addWidget(self._center_splitter)   # index 0: full
        self._panel_stack.addWidget(self._metadata_panel)     # index 1: collapsed
        self._panel_collapsed = False

        center_layout.addWidget(self._panel_stack)

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

        # ===== HiFi Now Playing overlay =====
        self._hifi_page = HiFiNowPlayingPage()
        self._hifi_page.hide()
        self._hifi_overlay = QStackedWidget()
        self._hifi_overlay.addWidget(self._body)      # index 0: normal
        self._hifi_overlay.addWidget(self._hifi_page)  # index 1: hifi
        self._hifi_overlay.setCurrentIndex(0)
        # Replace body in root layout
        root.addWidget(self._hifi_overlay, 1)

    def _build_manage_page(self) -> QWidget:
        from audio_player.app import current_accent as _accent, current_theme_mode
        w = QWidget()
        w.setObjectName("managePage")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        is_light = current_theme_mode() == "light"
        accent = _accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        title_color = "#333" if is_light else "#e2e8f0"
        muted = "#555" if is_light else "#94a3b8"

        manage_header = QHBoxLayout()
        manage_header.setContentsMargins(8, 8, 8, 4)
        self._manage_title = QLabel(_("page.manage"))
        self._manage_title.setObjectName("pageTitle")
        manage_header.addWidget(self._manage_title)
        manage_header.addStretch()
        layout.addLayout(manage_header)

        # Content area with margins for buttons
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 0, 12, 12)
        content_layout.setSpacing(12)

        _a12 = f"{int(0.12 * 255):02x}"
        _a22 = f"{int(0.22 * 255):02x}"
        _bg12 = f"#{_a12}{r:02x}{g:02x}{b:02x}"
        _bg22 = f"#{_a22}{r:02x}{g:02x}{b:02x}"
        self._manage_btn_style_template = (
            f"QPushButton{{background:{_bg12};color:{accent.lighter(130).name()};border:none;"
            "border-radius:6px;padding:12px;font-size:13px;text-align:left;}"
            f"QPushButton:hover{{background:{_bg22};}}"
        )

        self._manage_import_folder_btn = QPushButton(_("manage.import_folder"))
        self._manage_import_folder_btn.setStyleSheet(self._manage_btn_style_template)
        self._manage_import_folder_btn.clicked.connect(self._open_folder)
        content_layout.addWidget(self._manage_import_folder_btn)

        self._manage_import_files_btn = QPushButton(_("manage.import_files"))
        self._manage_import_files_btn.setStyleSheet(self._manage_btn_style_template)
        self._manage_import_files_btn.clicked.connect(self._open_files)
        content_layout.addWidget(self._manage_import_files_btn)

        content_layout.addSpacing(8)

        self._manage_track_label = QLabel(_("manage.tracks_loaded", count=0))
        self._manage_track_label.setObjectName("statsLabel")
        content_layout.addWidget(self._manage_track_label)

        self._manage_album_label = QLabel(_("manage.albums_found", count=0))
        self._manage_album_label.setObjectName("statsLabel")
        content_layout.addWidget(self._manage_album_label)

        content_layout.addSpacing(8)

        reload_btn = QPushButton(_("manage.reload_albums"))
        reload_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:6px;"
            "padding:12px;font-size:13px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        reload_btn.clicked.connect(self._reload_albums)
        self._manage_reload_btn = reload_btn
        content_layout.addWidget(reload_btn)

        content_layout.addStretch()
        layout.addWidget(content, 1)
        return w

    def _build_favorites_page(self) -> QWidget:
        w = QWidget()
        w.setObjectName("favoritesPage")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 4)
        self._fav_label = QLabel(_("page.favorites"))
        self._fav_label.setObjectName("pageTitle")
        header.addWidget(self._fav_label)
        header.addStretch()
        # Search + Sort
        self._fav_search_btn, self._fav_search_bar = self._make_search_ui()
        self._fav_search_bar.textChanged.connect(lambda t: self._fav_view.setFilterText(t))
        self._fav_proxy = PlaylistFilterProxy()
        self._fav_sort_btn = self._make_sort_btn(self._fav_proxy)
        header.addWidget(self._fav_search_btn)
        header.addWidget(self._fav_search_bar)
        header.addSpacing(8)
        header.addWidget(self._fav_sort_btn)
        layout.addLayout(header)
        self._fav_proxy.setSourceModel(self._fav_playlist)
        self._fav_view = PlaylistView()
        self._fav_view.setModel(self._fav_proxy)
        self._fav_view._is_favorite_fn = self._library.is_favorite
        self._fav_view._get_playlist_names_fn = self._library.get_playlist_names
        self._fav_view.trackDoubleClicked.connect(self._library_ctrl.play_fav_track)
        self._fav_view.addToFavorites.connect(self._library_ctrl.on_add_to_favorites)
        self._fav_view.removeFromFavorites.connect(self._library_ctrl.on_remove_from_favorites)
        self._fav_view.addToPlaylist.connect(self._library_ctrl.on_add_to_playlist)
        layout.addWidget(self._fav_view, 1)
        return w

    def _build_playlists_page(self) -> QWidget:
        w = QWidget()
        w.setObjectName("playlistsPage")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 4)
        pls_title = QLabel(_("nav.playlists"))
        pls_title.setObjectName("pageTitle")
        self._pls_title_lbl = pls_title
        header.addWidget(pls_title)
        header.addStretch()
        # Grid/list toggle
        self._pls_view_btn = QPushButton("◧")
        self._pls_view_btn.setObjectName("viewToggle")
        self._pls_view_btn.setFixedSize(28, 28)
        self._pls_view_btn.setToolTip(_("playlist.view_toggle_grid"))
        self._pls_view_btn.clicked.connect(self._toggle_pls_view_mode)
        header.addWidget(self._pls_view_btn)
        header.addSpacing(8)
        new_pls_btn = QPushButton(_("playlist.new"))
        self._new_pls_btn = new_pls_btn
        accent = current_accent()
        new_pls_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
            f"border-radius:5px;padding:5px 12px;font-size:11px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        new_pls_btn.clicked.connect(self._create_new_playlist)
        header.addWidget(new_pls_btn)
        layout.addLayout(header)
        self._pls_grid_view = PlaylistGridView()
        self._pls_grid_view.playlistClicked.connect(self._on_playlist_clicked)
        self._pls_grid_view.editRequested.connect(self._on_edit_playlist)
        self._pls_grid_view.deleteRequested.connect(self._on_delete_playlist)
        layout.addWidget(self._pls_grid_view, 1)
        return w

    def _refresh_favorites_page(self):
        paths = self._library.get_favorites()
        self._fav_playlist.clear()
        if paths:
            self._fav_playlist.add_files(paths)
        self._fav_label.setText(_("page.favorites_count", count=len(paths)))

    def _refresh_playlists_page(self):
        names = self._library.get_playlist_names()
        infos = []
        for name in names:
            paths = self._library.get_playlist_tracks(name)
            info = build_playlist_info(name, paths, self._library)
            infos.append(info)
        self._pls_grid_view.set_playlists(infos)

    def _create_new_playlist(self):
        name, ok = QInputDialog.getText(self, _("playlist.new"), _("playlist.name_label") + ":")
        if ok and name.strip():
            if self._library.playlist_exists(name.strip()):
                self._log_message(_("log.playlist_exists", name=name.strip()))
            else:
                self._library.create_playlist(name.strip())
                self._refresh_playlists_page()
                self._log_message(_("log.playlist_created", name=name.strip()))

    def _on_playlist_clicked(self, info: PlaylistInfo):
        self._open_playlist_detail(info.name)

    def _open_playlist_detail(self, name: str):
        self._library_ctrl._current_pls_name = name
        paths = self._library.get_playlist_tracks(name)
        info = build_playlist_info(name, paths, self._library)
        self._pls_detail_page.show_playlist(info)
        self._content_stack.setCurrentIndex(Page.PLAYLIST_DETAIL)

    def _toggle_pls_view_mode(self):
        if self._pls_grid_view.view_mode() == "grid":
            self._pls_grid_view.set_view_mode("list")
            self._pls_view_btn.setText("⊞")
        else:
            self._pls_grid_view.set_view_mode("grid")
            self._pls_view_btn.setText("◧")

    def _on_edit_playlist(self, info: PlaylistInfo):
        dlg = PlaylistEditDialog(info, self)
        if dlg.exec() == PlaylistEditDialog.DialogCode.Accepted:
            new_name = dlg.get_name()
            if not new_name:
                return
            old_name = info.name
            # Rename if changed
            if new_name != old_name:
                if self._library.playlist_exists(new_name):
                    self._log_message(_("log.playlist_exists", name=new_name))
                    return
                self._library.rename_playlist(old_name, new_name)
                self._library_ctrl._current_pls_name = new_name
            # Update description
            desc = dlg.get_description()
            cover_path = dlg.get_cover_path()
            self._library.update_playlist_meta(
                new_name if new_name != old_name else old_name,
                description=desc,
                cover_path=cover_path if cover_path else None,
            )
            self._refresh_playlists_page()
            # Refresh detail page if we're on it
            if self._content_stack.currentIndex() == Page.PLAYLIST_DETAIL:
                self._open_playlist_detail(self._library_ctrl._current_pls_name)
            self._log_message(_("log.playlist_updated", name=new_name))

    def _on_edit_tags(self, filepath: str):
        meta = read_metadata(filepath)
        dlg = TagEditorDialog(filepath, meta, self)
        if dlg.exec() == TagEditorDialog.DialogCode.Accepted:
            tags = dlg.get_tags()
            try:
                write_tags(filepath, tags)
            except Exception as e:
                QMessageBox.warning(self, _("tags.error"), str(e))
                return
            # Refresh playlist model
            self._playlist.refresh_metadata_for(filepath)
            # Refresh metadata panel if this is the current track
            if self._engine.current_file == filepath:
                new_meta = read_metadata(filepath)
                self._metadata_panel.show_metadata(new_meta, filepath)
            self._log_message(
                _("tags.saved", name=meta.title or os.path.basename(filepath))
            )

    def _on_play_next(self, paths: list[str]):
        for p in paths:
            self._playlist.insert_next(p)
        self._log_message(_("log.play_next", count=len(paths)))

    def _on_playlist_btn_clicked(self):
        """Navigate to the all-songs page which shows the current playlist."""
        self._on_sidebar_nav("songs")

    def _on_delete_playlist(self, info: PlaylistInfo):
        reply = QMessageBox.question(
            self, _("playlist.delete"),
            _("playlist.confirm_delete", name=info.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._library.delete_playlist(info.name)
            self._refresh_playlists_page()
            self._log_message(_("log.playlist_deleted", name=info.name))


    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self, self._playback_ctrl.toggle)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_files)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self._open_folder)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_playlist)
        QShortcut(QKeySequence("Ctrl+L"), self, self._load_playlist)
        QShortcut(QKeySequence("V"), self, self._spectrum.cycle_mode)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, self._toggle_lyrics)
        QShortcut(QKeySequence("Left"), self, lambda: self._cast_ctrl.active_backend.seek(
            self._cast_ctrl.active_backend.position - 5000))
        QShortcut(QKeySequence("Right"), self, lambda: self._cast_ctrl.active_backend.seek(
            self._cast_ctrl.active_backend.position + 5000))
        QShortcut(QKeySequence("Up"), self,
                  lambda: setattr(self._engine, 'volume', min(1.0, self._engine.volume + 0.05)))
        QShortcut(QKeySequence("Down"), self,
                  lambda: setattr(self._engine, 'volume', max(0.0, self._engine.volume - 0.05)))
        QShortcut(QKeySequence("Ctrl+Right"), self, self._playback_ctrl.next_track)
        QShortcut(QKeySequence("Ctrl+Left"), self, self._playback_ctrl.prev_track)
        QShortcut(QKeySequence("Delete"), self, self._remove_selected)
        QShortcut(QKeySequence("R"), self, self._cycle_playback_mode_shortcut)
        # Number keys 1-9 jump to 10%-90% of track duration
        for n in range(1, 10):
            QShortcut(QKeySequence(str(n)), self, lambda n=n: self._jump_to_pct(n * 10))

    def _jump_to_pct(self, pct: int):
        # Skip if a text input has focus
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            return
        backend = self._cast_ctrl.active_backend
        dur = backend.duration
        if dur > 0:
            backend.seek(int(dur * pct / 100))

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        app_icon = QApplication.instance().windowIcon()
        if app_icon.isNull():
            pix = QPixmap(64, 64)
            pix.fill(QColor("#7c3aed"))
            p = QPainter(pix)
            p.setPen(QColor("#ffffff"))
            f = QFont()
            f.setPointSize(32)
            f.setBold(True)
            p.setFont(f)
            p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "V")
            p.end()
            app_icon = QIcon(pix)
        self._tray.setIcon(app_icon)
        self._tray.setToolTip("VB Player")

        tray_menu = QMenu()
        show_act = QAction(_("tray.show_main"), self)
        show_act.triggered.connect(self._tray_show_window)
        tray_menu.addAction(show_act)
        tray_menu.addSeparator()
        play_act = QAction(_("tray.play_pause"), self)
        play_act.triggered.connect(self._playback_ctrl.toggle)
        tray_menu.addAction(play_act)
        prev_act = QAction(_("tray.prev"), self)
        prev_act.triggered.connect(self._playback_ctrl.prev_track)
        tray_menu.addAction(prev_act)
        next_act = QAction(_("tray.next"), self)
        next_act.triggered.connect(self._playback_ctrl.next_track)
        tray_menu.addAction(next_act)
        tray_menu.addSeparator()
        quit_act = QAction(_("tray.quit"), self)
        quit_act.triggered.connect(self._tray_quit)
        tray_menu.addAction(quit_act)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._tray_activated)
        self._playback_ctrl.trackLoaded.connect(self._update_tray_tooltip)
        self._tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_quit(self):
        self._quitting = True
        self._engine.stop()
        self._lyrics_fetcher.cleanup()
        if self._system_media:
            self._system_media.cleanup()
        self._tray.hide()
        QApplication.quit()

    def _update_tray_tooltip(self, filepath):
        meta = read_metadata(filepath)
        title = meta.title or os.path.basename(filepath)
        artist = meta.artist or ""
        tip = f"{artist} — {title}" if artist else title
        self._tray.setToolTip(f"VB Player — {tip}")

    def _restore_settings(self):
        self._settings_ctrl.restore_settings(self._volume_control, self._sidebar)

        # Restore last playback state
        self._restore_playback_state()

        s = QSettings("VBPlayer", "VB Player")

        lyrics_on = str(s.value("lyrics_enabled", "true") or "true").lower() == "true"
        self._lyrics_enabled = lyrics_on

        # Configure online lyrics fetcher
        online_enabled = str(s.value("online_lyrics_enabled", "false")).lower() == "true"
        lrclib_on = str(s.value("lyrics_source_lrclib", "true")).lower() == "true"
        custom_on = str(s.value("lyrics_source_custom", "false")).lower() == "true"
        custom_url = str(s.value("lyrics_custom_url", "")) if custom_on else ""
        from audio_player.ui.settings_dialog import _deobfuscate
        custom_token = _deobfuscate(str(s.value("lyrics_custom_token", ""))) if custom_on else ""
        self._lyrics_fetcher.configure(online_enabled, lrclib_on, custom_url, custom_token)

        br = int(s.value("border_radius", 0) or 0)
        if br > 0:
            self._border_radius = br
        ui_r = int(s.value("ui_radius", 12) or 12)
        self._ui_radius = ui_r
        self._mask_dirty = True
        self.update()

        # Propagate loaded UI radius to sliders
        if self._ui_radius != 12:
            self._seek_slider._apply_sizing(self._ui_radius)
            self._volume_control._refresh_style(self._ui_radius)

    # ================================================================
    #  Signal Connections
    # ================================================================

    def _connect_signals(self):
        # Playback controller — engine signals
        self._playback_ctrl.connect_engine()
        self._playback_ctrl.playbackStateChanged.connect(lambda playing: (
            self._transport_bar.set_playing(playing),
            self._hifi_page.set_playing(playing),
        ))
        self._playback_ctrl.logMessage.connect(self._log_message)
        self._playback_ctrl.errorOccurred.connect(lambda msg: self._log_message(_("log.error", msg=msg)))
        self._playback_ctrl.trackLoaded.connect(self._on_track_loaded_ui)
        self._playback_ctrl.metadataLoaded.connect(self._on_metadata_loaded_ui)

        # Position/duration — keep direct for seek slider/waveform/spectrum
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)

        # Engine volume/exclusive/output direct connections
        self._engine.volumeChanged.connect(lambda v: self._volume_control.set_value(v))
        self._engine.exclusiveModeChanged.connect(lambda enabled: (
            self._output_spec_bar.set_audio_device(self._engine.output_info),
            self._log_message(_("log.exclusive_mode",
                mode=_("log.exclusive_alsa") if enabled else _("log.exclusive_shared")))
        ))
        self._engine.outputInfoChanged.connect(lambda info: self._output_spec_bar.set_audio_device(info))

        # Playlist index → playback controller
        self._playlist.currentIndexChanged.connect(self._playback_ctrl.on_playlist_index_changed)

        # Album view
        self._album_view.albumClicked.connect(self._on_album_clicked)

        # Library controller
        self._library_ctrl.playRequested.connect(self._play_from_paths)
        self._library_ctrl.logMessage.connect(self._log_message)
        self._library_ctrl.navigateToPage.connect(self._content_stack.setCurrentIndex)
        self._library_ctrl.playlistChanged.connect(self._refresh_playlists_page)

        # Playlist view context menu hooks
        self._playlist_view._is_favorite_fn = self._library.is_favorite
        self._playlist_view._get_playlist_names_fn = self._library.get_playlist_names
        self._playlist_view.addToFavorites.connect(self._library_ctrl.on_add_to_favorites)
        self._playlist_view.removeFromFavorites.connect(self._library_ctrl.on_remove_from_favorites)
        self._playlist_view.addToPlaylist.connect(self._library_ctrl.on_add_to_playlist)
        self._playlist_view.editTags.connect(self._on_edit_tags)
        self._playlist_view.playNext.connect(self._on_play_next)

        # Library controller tag editing
        self._library_ctrl.editTags.connect(self._on_edit_tags)

        # HiFi Now Playing page
        self._hifi_page.collapseRequested.connect(self._collapse_hifi)
        self._hifi_page.fullscreenRequested.connect(self._toggle_fullscreen)
        self._hifi_page.playPauseClicked.connect(self._playback_ctrl.toggle)
        self._hifi_page.nextClicked.connect(self._playback_ctrl.next_track)
        self._hifi_page.prevClicked.connect(self._playback_ctrl.prev_track)
        self._hifi_page.seekRequested.connect(self._engine.seek)

        # Settings controller
        self._settings_ctrl.themeChanged.connect(self._on_theme_changed_ui)
        self._settings_ctrl.accentChanged.connect(self._refresh_accent_colors)
        self._settings_ctrl.logMessage.connect(self._log_message)

    def _connect_analyzer(self):
        self._analyzer.waveformReady.connect(self._waveform.set_waveform_data)
        self._analyzer.spectrumReady.connect(self._spectrum.set_audio_data)
        self._analyzer.lyricsReady.connect(self._on_lyrics_loaded)
        self._lyrics_fetcher.lyricsReady.connect(self._on_online_lyrics_fetched)
        self._lyrics_fetcher.stateChanged.connect(self._on_lyrics_state_changed)
        self._spectrum.lyrics_overlay.searchRequested.connect(self._manual_lyrics_search)

    def _log_message(self, msg: str):
        self._sidebar.append_log(msg)

    def _make_search_ui(self):
        """Create a search button + hidden search bar. Returns (button, line_edit)."""
        btn = QPushButton("🔍")
        btn.setObjectName("searchBtn")
        btn.setFixedSize(28, 28)
        btn.setToolTip(_("search.tooltip"))
        btn.setCheckable(True)
        btn.setStyleSheet(
            "QPushButton{background:#1a1a2e;color:#94a3b8;border:none;"
            "border-radius:5px;font-size:13px;}"
            "QPushButton:hover{background:#2a2a4a;color:#e2e8f0;}"
            "QPushButton:checked{background:#2a2a4a;color:#e2e8f0;}"
        )
        bar = QLineEdit()
        bar.setPlaceholderText(_("search.placeholder"))
        bar.setFixedWidth(180)
        bar.setStyleSheet(
            "QLineEdit{background:#1a1a2e;color:#e2e8f0;border:1px solid #333;"
            "border-radius:5px;padding:4px 8px;font-size:12px;}"
            "QLineEdit:focus{border:1px solid #7c3aed;}"
        )
        bar.setVisible(False)
        btn.toggled.connect(bar.setVisible)
        return btn, bar

    def _make_sort_btn(self, proxy: PlaylistFilterProxy) -> QPushButton:
        """Create a sort button that shows a dropdown menu."""
        from audio_player.ui.icons import SORT_ALPHA, _icon
        from audio_player.ui.theme_helpers import menu_style

        btn = QPushButton()
        btn.setIcon(_icon(SORT_ALPHA, color="#64748b"))
        btn.setObjectName("sortBtn")
        btn.setFixedSize(28, 28)
        btn.setToolTip(_("sort.default"))
        btn.setStyleSheet(
            "QPushButton{background:#1a1a2e;color:#94a3b8;border:none;"
            "border-radius:5px;}"
            "QPushButton:hover{background:#2a2a4a;color:#e2e8f0;}"
        )

        def _show_menu():
            from audio_player.player.playlist import PlaylistManager as PM
            menu = QMenu(btn)
            menu.setStyleSheet(menu_style())
            for label_key, role in [
                ("sort.default", 0),
                ("sort.title", PM.TitleRole),
                ("sort.artist", PM.ArtistRole),
                ("sort.duration", PM.DurationRole),
            ]:
                act = QAction(_(label_key), menu)
                act.triggered.connect(lambda checked, r=role, k=label_key: self._apply_sort(proxy, r, k, btn))
                menu.addAction(act)
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

        btn.clicked.connect(_show_menu)
        return btn

    def _apply_sort(self, proxy: PlaylistFilterProxy, role: int, label_key: str, btn: QPushButton):
        if role == 0:
            proxy.setSortRole(Qt.ItemDataRole.DisplayRole)
            proxy.sort(-1)  # unsort — restore original order
        else:
            proxy.setSortRole(role)
            proxy.sort(Qt.SortOrder.AscendingOrder)
        btn.setToolTip(_(label_key))

    def _init_system_media(self):
        if sys.platform == "linux":
            try:
                from audio_player.player.mpris2 import Mpris2Service
                self._system_media = Mpris2Service(
                    self._engine, self._playback_ctrl, self._playlist, self
                )
                self._system_media.raiseRequested.connect(self._on_raise_requested)
                self._system_media.connect_signals()
            except Exception as e:
                print(f"[mpris2] init failed: {e}", file=sys.stderr)
        elif sys.platform == "darwin":
            try:
                from audio_player.player.macos_media import MacOSSMediaService
                self._system_media = MacOSSMediaService(
                    self._engine, self._playback_ctrl, self
                )
                self._system_media.connect_signals()
            except Exception as e:
                print(f"[macos_media] init failed: {e}", file=sys.stderr)
        elif sys.platform == "win32":
            try:
                from audio_player.player.smtc import SmtcService
                self._system_media = SmtcService(
                    self._engine, self._playback_ctrl, self
                )
                self._system_media.connect_signals()
            except Exception as e:
                print(f"[smtc] init failed: {e}", file=sys.stderr)

    def _on_raise_requested(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_sidebar_nav(self, key: str):
        page_map = {
            "songs": Page.SONGS, "albums": Page.ALBUMS, "favorites": Page.FAVORITES,
            "playlists": Page.PLAYLISTS, "manage": Page.MANAGE, "network": Page.NETWORK,
        }
        if key in page_map:
            self._content_stack.setCurrentIndex(page_map[key])
            if key == "albums":
                self._album_view.refresh_from_playlist()
            elif key == "favorites":
                self._library_ctrl.refresh_favorites_page(self._fav_label)
            elif key == "playlists":
                self._refresh_playlists_page()
        elif key == "settings":
            self._open_settings()

    def closeEvent(self, event):
        # If tray is visible and this isn't a tray-quit, hide to tray
        if hasattr(self, '_tray') and self._tray.isVisible() and not getattr(self, '_quitting', False):
            event.ignore()
            self.hide()
            self._tray.showMessage("VB Player", _("tray.minimized"),
                                   QSystemTrayIcon.MessageIcon.Information, 1500)
            return
        self._save_playback_state()
        self._device_registry.stop()
        self._http_server.stop()
        self._engine.stop()
        self._lyrics_fetcher.cleanup()
        if self._system_media:
            self._system_media.cleanup()
        self._tray.hide()
        super().closeEvent(event)

    def _save_playback_state(self):
        """Persist current playback state so it can be restored on next launch."""
        s = QSettings("VBPlayer", "VB Player")
        s.setValue("restore/enabled", True)
        s.setValue("restore/track", self._engine.current_file)
        s.setValue("restore/position_ms", self._engine.position)
        # Save playlist file list
        paths = [self._playlist.track_at(i).get("path", "")
                 for i in range(self._playlist.count)]
        paths = [p for p in paths if p]
        s.setValue("restore/playlist", paths)
        s.setValue("restore/index", self._playlist.current_index)

    def _restore_playback_state(self):
        """Restore last playback state if saved."""
        s = QSettings("VBPlayer", "VB Player")
        if not s.value("restore/enabled", False):
            return
        track = str(s.value("restore/track", ""))
        if not track:
            return
        # Restore playlist
        paths = s.value("restore/playlist", [])
        if isinstance(paths, list) and paths:
            self._playlist.clear()
            self._playlist.add_files(paths)
            idx = int(s.value("restore/index", 0) or 0)
            if 0 <= idx < self._playlist.count:
                self._playlist.current_index = idx
            elif self._playlist.count > 0:
                self._playlist.current_index = 0
        # Restore position
        pos_ms = int(s.value("restore/position_ms", 0) or 0)
        if self._engine.current_file:
            self._engine.load(self._engine.current_file)
            if pos_ms > 0:
                # Seek after pipeline is ready — use a short timer
                QTimer.singleShot(200, lambda: self._engine.seek(pos_ms))

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
        self._playlist_proxy.invalidate()
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

    def _auto_scan_library(self):
        """On startup: scan watch folders in background, load tracks when done."""
        folders = self._library.get_watch_folders()
        if not folders:
            return
        self._library.scanFinished.connect(self._on_scan_finished)
        self._library.scan_watch_folders_async()

    def _on_scan_finished(self, paths: list[str]):
        """Handle async scan results — load tracks into playlist."""
        if not paths:
            return
        self._playlist.blockSignals(True)
        self._playlist.clear()
        self._playlist.add_files(paths)
        if self._playlist.count > 0:
            self._playlist.current_index = 0
        self._playlist.blockSignals(False)
        if hasattr(self, '_playlist_proxy'):
            self._playlist_proxy.invalidate()

        self._album_view.refresh_from_playlist()

        path = self._playlist.current_track_path
        if path:
            self._engine.load(path)
        album_count = len(self._album_view._albums)
        self._sidebar.update_stats(self._playlist.count, album_count)
        if hasattr(self, '_manage_track_label'):
            self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
        if hasattr(self, '_manage_album_label'):
            self._manage_album_label.setText(_("manage.albums_found", count=album_count))
        self._log_message(_("log.library_loaded", count=self._playlist.count, albums=album_count))

    def _on_album_clicked(self, album_info):
        self._album_detail_page.show_album(album_info)
        self._content_stack.setCurrentIndex(Page.ALBUM_DETAIL)

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
        self._hifi_page.set_lyrics(lines)
        s = QSettings("VBPlayer", "VB Player")
        lyrics_on = str(s.value("lyrics_enabled", "true") or "true").lower() == "true"
        if lines:
            if lyrics_on:
                self._spectrum.show_lyrics()
            self._log_message(_("log.lyrics_loaded", count=len(lines)))
        else:
            online_enabled = str(s.value("online_lyrics_enabled", "false")).lower() == "true"
            if online_enabled:
                self._try_online_lyrics()
            else:
                self._log_message(_("log.lyrics_not_found"))

    def _try_online_lyrics(self):
        """Trigger online lyrics search for current track."""
        filepath = self._engine.current_file
        if not filepath or filepath.startswith(("http://", "https://", "smb://")):
            return
        meta = read_metadata(filepath)
        if not meta.title:
            return
        s = QSettings("VBPlayer", "VB Player")
        lrclib_on = str(s.value("lyrics_source_lrclib", "true")).lower() == "true"
        custom_on = str(s.value("lyrics_source_custom", "false")).lower() == "true"
        custom_url = str(s.value("lyrics_custom_url", "")) if custom_on else ""
        custom_token = _deobfuscate(str(s.value("lyrics_custom_token", ""))) if custom_on else ""
        self._lyrics_fetcher.configure(
            online_enabled=True,
            lrclib_enabled=lrclib_on,
            custom_url=custom_url,
            custom_token=custom_token,
        )
        self._lyrics_fetcher.fetch(meta.title, meta.artist, meta.duration_seconds)

    def _on_online_lyrics_fetched(self, lines):
        if not lines:
            return
        self._spectrum.set_lyrics(lines)
        self._fullscreen_lyrics.set_lyrics(lines)
        self._hifi_page.set_lyrics(lines)
        s = QSettings("VBPlayer", "VB Player")
        lyrics_on = str(s.value("lyrics_enabled", "true") or "true").lower() == "true"
        if lyrics_on:
            self._spectrum.show_lyrics()
        self._log_message(_("log.lyrics_loaded", count=len(lines)))
        # Cache in fetcher
        filepath = self._engine.current_file
        if filepath:
            meta = read_metadata(filepath)
            if meta.title:
                self._lyrics_fetcher.cache_result(meta.artist, meta.title, lines)
        # Auto-save if enabled
        auto_save = str(s.value("auto_save_lyrics", "false")).lower() == "true"
        if auto_save and filepath and not filepath.startswith(("http://", "https://")):
            self._save_lyrics_to_file(lines)

    def _on_lyrics_state_changed(self, state):
        overlay = self._spectrum.lyrics_overlay
        if state == LyricsState.LOADING:
            overlay.set_loading_state(True)
        elif state == LyricsState.EMPTY:
            overlay.set_loading_state(False)
            self._log_message(_("log.lyrics_online_not_found"))
        elif state == LyricsState.NETWORK_ERROR:
            overlay.set_loading_state(False)
            self._log_message(_("log.lyrics_network_error"))
        elif state in (LyricsState.SUCCESS, LyricsState.IDLE):
            overlay.set_loading_state(False)

    def _save_lyrics_to_file(self, lines):
        """Save lyrics as .lrc file next to the audio file. Does not overwrite."""
        filepath = self._engine.current_file
        if not filepath or filepath.startswith(("http://", "https://")):
            return
        from pathlib import Path
        lrc_path = Path(filepath).with_suffix(".lrc")
        if lrc_path.exists():
            return
        try:
            lrc_path.write_text(export_lrc(lines), encoding="utf-8")
        except OSError as e:
            self._log_message(_("log.lyrics_save_error", msg=str(e)))

    def _manual_lyrics_search(self):
        """Manual re-search triggered by overlay search button."""
        self._try_online_lyrics()

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
    #  UI Bridge Methods (controllers → UI)
    # ================================================================

    def _on_track_loaded_ui(self, filepath):
        """Called when playback controller loads a new track — update UI."""
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
        self._album_detail_page.set_current_playlist_index(self._playlist.current_index)
        # HiFi page
        self._hifi_page.set_track_info(meta.title or "", meta.artist or "", meta.album or "")
        self._hifi_page.set_cover(meta.cover_data)
        self._hifi_page.set_quality(self._build_quality_text(meta))
        self._hifi_page.set_file_info(self._build_file_info(meta, filepath))

    def _on_metadata_loaded_ui(self, meta, filepath):
        self._metadata_panel.show_metadata(meta, filepath)

    def _on_position_changed(self, ms):
        self._seek_slider.set_position(ms)
        dur = self._engine.duration
        if dur > 0:
            ratio = ms / dur
            self._waveform.set_position(ratio)
            self._spectrum.set_position_ratio(ratio)
            self._spectrum.lyrics_overlay.set_position(ms)
        self._fullscreen_lyrics.set_position(ms)
        self._hifi_page.set_position(ms)
        self._hifi_page.set_lyrics_position(ms)

    def _on_duration_changed(self, ms):
        self._seek_slider.set_duration(ms)
        self._hifi_page.set_duration(ms)
        self._spectrum.lyrics_overlay.set_duration(ms)
        self._fullscreen_lyrics.set_duration(ms)

    def _show_hifi(self):
        """Switch to HiFi Now Playing overlay."""
        self._hifi_page.show()
        self._hifi_overlay.setCurrentIndex(1)

    def _collapse_hifi(self):
        """Return from HiFi Now Playing to normal view."""
        self._hifi_overlay.setCurrentIndex(0)
        self._hifi_page.hide()

    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
            self._title_bar.show()
            self._border_radius = 12
            self._mask_dirty = True
            self.update()
        else:
            self._title_bar.hide()
            self._border_radius = 0
            self._mask_dirty = True
            self.showFullScreen()

    def _build_quality_text(self, meta) -> str:
        """Build one-line HiFi quality string like 'FLAC · 24bit/96kHz · 1411kbps · Stereo'."""
        parts = []
        if meta.format:
            parts.append(meta.format)
        if meta.bits_per_sample and meta.sample_rate:
            parts.append(f"{meta.bits_per_sample}bit/{meta.sample_rate // 1000}kHz")
        elif meta.sample_rate:
            parts.append(f"{meta.sample_rate // 1000}kHz")
        if meta.bitrate:
            parts.append(f"{meta.bitrate}kbps")
        if meta.channels:
            ch_map = {1: "Mono", 2: "Stereo"}
            parts.append(ch_map.get(meta.channels, f"{meta.channels}ch"))
        return " · ".join(parts) if parts else ""

    def _build_file_info(self, meta, filepath: str) -> str:
        """Build expanded detail text for HiFi page."""
        lines = []
        if meta.duration_seconds:
            lines.append(f"时长: {_format_duration(meta.duration_seconds)}")
        if meta.file_size:
            lines.append(f"大小: {_format_size(meta.file_size)}")
        if meta.year:
            lines.append(f"年份: {meta.year}")
        if meta.genre:
            lines.append(f"流派: {meta.genre}")
        lines.append(f"路径: {filepath}")
        return "\n".join(lines)

    def _play_from_paths(self, paths):
        """Load paths into main playlist and play."""
        self._playback_ctrl.load_and_play(paths)
        self._update_manage_labels()

    def _play_stream_url(self, url: str):
        """Play a network stream URL directly."""
        self._playlist.add_url(url)
        idx = self._playlist.count - 1
        self._playback_ctrl.play_track_at(idx)

    def _on_smb_browse(self, server: str, username: str, password: str):
        """Handle SMB NAS connection request."""
        from audio_player.player.smb_scanner import is_smb_available, list_shares
        if not is_smb_available():
            self._sidebar.append_log(_("network.smb_not_available"))
            return
        try:
            shares = list_shares(server, username, password)
            self._network_page.add_share_items(shares)
            self._sidebar.append_log(f"NAS {server}: {len(shares)} shares")
        except Exception as e:
            self._sidebar.append_log(f"NAS error: {e}")

    def _on_device_selected(self, device_id: str):
        """Handle device selection from network page."""
        current_file = self._engine.current_file
        self._cast_ctrl.switch_to_device(device_id, current_file)

    def _on_active_device_changed(self, name: str):
        """Update UI when active output device changes."""
        self._sidebar.append_log(_("log.output_device", name=name))
        self._update_network_devices()

    def _update_network_devices(self):
        """Sync device list to network page."""
        devices = self._cast_ctrl.devices()
        active_id = self._cast_ctrl.active_device_id
        self._network_page.set_devices(devices, active_id)

    def _update_manage_labels(self):
        if hasattr(self, '_manage_track_label'):
            self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))

    def _remove_selected(self):
        indices = [idx.row() for idx in self._playlist_view.selectedIndexes()]
        if indices:
            self._playlist.remove_indices(indices)

    def _on_repeat_mode_changed(self, mode: int):
        from audio_player.player.playlist import RepeatMode
        self._playlist.repeat = RepeatMode(mode)

    def _on_shuffle_changed(self, enabled: bool):
        self._playlist.shuffle = enabled

    def _cycle_playback_mode_shortcut(self):
        """Advance playback mode: sequential → repeat all → repeat one → shuffle."""
        self._playback_mode.cycle_mode()

    # ================================================================
    #  File Operations
    # ================================================================

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, _("manage.select_folder"))
        if not folder:
            return
        self._library.add_watch_folder(folder)
        self._playlist.clear()
        self._playlist.add_folder(folder)
        self._sidebar.update_stats(self._playlist.count, 0)
        self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
        self._log_message(_("log.loaded_folder", count=self._playlist.count, folder=folder))

    def _open_files(self):
        files, __ = QFileDialog.getOpenFileNames(
            self, _("manage.import_files"), "",
            _("manage.audio_files_filter")
        )
        if files:
            self._playlist.add_files(files)
            self._sidebar.update_stats(self._playlist.count, 0)
            self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))
            self._log_message(_("log.added_files", count=len(files)))

    def _load_paths(self, paths: list[str]):
        # Save dragged-in folders as watch folders
        for p in paths:
            if os.path.isdir(p):
                self._library.add_watch_folder(p)
        self._playlist.clear()
        self._playback_ctrl.load_paths(paths)
        self._sidebar.update_stats(self._playlist.count, 0)
        self._manage_track_label.setText(_("manage.tracks_loaded", count=self._playlist.count))

    def _save_playlist(self):
        path, __ = QFileDialog.getSaveFileName(
            self, _("manage.load_playlist_title"), "", _("manage.m3u_filter")
        )
        if path:
            self._playlist.save_m3u(path)
            self._log_message(_("log.playlist_saved", path=path))

    def _load_playlist(self):
        path, __ = QFileDialog.getOpenFileName(
            self, _("manage.load_playlist_title"), "", _("manage.m3u_filter")
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
        self._settings_ctrl.open_settings(self)

    def _on_theme_changed_ui(self, mode: str, accent_name: str):
        """Update UI widgets after theme has been applied by SettingsController."""
        is_light = mode == "light"
        self._sidebar.refresh_theme_mode(is_light)
        self._album_view.refresh_theme_mode(is_light)
        self._output_spec_bar.refresh_theme_mode(is_light)
        self._playback_mode.refresh_theme_mode(is_light)
        if hasattr(self, '_pls_grid_view'):
            self._pls_grid_view.refresh_theme_mode(is_light)
        if hasattr(self, '_pls_detail_page'):
            self._pls_detail_page.refresh_theme_mode(is_light)
        self._refresh_panel_toggle_style()
        self._refresh_accent_colors()
        accent = current_accent()
        if hasattr(self, '_new_pls_btn'):
            self._new_pls_btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
                f"border-radius:5px;padding:5px 12px;font-size:11px;}}"
                f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
            )

    def _refresh_accent_colors(self):
        """Re-apply inline accent-dependent styles across all widgets."""
        self._sidebar.refresh_accent()
        self._refresh_manage_accent()
        self._seek_slider._apply_sizing()
        self._volume_control._refresh_style()
        self._transport_bar._apply_sizing()
        self._playback_mode.refresh_accent()
        self._album_view.refresh_from_playlist()

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
        self._playback_mode.refresh_language()
        # Album view
        self._album_view.refresh_language()
        self._album_detail_page.refresh_language()
        # Playlist view
        if hasattr(self, '_pls_grid_view'):
            self._pls_grid_view.refresh_language()
            self._pls_title_lbl.setText(_("nav.playlists"))
            self._pls_view_btn.setToolTip(_("playlist.view_toggle_grid"))
            self._new_pls_btn.setText(_("playlist.new"))
        if hasattr(self, '_pls_detail_page'):
            self._pls_detail_page.refresh_language()
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
            _a12 = f"{int(0.12 * 255):02x}"
            _a22 = f"{int(0.22 * 255):02x}"
            _bg12 = f"#{_a12}{r:02x}{g:02x}{b:02x}"
            _bg22 = f"#{_a22}{r:02x}{g:02x}{b:02x}"
            self._manage_btn_style_template = (
                f"QPushButton{{background:{_bg12};color:{accent.lighter(130).name()};border:none;"
                "border-radius:6px;padding:12px;font-size:13px;text-align:left;}"
                f"QPushButton:hover{{background:{_bg22};}}"
            )
            self._manage_import_folder_btn.setStyleSheet(self._manage_btn_style_template)
            self._manage_import_files_btn.setStyleSheet(self._manage_btn_style_template)
            self._manage_reload_btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:6px;"
                "padding:12px;font-size:13px;}"
                f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
            )

    # ================================================================
    #  Toggles
    # ================================================================

    def _toggle_lyrics(self):
        visible = self._spectrum.toggle_lyrics()
        self._log_message(_("log.lyrics_on") if visible else _("log.lyrics_off"))

    def _toggle_right_panel(self):
        self._panel_collapsed = not self._panel_collapsed
        if self._panel_collapsed:
            self._panel_stack.setCurrentIndex(1)
            self._panel_toggle_btn.setIcon(_icon(PANEL_EXPAND, color="#94a3b8"))
            self._panel_toggle_btn.setToolTip(_("panel.expand"))
        else:
            self._panel_stack.setCurrentIndex(0)
            self._panel_toggle_btn.setIcon(_icon(PANEL_COLLAPSE, color="#94a3b8"))
            self._panel_toggle_btn.setToolTip(_("panel.collapse"))

    def _update_panel_toggle_pos(self):
        """Position toggle button at top-left of center panel, avoiding lyrics overlay buttons."""
        btn = self._panel_toggle_btn
        parent = btn.parent()
        if parent:
            btn.move(6, 6)

    def _refresh_panel_toggle_style(self):
        is_light = current_theme_mode() == "light"
        if is_light:
            self._panel_toggle_btn.setStyleSheet(
                "QPushButton#panelToggleBtn{background:rgba(0,0,0,0.05);border:none;"
                "border-radius:14px;}"
                "QPushButton#panelToggleBtn:hover{background:rgba(0,0,0,0.10);}"
            )
        else:
            self._panel_toggle_btn.setStyleSheet(
                "QPushButton#panelToggleBtn{background:rgba(255,255,255,0.08);border:none;"
                "border-radius:14px;}"
                "QPushButton#panelToggleBtn:hover{background:rgba(255,255,255,0.15);}"
            )


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
        self._update_panel_toggle_pos()

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
        if self._border_radius > 0 and not self.isMaximized() and not self.isFullScreen():
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
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
            else:
                s = url.toString()
                if s.startswith(("http://", "https://")):
                    paths.append(s)
        if paths:
            self._load_paths(paths)
        event.acceptProposedAction()

