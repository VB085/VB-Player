from PyQt6.QtCore import QObject, pyqtSignal, QSettings
from PyQt6.QtWidgets import QApplication

from audio_player.app import apply_theme, current_accent, current_theme_mode
from audio_player.player.engine import AudioEngine
from audio_player.player.equalizer import EqualizerManager
from audio_player.ui.settings_dialog import SettingsDialog
from audio_player.i18n import _


class SettingsController(QObject):
    """Controller for settings, theme, and toggle actions. Emits signals for
    UI changes instead of directly calling widget methods."""

    themeChanged = pyqtSignal(str, str)   # (mode, accent_name)
    accentChanged = pyqtSignal()          # after accent colors refreshed
    logMessage = pyqtSignal(str)          # status bar text
    coverRadiusChanged = pyqtSignal()     # album cover corner radius toggled

    # Widget control signals — connected in MainWindow
    vizModeChanged = pyqtSignal(int)
    lyricsToggled = pyqtSignal(bool)
    lyricsLineHeightChanged = pyqtSignal(int)
    lyricsFullscreenLineHeightChanged = pyqtSignal(int)
    lyricsFontSizeChanged = pyqtSignal(int)
    lyricsLetterSpacingChanged = pyqtSignal(int)
    lyricsShowSpecToggled = pyqtSignal(bool)
    fullscreenLyricsUpdate = pyqtSignal()
    defaultVolumeChanged = pyqtSignal(float)

    materialChanged = pyqtSignal(str)

    def __init__(self, equalizer_mgr: EqualizerManager,
                 engine: AudioEngine, parent=None):
        super().__init__(parent)
        self._equalizer_mgr = equalizer_mgr
        self._engine = engine

    # ------------------------------------------------------------------
    #  Settings dialog
    # ------------------------------------------------------------------

    def open_settings(self, parent_widget=None):
        """Create and exec the settings dialog, wiring all signals."""
        dlg = SettingsDialog(parent_widget)
        dlg.themeChanged.connect(self._on_theme_changed)
        dlg.vizModeChanged.connect(lambda m: self.vizModeChanged.emit(m))
        dlg.defaultVolumeChanged.connect(lambda v: setattr(self._engine, 'volume', v))
        dlg.lyricsToggled.connect(self.on_lyrics_toggled)
        dlg.lyricsLineHeightChanged.connect(self.on_lyrics_line_height)
        dlg.lyricsFullscreenLineHeightChanged.connect(self.on_lyrics_fullscreen_line_height)
        dlg.lyricsFontSizeChanged.connect(self.on_lyrics_font_size)
        dlg.lyricsLetterSpacingChanged.connect(self.on_lyrics_letter_spacing)
        dlg.lyricsShowSpecToggled.connect(self.on_lyrics_show_spec_toggled)
        dlg.onlineLyricsToggled.connect(self.on_online_lyrics_toggled)
        dlg.autoSaveLyricsToggled.connect(self.on_auto_save_lyrics_toggled)
        dlg.showTranslationToggled.connect(self.on_show_translation_toggled)
        dlg.sidebarLogToggled.connect(self.on_sidebar_log_toggled)
        dlg.albumCoverRadiusToggled.connect(self.on_album_cover_radius_toggled)
        dlg.materialChanged.connect(lambda v: self.materialChanged.emit(v))
        dlg.titlebarChanged.connect(lambda v: self.logMessage.emit(_("log.titlebar_restart")))
        dlg.dynamicAccentToggled.connect(self._on_dynamic_accent_toggled)

        # Equalizer state -> settings dialog
        dlg.set_eq_state(
            self._equalizer_mgr.enabled,
            self._equalizer_mgr.current_preset,
            self._equalizer_mgr.all_gains(),
        )
        dlg.eqBandChanged.connect(self._equalizer_mgr.set_band_gain)
        dlg.eqBandChanged.connect(self._engine.set_eq_band_gain)
        dlg.eqPresetSelected.connect(self.on_eq_preset_from_settings)
        dlg.eqResetRequested.connect(self.on_eq_reset_from_settings)
        dlg.eqEnabledToggled.connect(self.on_eq_enabled_from_settings)

        # Exclusive mode
        dlg.set_exclusive_state(self._engine.exclusive_mode, self._engine.exclusive_device)
        dlg.exclusiveModeToggled.connect(lambda v: setattr(self._engine, 'exclusive_mode', v))
        dlg.exclusiveDeviceChanged.connect(lambda v: setattr(self._engine, 'exclusive_device', v))
        # DSD decode mode
        dlg.set_dsd_mode(self._engine.dsd_mode)
        dlg.dsdModeChanged.connect(lambda v: setattr(self._engine, 'dsd_mode', v))

        # ReplayGain
        dlg.set_replaygain_state(self._engine.replaygain_enabled)
        dlg.replaygainToggled.connect(lambda v: setattr(self._engine, 'replaygain_enabled', v))

        # Gapless playback
        dlg.set_gapless_state(self._engine.gapless_enabled)
        dlg.gaplessToggled.connect(lambda v: setattr(self._engine, 'gapless_enabled', v))

        # Account stats — passed from MainWindow
        from audio_player.platform import platform_info
        if hasattr(parent_widget, '_library') and hasattr(parent_widget, '_playlist'):
            tracks = parent_widget._playlist.count if hasattr(parent_widget, '_playlist') else 0
            albums = len(parent_widget._album_view._albums) if hasattr(parent_widget, '_album_view') else 0
            playlists = len(parent_widget._library.get_playlist_names()) if hasattr(parent_widget, '_library') else 0
            dlg.set_account_stats(tracks, albums, playlists)

        if dlg.exec():
            self.logMessage.emit(_("log.settings_saved"))

    # ------------------------------------------------------------------
    #  Theme
    # ------------------------------------------------------------------

    def _on_dynamic_accent_toggled(self, enabled: bool):
        from audio_player.app import clear_dynamic_accent
        from audio_player.player.metadata import read_metadata
        from audio_player.app import set_dynamic_accent
        from audio_player.ui.color_extractor import extract_accent
        from PyQt6.QtGui import QPixmap

        if not enabled:
            clear_dynamic_accent()
            self.logMessage.emit(_("log.dynamic_accent_off"))
        else:
            # Re-apply dynamic accent from current track immediately
            if self._engine and self._engine.current_file:
                meta = read_metadata(self._engine.current_file)
                if meta and meta.cover_data:
                    pix = QPixmap()
                    pix.loadFromData(meta.cover_data)
                    if not pix.isNull():
                        color = extract_accent(pix)
                        set_dynamic_accent(color)
            self.logMessage.emit(_("log.dynamic_accent_on"))
        self.accentChanged.emit()

    def _on_theme_changed(self, mode: str, accent_name: str):
        apply_theme(QApplication.instance(), mode, accent_name)
        self.themeChanged.emit(mode, accent_name)
        self.accentChanged.emit()

    # ------------------------------------------------------------------
    #  Lyrics toggles
    # ------------------------------------------------------------------

    # Note: toggle_lyrics moved to MainWindow since it needs widget ref

    def on_lyrics_toggled(self, enabled: bool):
        self.lyricsToggled.emit(enabled)

    def on_lyrics_line_height(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_line_height", px)
        self.lyricsLineHeightChanged.emit(px)

    def on_lyrics_fullscreen_line_height(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_fullscreen_line_height", px)
        self.lyricsFullscreenLineHeightChanged.emit(px)

    def on_lyrics_font_size(self, pt: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_font_size", pt)
        self.lyricsFontSizeChanged.emit(pt)

    def on_lyrics_letter_spacing(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_letter_spacing", px)
        self.lyricsLetterSpacingChanged.emit(px)

    def on_lyrics_show_spec_toggled(self, show: bool):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_show_spec", show)
        self.lyricsShowSpecToggled.emit(show)

    def on_online_lyrics_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("online_lyrics_enabled", enabled)

    def on_auto_save_lyrics_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("auto_save_lyrics", enabled)

    def on_show_translation_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("show_translation", enabled)

    # ------------------------------------------------------------------
    #  Sidebar / misc toggles
    # ------------------------------------------------------------------

    def on_sidebar_log_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("sidebar_log", enabled)

    def on_eq_preset_from_settings(self, name: str):
        self._equalizer_mgr.apply_preset(name)
        self._engine.set_eq_all_gains(self._equalizer_mgr.all_gains())

    def on_eq_reset_from_settings(self):
        self._equalizer_mgr.reset_flat()
        self._engine.set_eq_all_gains([0.0] * 10)

    def on_eq_enabled_from_settings(self, enabled: bool):
        self._equalizer_mgr.enabled = enabled
        self._engine.set_eq_enabled(enabled)

    def on_exclusive_mode_changed(self, enabled: bool):
        self.logMessage.emit(
            _("log.exclusive_alsa") if enabled else _("log.exclusive_shared")
        )

    def on_album_cover_radius_toggled(self, enabled: bool):
        QSettings("VBPlayer", "VB Player").setValue("album_cover_radius", enabled)
        self.coverRadiusChanged.emit()

    # ------------------------------------------------------------------
    #  Restore persisted settings
    # ------------------------------------------------------------------

    def restore_settings(self, volume_control=None, sidebar=None):
        """Read QSettings and apply to engine/volume/sidebar. Emits signals for
        UI widgets to pick up."""
        s = QSettings("VBPlayer", "VB Player")

        # Volume
        vol = float(s.value("default_volume", 100) or 100) / 100.0
        self._engine.volume = vol
        if volume_control is not None:
            volume_control.set_value(vol)

        # Lyrics line height — emit signal, MainWindow connects to spectrum
        lh = int(s.value("lyrics_line_height", 40) or 40)
        self.lyricsLineHeightChanged.emit(lh)

        # Sidebar log
        sidebar_log = str(s.value("sidebar_log", "false")).lower() == "true"
        if sidebar is not None:
            sidebar.set_log_visible(sidebar_log)

        # Exclusive mode
        exclusive = str(s.value("exclusive_mode", "false")).lower() == "true"
        exclusive_dev = str(s.value("exclusive_device", "hw:0,0") or "hw:0,0")
        self._engine.exclusive_mode = exclusive
        self._engine.exclusive_device = exclusive_dev

        # ReplayGain
        rg = str(s.value("replaygain_enabled", "false")).lower() == "true"
        self._engine.replaygain_enabled = rg

        # Gapless playback
        gapless = str(s.value("gapless_enabled", "false")).lower() == "true"
        self._engine.gapless_enabled = gapless
