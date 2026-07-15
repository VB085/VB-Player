"""Settings page — full embedded page replacing the settings dialog."""
import sys
import base64
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QComboBox, QCheckBox, QSlider,
                             QPushButton, QGroupBox, QFormLayout,
                             QListWidget, QListWidgetItem, QScrollArea,
                             QSpinBox, QAbstractItemView, QGridLayout,
                             QLineEdit, QFileDialog)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QBuffer, QByteArray
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QIcon

from audio_player.ui.widgets.animated_stack import AnimatedStackedWidget
from audio_player.i18n import _, set_language, current_lang, languageChanged
from audio_player.app import current_accent, current_theme_mode

# Reuse helpers from settings_dialog
from audio_player.ui.settings_dialog import (
    _AccentSwatch, _NoWheelList, _NoWheelSpinBox,
    _NoWheelSlider, _NoWheelComboBox, _obfuscate, _deobfuscate,
)


class SettingsPage(QWidget):
    """Full-page settings widget with left nav + right stacked tabs."""

    themeChanged = pyqtSignal(str, str)
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
    accentChanged = pyqtSignal()

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
    LANGUAGES = {
        "zh_CN": "简体中文",
        "zh_TW": "繁體中文",
        "en": "English",
        "ja": "日本語",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._settings = QSettings("VBPlayer", "VB Player")
        self._setup_ui()
        self._load_settings()
        languageChanged.connect(self._refresh_all_labels)

    # ── UI setup ──────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header — matches other pages
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        self._title_label = QLabel(_("settings.title"))
        self._title_label.setObjectName("pageTitle")
        header.addWidget(self._title_label)
        header.addStretch()
        outer.addLayout(header)

        # Body: left nav + right stacked pages
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._nav_list = _NoWheelList()
        self._nav_list.setFixedWidth(110)
        self._nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._nav_labels = [
            "settings.general", "settings.account", "settings.appearance",
            "settings.lyrics_tab", "settings.playback",
            "settings.advanced", "settings.about",
        ]
        for key in self._nav_labels:
            item = QListWidgetItem(_(key))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._nav_list.addItem(item)
        self._nav_list.setCurrentRow(0)
        body.addWidget(self._nav_list)

        self._pages = AnimatedStackedWidget()
        self._pages.addWidget(self._build_general_tab())
        self._pages.addWidget(self._build_account_tab())
        self._pages.addWidget(self._build_appearance_tab())
        self._pages.addWidget(self._build_lyrics_tab())
        self._pages.addWidget(self._build_playback_tab())
        self._pages.addWidget(self._build_advanced_tab())
        self._pages.addWidget(self._build_about_tab())
        self._nav_list.currentRowChanged.connect(self._pages.setCurrentIndex)
        body.addWidget(self._pages, 1)

        outer.addLayout(body, 1)
        self._apply_nav_style()

    # ── Style ─────────────────────────────────────────────────

    def _apply_nav_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        nav_bg = "#f5f5f5" if is_light else "#1e1e1e"
        nav_border = "#ddd" if is_light else "#2a2a2a"
        nav_text = "#555" if is_light else "#94a3b8"
        self._nav_list.setStyleSheet(
            f"QListWidget{{background:{nav_bg};border:none;"
            f"border-right:1px solid {nav_border};font-size:13px;padding:8px 4px;}}"
            f"QListWidget::item{{color:{nav_text};padding:12px 8px;border-radius:8px;margin:2px 4px;}}"
            f"QListWidget::item:selected{{color:#fff;background:{accent.name()};border:none;}}"
            f"QListWidget::item:hover{{color:#fff;background:{accent.lighter(120).name()};}}"
        )

    def refresh_accent(self):
        self._apply_nav_style()

    def refresh_theme_mode(self, is_light: bool):
        self._apply_nav_style()

    # ── Tab builders ──────────────────────────────────────────

    def _make_group(self, title_key: str) -> QGroupBox:
        g = QGroupBox(_(title_key))
        g.setObjectName("settingsGroup")
        return g

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._lang_group = self._make_group("settings.language")
        lang_layout = QVBoxLayout(self._lang_group)
        self._lang_combo = _NoWheelComboBox()
        for code, name in self.LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self._lang_combo)
        layout.addWidget(self._lang_group)

        self._tray_cb = QCheckBox(_("settings.close_to_tray"))
        self._tray_cb.setChecked(True)
        self._tray_cb.toggled.connect(lambda v: self._settings.setValue("close_to_tray", v))
        layout.addWidget(self._tray_cb)

        layout.addStretch()
        return w

    def _build_account_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        avatar_group = self._make_group("settings.avatar")
        avatar_layout = QVBoxLayout(avatar_group)
        avatar_row = QHBoxLayout()
        avatar_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._avatar_btn = QPushButton()
        self._avatar_btn.setFixedSize(96, 96)
        self._avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._avatar_btn.clicked.connect(self._pick_avatar)
        self._avatar_btn.setStyleSheet(
            "QPushButton{background:transparent;border:2px dashed #555;border-radius:48px;}"
            "QPushButton:hover{border-color:#888;}"
        )
        avatar_row.addWidget(self._avatar_btn)
        avatar_layout.addLayout(avatar_row)

        self._avatar_hint = QLabel(_("settings.avatar_hint"))
        self._avatar_hint.setObjectName("subLabel")
        self._avatar_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_layout.addWidget(self._avatar_hint)
        layout.addWidget(avatar_group)

        name_group = self._make_group("settings.username")
        name_layout = QVBoxLayout(name_group)
        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText(_("settings.username_placeholder"))
        self._username_input.textChanged.connect(
            lambda v: self._settings.setValue("account_username", v.strip()))
        name_layout.addWidget(self._username_input)
        layout.addWidget(name_group)

        stats_group = self._make_group("settings.stats")
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

    def _build_appearance_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._theme_group = self._make_group("settings.theme")
        mode_layout = QVBoxLayout(self._theme_group)
        self._mode_combo = _NoWheelComboBox()
        for k in self.THEME_MODES:
            self._mode_combo.addItem(_(f"theme.{k}"), k)
        self._mode_combo.currentIndexChanged.connect(self._emit_theme)
        mode_layout.addWidget(self._mode_combo)
        layout.addWidget(self._theme_group)

        self._accent_group = self._make_group("settings.accent")
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

        self._window_radius_group = self._make_group("settings.window_radius")
        wr_layout = QHBoxLayout(self._window_radius_group)
        self._border_radius_spin = _NoWheelSpinBox()
        self._border_radius_spin.setRange(0, 20)
        self._border_radius_spin.setSuffix(" px")
        self._border_radius_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("border_radius", v),
                       self.borderRadiusChanged.emit(v)))
        wr_layout.addWidget(QLabel(_("settings.radius_label")))
        wr_layout.addWidget(self._border_radius_spin, 1)
        layout.addWidget(self._window_radius_group)

        self._ui_radius_group = self._make_group("settings.ui_radius")
        ur_layout = QHBoxLayout(self._ui_radius_group)
        self._ui_radius_spin = _NoWheelSpinBox()
        self._ui_radius_spin.setRange(0, 24)
        self._ui_radius_spin.setSuffix(" px")
        self._ui_radius_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("ui_radius", v),
                       self.uiRadiusChanged.emit(v)))
        ur_layout.addWidget(QLabel(_("settings.radius_label")))
        ur_layout.addWidget(self._ui_radius_spin, 1)
        layout.addWidget(self._ui_radius_group)

        self._cover_group = self._make_group("settings.album_cover")
        cover_layout = QVBoxLayout(self._cover_group)
        self._cover_cb = QCheckBox(_("settings.cover_radius"))
        self._cover_cb.setChecked(True)
        self._cover_cb.toggled.connect(lambda v: (
            self._settings.setValue("album_cover_radius", v),
            self.albumCoverRadiusToggled.emit(v)))
        cover_layout.addWidget(self._cover_cb)
        layout.addWidget(self._cover_group)

        self._dynamic_group = self._make_group("settings.dynamic_accent")
        dyn_layout = QVBoxLayout(self._dynamic_group)
        self._dynamic_cb = QCheckBox(_("settings.dynamic_accent_enable"))
        self._dynamic_cb.setChecked(True)
        self._dynamic_cb.toggled.connect(self._on_dynamic_accent_toggled)
        dyn_layout.addWidget(self._dynamic_cb)
        layout.addWidget(self._dynamic_group)

        self._titlebar_group = self._make_group("settings.titlebar_style")
        tb_layout = QVBoxLayout(self._titlebar_group)
        self._titlebar_combo = _NoWheelComboBox()
        self._titlebar_combo.addItem(_("settings.titlebar_auto"), "auto")
        self._titlebar_combo.addItem(_("settings.titlebar_frameless"), "frameless")
        self._titlebar_combo.addItem(_("settings.titlebar_csd"), "csd")
        self._titlebar_combo.addItem(_("settings.titlebar_native"), "native")
        self._titlebar_combo.currentIndexChanged.connect(self._on_titlebar_changed)
        tb_layout.addWidget(self._titlebar_combo)
        self._titlebar_note = QLabel(_("settings.titlebar_restart_note"))
        self._titlebar_note.setObjectName("subLabel")
        tb_layout.addWidget(self._titlebar_note)
        layout.addWidget(self._titlebar_group)

        self._material_group = self._make_group("settings.material_effect")
        mat_layout = QVBoxLayout(self._material_group)
        self._material_combo = _NoWheelComboBox()
        self._material_combo.addItem(_("settings.material_auto"), "auto")
        self._material_combo.addItem(_("settings.material_acrylic"), "acrylic")
        self._material_combo.addItem(_("settings.material_glass"), "glass")
        self._material_combo.addItem(_("settings.material_none"), "none")
        self._material_combo.currentIndexChanged.connect(self._on_material_changed)
        mat_layout.addWidget(self._material_combo)
        self._material_note = QLabel(_("settings.material_desc"))
        self._material_note.setObjectName("subLabel")
        mat_layout.addWidget(self._material_note)

        mat_layout.addSpacing(8)
        self._opacity_label = QLabel(_("settings.material_opacity"))
        mat_layout.addWidget(self._opacity_label)
        self._opacity_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(70, 100)
        self._opacity_slider.setValue(84)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._opacity_slider.sliderReleased.connect(self._emit_material_live)
        mat_layout.addWidget(self._opacity_slider)

        self._texture_label = QLabel(_("settings.material_texture"))
        mat_layout.addWidget(self._texture_label)
        self._texture_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._texture_slider.setRange(0, 30)
        self._texture_slider.setValue(10)
        self._texture_slider.valueChanged.connect(self._on_texture_changed)
        self._texture_slider.sliderReleased.connect(self._emit_material_live)
        mat_layout.addWidget(self._texture_slider)
        layout.addWidget(self._material_group)

        # Playback bar style
        self._barstyle_group = self._make_group("settings.bar_style")
        bar_layout = QVBoxLayout(self._barstyle_group)
        self._barstyle_combo = _NoWheelComboBox()
        self._barstyle_combo.addItem(_("settings.bar_full"), "full")
        self._barstyle_combo.addItem(_("settings.bar_pill"), "pill")
        self._barstyle_combo.currentIndexChanged.connect(self._on_barstyle_changed)
        bar_layout.addWidget(self._barstyle_combo)

        self._pill_progress_combo = _NoWheelComboBox()
        self._pill_progress_combo.addItem(_("settings.pill_progress_line"), "line")
        self._pill_progress_combo.addItem(_("settings.pill_progress_ring"), "ring")
        self._pill_progress_combo.currentIndexChanged.connect(self._on_pill_progress_changed)
        bar_layout.addWidget(self._pill_progress_combo)
        layout.addWidget(self._barstyle_group)

        # Highlight style
        self._highlight_group = self._make_group("settings.highlight_style")
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

        self._online_lyrics_group = self._make_group("settings.online_lyrics")
        online_layout = QVBoxLayout(self._online_lyrics_group)

        self._online_lyrics_cb = QCheckBox(_("settings.enable_online_lyrics"))
        self._online_lyrics_cb.toggled.connect(self.onlineLyricsToggled)
        online_layout.addWidget(self._online_lyrics_cb)

        self._lrclib_cb = QCheckBox(_("settings.source_lrclib"))
        self._lrclib_cb.setChecked(True)
        online_layout.addWidget(self._lrclib_cb)

        self._custom_api_cb = QCheckBox(_("settings.source_custom_api"))
        self._custom_api_cb.toggled.connect(self._on_custom_api_toggled)
        online_layout.addWidget(self._custom_api_cb)

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

        self._auto_save_cb = QCheckBox(_("settings.auto_save_lyrics"))
        self._auto_save_cb.toggled.connect(self.autoSaveLyricsToggled)
        layout.addWidget(self._auto_save_cb)

        self._show_translation_cb = QCheckBox(_("settings.show_translation"))
        self._show_translation_cb.setChecked(True)
        self._show_translation_cb.toggled.connect(self.showTranslationToggled)
        layout.addWidget(self._show_translation_cb)

        self._lyrics_group = self._make_group("settings.lyrics_display")
        lyrics_layout = QVBoxLayout(self._lyrics_group)

        self._lyrics_cb = QCheckBox(_("settings.lyrics_enable"))
        self._lyrics_cb.setChecked(True)
        self._lyrics_cb.toggled.connect(self.lyricsToggled)
        lyrics_layout.addWidget(self._lyrics_cb)

        lh_row = QHBoxLayout()
        lh_row.addWidget(QLabel(_("settings.lyrics_height")))
        self._lyrics_overlay_height_spin = _NoWheelSpinBox()
        self._lyrics_overlay_height_spin.setRange(24, 72)
        self._lyrics_overlay_height_spin.setSuffix(" px")
        self._lyrics_overlay_height_spin.setValue(40)
        self._lyrics_overlay_height_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("lyrics_line_height", v),
                       self.lyricsLineHeightChanged.emit(v)))
        lh_row.addWidget(self._lyrics_overlay_height_spin, 1)
        lyrics_layout.addLayout(lh_row)
        layout.addWidget(self._lyrics_group)

        self._lyrics_fullscreen_group = self._make_group("settings.lyrics_fullscreen_group")
        fs_grid = QFormLayout(self._lyrics_fullscreen_group)
        fs_grid.setSpacing(8)

        self._lyrics_font_size_spin = _NoWheelSpinBox()
        self._lyrics_font_size_spin.setRange(16, 72)
        self._lyrics_font_size_spin.setSuffix(" pt")
        self._lyrics_font_size_spin.setValue(32)
        self._lyrics_font_size_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("lyrics_font_size", v),
                       self.lyricsFontSizeChanged.emit(v)))
        fs_grid.addRow(_("settings.lyrics_font_size"), self._lyrics_font_size_spin)

        self._lyrics_fs_line_height_spin = _NoWheelSpinBox()
        self._lyrics_fs_line_height_spin.setRange(30, 120)
        self._lyrics_fs_line_height_spin.setSuffix(" px")
        self._lyrics_fs_line_height_spin.setValue(60)
        self._lyrics_fs_line_height_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("lyrics_fullscreen_line_height", v),
                       self.lyricsFullscreenLineHeightChanged.emit(v)))
        fs_grid.addRow(_("settings.lyrics_height"), self._lyrics_fs_line_height_spin)

        self._lyrics_letter_spacing_spin = _NoWheelSpinBox()
        self._lyrics_letter_spacing_spin.setRange(0, 20)
        self._lyrics_letter_spacing_spin.setSuffix(" px")
        self._lyrics_letter_spacing_spin.setValue(2)
        self._lyrics_letter_spacing_spin.valueChanged.connect(
            lambda v: (self._settings.setValue("lyrics_letter_spacing", v),
                       self.lyricsLetterSpacingChanged.emit(v)))
        fs_grid.addRow(_("settings.lyrics_letter_spacing"), self._lyrics_letter_spacing_spin)

        self._lyrics_show_spec_cb = QCheckBox(_("settings.lyrics_audio_spec"))
        self._lyrics_show_spec_cb.setChecked(True)
        self._lyrics_show_spec_cb.toggled.connect(
            lambda v: (self._settings.setValue("lyrics_show_spec", v),
                       self.lyricsShowSpecToggled.emit(v)))
        fs_grid.addRow(self._lyrics_show_spec_cb)
        layout.addWidget(self._lyrics_fullscreen_group)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_playback_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._viz_group = self._make_group("settings.visualization")
        viz_layout = QFormLayout(self._viz_group)
        self._viz_combo = _NoWheelComboBox()
        for idx in self.VIZ_MODES:
            self._viz_combo.addItem(_(f"viz.{['bars','line','circular'][idx]}"), idx)
        self._viz_combo.currentIndexChanged.connect(self._on_viz)
        viz_layout.addRow(self._viz_combo)
        layout.addWidget(self._viz_group)

        self._vol_group = self._make_group("settings.default_volume")
        vol_row = QHBoxLayout(self._vol_group)
        self._vol_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.valueChanged.connect(lambda v: self._vol_label.setText(f"{v}%"))
        self._vol_slider.sliderReleased.connect(
            lambda: (self._settings.setValue("default_volume", self._vol_slider.value()),
                     self.defaultVolumeChanged.emit(self._vol_slider.value() / 100.0)))
        vol_row.addWidget(self._vol_slider, 1)
        self._vol_label = QLabel("100%")
        self._vol_label.setFixedWidth(36)
        vol_row.addWidget(self._vol_label)
        layout.addWidget(self._vol_group)

        # Audio quality
        self._rg_cb = QCheckBox(_("settings.replaygain"))
        self._rg_cb.setToolTip(_("settings.replaygain_tooltip"))
        self._rg_cb.toggled.connect(self.replaygainToggled)
        layout.addWidget(self._rg_cb)

        self._gapless_cb = QCheckBox(_("settings.gapless"))
        self._gapless_cb.setToolTip(_("settings.gapless_tooltip"))
        self._gapless_cb.toggled.connect(self.gaplessToggled)
        layout.addWidget(self._gapless_cb)

        layout.addStretch()
        scroll.setWidget(w)
        return scroll

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        log_group = self._make_group("settings.sidebar_log")
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
        layout.setContentsMargins(40, 40, 40, 100)  # bottom clears pill bar
        layout.setSpacing(16)

        layout.addStretch()

        self._about_title = QLabel("VB Player")
        self._about_title.setStyleSheet(
            'font-family: "HarmonyOS Sans SC"; font-size: 24px; font-weight: bold; letter-spacing: 3px;')
        self._about_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._about_title)

        self._about_ver = QLabel("v0.7.1")
        self._about_ver.setStyleSheet('font-family: "HarmonyOS Sans SC"; font-size: 13px; color: #888;')
        self._about_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._about_ver)

        self._about_desc = QLabel("PyQt6 + GStreamer + ASIO")
        self._about_desc.setStyleSheet('font-family: "HarmonyOS Sans SC"; font-size: 13px; color: #888;')
        self._about_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._about_desc.setWordWrap(True)
        layout.addWidget(self._about_desc)

        layout.addStretch()

        check_btn = QPushButton(_("settings.check_integrity"))
        check_btn.setFixedWidth(180)
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        check_btn.clicked.connect(self._run_integrity_check)
        layout.addWidget(check_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._integrity_result = QLabel("")
        self._integrity_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._integrity_result.setWordWrap(True)
        self._integrity_result.setStyleSheet("font-size:12px;color:#888;")
        self._integrity_result.setVisible(False)
        layout.addWidget(self._integrity_result)
        layout.addStretch()
        return w

    # ── Handlers ───────────────────────────────────────────────

    def _on_language_changed(self):
        code = self._lang_combo.currentData()
        if code and code != current_lang():
            self._settings.setValue("language", code)
            set_language(code)
            self._refresh_all_labels()
            self.languageChanged.emit(code)

    def _emit_theme(self):
        mode = self._mode_combo.currentData()
        accent = self._current_accent_name()
        self._settings.setValue("theme_mode", mode)
        self._settings.setValue("accent", accent)
        self.themeChanged.emit(mode, accent)
        self._apply_nav_style()

    def _on_accent_picked(self, name: str):
        for n, sw in self._accent_swatches.items():
            sw.set_selected(n == name)
        self._settings.setValue("accent", name)
        self._emit_theme()

    def _on_viz(self, idx):
        mode = self._viz_combo.itemData(idx)
        if mode is not None:
            self._settings.setValue("viz_mode", mode)
            self.vizModeChanged.emit(mode)

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
        self.materialChanged.emit(self._material_combo.currentData())

    def _update_texture_visibility(self):
        mat = self._material_combo.currentData()
        visible = mat == "acrylic"
        self._texture_label.setVisible(visible)
        self._texture_slider.setVisible(visible)

    def _on_custom_api_toggled(self, checked: bool):
        self._settings.setValue("lyrics_source_custom", checked)
        self._custom_api_widget.setVisible(checked)

    # ── Avatar ─────────────────────────────────────────────────

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, _("settings.avatar_pick"), "",
            _("settings.avatar_filter"))
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._avatar_pixmap = pix
                self._apply_avatar()
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QBuffer.OpenModeFlag.WriteOnly)
                pix.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation).save(buf, "PNG")
                self._settings.setValue("account_avatar",
                                        base64.b64encode(ba.data()).decode())

    def _apply_avatar(self):
        if hasattr(self, '_avatar_pixmap') and not self._avatar_pixmap.isNull():
            scaled = self._avatar_pixmap.scaled(88, 88,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
            icon = QIcon(scaled)
            self._avatar_btn.setIcon(icon)
            self._avatar_btn.setIconSize(scaled.size())
            self._avatar_btn.setStyleSheet(
                "QPushButton{background:transparent;border:2px solid #555;border-radius:48px;}"
                "QPushButton:hover{border-color:#888;}"
            )

    # ── Integrity check ────────────────────────────────────────

    def _run_integrity_check(self):
        from importlib import util as _il_util
        checks: list[tuple[str, bool, str]] = []

        for mod, label in [
            ("PyQt6.QtCore", "PyQt6"),
            ("numpy", "NumPy"),
            ("mutagen", "Mutagen"),
        ]:
            ok = _il_util.find_spec(mod) is not None
            checks.append((label, ok, ""))

        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            checks.append(("GStreamer", True, ""))
        except Exception as e:
            checks.append(("GStreamer", False, str(e)))

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

    # ── Test connection ────────────────────────────────────────

    def _on_test_connection(self):
        url = self._custom_url_input.text().strip()
        if not url:
            self._test_conn_btn.setText(_("settings.test_fail"))
            return
        self._test_conn_btn.setEnabled(False)
        self._test_conn_btn.setText(_("settings.test_running"))
        token = self._custom_token_input.text().strip()

        from PyQt6.QtCore import QThread, pyqtSignal as _S

        class _TestWorker(QThread):
            ok = _S()
            fail = _S()

            def run(self_):
                import urllib.request, json
                test_url = f"{url.rstrip('/')}?track_name=test&artist_name=test&duration=0"
                headers = {"User-Agent": "VBPlayer/1.0"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                req = urllib.request.Request(test_url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        json.loads(resp.read().decode("utf-8"))
                    self_.ok.emit()
                except Exception:
                    self_.fail.emit()

        self._test_worker = _TestWorker(self)
        self._test_worker.ok.connect(lambda: (
            self._test_conn_btn.setText(_("settings.test_ok")),
            self._test_conn_btn.setEnabled(True)))
        self._test_worker.fail.connect(lambda: (
            self._test_conn_btn.setText(_("settings.test_fail")),
            self._test_conn_btn.setEnabled(True)))
        self._test_worker.start()

    # ── Public API ─────────────────────────────────────────────

    def set_replaygain_state(self, enabled: bool):
        self._rg_cb.blockSignals(True)
        self._rg_cb.setChecked(enabled)
        self._rg_cb.blockSignals(False)

    def set_gapless_state(self, enabled: bool):
        self._gapless_cb.blockSignals(True)
        self._gapless_cb.setChecked(enabled)
        self._gapless_cb.blockSignals(False)

    def set_account_stats(self, tracks: int, albums: int, playlists: int):
        self._stat_tracks.setText(str(tracks))
        self._stat_albums.setText(str(albums))
        self._stat_playlists.setText(str(playlists))

    def _current_accent_name(self) -> str:
        for name, sw in self._accent_swatches.items():
            if sw._selected:
                return name
        return "purple"

    # ── Load / refresh ─────────────────────────────────────────

    def _load_settings(self):
        s = self._settings

        # Block signals during bulk load to avoid spurious saves on init
        self._mode_combo.blockSignals(True)
        self._titlebar_combo.blockSignals(True)
        self._material_combo.blockSignals(True)

        # Account
        avatar_b64 = str(s.value("account_avatar", "") or "")
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
        username = str(s.value("account_username", "") or "")
        if username:
            self._username_input.setText(username)

        mode = str(s.value("theme_mode", "dark") or "dark")
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)

        lang = str(s.value("language", "zh_CN") or "zh_CN")
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        tray = str(s.value("close_to_tray", "true")).lower() == "true"
        self._tray_cb.setChecked(tray)

        accent_name = str(s.value("accent", "purple") or "purple")
        for name, sw in self._accent_swatches.items():
            sw.set_selected(name == accent_name)

        viz_mode = int(s.value("viz_mode", 0) or 0)
        idx = self._viz_combo.findData(viz_mode)
        if idx >= 0:
            self._viz_combo.setCurrentIndex(idx)

        self._lyrics_cb.setChecked(
            str(s.value("lyrics_enabled", "true")).lower() == "true")
        vol = int(s.value("default_volume", 100) or 100)
        self._vol_slider.setValue(vol)

        br = int(s.value("border_radius", 0) or 0)
        self._border_radius_spin.setValue(br)

        ui_r = int(s.value("ui_radius", 12) or 12)
        self._ui_radius_spin.setValue(ui_r)

        titlebar = str(s.value("window_titlebar", "auto") or "auto")
        idx = self._titlebar_combo.findData(titlebar)
        if idx >= 0:
            self._titlebar_combo.setCurrentIndex(idx)

        dyn = str(s.value("dynamic_accent_enabled", "true")).lower() == "true"
        self._dynamic_cb.setChecked(dyn)

        material = str(s.value("window_material", "auto") or "auto")
        idx = self._material_combo.findData(material)
        if idx >= 0:
            self._material_combo.setCurrentIndex(idx)
        self._update_texture_visibility()

        alpha = int(s.value("material_alpha", 92) or 92)
        self._opacity_slider.setValue(alpha)
        self._opacity_label.setText(_("settings.material_opacity_value", pct=alpha))

        tex = int(s.value("material_texture", 10) or 10)
        self._texture_slider.setValue(tex)
        self._texture_label.setText(_("settings.material_texture_value", pct=tex))

        barstyle = str(s.value("playback_bar_style", "full") or "full")
        idx = self._barstyle_combo.findData(barstyle)
        if idx >= 0:
            self._barstyle_combo.setCurrentIndex(idx)
        self._pill_progress_combo.setVisible(barstyle == "pill")

        pgstyle = str(s.value("pill_progress_style", "line") or "line")
        idx2 = self._pill_progress_combo.findData(pgstyle)
        if idx2 >= 0:
            self._pill_progress_combo.setCurrentIndex(idx2)

        hl = str(s.value("current_track_highlight", "glow") or "glow")
        idx3 = self._highlight_combo.findData(hl)
        if idx3 >= 0:
            self._highlight_combo.setCurrentIndex(idx3)

        lh = int(s.value("lyrics_line_height", 40) or 40)
        self._lyrics_overlay_height_spin.setValue(lh)
        lfsh = int(s.value("lyrics_fullscreen_line_height", 60) or 60)
        self._lyrics_fs_line_height_spin.setValue(lfsh)
        lfs = int(s.value("lyrics_font_size", 32) or 32)
        self._lyrics_font_size_spin.setValue(lfs)
        lls = int(s.value("lyrics_letter_spacing", 2) or 2)
        self._lyrics_letter_spacing_spin.setValue(lls)
        lss = str(s.value("lyrics_show_spec", "true")).lower() == "true"
        self._lyrics_show_spec_cb.setChecked(lss)

        online = str(s.value("online_lyrics_enabled", "false")).lower() == "true"
        self._online_lyrics_cb.setChecked(online)
        lrclib = str(s.value("lyrics_source_lrclib", "true")).lower() == "true"
        self._lrclib_cb.setChecked(lrclib)
        custom = str(s.value("lyrics_source_custom", "false")).lower() == "true"
        self._custom_api_cb.setChecked(custom)
        self._custom_url_input.setText(str(s.value("lyrics_custom_url", "")))
        self._custom_token_input.setText(_deobfuscate(str(s.value("lyrics_custom_token", ""))))
        self._custom_api_widget.setVisible(custom)
        auto_save = str(s.value("auto_save_lyrics", "false")).lower() == "true"
        self._auto_save_cb.setChecked(auto_save)
        show_trans = str(s.value("show_translation", "true")).lower() == "true"
        self._show_translation_cb.setChecked(show_trans)

        sidebar_log = str(s.value("sidebar_log", "false")).lower() == "true"
        self._sidebar_log_cb.setChecked(sidebar_log)

        cover_radius = str(s.value("album_cover_radius", "true")).lower() == "true"
        self._cover_cb.setChecked(cover_radius)

        rg = str(s.value("replaygain_enabled", "false")).lower() == "true"
        self._rg_cb.setChecked(rg)

        gapless = str(s.value("gapless_enabled", "false")).lower() == "true"
        self._gapless_cb.setChecked(gapless)

        # Online lyrics custom fields
        self._custom_url_input.textChanged.connect(
            lambda v: s.setValue("lyrics_custom_url", v))
        self._custom_token_input.textChanged.connect(
            lambda v: s.setValue("lyrics_custom_token", _obfuscate(v)))

        # Re-enable signals after bulk load
        self._mode_combo.blockSignals(False)
        self._titlebar_combo.blockSignals(False)
        self._material_combo.blockSignals(False)

    def _refresh_all_labels(self, _code: str = ""):
        # Nav list
        for i, key in enumerate(self._nav_labels):
            item = self._nav_list.item(i)
            if item:
                item.setText(_(key))
        self._title_label.setText(_("settings.title"))
        # Tabs
        self._lang_group.setTitle(_("settings.language"))
        self._tray_cb.setText(_("settings.close_to_tray"))
        if hasattr(self, '_avatar_hint'):
            self._avatar_hint.setText(_("settings.avatar_hint"))
        self._theme_group.setTitle(_("settings.theme"))
        self._accent_group.setTitle(_("settings.accent"))
        self._window_radius_group.setTitle(_("settings.window_radius"))
        self._ui_radius_group.setTitle(_("settings.ui_radius"))
        self._cover_group.setTitle(_("settings.album_cover"))
        self._cover_cb.setText(_("settings.cover_radius"))
        self._dynamic_group.setTitle(_("settings.dynamic_accent"))
        self._dynamic_cb.setText(_("settings.dynamic_accent_enable"))
        self._titlebar_group.setTitle(_("settings.titlebar_style"))
        self._titlebar_note.setText(_("settings.titlebar_restart_note"))
        self._material_group.setTitle(_("settings.material_effect"))
        self._material_note.setText(_("settings.material_desc"))
        self._barstyle_group.setTitle(_("settings.bar_style"))
        self._highlight_group.setTitle(_("settings.highlight_style"))
        # Mode combo items
        self._mode_combo.blockSignals(True)
        self._mode_combo.clear()
        for k in self.THEME_MODES:
            self._mode_combo.addItem(_(f"theme.{k}"), k)
        mode = str(self._settings.value("theme_mode", "dark") or "dark")
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._mode_combo.blockSignals(False)
        # Titlebar combo
        self._titlebar_combo.blockSignals(True)
        self._titlebar_combo.clear()
        self._titlebar_combo.addItem(_("settings.titlebar_auto"), "auto")
        self._titlebar_combo.addItem(_("settings.titlebar_frameless"), "frameless")
        self._titlebar_combo.addItem(_("settings.titlebar_csd"), "csd")
        self._titlebar_combo.addItem(_("settings.titlebar_native"), "native")
        titlebar = str(self._settings.value("window_titlebar", "auto") or "auto")
        idx = self._titlebar_combo.findData(titlebar)
        if idx >= 0:
            self._titlebar_combo.setCurrentIndex(idx)
        self._titlebar_combo.blockSignals(False)
        # Material combo
        self._material_combo.blockSignals(True)
        self._material_combo.clear()
        self._material_combo.addItem(_("settings.material_auto"), "auto")
        self._material_combo.addItem(_("settings.material_acrylic"), "acrylic")
        self._material_combo.addItem(_("settings.material_glass"), "glass")
        self._material_combo.addItem(_("settings.material_none"), "none")
        mat = str(self._settings.value("window_material", "auto") or "auto")
        idx = self._material_combo.findData(mat)
        if idx >= 0:
            self._material_combo.setCurrentIndex(idx)
        self._material_combo.blockSignals(False)
        # Bar style combo
        self._barstyle_combo.blockSignals(True)
        self._barstyle_combo.clear()
        self._barstyle_combo.addItem(_("settings.bar_full"), "full")
        self._barstyle_combo.addItem(_("settings.bar_pill"), "pill")
        barstyle = str(self._settings.value("playback_bar_style", "full") or "full")
        idx = self._barstyle_combo.findData(barstyle)
        if idx >= 0:
            self._barstyle_combo.setCurrentIndex(idx)
        self._barstyle_combo.blockSignals(False)
        # Pill progress combo
        self._pill_progress_combo.blockSignals(True)
        self._pill_progress_combo.clear()
        self._pill_progress_combo.addItem(_("settings.pill_progress_line"), "line")
        self._pill_progress_combo.addItem(_("settings.pill_progress_ring"), "ring")
        pgstyle = str(self._settings.value("pill_progress_style", "line") or "line")
        idx = self._pill_progress_combo.findData(pgstyle)
        if idx >= 0:
            self._pill_progress_combo.setCurrentIndex(idx)
        self._pill_progress_combo.blockSignals(False)
        # Highlight combo
        self._highlight_combo.blockSignals(True)
        self._highlight_combo.clear()
        self._highlight_combo.addItem(_("settings.highlight_glow"), "glow")
        self._highlight_combo.addItem(_("settings.highlight_bar"), "bar")
        hl = str(self._settings.value("current_track_highlight", "glow") or "glow")
        idx = self._highlight_combo.findData(hl)
        if idx >= 0:
            self._highlight_combo.setCurrentIndex(idx)
        self._highlight_combo.blockSignals(False)
        # Lyrics tab
        self._lyrics_group.setTitle(_("settings.lyrics_display"))
        self._lyrics_cb.setText(_("settings.lyrics_enable"))
        self._lyrics_fullscreen_group.setTitle(_("settings.lyrics_fullscreen_group"))
        self._lyrics_show_spec_cb.setText(_("settings.lyrics_audio_spec"))
        self._online_lyrics_group.setTitle(_("settings.online_lyrics"))
        self._online_lyrics_cb.setText(_("settings.enable_online_lyrics"))
        self._lrclib_cb.setText(_("settings.source_lrclib"))
        self._custom_api_cb.setText(_("settings.source_custom_api"))
        self._custom_url_input.setPlaceholderText(_("settings.custom_url_placeholder"))
        self._custom_token_input.setPlaceholderText(_("settings.custom_token_placeholder"))
        self._auto_save_cb.setText(_("settings.auto_save_lyrics"))
        self._show_translation_cb.setText(_("settings.show_translation"))
        self._test_conn_btn.setText(_("settings.test_connection"))
        # Playback tab
        self._viz_group.setTitle(_("settings.visualization"))
        self._viz_combo.clear()
        for label in [_("viz.bars"), _("viz.line"), _("viz.circular")]:
            self._viz_combo.addItem(label)
        self._vol_group.setTitle(_("settings.default_volume"))
        self._rg_cb.setText(_("settings.replaygain"))
        self._rg_cb.setToolTip(_("settings.replaygain_tooltip"))
        self._gapless_cb.setText(_("settings.gapless"))
        self._gapless_cb.setToolTip(_("settings.gapless_tooltip"))
        # Advanced
        if hasattr(self, '_sidebar_log_cb'):
            self._sidebar_log_cb.setText(_("settings.sidebar_log"))
        # About
        self._about_title.setText(_("app.title"))
        self._about_ver.setText("v0.7.1")
