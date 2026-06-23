import sys
import base64
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QComboBox, QCheckBox, QSlider,
                             QPushButton, QGroupBox, QFormLayout,
                             QListWidget, QListWidgetItem, QScrollArea,
                             QSpinBox, QAbstractItemView, QGridLayout, QFrame,
                             QLineEdit, QFileDialog)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QRectF, QTimer, QBuffer, QByteArray
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QRegion, QPixmap, QIcon

from audio_player.ui.widgets.equalizer_widget import EqualizerWidget
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.player.equalizer import PRESETS
from audio_player.i18n import _, set_language, current_lang, languageChanged
from audio_player.app import current_accent
from audio_player.ui.widgets.frameless_resize import FramelessResizeMixin


def _obfuscate(text: str) -> str:
    """XOR + base64 obfuscation for sensitive settings (not encryption)."""
    if not text:
        return ""
    key = b"VBPlayerSettings"
    data = text.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(xored).decode("ascii")


def _deobfuscate(text: str) -> str:
    """Reverse _obfuscate."""
    if not text:
        return ""
    key = b"VBPlayerSettings"
    try:
        data = base64.b64decode(text.encode("ascii"))
        xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return xored.decode("utf-8")
    except Exception as e:
        import sys; print(f"[settings] 解密失败: {e}", file=sys.stderr)
        return text


class _AccentSwatch(QPushButton):
    selected = pyqtSignal(str)

    def __init__(self, name: str, color: QColor, size=28):
        super().__init__()
        self._name = name
        self._color = color
        self._selected = False
        self.setFixedSize(size + 8, size + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: self.selected.emit(name))
        self.setStyleSheet("border:2px solid transparent;border-radius:16px;background:transparent;")

    def set_selected(self, sel: bool):
        self._selected = sel
        border = "#ffffff" if sel else "transparent"
        self.setStyleSheet(
            f"border:2px solid {border};border-radius:{self.width()//2}px;background:transparent;"
        )

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2
        r = (self.width() - 8) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(cx - r, cx - r, r * 2, r * 2)
        if self._selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(self._color.lighter(200))
            p.drawEllipse(cx - r - 1, cx - r - 1, r * 2 + 2, r * 2 + 2)
        p.end()


class _CloseButton(QPushButton):
    """Clean circular close button with painted X icon."""

    def __init__(self, size=32):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self.setStyleSheet("background:transparent;border:none;")

    def enterEvent(self, ev):
        self._hovered = True
        self.update()

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        cx = w // 2
        r = (w - 4) // 2
        top = cx - r

        if self._hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 25))
            p.drawEllipse(top, top, r * 2, r * 2)

        pen_color = QColor("#e2e8f0") if self._hovered else QColor("#64748b")
        p.setPen(pen_color)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = 9
        x1 = top + inset
        x2 = cx + r - inset
        p.drawLine(x1, x1, x2, x2)
        p.drawLine(x2, x1, x1, x2)
        p.end()



class _NoWheelList(QListWidget):
    """QListWidget that ignores mouse wheel events to prevent accidental page switches."""
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel to prevent accidental value changes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelSlider(QSlider):
    """QSlider that ignores mouse wheel to prevent accidental value changes."""
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel to prevent accidental selection changes."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, event):
        event.ignore()


from audio_player.platform import platform_info


_SettingsBase = (FramelessResizeMixin, QDialog) if platform_info.policy.titlebar_style == "frameless" else (QDialog,)


