import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QMessageBox, QMenu,
    QLabel, QFrame, QPushButton, QApplication, QStyle, QSizePolicy,
    QSplitter, QScrollArea, QInputDialog, QSystemTrayIcon, QLineEdit,
    QStackedWidget
)
from PyQt6.QtCore import (Qt, QSize, QTimer, QPoint, QRect, QSettings, QEvent, QRectF,
                          QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (QKeySequence, QShortcut, QFont,
                         QDragEnterEvent, QDropEvent, QMouseEvent, QColor,
                         QRegion, QPixmap,
                         QPainterPath, QPainter, QPen, QBrush, QPalette,
                         QAction, QIcon)

from audio_player.app import current_accent, current_theme_mode, on_anim_tick
from audio_player.player.engine import AudioEngine
from audio_player.player.playlist import PlaylistManager
from audio_player.player.metadata import read_metadata, write_tags
from audio_player.player.audio_analyzer import AudioAnalyzer
from audio_player.player.lyrics_fetcher import LyricsFetcher, LyricsState
from audio_player.player.lrc_parser import export_lrc
from audio_player.player.equalizer import EqualizerManager
from audio_player.player.library import LibraryManager

from audio_player.ui.widgets.playlist_view import PlaylistView
from audio_player.ui.widgets.spectrum import SpectrumWidget
from audio_player.ui.widgets.waveform import WaveformWidget
from audio_player.ui.widgets.metadata_panel import MetadataPanel
from audio_player.ui.widgets.hifi_now_playing import HiFiNowPlayingPage
from audio_player.ui.widgets.now_playing_bar import NowPlayingBar
from audio_player.ui.widgets.floating_pill import FloatingPill
from audio_player.ui.utils import format_duration as _format_duration, format_size as _format_size
from audio_player.ui.widgets.sidebar import Sidebar
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _, set_language, languageChanged
from audio_player.ui.pages import Page
from audio_player.ui.widgets.album_view import AlbumGridView, AlbumDetailPage
from audio_player.ui.widgets.search_filter import PlaylistFilterProxy
from audio_player.ui.icons import _icon
from audio_player.ui.widgets.playlist_browse import (
    PlaylistGridView, PlaylistDetailPage, PlaylistEditDialog, PlaylistInfo, build_playlist_info,
)
from audio_player.ui.widgets.fullscreen_lyrics import FullscreenLyricsWindow
from audio_player.ui.widgets.frameless_resize import FramelessResizeMixin
from audio_player.ui.widgets.tag_editor_dialog import TagEditorDialog
from audio_player.ui.widgets.network_page import NetworkPage
from audio_player.ui.settings_dialog import SettingsDialog

from audio_player.ui.controllers.library_controller import LibraryController
from audio_player.ui.controllers.playback_controller import PlaybackController
from audio_player.ui.controllers.settings_controller import SettingsController
from audio_player.ui.controllers.cast_controller import CastController
from audio_player.player.backend import LocalBackend
from audio_player.player.http_server import EmbeddedHttpServer
from audio_player.player.dlna.registry import DeviceRegistry
from audio_player.platform import platform_info


class MainWindow(FramelessResizeMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VB Player")
        self.setMinimumSize(900, 580)
        self.resize(1200, 720)

        # Platform-aware window flags: use CSD on Wayland, frameless elsewhere
        if platform_info.policy.titlebar_style == "csd":
            self._use_csd = True
            self._use_frameless = False
        elif platform_info.policy.titlebar_style == "native":
            self._use_csd = False
            self._use_frameless = False
        else:
            self._use_csd = False
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            self._use_frameless = True

        self.setAcceptDrops(True)

        self._border_radius = 12
        self._bar_style = "full"
        self._material = platform_info.policy.material  # "acrylic" | "glass" | "vibrancy" | etc
        self._blur_enabler = None
        self._noise_pixmap = None

        self._use_translucent = self._material in ("glass", "acrylic")
        if self._use_translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # KDE KWin true blur (X11 only)
        if self._material == "acrylic":
            self._init_blur()
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
        self._settings_ctrl = SettingsController(self._equalizer_mgr, self._engine, self)

        self._setup_ui()

        # Fullscreen lyrics window
        self._fullscreen_lyrics = FullscreenLyricsWindow()

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
        self._pls_grid_view.refresh_theme_mode(is_light)
        self._bar_update("refresh_theme")

        # Clear playlist selection when clicking away
        self._body.installEventFilter(self)

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

        # Custom title bar — hidden on CSD (Wayland uses compositor decorations)
        from audio_player.ui.title_bar import TitleBar
        self._title_bar = TitleBar(self)
        self._title_bar.minimizeClicked.connect(self.showMinimized)
        self._title_bar.maximizeClicked.connect(
            lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        self._title_bar.closeClicked.connect(self.close)
        if self._use_csd:
            self._title_bar.hide()
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
        pl_header.setContentsMargins(12, 10, 12, 6)
        self._pl_label = QLabel(_("page.all_songs"))
        self._pl_label.setObjectName("pageTitle")
        pl_header.addWidget(self._pl_label)
        pl_header.addStretch()
        self._pl_search_bar = self._make_search_bar()
        self._pl_search_bar.textChanged.connect(lambda t: self._playlist_view.setFilterText(t))
        pl_header.addWidget(self._pl_search_bar)
        pl_header.addSpacing(8)
        self._playlist_proxy = PlaylistFilterProxy()
        self._pl_sort_btn = self._make_sort_btn(self._playlist_proxy)
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
        album_header.setContentsMargins(12, 10, 12, 6)
        self._album_lbl = QLabel(_("page.albums"))
        self._album_lbl.setObjectName("pageTitle")
        album_header.addWidget(self._album_lbl)
        album_header.addStretch()
        self._album_search_bar = self._make_search_bar()
        self._album_search_bar.textChanged.connect(lambda t: self._album_view.set_filter(t))
        album_header.addWidget(self._album_search_bar)
        album_header.addSpacing(8)
        self._album_view_btn = QPushButton("◧")
        self._album_view_btn.setObjectName("viewToggle")
        self._album_view_btn.setFixedSize(32, 32)
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
        self._album_detail_page.trackDoubleClicked.connect(self._play_album_track)
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

        # Now Playing overlay — reuses HiFi page (same design)

        # Hidden viz widgets — used by analyzer, shown on Now Playing page
        self._spectrum = SpectrumWidget()
        self._waveform = WaveformWidget()
        self._waveform.seekRequested.connect(self._engine.seek_ratio)
        self._metadata_panel = MetadataPanel()

        # ===== Layout: sidebar | content stack =====
        body_layout = QHBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._body_splitter.setHandleWidth(3)
        self._body_splitter.addWidget(self._sidebar)
        self._body_splitter.addWidget(self._content_stack)
        self._body_splitter.setSizes([200, 900])
        self._body_splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self._body_splitter)

        # ===== Bottom bar (full-width) + Floating pill (centered capsule) =====
        self._now_playing_bar = NowPlayingBar()
        self._pill = FloatingPill()

        for bar in (self._now_playing_bar, self._pill):
            bar.playPauseClicked.connect(self._playback_ctrl.toggle)
            bar.nextClicked.connect(self._playback_ctrl.next_track)
            bar.prevClicked.connect(self._playback_ctrl.prev_track)
            bar.expandRequested.connect(self._show_np_page)

        # Pill wrapper — centers the pill horizontally
        pill_wrapper = QWidget()
        pill_layout = QHBoxLayout(pill_wrapper)
        pill_layout.setContentsMargins(0, 0, 0, 10)
        pill_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        pill_layout.addWidget(self._pill)
        self._pill_wrapper = pill_wrapper

        self._engine.volume = 1.0

        # ===== Overlay stack: body | hifi (also used as now-playing overlay) =====
        self._hifi_page = HiFiNowPlayingPage()
        self._hifi_page.hide()
        self._now_playing_page = self._hifi_page  # same widget, reused
        self._hifi_overlay = QStackedWidget()
        self._hifi_overlay.addWidget(self._body)       # 0: normal
        self._hifi_overlay.addWidget(self._hifi_page)  # 1: overlay
        self._hifi_overlay.setCurrentIndex(0)
        root.addWidget(self._hifi_overlay, 1)

        # ===== Bottom bars =====
        root.addWidget(self._now_playing_bar)
        # Pill floats over body content — not in root bar area
        self._pill_wrapper.setParent(self._body)
        self._pill_wrapper.hide()

        # Register inline-styled widgets to refresh during accent animation
        on_anim_tick(lambda c: self._bar_update("refresh_accent"))
        on_anim_tick(lambda c: self._sidebar.refresh_accent())
        on_anim_tick(lambda c: self._refresh_manage_accent())
        on_anim_tick(lambda c: self._network_page.refresh_theme())
        on_anim_tick(lambda c: self._hifi_page.refresh_accent())
        on_anim_tick(lambda c: self._pls_detail_page.refresh_accent() if hasattr(self._pls_detail_page, 'refresh_accent') else None)
        on_anim_tick(lambda c: self._album_detail_page.refresh_accent() if hasattr(self._album_detail_page, 'refresh_accent') else None)
        on_anim_tick(lambda c: self._new_pls_btn.setStyleSheet(
            f"QPushButton{{background:{c.name()};color:#fff;border:none;"
            f"border-radius:8px;padding:6px 14px;font-size:12px;}}"
            f"QPushButton:hover{{background:{c.lighter(115).name()};}}"
        ))
        from audio_player.ui.icons import SORT_ALPHA, _icon
        on_anim_tick(lambda c: self._pl_sort_btn.setIcon(_icon(SORT_ALPHA, color=c.name())))
        on_anim_tick(lambda c: self._fav_sort_btn.setIcon(_icon(SORT_ALPHA, color=c.name())))
        # Search bar borders follow accent
        accent_dark = lambda c: c.darker(160).name()
        for bar_attr in ('_pl_search_bar', '_album_search_bar', '_fav_search_bar', '_pls_search_bar'):
            on_anim_tick(lambda c, a=bar_attr: getattr(self, a).setStyleSheet(
                f"QLineEdit{{background:rgba(0,0,0,0.12);color:#e2e8f0;"
                f"border:1px solid {c.darker(160).name()};"
                f"border-radius:10px;padding:6px 10px;font-size:12px;}}"
                f"QLineEdit:focus{{border:1px solid {c.name()};background:rgba(0,0,0,0.18);}}"
            ))

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
        header.setContentsMargins(12, 10, 12, 6)
        self._fav_label = QLabel(_("page.favorites"))
        self._fav_label.setObjectName("pageTitle")
        header.addWidget(self._fav_label)
        header.addStretch()
        self._fav_search_bar = self._make_search_bar()
        self._fav_search_bar.textChanged.connect(lambda t: self._fav_view.setFilterText(t))
        header.addWidget(self._fav_search_bar)
        header.addSpacing(8)
        self._fav_proxy = PlaylistFilterProxy()
        self._fav_sort_btn = self._make_sort_btn(self._fav_proxy)
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
        header.setContentsMargins(12, 10, 12, 6)
        pls_title = QLabel(_("nav.playlists"))
        pls_title.setObjectName("pageTitle")
        self._pls_title_lbl = pls_title
        header.addWidget(pls_title)
        header.addStretch()
        # Search
        self._pls_search_bar = self._make_search_bar()
        self._pls_search_bar.setPlaceholderText(_("search.playlists"))
        self._pls_search_bar.textChanged.connect(lambda t: self._pls_grid_view.filter(t))
        header.addWidget(self._pls_search_bar)
        header.addSpacing(8)
        # Grid/list toggle
        self._pls_view_btn = QPushButton("◧")
        self._pls_view_btn.setObjectName("viewToggle")
        self._pls_view_btn.setFixedSize(32, 32)
        self._pls_view_btn.setToolTip(_("playlist.view_toggle_grid"))
        self._pls_view_btn.clicked.connect(self._toggle_pls_view_mode)
        header.addWidget(self._pls_view_btn)
        header.addSpacing(6)
        new_pls_btn = QPushButton(_("playlist.new"))
        self._new_pls_btn = new_pls_btn
        new_pls_btn.setObjectName("accentBtn")
        accent = current_accent()
        new_pls_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
            f"border-radius:8px;padding:6px 14px;font-size:12px;}}"
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
        self._fav_proxy.invalidateFilter()
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
        from audio_player.ui.shortcut_manager import ShortcutManager
        sm = ShortcutManager(self)
        sm.register_all({
            "play_pause": self._playback_ctrl.toggle,
            "open_files": self._open_files,
            "open_folder": self._open_folder,
            "save_playlist": self._save_playlist,
            "load_playlist": self._load_playlist,
            "cycle_viz": self._spectrum.cycle_mode,
            "toggle_lyrics": self._toggle_lyrics,
            "seek_back": lambda: self._cast_ctrl.active_backend.seek(
                self._cast_ctrl.active_backend.position - 5000),
            "seek_forward": lambda: self._cast_ctrl.active_backend.seek(
                self._cast_ctrl.active_backend.position + 5000),
            "volume_up": lambda: setattr(self._engine, 'volume',
                                         min(1.0, self._engine.volume + 0.05)),
            "volume_down": lambda: setattr(self._engine, 'volume',
                                           max(0.0, self._engine.volume - 0.05)),
            "prev_track": self._playback_ctrl.prev_track,
            "next_track": self._playback_ctrl.next_track,
            "remove_selected": self._remove_selected,
            "cycle_playback_mode": self._cycle_playback_mode_shortcut,
            "jump_to_pct": lambda pct: self._jump_to_pct(pct),
        })

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
        from audio_player.ui.tray_manager import TrayManager
        self._tray_mgr = TrayManager(self)
        self._tray_mgr.showWindowRequested.connect(self._on_tray_show)
        self._tray_mgr.quitRequested.connect(self._on_tray_quit)
        self._tray_mgr.playPauseRequested.connect(self._playback_ctrl.toggle)
        self._tray_mgr.nextRequested.connect(self._playback_ctrl.next_track)
        self._tray_mgr.prevRequested.connect(self._playback_ctrl.prev_track)
        self._playback_ctrl.trackLoaded.connect(self._tray_mgr.update_tooltip)
        self._tray_mgr.setup()

    def _on_tray_show(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_tray_quit(self):
        self._quitting = True
        self._engine.stop()
        self._lyrics_fetcher.cleanup()
        if self._system_media:
            self._system_media.cleanup()
        if self._blur_enabler:
            self._blur_enabler.cleanup()
        for pl in [self._playlist, self._fav_playlist, self._pls_playlist]:
            if hasattr(pl, 'shutdown'):
                pl.shutdown()
        self._tray_mgr.hide_tray()
        QApplication.quit()

    def _restore_settings(self):
        self._settings_ctrl.restore_settings(None, self._sidebar)

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

        # Playback bar style
        style = str(s.value("playback_bar_style", "full") or "full")
        self._apply_bar_style(style)

        if self._ui_radius != 12:
            pass

    # ================================================================
    #  Signal Connections
    # ================================================================

    def _connect_signals(self):
        # Playback controller — engine signals
        self._playback_ctrl.connect_engine()
        self._playback_ctrl.playbackStateChanged.connect(lambda playing: (
            self._bar_update("set_playing", playing),
            self._hifi_page.set_playing(playing),
        ))
        self._playback_ctrl.logMessage.connect(self._log_message)
        self._playback_ctrl.errorOccurred.connect(lambda msg: self._log_message(_("log.error", msg=msg)))
        self._playback_ctrl.trackLoaded.connect(self._on_track_loaded_ui)
        self._playback_ctrl.metadataLoaded.connect(self._on_metadata_loaded_ui)

        # Position/duration — keep direct for seek slider/waveform/spectrum
        self._engine.positionChanged.connect(self._on_position_changed)
        self._engine.durationChanged.connect(self._on_duration_changed)


        # Engine exclusive mode log
        self._engine.exclusiveModeChanged.connect(lambda enabled: (
            self._log_message(_("log.exclusive_mode",
                mode=_("log.exclusive_alsa") if enabled else _("log.exclusive_shared")))
        ))

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
        self._hifi_page.outputDetailRequested.connect(self._show_output_detail)
        self._hifi_page.fullscreenRequested.connect(self._toggle_fullscreen)
        self._hifi_page.playPauseClicked.connect(self._playback_ctrl.toggle)
        self._hifi_page.nextClicked.connect(self._playback_ctrl.next_track)
        self._hifi_page.prevClicked.connect(self._playback_ctrl.prev_track)
        self._hifi_page.seekRequested.connect(self._engine.seek)

        # Settings controller
        self._settings_ctrl.themeChanged.connect(self._on_theme_changed_ui)
        self._settings_ctrl.accentChanged.connect(self._refresh_accent_colors)
        self._settings_ctrl.logMessage.connect(self._log_message)
        self._settings_ctrl.materialChanged.connect(self._on_material_changed)
        self._settings_ctrl.coverRadiusChanged.connect(self._refresh_covers)
        # Widget control signals (replacing direct widget refs)
        self._settings_ctrl.vizModeChanged.connect(self._spectrum.set_mode)
        self._settings_ctrl.lyricsToggled.connect(
            lambda on: self._spectrum.show_lyrics() if on else self._spectrum.hide_lyrics())
        self._settings_ctrl.lyricsLineHeightChanged.connect(
            self._spectrum.lyrics_overlay.set_line_height)
        self._settings_ctrl.lyricsFullscreenLineHeightChanged.connect(
            lambda _: self._fullscreen_lyrics.update())
        self._settings_ctrl.lyricsFontSizeChanged.connect(
            lambda _: self._fullscreen_lyrics.update())
        self._settings_ctrl.lyricsLetterSpacingChanged.connect(
            lambda _: self._fullscreen_lyrics.update())
        self._settings_ctrl.lyricsShowSpecToggled.connect(
            lambda _: self._fullscreen_lyrics._update_spec_bar())
        self._settings_ctrl.fullscreenLyricsUpdate.connect(
            self._fullscreen_lyrics.update)

    def _connect_analyzer(self):
        self._analyzer.waveformReady.connect(self._waveform.set_waveform_data)
        self._analyzer.spectrumReady.connect(self._spectrum.set_audio_data)
        self._analyzer.lyricsReady.connect(self._on_lyrics_loaded)
        self._lyrics_fetcher.lyricsReady.connect(self._on_online_lyrics_fetched)
        self._lyrics_fetcher.stateChanged.connect(self._on_lyrics_state_changed)
        self._spectrum.lyrics_overlay.searchRequested.connect(self._manual_lyrics_search)

    def _log_message(self, msg: str):
        self._sidebar.append_log(msg)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            pos = event.globalPosition().toPoint()
            widget = QApplication.widgetAt(pos)
            if widget is not self._playlist_view.viewport() and widget is not self._fav_view.viewport():
                self._playlist_view.clearSelection()
                if hasattr(self, '_fav_view'):
                    self._fav_view.clearSelection()
        return super().eventFilter(obj, event)

    def _apply_bar_style(self, style: str):
        self._bar_style = style
        if style == "pill":
            self._now_playing_bar.hide()
            self._pill_wrapper.show()
            self._position_pill()
        else:
            self._pill_wrapper.hide()
            self._now_playing_bar.show()

    def _position_pill(self):
        """Position pill centered at bottom of body area."""
        if not self._pill_wrapper.isVisible():
            return
        bw = self._body.width()
        bh = self._body.height()
        pw = min(self._pill.maximumWidth(), bw - 40)
        self._pill.setMaximumWidth(pw)
        self._pill_wrapper.setGeometry(0, bh - self._pill.height() - 16, bw, self._pill.height())

    def _bar_update(self, method: str, *args):
        """Call method on both bars — hidden bar is no-op."""
        for bar in (self._now_playing_bar, self._pill):
            getattr(bar, method)(*args)

    def _refresh_covers(self):
        """Re-render album covers after radius setting change."""
        meta = read_metadata(self._engine.current_file) if self._engine.current_file else None
        if meta:
            self._bar_update("update_cover", meta.cover_data)
            self._hifi_page.set_cover(meta.cover_data)
        self._album_view.refresh_from_playlist()
        self._metadata_panel.update()

    def _make_search_bar(self):
        """Create a glass-style search input — matches the floating pill aesthetic."""
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        bg = "rgba(0,0,0,0.12)" if not is_light else "rgba(0,0,0,0.05)"
        fg = "#e2e8f0" if not is_light else "#333"
        border = accent.darker(160).name() if not is_light else accent.lighter(130).name()
        bar = QLineEdit()
        bar.setPlaceholderText(_("search.placeholder"))
        bar.setFixedWidth(200)
        bar.setStyleSheet(
            f"QLineEdit{{background:{bg};color:{fg};border:1px solid {border};"
            f"border-radius:10px;padding:6px 10px;font-size:12px;}}"
            f"QLineEdit:focus{{border:1px solid {accent.name()};background:rgba(0,0,0,0.18);}}"
        )
        return bar

    def _make_sort_btn(self, proxy: PlaylistFilterProxy) -> QPushButton:
        """Create a sort button that shows a dropdown menu."""
        from audio_player.ui.icons import SORT_ALPHA, _icon
        from audio_player.ui.theme_helpers import menu_style

        btn = QPushButton()
        accent = current_accent()
        btn.setIcon(_icon(SORT_ALPHA, color=accent.name()))
        btn.setObjectName("sortBtn")
        btn.setFixedSize(32, 32)
        btn.setToolTip(_("sort.default"))

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
        from audio_player.platform import create_system_media_service
        try:
            self._system_media = create_system_media_service(
                self._engine, self._playback_ctrl, self._playlist, self._settings_ctrl, self)
            if self._system_media:
                if hasattr(self._system_media, 'raiseRequested'):
                    self._system_media.raiseRequested.connect(self._on_raise_requested)
                self._system_media.connect_signals()
        except Exception as e:
            print(f"[system_media] init failed: {e}", file=sys.stderr)

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
        s = QSettings("VBPlayer", "VB Player")
        close_to_tray = str(s.value("close_to_tray", "true")).lower() == "true"
        if (close_to_tray and hasattr(self, '_tray_mgr')
                and not getattr(self, '_quitting', False)):
            event.ignore()
            self.hide()
            return
        self._save_playback_state()
        self._device_registry.stop()
        self._http_server.stop()
        self._engine.stop()
        self._lyrics_fetcher.cleanup()
        if self._system_media:
            self._system_media.cleanup()
        if self._blur_enabler:
            self._blur_enabler.cleanup()
        self._tray_mgr.hide_tray()
        # Drain metadata worker pools before Qt destroys them
        for pl in [self._playlist, self._fav_playlist, self._pls_playlist]:
            if hasattr(pl, 'shutdown'):
                pl.shutdown()
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

    def _play_album_track(self, idx: int):
        """Load album tracks into main playlist and play at *idx*."""
        model = self._album_detail_page._track_model
        paths = [model.track_at(i).get("path", "") for i in range(model.count) if model.track_at(i)]
        if paths:
            existing = {self._playlist.track_at(i).get("path") for i in range(self._playlist.count)}
            new_paths = [p for p in paths if p not in existing]
            if new_paths:
                self._playlist.add_files(new_paths)
            target = paths[idx]
            for i in range(self._playlist.count):
                if self._playlist.track_at(i).get("path") == target:
                    self._playback_ctrl.play_track_at(i)
                    break

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
        import audio_player.ui.widgets.playlist_view as _pv
        _pv._current_file = filepath or ""
        # Use already-loaded metadata from playlist model
        meta = self._playlist.track_metadata(self._playlist.current_index)
        if meta is None:
            meta = read_metadata(filepath)
        self._metadata_panel.show_metadata(meta, filepath)
        title = meta.title or os.path.basename(filepath)
        artist = meta.artist or ""
        if artist:
            self._log_message(_("log.now_playing", artist=artist, title=title))
        else:
            self._log_message(_("log.now_playing_no_artist", title=title))
        self._fullscreen_lyrics.set_meta(meta)
        self._album_detail_page.set_current_playlist_index(self._playlist.current_index)
        # Bottom bar
        self._bar_update("set_track", meta.title or "", meta.artist or "", meta.album or "")
        self._bar_update("update_cover", meta.cover_data)
        # HiFi page (also serves as Now Playing overlay)
        self._hifi_page.set_track_info(meta.title or "", meta.artist or "", meta.album or "")
        self._hifi_page.set_cover(meta.cover_data)
        self._hifi_page.set_quality(self._build_quality_text(meta))
        # Dynamic accent from album art
        self._apply_album_accent(meta)

    def _apply_album_accent(self, meta):
        """Extract accent color from album art and apply it dynamically."""
        from audio_player.ui.color_extractor import extract_accent
        from audio_player.app import set_dynamic_accent
        cover_data = getattr(meta, 'cover_data', None)
        if cover_data:
            pix = QPixmap()
            pix.loadFromData(cover_data)
            if not pix.isNull():
                color = extract_accent(pix)
                set_dynamic_accent(color)
                # Don't refresh here — animation callbacks handle it

    def _on_metadata_loaded_ui(self, meta, filepath):
        self._metadata_panel.show_metadata(meta, filepath)

    def _on_position_changed(self, ms):
        self._bar_update("set_position", ms)
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
        self._bar_update("set_duration", ms)
        self._hifi_page.set_duration(ms)
        self._spectrum.lyrics_overlay.set_duration(ms)
        self._fullscreen_lyrics.set_duration(ms)

    def _show_output_detail(self):
        """Open the audio output detail dialog from the HiFi page."""
        from audio_player.ui.widgets.output_spec_bar import _OutputDetailDialog
        from audio_player.player.metadata import read_metadata
        from audio_player.app import current_theme_mode
        meta = read_metadata(self._engine.current_file) if self._engine.current_file else None
        info = self._engine.output_info
        is_light = current_theme_mode() == "light"
        dlg = _OutputDetailDialog(meta, info, is_light, self)
        dlg.exec()

    def _show_np_page(self):
        """Open Now Playing overlay with slide-up from bottom bar."""
        self._pill_wrapper.hide()  # hide pill during HiFi overlay
        if self._now_playing_bar.isVisible():
            self._now_playing_bar.hide()
            bar_global = self._now_playing_bar.mapToGlobal(QPoint(0, 0))
        else:
            bar_global = self.mapToGlobal(QPoint(0, self.height()))
        win_global = self.mapToGlobal(QPoint(0, 0))
        from_rect = QRect(win_global.x(), bar_global.y(),
                          self.width(), self.height())
        self._hifi_page.show()
        self._hifi_overlay.setCurrentWidget(self._hifi_page)
        # Slide-up animation via geometry
        to_rect = self.geometry()
        self._hifi_page.setGeometry(from_rect)
        anim = QPropertyAnimation(self._hifi_page, b"geometry")
        anim.setDuration(350)
        anim.setStartValue(from_rect)
        anim.setEndValue(to_rect)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._hifi_page._slide_anim = anim  # keep ref

    def _collapse_hifi(self):
        """Return from overlay to normal view."""
        s = QSettings("VBPlayer", "VB Player")
        style = str(s.value("playback_bar_style", "full") or "full")
        if style == "full":
            self._now_playing_bar.show()
        elif style == "pill":
            self._pill_wrapper.show()
            self._position_pill()
        self._hifi_overlay.setCurrentWidget(self._body)
        self._hifi_page.hide()

    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
            if self._use_frameless:
                self._title_bar.show()
            self._border_radius = 12
            self._mask_dirty = True
            self.update()
        else:
            if self._use_frameless:
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
        self._bar_update("refresh_theme")
        if hasattr(self, '_pls_grid_view'):
            self._pls_grid_view.refresh_theme_mode(is_light)
        if hasattr(self, '_pls_detail_page'):
            self._pls_detail_page.refresh_theme_mode(is_light)
        self._refresh_accent_colors()
        accent = current_accent()
        if hasattr(self, '_new_pls_btn'):
            self._new_pls_btn.setStyleSheet(
                f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
                f"border-radius:5px;padding:5px 12px;font-size:11px;}}"
                f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
            )

    def _init_blur(self):
        """Set up KWin blur if on KDE X11."""
        from audio_player.platform.linux.blur import KWinBlurEnabler
        self._blur_enabler = KWinBlurEnabler(self)
        self._blur_enabler.enable()

    def _on_material_changed(self, val: str):
        from audio_player.platform import platform_info
        if val and val != "auto":
            self._material = val
        else:
            self._material = platform_info.policy.material
        want = self._material in ("glass", "acrylic")
        if want != self._use_translucent:
            self._use_translucent = want
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, want)
        self.update()

    def _refresh_accent_colors(self):
        """Re-apply inline accent-dependent styles across all widgets."""
        self._sidebar.refresh_accent()
        self._refresh_manage_accent()
        self._bar_update("refresh_accent")
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
        if hasattr(self, '_output_spec_bar') and self._output_spec_bar is not None:
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
        self._position_pill()
        if self._blur_enabler:
            self._blur_enabler.update_rect()

    def showEvent(self, event):
        super().showEvent(event)
        self._mask_dirty = True
        self._position_pill()
        if self._blur_enabler:
            self._blur_enabler.enable()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._mask_dirty = True
            if self.isMaximized():
                self.clearMask()

    def _apply_mask(self):
        if not self._use_frameless:
            return  # CSD/native titlebar: compositor handles corners
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

    def _material_alpha(self) -> int:
        """Read user-configured alpha (0-255 scale) from QSettings percentage (70-100)."""
        s = QSettings("VBPlayer", "VB Player")
        user_val = s.value("material_alpha")
        if user_val is not None:
            pct = int(user_val)
            return int(pct * 255 / 100)
        # Defaults (percentage)
        if self._material == "acrylic":
            return int(92 * 255 / 100)  # 92%
        return int(84 * 255 / 100)  # 84%

    def _material_texture_opacity(self) -> float:
        """Read user-configured texture strength from QSettings."""
        if self._material != "acrylic":
            return 0.0
        s = QSettings("VBPlayer", "VB Player")
        user_val = s.value("material_texture")
        if user_val is not None:
            return int(user_val) / 100.0
        return 0.10

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Window)

        if self._use_translucent and self._material in ("glass", "acrylic"):
            alpha = self._material_alpha()
            base = QColor(base.red(), base.green(), base.blue(), alpha)

        if self._use_frameless and self._border_radius > 0 and not self.isMaximized() and not self.isFullScreen():
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._border_radius, self._border_radius)
            painter.fillPath(path, base)
        else:
            painter.fillRect(self.rect(), base)

        # Acrylic noise texture (no accent tint)
        if self._material == "acrylic" and self._use_translucent:
            tex_opacity = self._material_texture_opacity()
            if tex_opacity > 0:
                if self._noise_pixmap is None or self._noise_pixmap.width() < self.width() or \
                   self._noise_pixmap.height() < self.height():
                    self._noise_pixmap = self._generate_noise(self.width(), self.height())
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
                painter.setOpacity(tex_opacity)
                painter.drawPixmap(0, 0, self._noise_pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.setOpacity(1.0)

        painter.end()
        if self._mask_dirty:
            self._mask_dirty = False
            self._apply_mask()

    def _acrylic_gradient(self, w: int, h: int, accent: QColor, is_light: bool):
        """Radial gradient from top-left simulating frosted glass light scatter."""
        from PyQt6.QtGui import QRadialGradient
        grad = QRadialGradient(w * 0.2, h * 0.15, max(w, h) * 0.7)
        if is_light:
            # Light theme: subtle darker edges
            grad.setColorAt(0.0, QColor(255, 255, 255, 40))
            grad.setColorAt(0.6, QColor(255, 255, 255, 10))
            grad.setColorAt(1.0, QColor(0, 0, 0, 25))
        else:
            # Dark theme: subtle lighter center, darker edges
            grad.setColorAt(0.0, QColor(255, 255, 255, 35))
            grad.setColorAt(0.5, QColor(255, 255, 255, 8))
            grad.setColorAt(1.0, QColor(0, 0, 0, 50))
        return grad

    def _generate_noise(self, w: int, h: int):
        """Fine native-resolution grain for SoftLight blending.

        Full 0–255 range for maximum entropy (no banding),
        centered on 128 (SoftLight neutral). Opacity controls strength.
        """
        import numpy as np
        from PyQt6.QtGui import QImage

        rng = np.random.default_rng(42)
        noise = rng.integers(0, 256, (h, w), dtype=np.uint8)
        data = noise.tobytes()
        img = QImage(data, w, h, w, QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(img)

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

