"""macOS native notifications -- UNUserNotificationCenter with NSUserNotification fallback."""

import sys

from audio_player.platform.base import PlatformNotifier

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import Foundation
        import objc
        _HAS_OBJC = True
    except ImportError:
        pass


class MacOSNotifier(PlatformNotifier):
    """Sends macOS native notifications.

    On macOS 10.14+ (Mojave) uses UNUserNotificationCenter.
    Falls back to deprecated NSUserNotification on older systems.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available = False
        self._use_un = False  # True = UNUserNotificationCenter
        self._delegate = None
        self._un_center = None
        if not _HAS_OBJC:
            return
        try:
            import UserNotifications
            self._UserNotifications = UserNotifications
            self._un_center = UserNotifications.UNUserNotificationCenter.currentNotificationCenter()
            self._use_un = True
            self._available = True
            # Request authorization
            self._un_center.requestAuthorizationWithOptions_completionHandler_(
                7,  # alert + sound + badge
                lambda granted, err: None,
            )
        except (ImportError, Exception):
            # Fallback to NSUserNotification (pre-Mojave)
            self._available = True

    def show(self, title: str, body: str):
        if not self._available:
            return
        if self._use_un:
            self._show_un(title, body)
        else:
            self._show_legacy(title, body)

    def is_authorized(self) -> bool:
        return self._available

    def request_authorization(self):
        if self._use_un and self._un_center is not None:
            self._un_center.requestAuthorizationWithOptions_completionHandler_(
                7, lambda granted, err: None,
            )

    # ------------------------------------------------------------------
    #  UNUserNotificationCenter (10.14+)
    # ------------------------------------------------------------------

    def _show_un(self, title: str, body: str):
        try:
            UN = self._UserNotifications
            content = UNMutableContent = UN.UNMutableNotificationContent.alloc().init()
            content.setTitle_(title)
            content.setBody_(body)
            content.setSound_(UN.UNNotificationSound.defaultSound())

            request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(
                f"vbplayer-{id(title)}",
                content,
                None,  # deliver immediately
            )
            self._un_center.addNotificationRequest_withCompletionHandler_(
                request, lambda err: None,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  NSUserNotification fallback (pre-Mojave, deprecated)
    # ------------------------------------------------------------------

    def _show_legacy(self, title: str, body: str):
        try:
            import AppKit
            notification = AppKit.NSUserNotification.alloc().init()
            notification.setTitle_(title)
            notification.setInformativeText_(body)
            notification.setSoundName_(AppKit.NSUserNotificationDefaultSoundName)
            center = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
            center.deliverNotification_(notification)
        except Exception:
            pass
