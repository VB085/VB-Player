"""System tray manager — wraps QSystemTrayIcon lifecycle and menu."""

import os

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon, QAction
from PyQt6.QtCore import Qt

from audio_player.i18n import _
from audio_player.player.metadata import read_metadata


class TrayManager(QObject):
    """Manages QSystemTrayIcon: icon, context menu, tooltip, lifecycle."""

    showWindowRequested = pyqtSignal()
    quitRequested = pyqtSignal()
    playPauseRequested = pyqtSignal()
    nextRequested = pyqtSignal()
    prevRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None

    def setup(self):
        """Create and show the system tray icon."""
        self._tray = QSystemTrayIcon(self.parent())
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
        show_act.triggered.connect(self.showWindowRequested.emit)
        tray_menu.addAction(show_act)
        tray_menu.addSeparator()
        play_act = QAction(_("tray.play_pause"), self)
        play_act.triggered.connect(self.playPauseRequested.emit)
        tray_menu.addAction(play_act)
        prev_act = QAction(_("tray.prev"), self)
        prev_act.triggered.connect(self.prevRequested.emit)
        tray_menu.addAction(prev_act)
        next_act = QAction(_("tray.next"), self)
        next_act.triggered.connect(self.nextRequested.emit)
        tray_menu.addAction(next_act)
        tray_menu.addSeparator()
        quit_act = QAction(_("tray.quit"), self)
        quit_act.triggered.connect(self.quitRequested.emit)
        tray_menu.addAction(quit_act)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def update_tooltip(self, filepath: str):
        """Update tray tooltip with current track info."""
        if not self._tray:
            return
        meta = read_metadata(filepath)
        title = meta.title or os.path.basename(filepath)
        artist = meta.artist or ""
        tip = f"{artist} — {title}" if artist else title
        self._tray.setToolTip(f"VB Player — {tip}")

    def show_message(self, title: str, message: str):
        """Show a tray notification."""
        if self._tray and self._tray.isVisible():
            self._tray.showMessage(title, message,
                                   QSystemTrayIcon.MessageIcon.Information, 1500)

    def hide_tray(self):
        if self._tray:
            self._tray.hide()

    def is_visible(self) -> bool:
        return self._tray is not None and self._tray.isVisible()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showWindowRequested.emit()