class SettingsDialog(*_SettingsBase):
    themeChanged = pyqtSignal(str, str)  # mode, accent_name
    vizModeChanged = pyqtSignal(int)
    defaultVolumeChanged = pyqtSignal(float)
    borderRadiusChanged = pyqtSignal(int)
    uiRadiusChanged = pyqtSignal(int)
    lyricsToggled = pyqtSignal(bool)
    lyricsLineHeightChanged = pyqtSignal(int)
    lyricsFullscreenLineHeightChanged = pyqtSignal(int)
    lyricsFontSizeChanged = pyqtSignal(int)
    lyricsLetterSpacingChanged = pyqtSignal(int)
    lyricsShowSpecToggled = pyqtSignal(bool)
    sidebarLogToggled = pyqtSignal(bool)
    albumCoverRadiusToggled = pyqtSignal(bool)

    # Equalizer signals
    eqBandChanged = pyqtSignal(int, float)
    eqPresetSelected = pyqtSignal(str)
    eqResetRequested = pyqtSignal()
    eqEnabledToggled = pyqtSignal(bool)
    reloadRequested = pyqtSignal()
    exclusiveModeToggled = pyqtSignal(bool)
    exclusiveDeviceChanged = pyqtSignal(str)
    dsdModeChanged = pyqtSignal(str)
    replaygainToggled = pyqtSignal(bool)
    gaplessToggled = pyqtSignal(bool)
    languageChanged = pyqtSignal(str)
    onlineLyricsToggled = pyqtSignal(bool)
    autoSaveLyricsToggled = pyqtSignal(bool)
    showTranslationToggled = pyqtSignal(bool)
    titlebarChanged = pyqtSignal(str)
    materialChanged = pyqtSignal(str)
    dynamicAccentToggled = pyqtSignal(bool)
    barStyleChanged = pyqtSignal(str)

    THEME_MODES = {"dark": "深色 (Dark)", "light": "浅色 (Light)"}
    ACCENTS = {
        "purple": QColor("#7c3aed"),
        "blue":   QColor("#007AFF"),
        "green":  QColor("#10b981"),
        "orange": QColor("#f59e0b"),
        "pink":   QColor("#ec4899"),
        "red":    QColor("#ef4444"),
    }
    VIZ_MODES = {0: "柱状图 (Bars)", 1: "折线图 (Line)", 2: "圆形 (Circular)"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("settings.window_title"))
        self.setMinimumSize(560, 520)
        self.resize(600, 660)
        if platform_info.policy.titlebar_style == "frameless":
            self.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self._border_radius = 12
        self._mask_dirty = True
        self._settings = QSettings("VBPlayer", "VB Player")
        self._setup_ui()
        self._load_settings()
        # Connect signals AFTER loading saved values to avoid overwriting QSettings on init
        self._titlebar_combo.currentIndexChanged.connect(self._on_titlebar_changed)
        self._material_combo.currentIndexChanged.connect(self._on_material_changed)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if platform_info.policy.titlebar_style == "frameless" and self._border_radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._border_radius, self._border_radius)
            painter.fillPath(path, self.palette().color(QPalette.ColorRole.Window))
        else:
            painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        painter.end()
        if self._mask_dirty:
            self._mask_dirty = False
            self._apply_mask()

    def _apply_mask(self):
        if platform_info.policy.titlebar_style != "frameless":
            return
        r = self._border_radius
        w, h = self.width(), self.height()
        if r > 0 and w > 0 and h > 0:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._mask_dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        self._mask_dirty = True

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Custom drag handle
        drag_bar = QWidget()
        self._drag_bar = drag_bar
        drag_bar.setFixedHeight(40)
        def _on_drag(e):
            if e.button() == Qt.MouseButton.LeftButton and self.windowHandle():
                self.windowHandle().startSystemMove()
        drag_bar.mousePressEvent = _on_drag
        drag_layout = QHBoxLayout(drag_bar)
        drag_layout.setContentsMargins(16, 0, 10, 0)
        drag_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._drag_label = QLabel(_("settings.window_title"))
        self._drag_label.setStyleSheet("color:#94a3b8;font-size:13px;font-weight:500;")
        drag_layout.addWidget(self._drag_label)
        drag_layout.addStretch()
        close_btn = _CloseButton()
        close_btn.clicked.connect(self.reject)
        drag_layout.addWidget(close_btn)
        outer.addWidget(drag_bar)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left navigation list (vertical, text horizontal)
        self._nav_list = _NoWheelList()
        self._nav_list.setFixedWidth(100)
        self._nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_nav_style()
        self._nav_labels = ["settings.general", "settings.account", "settings.appearance",
                           "settings.lyrics_tab", "settings.playback",
                           "settings.advanced", "settings.about"]
        for key in self._nav_labels:
            item = QListWidgetItem(_(key))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._nav_list.addItem(item)
        self._nav_list.setCurrentRow(0)

        # Right stacked pages
        self._pages = AnimatedStackedWidget()
        self._pages.addWidget(self._build_general_tab())
        self._pages.addWidget(self._build_account_tab())
        self._pages.addWidget(self._build_appearance_tab())
        self._pages.addWidget(self._build_lyrics_tab())
        self._pages.addWidget(self._build_playback_tab())
        self._pages.addWidget(self._build_advanced_tab())
        self._pages.addWidget(self._build_about_tab())

        self._nav_list.currentRowChanged.connect(self._pages.setCurrentIndex)

        main_layout.addWidget(self._nav_list)
        main_layout.addWidget(self._pages, 1)

        outer.addLayout(main_layout)

    LANGUAGES = {
        "zh_CN": "简体中文",
        "zh_TW": "繁體中文",
        "en": "English",
        "ja": "日本語",
    }

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._lang_group = QGroupBox(_("settings.language"))
        lang_layout = QVBoxLayout(self._lang_group)
        self._lang_combo = _NoWheelComboBox()
        for code, name in self.LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._lang_combo)
        layout.addWidget(self._lang_group)

        # Close to tray
        self._tray_cb = QCheckBox(_("settings.close_to_tray"))
        self._tray_cb.setChecked(True)
        self._tray_cb.toggled.connect(self._on_tray_toggled)
        layout.addWidget(self._tray_cb)

        layout.addStretch()

        ok = QPushButton(_("settings.ok"))
        ok.setFixedWidth(80)
        ok.setStyleSheet(
            f"QPushButton{{background:{current_accent().name()};color:#fff;border:none;"
            "border-radius:4px;padding:8px;font-size:13px;}}"
            f"QPushButton:hover{{background:{current_accent().lighter(115).name()};}}"
        )
        ok.clicked.connect(self._save_and_close)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        return w

    def _on_tray_toggled(self, checked: bool):
        self._settings.setValue("close_to_tray", checked)

    def _on_language_changed(self):
        code = self._lang_combo.currentData()
        if code and code != current_lang():
            self._settings.setValue("language", code)
            set_language(code)
            self._refresh_all_labels()
            self.languageChanged.emit(code)

    def _refresh_all_labels(self):
        """Refresh all translatable labels after language change."""
        # Nav list
        for i, key in enumerate(self._nav_labels):
            item = self._nav_list.item(i)
            if item:
                item.setText(_(key))
        # Tab group boxes
        self._lang_group.setTitle(_("settings.language"))
        if hasattr(self, '_avatar_hint'):
            self._avatar_hint.setText(_("settings.avatar_hint"))
        if hasattr(self, '_theme_group'):
            self._theme_group.setTitle(_("settings.theme"))
        if hasattr(self, '_accent_group'):
            self._accent_group.setTitle(_("settings.accent"))
        self._window_radius_group.setTitle(_("settings.window_radius"))
        self._ui_radius_group.setTitle(_("settings.ui_radius"))
        self._lyrics_group.setTitle(_("settings.lyrics_display"))
        self._lyrics_cb.setText(_("settings.lyrics_enable"))
        self._lyrics_fullscreen_group.setTitle(_("settings.lyrics_fullscreen_group"))
        self._lyrics_show_spec_cb.setText(_("settings.lyrics_audio_spec"))
        # Online lyrics tab
        self._online_lyrics_group.setTitle(_("settings.online_lyrics"))
        self._online_lyrics_cb.setText(_("settings.enable_online_lyrics"))
        self._lrclib_cb.setText(_("settings.source_lrclib"))
        self._custom_api_cb.setText(_("settings.source_custom_api"))
        self._custom_url_input.setPlaceholderText(_("settings.custom_url_placeholder"))
        self._custom_token_input.setPlaceholderText(_("settings.custom_token_placeholder"))
        self._auto_save_cb.setText(_("settings.auto_save_lyrics"))
        self._show_translation_cb.setText(_("settings.show_translation"))
        self._test_conn_btn.setText(_("settings.test_connection"))
        self._cover_group.setTitle(_("settings.album_cover"))
        self._cover_cb.setText(_("settings.cover_radius"))
        if hasattr(self, '_dynamic_group'):
            self._dynamic_group.setTitle(_("settings.dynamic_accent"))
            self._dynamic_cb.setText(_("settings.dynamic_accent_enable"))
        if hasattr(self, '_titlebar_group'):
            self._titlebar_group.setTitle(_("settings.titlebar_style"))
        if hasattr(self, '_material_group'):
            self._material_group.setTitle(_("settings.material_effect"))
        self._viz_group.setTitle(_("settings.visualization"))
        self._viz_combo.clear()
        for label in [_("viz.bars"), _("viz.line"), _("viz.circular")]:
            self._viz_combo.addItem(label)
        self._vol_group.setTitle(_("settings.default_volume"))
        self._eq_group.setTitle(_("settings.equalizer"))
        self._exclusive_cb.setText(_("settings.exclusive_mode"))
        self._exclusive_cb.setToolTip(_("settings.exclusive_tooltip"))
        self._sidebar_log_cb.setText(_("settings.sidebar_log"))
        # DSD combo
        self._dsd_combo.blockSignals(True)
        self._dsd_combo.clear()
        self._dsd_combo.addItem(_("settings.dsd_pcm"), "pcm")
        from audio_player.platform import platform_info
        if platform_info.capabilities.supports_dsd_native:
            self._dsd_combo.addItem(_("settings.dsd_native"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop"), "dop")
        else:
            self._dsd_combo.addItem(_("settings.dsd_native") + "  " + _("settings.dsd_windows_only"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop") + "  " + _("settings.dsd_windows_only"), "dop")
            self._dsd_combo.model().item(1).setEnabled(False)
            self._dsd_combo.model().item(2).setEnabled(False)
        self._dsd_combo.setToolTip(_("settings.dsd_tooltip"))
        self._dsd_combo.blockSignals(False)
        # Drag bar
        self._drag_label.setText(_("settings.window_title"))
        self._refresh_about_labels()

    def _build_account_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Avatar
        avatar_group = QGroupBox(_("settings.avatar"))
        avatar_layout = QVBoxLayout(avatar_group)
        avatar_row = QHBoxLayout()
        avatar_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._avatar_btn = QPushButton()
        self._avatar_btn.setFixedSize(96, 96)
        self._avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._avatar_btn.clicked.connect(self._pick_avatar)
        self._avatar_btn.setStyleSheet(
            "QPushButton{background:transparent;border:2px dashed #444;border-radius:48px;}"
            "QPushButton:hover{border-color:#888;}"
        )
        avatar_row.addWidget(self._avatar_btn)
        avatar_layout.addLayout(avatar_row)

        self._avatar_hint = QLabel(_("settings.avatar_hint"))
        self._avatar_hint.setObjectName("subLabel")
        self._avatar_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_layout.addWidget(self._avatar_hint)
        layout.addWidget(avatar_group)

        # Username
        name_group = QGroupBox(_("settings.username"))
        name_layout = QVBoxLayout(name_group)
        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText(_("settings.username_placeholder"))
        self._username_input.textChanged.connect(self._on_username_changed)
        name_layout.addWidget(self._username_input)
        layout.addWidget(name_group)

        # Stats
        stats_group = QGroupBox(_("settings.stats"))
        stats_layout = QFormLayout(stats_group)
        stats_layout.setSpacing(8)
        self._stat_tracks = QLabel("0")
        self._stat_albums = QLabel("0")
        self._stat_playlists = QLabel("0")
        stats_layout.addRow(_("settings.stat_tracks"), self._stat_tracks)
        stats_layout.addRow(_("settings.stat_albums"), self._stat_albums)
        stats_layout.addRow(_("settings.stat_playlists"), self._stat_playlists)
        layout.addWidget(stats_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _pick_avatar(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _("settings.avatar_pick"), "",
            _("settings.avatar_filter")
        )
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._avatar_pixmap = pix
                self._apply_avatar()
                # Save to QSettings as base64
                import base64
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QBuffer.OpenModeFlag.WriteOnly)
                pix.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation).save(buf, "PNG")
                self._settings.setValue("account_avatar", base64.b64encode(ba.data()).decode())

    def _apply_avatar(self):
        if hasattr(self, '_avatar_pixmap') and not self._avatar_pixmap.isNull():
            scaled = self._avatar_pixmap.scaled(88, 88,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
            icon = QIcon(scaled)
            self._avatar_btn.setIcon(icon)
            self._avatar_btn.setIconSize(scaled.size())
            self._avatar_btn.setStyleSheet(
                "QPushButton{background:transparent;border:2px solid #444;border-radius:48px;}"
                "QPushButton:hover{border-color:#888;}"
            )

    def _on_username_changed(self, text: str):
        self._settings.setValue("account_username", text.strip())
        self._refresh_drag_label()

    def _refresh_drag_label(self):
        name = str(self._settings.value("account_username", "") or "")
        if name:
            self._drag_label.setText(f"VB Player — {name}")
        else:
            self._drag_label.setText(_("settings.window_title"))

    def set_account_stats(self, tracks: int, albums: int, playlists: int):
        self._stat_tracks.setText(str(tracks))
        self._stat_albums.setText(str(albums))
        self._stat_playlists.setText(str(playlists))

    def _build_appearance_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Theme mode
        self._theme_group = QGroupBox(_("settings.theme"))
        mode_layout = QVBoxLayout(self._theme_group)
        self._mode_combo = _NoWheelComboBox()
        for k in self.THEME_MODES:
            self._mode_combo.addItem(_(f"theme.{k}"), k)
        self._mode_combo.currentIndexChanged.connect(self._emit_theme)
        mode_layout.addWidget(self._mode_combo)
        layout.addWidget(self._theme_group)

        # Accent color
        self._accent_group = QGroupBox(_("settings.accent"))
        accent_layout = QGridLayout(self._accent_group)
        accent_layout.setSpacing(6)
        self._accent_swatches: dict[str, _AccentSwatch] = {}
        row, col = 0, 0
        for name, color in self.ACCENTS.items():
            sw = _AccentSwatch(name, color)
            sw.selected.connect(self._on_accent_picked)
            accent_layout.addWidget(sw, row, col)
            self._accent_swatches[name] = sw
            col += 1
            if col >= 3:
                col = 0
                row += 1
        layout.addWidget(self._accent_group)

        # Window corner radius
        self._window_radius_group = QGroupBox(_("settings.window_radius"))
        win_radius_layout = QHBoxLayout(self._window_radius_group)
        self._border_radius_spin = _NoWheelSpinBox()
        self._border_radius_spin.setRange(0, 20)
        self._border_radius_spin.setSuffix(" px")
        self._border_radius_spin.setValue(0)
        self._radius_label = QLabel(_("settings.radius_label"))
        win_radius_layout.addWidget(self._radius_label)
        win_radius_layout.addWidget(self._border_radius_spin, 1)
        layout.addWidget(self._window_radius_group)

        # UI corner radius
        self._ui_radius_group = QGroupBox(_("settings.ui_radius"))
        ui_radius_layout = QHBoxLayout(self._ui_radius_group)
        self._ui_radius_spin = _NoWheelSpinBox()
        self._ui_radius_spin.setRange(0, 24)
        self._ui_radius_spin.setSuffix(" px")
        self._ui_radius_spin.setValue(12)
        self._ui_radius_label = QLabel(_("settings.radius_label"))
        ui_radius_layout.addWidget(self._ui_radius_label)
        ui_radius_layout.addWidget(self._ui_radius_spin, 1)
        layout.addWidget(self._ui_radius_group)

        # Album cover rounded corners
        self._cover_group = QGroupBox(_("settings.album_cover"))
        cover_layout = QVBoxLayout(self._cover_group)
        self._cover_cb = QCheckBox(_("settings.cover_radius"))
        self._album_cover_radius_cb = self._cover_cb  # alias for old code
        self._cover_cb.setChecked(True)
        self._cover_cb.toggled.connect(self.albumCoverRadiusToggled)
        cover_layout.addWidget(self._cover_cb)
        layout.addWidget(self._cover_group)

        # Dynamic accent from album art
        self._dynamic_group = QGroupBox(_("settings.dynamic_accent"))
        dyn_layout = QVBoxLayout(self._dynamic_group)
        self._dynamic_cb = QCheckBox(_("settings.dynamic_accent_enable"))
        self._dynamic_cb.setChecked(True)
        self._dynamic_cb.toggled.connect(self._on_dynamic_accent_toggled)
        dyn_layout.addWidget(self._dynamic_cb)
        layout.addWidget(self._dynamic_group)

        # ── Titlebar style (requires restart) ──
        self._titlebar_group = QGroupBox(_("settings.titlebar_style"))
        tb_layout = QVBoxLayout(self._titlebar_group)
        self._titlebar_combo = _NoWheelComboBox()
        self._titlebar_combo.addItem(_("settings.titlebar_auto"), "auto")
        self._titlebar_combo.addItem(_("settings.titlebar_frameless"), "frameless")
        self._titlebar_combo.addItem(_("settings.titlebar_csd"), "csd")
        self._titlebar_combo.addItem(_("settings.titlebar_native"), "native")
        tb_layout.addWidget(self._titlebar_combo)
        self._titlebar_note = QLabel(_("settings.titlebar_restart_note"))
        self._titlebar_note.setObjectName("subLabel")
        tb_layout.addWidget(self._titlebar_note)
        layout.addWidget(self._titlebar_group)

        # ── Material effect (live preview) ──
        self._material_group = QGroupBox(_("settings.material_effect"))
        mat_layout = QVBoxLayout(self._material_group)
        self._material_combo = _NoWheelComboBox()
        self._material_combo.addItem(_("settings.material_auto"), "auto")
        self._material_combo.addItem(_("settings.material_acrylic"), "acrylic")
        self._material_combo.addItem(_("settings.material_glass"), "glass")
        self._material_combo.addItem(_("settings.material_none"), "none")
        mat_layout.addWidget(self._material_combo)
        self._material_note = QLabel(_("settings.material_desc"))
        self._material_note.setObjectName("subLabel")
        mat_layout.addWidget(self._material_note)

        # Opacity slider (applies to glass & acrylic)
        mat_layout.addSpacing(8)
        self._opacity_label = QLabel(_("settings.material_opacity"))
        mat_layout.addWidget(self._opacity_label)
        self._opacity_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(70, 100)
        self._opacity_slider.setValue(84)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._opacity_slider.sliderReleased.connect(self._emit_material_live)
        mat_layout.addWidget(self._opacity_slider)

        # Texture slider (acrylic only)
        self._texture_label = QLabel(_("settings.material_texture"))
        mat_layout.addWidget(self._texture_label)
        self._texture_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._texture_slider.setRange(0, 30)
        self._texture_slider.setValue(10)
        self._texture_slider.valueChanged.connect(self._on_texture_changed)
        self._texture_slider.sliderReleased.connect(self._emit_material_live)
        mat_layout.addWidget(self._texture_slider)

        layout.addWidget(self._material_group)

        # ── Playback bar style ──
        self._barstyle_group = QGroupBox(_("settings.bar_style"))
        bar_layout = QVBoxLayout(self._barstyle_group)
        self._barstyle_combo = _NoWheelComboBox()
        self._barstyle_combo.addItem(_("settings.bar_full"), "full")
        self._barstyle_combo.addItem(_("settings.bar_pill"), "pill")
        self._barstyle_combo.currentIndexChanged.connect(self._on_barstyle_changed)
        bar_layout.addWidget(self._barstyle_combo)

        # Pill progress style (only shown for pill)
        self._pill_progress_combo = _NoWheelComboBox()
        self._pill_progress_combo.addItem(_("settings.pill_progress_line"), "line")
        self._pill_progress_combo.addItem(_("settings.pill_progress_ring"), "ring")
        self._pill_progress_combo.currentIndexChanged.connect(self._on_pill_progress_changed)
        bar_layout.addWidget(self._pill_progress_combo)

        layout.addWidget(self._barstyle_group)

        # ── Current track highlight style ──
        self._highlight_group = QGroupBox(_("settings.highlight_style"))
        hl_layout = QVBoxLayout(self._highlight_group)
        self._highlight_combo = _NoWheelComboBox()
        self._highlight_combo.addItem(_("settings.highlight_glow"), "glow")
        self._highlight_combo.addItem(_("settings.highlight_bar"), "bar")
        self._highlight_combo.currentIndexChanged.connect(self._on_highlight_changed)
        hl_layout.addWidget(self._highlight_combo)
        layout.addWidget(self._highlight_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_lyrics_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # === Online lyrics section ===
        self._online_lyrics_group = QGroupBox(_("settings.online_lyrics"))
        online_layout = QVBoxLayout(self._online_lyrics_group)

        self._online_lyrics_cb = QCheckBox(_("settings.enable_online_lyrics"))
        self._online_lyrics_cb.setChecked(False)
        self._online_lyrics_cb.toggled.connect(self.onlineLyricsToggled)
        online_layout.addWidget(self._online_lyrics_cb)

        # Source checkboxes
        self._lrclib_cb = QCheckBox(_("settings.source_lrclib"))
        self._lrclib_cb.setChecked(True)
        online_layout.addWidget(self._lrclib_cb)

        self._custom_api_cb = QCheckBox(_("settings.source_custom_api"))
        self._custom_api_cb.setChecked(False)
        self._custom_api_cb.toggled.connect(self._on_custom_api_toggled)
        online_layout.addWidget(self._custom_api_cb)

        # Custom API fields (shown only when custom checkbox checked)
        self._custom_api_widget = QWidget()
        custom_form = QFormLayout(self._custom_api_widget)
        custom_form.setContentsMargins(24, 0, 0, 0)
        self._custom_url_input = QLineEdit()
        self._custom_url_input.setPlaceholderText(_("settings.custom_url_placeholder"))
        custom_form.addRow(_("settings.custom_url"), self._custom_url_input)
        self._custom_token_input = QLineEdit()
        self._custom_token_input.setPlaceholderText(_("settings.custom_token_placeholder"))
        self._custom_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        custom_form.addRow(_("settings.custom_token"), self._custom_token_input)

        self._test_conn_btn = QPushButton(_("settings.test_connection"))
        self._test_conn_btn.clicked.connect(self._on_test_connection)
        custom_form.addRow("", self._test_conn_btn)

        self._custom_api_widget.setVisible(False)
        online_layout.addWidget(self._custom_api_widget)

        layout.addWidget(self._online_lyrics_group)

        # Auto-save and translation toggles
        self._auto_save_cb = QCheckBox(_("settings.auto_save_lyrics"))
        self._auto_save_cb.setChecked(False)
        self._auto_save_cb.toggled.connect(self.autoSaveLyricsToggled)
        layout.addWidget(self._auto_save_cb)

        self._show_translation_cb = QCheckBox(_("settings.show_translation"))
        self._show_translation_cb.setChecked(True)
        self._show_translation_cb.toggled.connect(self.showTranslationToggled)
        layout.addWidget(self._show_translation_cb)

        # === Lyrics display settings (moved from Appearance) ===
        self._lyrics_group = QGroupBox(_("settings.lyrics_display"))
        lyrics_layout = QVBoxLayout(self._lyrics_group)

        self._lyrics_cb = QCheckBox(_("settings.lyrics_enable"))
        self._lyrics_cb.setChecked(True)
        self._lyrics_cb.toggled.connect(self.lyricsToggled)
        lyrics_layout.addWidget(self._lyrics_cb)

        lyrics_overlay_row = QHBoxLayout()
        lyrics_overlay_row.addWidget(QLabel(_("settings.lyrics_height")))
        self._lyrics_overlay_height_spin = _NoWheelSpinBox()
        self._lyrics_overlay_height_spin.setRange(24, 72)
        self._lyrics_overlay_height_spin.setSuffix(" px")
        self._lyrics_overlay_height_spin.setValue(40)
        self._lyrics_overlay_height_spin.valueChanged.connect(
            lambda v: self.lyricsLineHeightChanged.emit(v))
        lyrics_overlay_row.addWidget(self._lyrics_overlay_height_spin, 1)
        lyrics_layout.addLayout(lyrics_overlay_row)
        layout.addWidget(self._lyrics_group)

        # === Fullscreen lyrics settings (moved from Appearance) ===
        self._lyrics_fullscreen_group = QGroupBox(_("settings.lyrics_fullscreen_group"))
        lyrics_fs_grid = QFormLayout(self._lyrics_fullscreen_group)
        lyrics_fs_grid.setSpacing(8)

        self._lyrics_font_size_spin = _NoWheelSpinBox()
        self._lyrics_font_size_spin.setRange(16, 72)
        self._lyrics_font_size_spin.setSuffix(" pt")
        self._lyrics_font_size_spin.setValue(32)
        self._lyrics_font_size_spin.valueChanged.connect(
            lambda v: self.lyricsFontSizeChanged.emit(v))
        lyrics_fs_grid.addRow(_("settings.lyrics_font_size"), self._lyrics_font_size_spin)

        self._lyrics_fs_line_height_spin = _NoWheelSpinBox()
        self._lyrics_fs_line_height_spin.setRange(30, 120)
        self._lyrics_fs_line_height_spin.setSuffix(" px")
        self._lyrics_fs_line_height_spin.setValue(60)
        self._lyrics_fs_line_height_spin.valueChanged.connect(
            lambda v: self.lyricsFullscreenLineHeightChanged.emit(v))
        lyrics_fs_grid.addRow(_("settings.lyrics_height"), self._lyrics_fs_line_height_spin)

        self._lyrics_letter_spacing_spin = _NoWheelSpinBox()
        self._lyrics_letter_spacing_spin.setRange(0, 20)
        self._lyrics_letter_spacing_spin.setSuffix(" px")
        self._lyrics_letter_spacing_spin.setValue(2)
        self._lyrics_letter_spacing_spin.valueChanged.connect(
            lambda v: self.lyricsLetterSpacingChanged.emit(v))
        lyrics_fs_grid.addRow(_("settings.lyrics_letter_spacing"), self._lyrics_letter_spacing_spin)

        self._lyrics_show_spec_cb = QCheckBox(_("settings.lyrics_audio_spec"))
        self._lyrics_show_spec_cb.setChecked(True)
        self._lyrics_show_spec_cb.toggled.connect(self.lyricsShowSpecToggled)
        lyrics_fs_grid.addRow(self._lyrics_show_spec_cb)

        layout.addWidget(self._lyrics_fullscreen_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _on_custom_api_toggled(self, checked: bool):
        self._custom_api_widget.setVisible(checked)

    def _on_test_connection(self):
        url = self._custom_url_input.text().strip()
        if not url:
            self._test_conn_btn.setText(_("settings.test_fail"))
            return
        self._test_conn_btn.setEnabled(False)
        self._test_conn_btn.setText(_("settings.test_running"))
        token = self._custom_token_input.text().strip()

        from PyQt6.QtCore import QThread, pyqtSignal as _Signal

        class _TestWorker(QThread):
            ok = _Signal()
            fail = _Signal()

            def run(self_):
                import urllib.request
                import json
                test_url = f"{url.rstrip('/')}?track_name=test&artist_name=test&duration=0"
                headers = {"User-Agent": "VBPlayer/1.0"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                req = urllib.request.Request(test_url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        json.loads(resp.read().decode("utf-8"))
                    self_.ok.emit()
                except Exception as e:
                    import sys; print(f"[settings] 更新检查失败: {e}", file=sys.stderr)
                    self_.fail.emit()

        self._test_worker = _TestWorker(self)
        self._test_worker.ok.connect(lambda: (
            self._test_conn_btn.setText(_("settings.test_ok")),
            self._test_conn_btn.setEnabled(True),
        ))
        self._test_worker.fail.connect(lambda: (
            self._test_conn_btn.setText(_("settings.test_fail")),
            self._test_conn_btn.setEnabled(True),
        ))
        self._test_worker.start()

    def _build_playback_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._viz_group = QGroupBox(_("settings.visualization"))
        viz_layout = QFormLayout(self._viz_group)
        self._viz_combo = _NoWheelComboBox()
        for idx in self.VIZ_MODES:
            self._viz_combo.addItem(_(f"viz.{['bars','line','circular'][idx]}"), idx)
        self._viz_combo.currentIndexChanged.connect(self._on_viz)
        viz_layout.addRow(self._viz_combo)
        layout.addWidget(self._viz_group)

        self._vol_group = QGroupBox(_("settings.default_volume"))
        vol_row = QHBoxLayout(self._vol_group)
        self._vol_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.valueChanged.connect(lambda v: self._vol_label.setText(f"{v}%"))
        vol_row.addWidget(self._vol_slider, 1)
        self._vol_label = QLabel("100%")
        self._vol_label.setFixedWidth(36)
        vol_row.addWidget(self._vol_label)
        layout.addWidget(self._vol_group)

        # Equalizer
        self._eq_group = QGroupBox(_("settings.equalizer"))
        eq_layout = QVBoxLayout(self._eq_group)
        eq_layout.setContentsMargins(0, 8, 0, 0)
        self._eq_widget = EqualizerWidget()
        self._eq_widget.bandChanged.connect(self.eqBandChanged)
        self._eq_widget.presetSelected.connect(self._on_eq_preset_local)
        self._eq_widget.resetRequested.connect(self._on_eq_reset_local)
        self._eq_widget.enabledToggled.connect(self.eqEnabledToggled)
        eq_layout.addWidget(self._eq_widget)
        layout.addWidget(self._eq_group, 1)

        # Audio output
        self._rg_cb = QCheckBox(_("settings.replaygain"))
        self._rg_cb.setToolTip(_("settings.replaygain_tooltip"))
        self._rg_cb.toggled.connect(self.replaygainToggled)
        layout.addWidget(self._rg_cb)

        self._gapless_cb = QCheckBox(_("settings.gapless"))
        self._gapless_cb.setToolTip(_("settings.gapless_tooltip"))
        self._gapless_cb.toggled.connect(self.gaplessToggled)
        layout.addWidget(self._gapless_cb)

        out_group = QGroupBox(_("settings.exclusive_mode"))
        out_layout = QVBoxLayout(out_group)

        self._exclusive_cb = QCheckBox(_("settings.exclusive_mode"))
        self._exclusive_cb.setToolTip(_("settings.exclusive_tooltip"))
        self._exclusive_cb.toggled.connect(self._on_exclusive_toggled)
        out_layout.addWidget(self._exclusive_cb)

        self._device_combo = _NoWheelComboBox()
        self._device_combo.setEnabled(False)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        out_layout.addWidget(self._device_combo)

        self._dsd_combo = _NoWheelComboBox()
        self._dsd_combo.addItem(_("settings.dsd_pcm"), "pcm")
        from audio_player.platform import platform_info
        if platform_info.capabilities.supports_dsd_native:
            self._dsd_combo.addItem(_("settings.dsd_native"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop"), "dop")
        else:
            self._dsd_combo.addItem(_("settings.dsd_native") + "  " + _("settings.dsd_windows_only"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop") + "  " + _("settings.dsd_windows_only"), "dop")
            self._dsd_combo.model().item(1).setEnabled(False)
            self._dsd_combo.model().item(2).setEnabled(False)
        self._dsd_combo.setToolTip(_("settings.dsd_tooltip"))
        self._dsd_combo.currentIndexChanged.connect(self._on_dsd_mode_changed)
        out_layout.addWidget(self._dsd_combo)

        layout.addWidget(out_group)

        reload_btn = QPushButton(_("manage.reload_albums"))
        accent = current_accent()
        reload_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:5px;"
            f"padding:8px;font-size:13px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        reload_btn.clicked.connect(self.reloadRequested)
        layout.addWidget(reload_btn)

        scroll.setWidget(w)
        return scroll

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        log_group = QGroupBox(_("settings.sidebar_log"))
        log_layout = QVBoxLayout(log_group)
        self._sidebar_log_cb = QCheckBox(_("settings.sidebar_log"))
        self._sidebar_log_cb.toggled.connect(self.sidebarLogToggled)
        log_layout.addWidget(self._sidebar_log_cb)
        layout.addWidget(log_group)

        layout.addStretch()
        return w

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        layout.addStretch()

        self._about_title = QLabel("VB Player")
        self._about_title.setStyleSheet("font-size: 24px; font-weight: bold; letter-spacing: 3px;")
        self._about_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._about_title)

        self._about_ver = QLabel("v0.6.4")
        self._about_ver.setStyleSheet("font-size: 13px; color: #888;")
        self._about_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._about_ver)

        self._about_desc = QLabel("PyQt6 + GStreamer")
        self._about_desc.setStyleSheet("font-size: 13px; color: #888; line-height: 1.6;")
        self._about_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._about_desc.setWordWrap(True)
        layout.addWidget(self._about_desc)

        layout.addStretch()

        # Integrity check button
        check_btn = QPushButton(_("settings.check_integrity"))
        check_btn.setFixedWidth(180)
        accent = current_accent()
        check_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
            "border-radius:4px;padding:8px 16px;font-size:13px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        check_btn.clicked.connect(self._run_integrity_check)
        layout.addWidget(check_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._integrity_result = QLabel("")
        self._integrity_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._integrity_result.setWordWrap(True)
        self._integrity_result.setStyleSheet("font-size:12px;color:#888;")
        self._integrity_result.setVisible(False)
        layout.addWidget(self._integrity_result)

        return w

    def _refresh_about_labels(self):
        self._about_title.setText(_("app.title"))
        self._about_ver.setText("v0.5")
        self._about_desc.setText("PyQt6 + GStreamer")

    def _run_integrity_check(self):
        """Check core and platform dependencies, show results."""
        from importlib import util as _il_util
        import sys as _sys

        checks: list[tuple[str, bool, str]] = []

        # Core deps
        for mod, label in [
            ("PyQt6.QtCore", "PyQt6"),
            ("numpy", "NumPy"),
            ("mutagen", "Mutagen"),
        ]:
            ok = _il_util.find_spec(mod) is not None
            checks.append((label, ok, ""))

        # GStreamer
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            checks.append(("GStreamer", True, ""))
        except Exception as e:
            checks.append(("GStreamer", False, str(e)))

        # Platform media controls
        from audio_player.platform import platform_info
        if platform_info.is_linux:
            try:
                from gi.repository import Gio
                checks.append(("MPRIS2", True, ""))
            except Exception as e:
                checks.append(("MPRIS2", False, str(e)))
        elif platform_info.is_macos:
            ok = _il_util.find_spec("MediaPlayer") is not None
            checks.append(("Now Playing", ok, "" if ok else "pip install pyobjc-framework-MediaPlayer"))
        elif platform_info.is_windows:
            ok = _il_util.find_spec("winsdk.windows.media") is not None
            checks.append(("SMTC", ok, "" if ok else "pip install winsdk"))

        # Build result text
        all_ok = all(ok for _, ok, _ in checks)
        lines = []
        for label, ok, detail in checks:
            icon = "✓" if ok else "✗"
            line = f"{icon} {label}"
            if not ok and detail:
                line += f" — {detail}"
            lines.append(line)

        result_text = "\n".join(lines)
        if all_ok:
            result_text = _("settings.integrity_ok") + "\n" + result_text
            color = "#4ade80"
        else:
            result_text = _("settings.integrity_issues") + "\n" + result_text
            color = "#f59e0b"

        self._integrity_result.setText(result_text)
        self._integrity_result.setStyleSheet(f"font-size:12px;color:{color};")
        self._integrity_result.setVisible(True)

    def set_eq_state(self, enabled: bool, preset: str, gains: list[float]):
        """Initialize equalizer widget state from outside."""
        self._eq_widget._enabled_cb.setChecked(enabled)
        idx = self._eq_widget._preset_combo.findText(preset)
        if idx >= 0:
            self._eq_widget._preset_combo.setCurrentIndex(idx)
        self._eq_widget.set_all_gains(gains)

    def set_exclusive_state(self, mode: bool, device: str):
        """Initialize exclusive mode UI state from outside."""
        self._exclusive_cb.blockSignals(True)
        self._exclusive_cb.setChecked(mode)
        self._exclusive_cb.blockSignals(False)
        if mode and not getattr(self, '_hw_loaded', False):
            self._hw_loaded = True
        idx = self._device_combo.findData(device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

    def set_dsd_mode(self, mode: str):
        """Initialize DSD decode mode UI state from outside."""
        idx = self._dsd_combo.findData(mode)
        if idx >= 0:
            self._dsd_combo.setCurrentIndex(idx)

    def set_replaygain_state(self, enabled: bool):
        """Initialize ReplayGain UI state from outside."""
        self._rg_cb.blockSignals(True)
        self._rg_cb.setChecked(enabled)
        self._rg_cb.blockSignals(False)

    def set_gapless_state(self, enabled: bool):
        """Initialize gapless playback UI state from outside."""
        self._gapless_cb.blockSignals(True)
        self._gapless_cb.setChecked(enabled)
        self._gapless_cb.blockSignals(False)

    def _on_eq_preset_local(self, name: str):
        """Apply preset locally to update sliders, then forward signal."""
        preset = PRESETS.get(name)
        if preset:
            self._eq_widget.set_all_gains(preset.gains)
        self.eqPresetSelected.emit(name)

    def _on_eq_reset_local(self):
        """Reset locally, then forward signal."""
        self._eq_widget.set_all_gains([0.0] * 10)
        self._eq_widget._preset_combo.setCurrentIndex(0)
        self.eqResetRequested.emit()

    def _load_settings(self):
        # Block signals during bulk load to prevent spurious save-on-init
        self._titlebar_combo.blockSignals(True)
        self._material_combo.blockSignals(True)
        self._mode_combo.blockSignals(True)

        # Account
        avatar_b64 = str(self._settings.value("account_avatar", "") or "")
        if avatar_b64:
            try:
                data = base64.b64decode(avatar_b64)
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    self._avatar_pixmap = pix
                    self._apply_avatar()
            except Exception:
                pass
        username = str(self._settings.value("account_username", "") or "")
        if username:
            self._username_input.setText(username)
            self._refresh_drag_label()

        mode = str(self._settings.value("theme_mode", "dark") or "dark")
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)

        lang = str(self._settings.value("language", "zh_CN") or "zh_CN")
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        tray = str(self._settings.value("close_to_tray", "true")).lower() == "true"
        self._tray_cb.setChecked(tray)

        accent = str(self._settings.value("accent", "purple") or "purple")
        for name, sw in self._accent_swatches.items():
            sw.set_selected(name == accent)

        viz_mode = int(self._settings.value("viz_mode", 0) or 0)
        idx = self._viz_combo.findData(viz_mode)
        if idx >= 0:
            self._viz_combo.setCurrentIndex(idx)

        self._lyrics_cb.setChecked(
            str(self._settings.value("lyrics_enabled", "true")).lower() == "true"
        )
        vol = int(self._settings.value("default_volume", 100) or 100)
        self._vol_slider.setValue(vol)

        br = int(self._settings.value("border_radius", 0) or 0)
        self._border_radius_spin.setValue(br)

        ui_r = int(self._settings.value("ui_radius", 12) or 12)
        self._ui_radius_spin.setValue(ui_r)

        # Titlebar style
        titlebar = str(self._settings.value("window_titlebar", "auto") or "auto")
        idx = self._titlebar_combo.findData(titlebar)
        if idx >= 0:
            self._titlebar_combo.setCurrentIndex(idx)

        # Dynamic accent
        dyn = str(self._settings.value("dynamic_accent_enabled", "true")).lower() == "true"
        self._dynamic_cb.setChecked(dyn)

        # Material effect
        material = str(self._settings.value("window_material", "auto") or "auto")
        idx = self._material_combo.findData(material)
        if idx >= 0:
            self._material_combo.setCurrentIndex(idx)
        self._update_texture_visibility()

        # Opacity (percentage 70-100, material defaults used when unset)
        alpha = int(self._settings.value("material_alpha", 92) or 92)
        self._opacity_slider.setValue(alpha)
        self._opacity_label.setText(_("settings.material_opacity_value", pct=alpha))

        # Texture (percentage 0-30, acrylic only)
        tex = int(self._settings.value("material_texture", 10) or 10)
        self._texture_slider.setValue(tex)
        self._texture_label.setText(_("settings.material_texture_value", pct=tex))

        # Playback bar style
        barstyle = str(self._settings.value("playback_bar_style", "full") or "full")
        idx = self._barstyle_combo.findData(barstyle)
        if idx >= 0:
            self._barstyle_combo.setCurrentIndex(idx)
        self._pill_progress_combo.setVisible(barstyle == "pill")

        pgstyle = str(self._settings.value("pill_progress_style", "line") or "line")
        idx2 = self._pill_progress_combo.findData(pgstyle)
        if idx2 >= 0:
            self._pill_progress_combo.setCurrentIndex(idx2)

        hl = str(self._settings.value("current_track_highlight", "glow") or "glow")
        idx3 = self._highlight_combo.findData(hl)
        if idx3 >= 0:
            self._highlight_combo.setCurrentIndex(idx3)

        lh = int(self._settings.value("lyrics_line_height", 40) or 40)
        self._lyrics_overlay_height_spin.setValue(lh)
        lfsh = int(self._settings.value("lyrics_fullscreen_line_height", 60) or 60)
        self._lyrics_fs_line_height_spin.setValue(lfsh)
        lfs = int(self._settings.value("lyrics_font_size", 32) or 32)
        self._lyrics_font_size_spin.setValue(lfs)
        lls = int(self._settings.value("lyrics_letter_spacing", 2) or 2)
        self._lyrics_letter_spacing_spin.setValue(lls)
        lss = str(self._settings.value("lyrics_show_spec", "true")).lower() == "true"
        self._lyrics_show_spec_cb.setChecked(lss)

        # Online lyrics settings
        online = str(self._settings.value("online_lyrics_enabled", "false")).lower() == "true"
        self._online_lyrics_cb.setChecked(online)
        lrclib = str(self._settings.value("lyrics_source_lrclib", "true")).lower() == "true"
        self._lrclib_cb.setChecked(lrclib)
        custom = str(self._settings.value("lyrics_source_custom", "false")).lower() == "true"
        self._custom_api_cb.setChecked(custom)
        self._custom_url_input.setText(str(self._settings.value("lyrics_custom_url", "")))
        self._custom_token_input.setText(_deobfuscate(str(self._settings.value("lyrics_custom_token", ""))))
        self._custom_api_widget.setVisible(custom)
        auto_save = str(self._settings.value("auto_save_lyrics", "false")).lower() == "true"
        self._auto_save_cb.setChecked(auto_save)
        show_trans = str(self._settings.value("show_translation", "true")).lower() == "true"
        self._show_translation_cb.setChecked(show_trans)

        sidebar_log = str(self._settings.value("sidebar_log", "false")).lower() == "true"
        self._sidebar_log_cb.setChecked(sidebar_log)

        cover_radius = str(self._settings.value("album_cover_radius", "true")).lower() == "true"
        self._album_cover_radius_cb.setChecked(cover_radius)

        # Restore exclusive mode state
        self._hw_loaded = False
        exclusive = str(self._settings.value("exclusive_mode", "false")).lower() == "true"
        exclusive_dev = str(self._settings.value("exclusive_device", "hw:0,0") or "hw:0,0")
        # Block signals during restore so setChecked doesn't trigger enumeration yet
        self._exclusive_cb.blockSignals(True)
        self._exclusive_cb.setChecked(exclusive)
        self._device_combo.setEnabled(exclusive)
        self._exclusive_cb.blockSignals(False)
        if exclusive:
            # Re-enumerate — Windows mic permission is one-time, won't prompt again
            self._load_hw_devices()
        else:
            self._device_combo.clear()
        # Restore saved device selection
        idx = self._device_combo.findData(exclusive_dev)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

        # Restore DSD decode mode
        dsd_mode = str(self._settings.value("dsd_mode", "pcm") or "pcm")
        dsd_idx = self._dsd_combo.findData(dsd_mode)
        if dsd_idx >= 0:
            self._dsd_combo.setCurrentIndex(dsd_idx)

        # Re-enable signals after bulk load
        self._titlebar_combo.blockSignals(False)
        self._material_combo.blockSignals(False)
        self._mode_combo.blockSignals(False)

        self._refresh_theme()

    def _refresh_nav_style(self):
        accent = current_accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        # Detect theme mode
        p = self.palette()
        is_light = p.color(QPalette.ColorRole.Window).lightness() > 128
        nav_bg = p.color(QPalette.ColorRole.Base).name()
        nav_border = "#ddd" if is_light else "#141414"
        nav_text = "#555" if is_light else "#64748b"

        self._nav_list.setStyleSheet(
            "QListWidget{"
            f"background:{nav_bg};border:none;border-right:1px solid {nav_border};"
            "font-size:13px;padding:8px 4px;"
            "}"
            "QListWidget::item{"
            f"color:{nav_text};padding:14px 10px;border-radius:6px;margin:1px 4px;"
            "}"
            "QListWidget::item:selected{"
            f"color:#fff;background:{accent.name()};"
            "border:none;outline:none;"
            "}"
            "QListWidget::item:hover{"
            f"color:#fff;background:{accent.name()};"
            "}"
            "QListWidget::item:focus{"
            "border:none;outline:none;background:transparent;"
            "}"
        )

    def _refresh_theme(self):
        """Update drag bar and nav panel to match current palette (light/dark)."""
        p = self.palette()
        win = p.color(QPalette.ColorRole.Window).name()
        base = p.color(QPalette.ColorRole.Base).name()
        is_light = p.color(QPalette.ColorRole.Window).lightness() > 128

        self._drag_bar.setStyleSheet(f"background:{win};")
        self._drag_label.setStyleSheet(
            f"color:{'#555' if is_light else '#94a3b8'};font-size:13px;font-weight:500;"
        )
        accent = current_accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        nav_bg = base
        nav_border = "#ddd" if is_light else "#141414"
        nav_text = "#555" if is_light else "#64748b"
        self._nav_list.setStyleSheet(
            "QListWidget{"
            f"background:{nav_bg};border:none;border-right:1px solid {nav_border};"
            "font-size:13px;padding:8px 4px;"
            "}"
            "QListWidget::item{"
            f"color:{nav_text};padding:14px 10px;border-radius:6px;margin:1px 4px;"
            "}"
            "QListWidget::item:selected{"
            f"color:#fff;background:{accent.name()};"
            "border:none;outline:none;"
            "}"
            "QListWidget::item:hover{"
            f"color:#fff;background:{accent.name()};"
            "}"
            "QListWidget::item:focus{"
            "border:none;outline:none;background:transparent;"
            "}"
        )

    def _on_accent_picked(self, name: str):
        for n, sw in self._accent_swatches.items():
            sw.set_selected(n == name)
        self._refresh_nav_style()

    def _on_viz(self, idx):
        mode = self._viz_combo.itemData(idx)
        if mode is not None:
            self.vizModeChanged.emit(mode)

    def _load_hw_devices(self):
        """Enumerate audio output devices (lazy — avoids WASAPI prompt on dialog open)."""
        if getattr(self, '_hw_loaded', False):
            return
        self._hw_loaded = True
        from audio_player.player.engine import enumerate_hw_devices
        try:
            self._alsa_devices = enumerate_hw_devices()
        except Exception as e:
            import sys; print(f"[settings] 设备枚举失败: {e}", file=sys.stderr)
            self._alsa_devices = [{"name": _("engine.default_device"), "hw": "", "driver": "WASAPI"}]
        self._device_combo.clear()
        for dev in self._alsa_devices:
            driver_tag = dev.get("driver", "")
            label = f"{dev['name']}  [{driver_tag}]" if driver_tag else dev["name"]
            self._device_combo.addItem(label, dev["hw"])

    def _on_exclusive_toggled(self, checked: bool):
        if checked:
            self._load_hw_devices()
        self._device_combo.setEnabled(checked)
        self.exclusiveModeToggled.emit(checked)

    def _on_device_changed(self, idx):
        hw = self._device_combo.itemData(idx)
        if hw:
            self.exclusiveDeviceChanged.emit(hw)

    def _on_dsd_mode_changed(self, idx):
        mode = self._dsd_combo.itemData(idx)
        if mode:
            self.dsdModeChanged.emit(mode)

    def _emit_theme(self):
        mode = self._mode_combo.currentData()
        accent = self._current_accent_name()
        self.themeChanged.emit(mode, accent)
        self._refresh_theme()

    def _on_titlebar_changed(self):
        val = self._titlebar_combo.currentData()
        self._settings.setValue("window_titlebar", val)
        self.titlebarChanged.emit(val)

    def _on_barstyle_changed(self):
        val = self._barstyle_combo.currentData()
        self._settings.setValue("playback_bar_style", val)
        self._pill_progress_combo.setVisible(val == "pill")
        self.barStyleChanged.emit(val)

    def _on_highlight_changed(self):
        val = self._highlight_combo.currentData()
        self._settings.setValue("current_track_highlight", val)

    def _on_pill_progress_changed(self):
        val = self._pill_progress_combo.currentData()
        self._settings.setValue("pill_progress_style", val)

    def _on_dynamic_accent_toggled(self, checked: bool):
        self._settings.setValue("dynamic_accent_enabled", checked)
        self.dynamicAccentToggled.emit(checked)

    def _on_material_changed(self):
        val = self._material_combo.currentData()
        self._settings.setValue("window_material", val)
        self._update_texture_visibility()
        self.materialChanged.emit(val)

    def _on_opacity_changed(self, val: int):
        self._settings.setValue("material_alpha", val)
        self._opacity_label.setText(_("settings.material_opacity_value", pct=val))

    def _on_texture_changed(self, val: int):
        self._settings.setValue("material_texture", val)
        self._texture_label.setText(_("settings.material_texture_value", pct=val))

    def _emit_material_live(self):
        """Trigger live repaint after slider drag ends."""
        self.materialChanged.emit(self._material_combo.currentData())

    def _update_texture_visibility(self):
        """Show texture slider only for acrylic mode."""
        mat = self._material_combo.currentData()
        visible = mat == "acrylic"
        self._texture_label.setVisible(visible)
        self._texture_slider.setVisible(visible)

    def _current_accent_name(self) -> str:
        for name, sw in self._accent_swatches.items():
            if sw._selected:
                return name
        return "purple"

    def _save_and_close(self):
        mode = self._mode_combo.currentData()
        accent = self._current_accent_name()
        self._settings.setValue("theme_mode", mode)
        self._settings.setValue("accent", accent)
        self._settings.setValue("viz_mode", self._viz_combo.currentData())
        self._settings.setValue("lyrics_enabled", self._lyrics_cb.isChecked())
        self._settings.setValue("default_volume", self._vol_slider.value())
        br = self._border_radius_spin.value()
        self._settings.setValue("border_radius", br)
        ui_r = self._ui_radius_spin.value()
        self._settings.setValue("ui_radius", ui_r)
        # Lyrics settings
        lh = self._lyrics_overlay_height_spin.value()
        lfsh = self._lyrics_fs_line_height_spin.value()
        lfs = self._lyrics_font_size_spin.value()
        lls = self._lyrics_letter_spacing_spin.value()
        lss = self._lyrics_show_spec_cb.isChecked()
        self._settings.setValue("lyrics_line_height", lh)
        self._settings.setValue("lyrics_fullscreen_line_height", lfsh)
        self._settings.setValue("lyrics_font_size", lfs)
        self._settings.setValue("lyrics_letter_spacing", lls)
        self._settings.setValue("lyrics_show_spec", lss)
        self.lyricsLineHeightChanged.emit(lh)
        self.lyricsFullscreenLineHeightChanged.emit(lfsh)
        self.lyricsFontSizeChanged.emit(lfs)
        self.lyricsLetterSpacingChanged.emit(lls)
        self.lyricsShowSpecToggled.emit(lss)
        self.defaultVolumeChanged.emit(self._vol_slider.value() / 100.0)
        self.borderRadiusChanged.emit(br)
        self.uiRadiusChanged.emit(ui_r)
        sidebar_log = self._sidebar_log_cb.isChecked()
        self._settings.setValue("sidebar_log", sidebar_log)
        self.sidebarLogToggled.emit(sidebar_log)
        cover_radius = self._album_cover_radius_cb.isChecked()
        self._settings.setValue("album_cover_radius", cover_radius)
        self.albumCoverRadiusToggled.emit(cover_radius)
        self._settings.setValue("exclusive_mode", self._exclusive_cb.isChecked())
        dev_hw = self._device_combo.currentData()
        if dev_hw:
            self._settings.setValue("exclusive_device", dev_hw)
        dsd = self._dsd_combo.currentData()
        if dsd:
            self._settings.setValue("dsd_mode", dsd)
        self._settings.setValue("replaygain_enabled", self._rg_cb.isChecked())
        # Online lyrics settings
        self._settings.setValue("online_lyrics_enabled", self._online_lyrics_cb.isChecked())
        self._settings.setValue("lyrics_source_lrclib", self._lrclib_cb.isChecked())
        self._settings.setValue("lyrics_source_custom", self._custom_api_cb.isChecked())
        self._settings.setValue("lyrics_custom_url", self._custom_url_input.text())
        self._settings.setValue("lyrics_custom_token", _obfuscate(self._custom_token_input.text()))
        self._settings.setValue("auto_save_lyrics", self._auto_save_cb.isChecked())
        self._settings.setValue("show_translation", self._show_translation_cb.isChecked())
        self.themeChanged.emit(mode, accent)
        self.accept()

    def current_theme(self) -> tuple[str, str]:
        return (self._mode_combo.currentData(), self._current_accent_name())
