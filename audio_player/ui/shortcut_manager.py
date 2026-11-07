"""Keyboard shortcut manager — registers all global shortcuts on a parent window."""

from PyQt6.QtWidgets import (QApplication, QLineEdit, QTextEdit, QPlainTextEdit,
                             QComboBox, QAbstractItemView, QAbstractSlider,
                             QAbstractSpinBox, QAbstractButton, QWidget)
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtCore import QObject, Qt


# Widget classes that "own" certain keys while focused.
_TEXT_ENTRY = (QLineEdit, QTextEdit, QPlainTextEdit)
# Widgets where arrow keys navigate/adjust the widget itself — bare-arrow
# seek/volume must not steal them.
_ARROWS_OWNED = (QComboBox, QAbstractSlider, QAbstractItemView, QAbstractSpinBox)
# Keys 0-9 or letters would interfere with these while focused.
_DIGITS_OWNED = (QComboBox, QAbstractSlider, QAbstractSpinBox, QAbstractButton)


class ShortcutManager(QObject):
    """Registers and manages all keyboard shortcuts for the main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shortcuts: list[QShortcut] = []
        self._callbacks: dict = {}

    def register_all(self, callbacks: dict):
        """Register all standard shortcuts. *callbacks* maps action names to callables.

        Expected keys:
          play_pause, open_files, open_folder, save_playlist, load_playlist,
          cycle_viz, toggle_lyrics, seek_back, seek_forward,
          volume_up, volume_down, prev_track, next_track,
          remove_selected, cycle_playback_mode, jump_to_pct

        Optional keys (registered only when present, so MainWindow can adopt
        them incrementally without touching this file):
          focus_search, toggle_mute, fullscreen_lyrics, goto_page(int)
        """
        self._callbacks = callbacks
        w = self.parent()

        # Platform-aware modifier: Cmd on macOS, Ctrl elsewhere
        mod = "Meta" if __import__("sys").platform == "darwin" else "Ctrl"

        bindings = [
            ("Space", "play_pause"),
            (f"{mod}+O", "open_files"),
            (f"{mod}+Shift+O", "open_folder"),
            (f"{mod}+S", "save_playlist"),
            (f"{mod}+L", "load_playlist"),
            ("V", "cycle_viz"),
            (f"{mod}+Shift+L", "toggle_lyrics"),
            ("Left", "seek_back"),
            ("Right", "seek_forward"),
            ("Up", "volume_up"),
            ("Down", "volume_down"),
            # Always-available volume keys — work even when a list/slider has focus
            (f"{mod}+Up", "volume_up"),
            (f"{mod}+Down", "volume_down"),
            (f"{mod}+Left", "prev_track"),
            (f"{mod}+Right", "next_track"),
            ("Delete", "remove_selected"),
            ("R", "cycle_playback_mode"),
        ]

        for keys, action in bindings:
            self._add(keys, action, guarded=True)

        # Optional extras — only activate if MainWindow provides the callback
        optional = [
            (f"{mod}+F", "focus_search"),
            ("M", "toggle_mute"),
            ("F11", "fullscreen_lyrics"),
        ]
        for keys, action in optional:
            if action in callbacks:
                self._add(keys, action, guarded=True)
        if "goto_page" in callbacks:
            for idx in range(1, 8):
                self._add(f"{mod}+{idx}", "goto_page", guarded=False,
                          arg=idx)

        # Hardware media keys — never guarded, no focused widget consumes them
        media_keys = [
            (Qt.Key.Key_MediaPlay, "play_pause"),
            (Qt.Key.Key_MediaPause, "play_pause"),
            (Qt.Key.Key_MediaTogglePlayPause, "play_pause"),
            (Qt.Key.Key_MediaNext, "next_track"),
            (Qt.Key.Key_MediaPrevious, "prev_track"),
        ]
        for key, action in media_keys:
            if action in callbacks:
                self._add(QKeySequence(key), action, guarded=False)

        # Number keys 1-9: seek to 10%-90%
        for pct in range(1, 10):
            self._add(str(pct), "jump_to_pct", guarded=True, arg=pct * 10)

    def _add(self, keys, action: str, guarded: bool, arg=None):
        sc = QShortcut(QKeySequence(keys), self.parent())
        sc.activated.connect(self._make_handler(action, guarded, arg))
        self._shortcuts.append(sc)

    def _blocks(self, action: str) -> bool:
        """True when the focused widget should handle this key instead of us."""
        w = QApplication.focusWidget()
        if w is None or not isinstance(w, QWidget):
            return False
        if isinstance(w, _TEXT_ENTRY):
            return True  # typing — block every action
        if action in ("seek_back", "seek_forward", "volume_up", "volume_down"):
            return isinstance(w, _ARROWS_OWNED)
        if action == "play_pause":
            return isinstance(w, QAbstractButton)  # Space activates buttons
        if action == "jump_to_pct":
            return isinstance(w, _DIGITS_OWNED)
        if action in ("cycle_viz", "cycle_playback_mode", "toggle_lyrics",
                      "focus_search", "toggle_mute", "fullscreen_lyrics"):
            return isinstance(w, (QComboBox, QAbstractSlider))
        return False

    def _make_handler(self, action: str, guarded: bool, arg=None):
        def handler():
            if guarded and self._blocks(action):
                return
            cb = self._callbacks.get(action)
            if cb:
                if arg is None:
                    cb()
                else:
                    cb(arg)
        return handler
