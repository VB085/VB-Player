"""Linux D-Bus notifications."""

from audio_player.platform.base import PlatformNotifier


class LinuxNotifier(PlatformNotifier):
    """Sends notifications via D-Bus org.freedesktop.Notifications."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = False
        try:
            import gi
            gi.require_version('Notify', '0.7')
            from gi.repository import Notify
            Notify.init("VB Player")
            self._Notify = Notify
            self._available = True
        except (ImportError, ValueError):
            pass

    def show(self, title: str, body: str):
        if not self._available:
            return
        try:
            n = self._Notify.Notification.new(title, body, "")
            n.show()
        except Exception:
            pass
