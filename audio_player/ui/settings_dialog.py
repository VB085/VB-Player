from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QComboBox, QCheckBox, QSlider,
                             QPushButton, QGroupBox, QFormLayout,
                             QListWidget, QListWidgetItem, QScrollArea,
                             QSpinBox, QAbstractItemView, QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPalette, QRegion, QPixmap

from audio_player.ui.widgets.equalizer_widget import EqualizerWidget
from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.player.equalizer import PRESETS
from audio_player.i18n import _, set_language, current_lang, languageChanged


def _accent_color() -> QColor:
    s = QSettings("VBPlayer", "VB Player")
    name = str(s.value("accent", "purple") or "purple")
    accents = {
        "purple": QColor("#7c3aed"),
        "blue":   QColor("#007AFF"),
        "green":  QColor("#10b981"),
        "orange": QColor("#f59e0b"),
        "pink":   QColor("#ec4899"),
        "red":    QColor("#ef4444"),
    }
    return accents.get(name, QColor("#7c3aed"))


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



class SettingsDialog(QDialog):
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
    languageChanged = pyqtSignal(str)

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
        super().__init__(None)  # Independent top-level window — no parent
        self.setWindowTitle("设置")
        self.setMinimumSize(560, 520)
        self.resize(600, 660)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._border_radius = 12
        self._mask_dirty = True
        self._settings = QSettings("VBPlayer", "VB Player")
        self._setup_ui()
        self._load_settings()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._border_radius > 0:
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
        self._drag_label = QLabel("设置")
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
        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(100)
        self._nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_nav_style()
        self._nav_labels = ["settings.general", "settings.appearance", "settings.playback",
                           "settings.advanced", "settings.about"]
        for key in self._nav_labels:
            item = QListWidgetItem(_(key))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._nav_list.addItem(item)
        self._nav_list.setCurrentRow(0)

        # Right stacked pages
        self._pages = AnimatedStackedWidget()
        self._pages.addWidget(self._build_general_tab())
        self._pages.addWidget(self._build_appearance_tab())
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
        self._lang_combo = QComboBox()
        for code, name in self.LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._lang_combo)
        layout.addWidget(self._lang_group)

        layout.addStretch()

        ok = QPushButton("确定")
        ok.setFixedWidth(80)
        ok.setStyleSheet(
            f"QPushButton{{background:{_accent_color().name()};color:#fff;border:none;"
            "border-radius:4px;padding:8px;font-size:13px;}}"
            f"QPushButton:hover{{background:{_accent_color().lighter(115).name()};}}"
        )
        ok.clicked.connect(self._save_and_close)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        return w

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
        if hasattr(self, '_theme_group'):
            self._theme_group.setTitle(_("settings.theme"))
        if hasattr(self, '_accent_group'):
            self._accent_group.setTitle(_("settings.accent"))
        self._window_radius_group.setTitle(_("settings.window_radius"))
        self._ui_radius_group.setTitle(_("settings.ui_radius"))
        self._lyrics_group.setTitle(_("settings.lyrics_group"))
        self._lyrics_cb.setText(_("settings.lyrics_enable"))
        self._lyrics_fullscreen_group.setTitle(_("settings.lyrics_fullscreen_group"))
        self._lyrics_show_spec_cb.setText(_("settings.lyrics_audio_spec"))
        self._cover_group.setTitle(_("settings.album_cover"))
        self._cover_cb.setText(_("settings.cover_radius"))
        self._viz_group.setTitle(_("settings.visualization"))
        self._viz_combo.clear()
        for label in [_("viz.bars"), _("viz.line"), _("viz.circular")]:
            self._viz_combo.addItem(label)
        self._vol_group.setTitle(_("settings.default_volume"))
        self._eq_group.setTitle(_("settings.equalizer"))
        self._exclusive_cb.setText(_("settings.exclusive_mode"))
        self._sidebar_log_cb.setText(_("settings.sidebar_log"))
        self._refresh_about_labels()

    def _build_appearance_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Lyrics (overlay) settings
        self._lyrics_group = QGroupBox(_("settings.lyrics_group"))
        lyrics_layout = QVBoxLayout(self._lyrics_group)
        self._lyrics_cb = QCheckBox(_("settings.lyrics_enable"))
        self._lyrics_cb.setChecked(True)
        self._lyrics_cb.toggled.connect(self.lyricsToggled)
        lyrics_layout.addWidget(self._lyrics_cb)

        lyrics_overlay_row = QHBoxLayout()
        lyrics_overlay_row.addWidget(QLabel(_("settings.lyrics_height")))
        self._lyrics_overlay_height_spin = QSpinBox()
        self._lyrics_overlay_height_spin.setRange(24, 72)
        self._lyrics_overlay_height_spin.setSuffix(" px")
        self._lyrics_overlay_height_spin.setValue(40)
        self._lyrics_overlay_height_spin.valueChanged.connect(
            lambda v: self.lyricsLineHeightChanged.emit(v))
        lyrics_overlay_row.addWidget(self._lyrics_overlay_height_spin, 1)
        lyrics_layout.addLayout(lyrics_overlay_row)
        layout.addWidget(self._lyrics_group)

        # Fullscreen lyrics settings
        self._lyrics_fullscreen_group = QGroupBox(_("settings.lyrics_fullscreen_group"))
        lyrics_fs_grid = QFormLayout(self._lyrics_fullscreen_group)
        lyrics_fs_grid.setSpacing(8)

        self._lyrics_font_size_spin = QSpinBox()
        self._lyrics_font_size_spin.setRange(16, 72)
        self._lyrics_font_size_spin.setSuffix(" pt")
        self._lyrics_font_size_spin.setValue(32)
        self._lyrics_font_size_spin.valueChanged.connect(
            lambda v: self.lyricsFontSizeChanged.emit(v))
        lyrics_fs_grid.addRow(_("settings.lyrics_font_size"), self._lyrics_font_size_spin)

        self._lyrics_fs_line_height_spin = QSpinBox()
        self._lyrics_fs_line_height_spin.setRange(30, 120)
        self._lyrics_fs_line_height_spin.setSuffix(" px")
        self._lyrics_fs_line_height_spin.setValue(60)
        self._lyrics_fs_line_height_spin.valueChanged.connect(
            lambda v: self.lyricsFullscreenLineHeightChanged.emit(v))
        lyrics_fs_grid.addRow(_("settings.lyrics_height"), self._lyrics_fs_line_height_spin)

        self._lyrics_letter_spacing_spin = QSpinBox()
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

        # Theme mode
        self._theme_group = QGroupBox(_("settings.theme"))
        mode_layout = QVBoxLayout(self._theme_group)
        self._mode_combo = QComboBox()
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
        self._border_radius_spin = QSpinBox()
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
        self._ui_radius_spin = QSpinBox()
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

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_playback_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._viz_group = QGroupBox(_("settings.visualization"))
        viz_layout = QFormLayout(self._viz_group)
        self._viz_combo = QComboBox()
        for idx in self.VIZ_MODES:
            self._viz_combo.addItem(_(f"viz.{['bars','line','circular'][idx]}"), idx)
        self._viz_combo.currentIndexChanged.connect(self._on_viz)
        viz_layout.addRow(self._viz_combo)
        layout.addWidget(self._viz_group)

        self._vol_group = QGroupBox(_("settings.default_volume"))
        vol_row = QHBoxLayout(self._vol_group)
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.valueChanged.connect(lambda v: self._vol_label.setText(f"{v}%"))
        vol_row.addWidget(self._vol_slider, 1)
        self._vol_label = QLabel("80%")
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
        out_group = QGroupBox(_("settings.exclusive_mode"))
        out_layout = QVBoxLayout(out_group)

        self._exclusive_cb = QCheckBox(_("settings.exclusive_mode"))
        self._exclusive_cb.setToolTip(
            "启用后直接访问 ALSA 硬件设备，绕过 PipeWire/PulseAudio\n"
            "注意：独占模式下其他应用将无法使用该音频设备"
        )
        self._exclusive_cb.toggled.connect(self._on_exclusive_toggled)
        out_layout.addWidget(self._exclusive_cb)

        self._device_combo = QComboBox()
        self._device_combo.setEnabled(False)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        out_layout.addWidget(self._device_combo)

        layout.addWidget(out_group)

        reload_btn = QPushButton("🔄  重新加载专辑")
        accent = _accent_color()
        reload_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:5px;"
            f"padding:8px;font-size:13px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        reload_btn.clicked.connect(self.reloadRequested)
        layout.addWidget(reload_btn)

        return w

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

        self._about_ver = QLabel("v3.0 — Frameless Edition")
        self._about_ver.setStyleSheet("font-size: 13px; color: #888;")
        self._about_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._about_ver)

        self._about_desc = QLabel("PyQt6 + GStreamer")
        self._about_desc.setStyleSheet("font-size: 13px; color: #888; line-height: 1.6;")
        self._about_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._about_desc.setWordWrap(True)
        layout.addWidget(self._about_desc)

        layout.addStretch()
        return w

    def _refresh_about_labels(self):
        self._about_title.setText(_("app.title"))
        self._about_ver.setText("v3.0 — Frameless Edition")
        self._about_desc.setText("PyQt6 + GStreamer")

    def set_eq_state(self, enabled: bool, preset: str, gains: list[float]):
        """Initialize equalizer widget state from outside."""
        self._eq_widget._enabled_cb.setChecked(enabled)
        idx = self._eq_widget._preset_combo.findText(preset)
        if idx >= 0:
            self._eq_widget._preset_combo.setCurrentIndex(idx)
        self._eq_widget.set_all_gains(gains)

    def set_exclusive_state(self, mode: bool, device: str):
        """Initialize exclusive mode UI state from outside."""
        self._exclusive_cb.setChecked(mode)
        idx = self._device_combo.findData(device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

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
        mode = str(self._settings.value("theme_mode", "dark") or "dark")
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)

        lang = str(self._settings.value("language", "zh_CN") or "zh_CN")
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

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
        vol = int(self._settings.value("default_volume", 80) or 80)
        self._vol_slider.setValue(vol)

        br = int(self._settings.value("border_radius", 0) or 0)
        self._border_radius_spin.setValue(br)

        ui_r = int(self._settings.value("ui_radius", 12) or 12)
        self._ui_radius_spin.setValue(ui_r)

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

        sidebar_log = str(self._settings.value("sidebar_log", "false")).lower() == "true"
        self._sidebar_log_cb.setChecked(sidebar_log)

        cover_radius = str(self._settings.value("album_cover_radius", "true")).lower() == "true"
        self._album_cover_radius_cb.setChecked(cover_radius)

        # Populate ALSA device combo
        from audio_player.player.engine import enumerate_alsa_hw_devices
        self._alsa_devices = enumerate_alsa_hw_devices()
        self._device_combo.clear()
        for dev in self._alsa_devices:
            self._device_combo.addItem(dev["name"], dev["hw"])

        exclusive = str(self._settings.value("exclusive_mode", "false")).lower() == "true"
        self._exclusive_cb.setChecked(exclusive)
        self._device_combo.setEnabled(exclusive)
        exclusive_dev = str(self._settings.value("exclusive_device", "hw:0,0") or "hw:0,0")
        idx = self._device_combo.findData(exclusive_dev)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)

        self._refresh_theme()

    def _refresh_nav_style(self):
        accent = _accent_color()
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
        accent = _accent_color()
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

    def _on_exclusive_toggled(self, checked: bool):
        self._device_combo.setEnabled(checked)
        self.exclusiveModeToggled.emit(checked)

    def _on_device_changed(self, idx):
        hw = self._device_combo.itemData(idx)
        if hw:
            self.exclusiveDeviceChanged.emit(hw)

    def _emit_theme(self):
        mode = self._mode_combo.currentData()
        accent = self._current_accent_name()
        self.themeChanged.emit(mode, accent)
        self._refresh_theme()

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
        self.themeChanged.emit(mode, accent)
        self.accept()

    def current_theme(self) -> tuple[str, str]:
        return (self._mode_combo.currentData(), self._current_accent_name())
