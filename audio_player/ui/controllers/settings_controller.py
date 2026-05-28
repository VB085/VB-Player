from PyQt6.QtCore import QObject, pyqtSignal, QSettings
from PyQt6.QtWidgets import QApplication

from audio_player.app import apply_theme, current_accent, current_theme_mode
from audio_player.player.engine import AudioEngine
from audio_player.player.equalizer import EqualizerManager
from audio_player.ui.widgets.spectrum import SpectrumWidget
from audio_player.ui.widgets.fullscreen_lyrics import FullscreenLyricsWindow
from audio_player.ui.settings_dialog import SettingsDialog
from audio_player.i18n import _


class SettingsController(QObject):
    """Controller for settings, theme, and toggle actions (Groups 7+10)."""

    themeChanged = pyqtSignal(str, str)   # (mode, accent_name)
    accentChanged = pyqtSignal()          # after accent colors refreshed
    logMessage = pyqtSignal(str)          # status bar text

    def __init__(self, equalizer_mgr: EqualizerManager,
                 spectrum: SpectrumWidget,
                 fullscreen_lyrics: FullscreenLyricsWindow,
                 engine: AudioEngine, parent=None):
        super().__init__(parent)
        self._equalizer_mgr = equalizer_mgr
        self._spectrum = spectrum
        self._fullscreen_lyrics = fullscreen_lyrics
        self._engine = engine

    # ------------------------------------------------------------------
    #  Settings dialog
    # ------------------------------------------------------------------

    def open_settings(self, parent_widget=None):
        """Create and exec the settings dialog, wiring all signals."""
        dlg = SettingsDialog(parent_widget)
        dlg.themeChanged.connect(self._on_theme_changed)
        dlg.vizModeChanged.connect(lambda m: self._spectrum.set_mode(m))
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

        if dlg.exec():
            self.logMessage.emit(_("log.settings_saved"))

    # ------------------------------------------------------------------
    #  Theme
    # ------------------------------------------------------------------

    def _on_theme_changed(self, mode: str, accent_name: str):
        apply_theme(QApplication.instance(), mode, accent_name)
        self.themeChanged.emit(mode, accent_name)
        self.accentChanged.emit()

    # ------------------------------------------------------------------
    #  Lyrics toggles
    # ------------------------------------------------------------------

    def toggle_lyrics(self):
        """Toggle spectrum lyrics overlay; return new visibility."""
        visible = self._spectrum.toggle_lyrics()
        return visible

    def on_lyrics_toggled(self, enabled: bool):
        if enabled:
            self._spectrum.show_lyrics()
        else:
            self._spectrum.hide_lyrics()

    def on_lyrics_line_height(self, px: int):
        self._spectrum.lyrics_overlay.set_line_height(px)
        QSettings("VBPlayer", "VB Player").setValue("lyrics_line_height", px)

    def on_lyrics_fullscreen_line_height(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_fullscreen_line_height", px)
        self._fullscreen_lyrics.update()

    def on_lyrics_font_size(self, pt: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_font_size", pt)
        self._fullscreen_lyrics.update()

    def on_lyrics_letter_spacing(self, px: int):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_letter_spacing", px)
        self._fullscreen_lyrics.update()

    def on_lyrics_show_spec_toggled(self, show: bool):
        QSettings("VBPlayer", "VB Player").setValue("lyrics_show_spec", show)
        self._fullscreen_lyrics._update_spec_bar()

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

    # ------------------------------------------------------------------
    #  Restore persisted settings
    # ------------------------------------------------------------------

    def restore_settings(self, volume_control=None, sidebar=None):
        """Read QSettings and apply to engine/spectrum/sidebar."""
        s = QSettings("VBPlayer", "VB Player")

        # Volume
        vol = float(s.value("default_volume", 100) or 100) / 100.0
        self._engine.volume = vol
        if volume_control is not None:
            volume_control.set_value(vol)

        # Lyrics line height
        lh = int(s.value("lyrics_line_height", 40) or 40)
        self._spectrum.lyrics_overlay.set_line_height(lh)

        # Sidebar log
        sidebar_log = str(s.value("sidebar_log", "false")).lower() == "true"
        if sidebar is not None:
            sidebar.set_log_visible(sidebar_log)

        # Exclusive mode
        exclusive = str(s.value("exclusive_mode", "false")).lower() == "true"
        exclusive_dev = str(s.value("exclusive_device", "hw:0,0") or "hw:0,0")
        self._engine._exclusive_mode = exclusive
        self._engine._exclusive_device = exclusive_dev

        # ReplayGain
        rg = str(s.value("replaygain_enabled", "false")).lower() == "true"
        self._engine._replaygain_enabled = rg

        # Gapless playback
        gapless = str(s.value("gapless_enabled", "false")).lower() == "true"
        self._engine._gapless_enabled = gapless
