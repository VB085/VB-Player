"""Keyboard shortcut manager — registers all global shortcuts on a parent window."""

from PyQt6.QtWidgets import QLineEdit, QApplication
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtCore import QObject


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
            (f"{mod}+Left", "prev_track"),
            (f"{mod}+Right", "next_track"),
            ("Delete", "remove_selected"),
            ("R", "cycle_playback_mode"),
        ]

        for keys, action in bindings:
            sc = QShortcut(QKeySequence(keys), w)
            sc.activated.connect(self._make_handler(action))
            self._shortcuts.append(sc)

        # Number keys 1-9: seek to 10%-90%
        for pct in range(1, 10):
            sc = QShortcut(QKeySequence(str(pct)), w)
            sc.activated.connect(self._make_jump_handler(pct * 10))
            self._shortcuts.append(sc)

    def _make_handler(self, action: str):
        def handler():
            # Skip shortcuts when a QLineEdit has focus
            if QApplication.focusWidget() and isinstance(QApplication.focusWidget(), QLineEdit):
                return
            cb = self._callbacks.get(action)
            if cb:
                cb()
        return handler

    def _make_jump_handler(self, pct: int):
        def handler():
            if QApplication.focusWidget() and isinstance(QApplication.focusWidget(), QLineEdit):
                return
            cb = self._callbacks.get("jump_to_pct")
            if cb:
                cb(pct)
        return handler
