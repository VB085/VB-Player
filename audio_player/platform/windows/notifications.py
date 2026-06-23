"""Windows toast notifications — delegates to QSystemTrayIcon.showMessage().

On Windows 10/11, QSystemTrayIcon.showMessage() renders as a native toast
notification, not a legacy balloon tip.
"""

from audio_player.platform.base import PlatformNotifier


class WinNotifier(PlatformNotifier):
    """Windows notification backend.

    The app's TrayManager owns the QSystemTrayIcon. A reference to its
    ``show_message`` method must be injected via :meth:`set_show_fn` after
    both objects are created (typically in MainWindow._setup_tray).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_fn = None

    def set_show_fn(self, fn):
        """Set the notification callback.

        *fn* should be a callable with signature ``(title: str, message: str)``.
        Typically this is :meth:`TrayManager.show_message
        <audio_player.ui.tray_manager.TrayManager.show_message>`.
        """
        self._show_fn = fn

    def show(self, title: str, body: str):
        """Show a native toast notification."""
        if self._show_fn:
            try:
                self._show_fn(title, body)
            except Exception:
                pass
