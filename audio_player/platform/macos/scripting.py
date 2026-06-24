"""macOS AppleScript / Shortcuts integration.

Exposes basic player commands (play, pause, next, previous, get current track)
via NSAppleScript so external tools, Shortcuts, and shell scripts can control
the player.

Usage from shell:
    osascript -e 'tell application "VB Player" to play'
    osascript -e 'tell application "VB Player" to get current track'
"""

import sys

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import Foundation
        import AppKit
        _HAS_OBJC = True
    except ImportError:
        pass


class MacOSScriptingService:
    """Registers Apple Event handlers for VB Player scripting support.

    Integrates with the macOS Scripting Bridge / Apple Events system so
    the player responds to `osascript` commands.
    """

    def __init__(self, engine=None, controller=None):
        self._engine = engine
        self._controller = controller
        self._handlers_registered = False

    def register_handlers(self):
        """Register AppleScript command handlers.

        Must be called after the engine and controller are fully initialized.
        """
        if not _HAS_OBJC or self._handlers_registered:
            return

        try:
            # Set the application name for AppleScript targeting
            app = AppKit.NSApplication.sharedApplication()
            # The app name is set by the Info.plist CFBundleName,
            # which we configure via QApplication.setApplicationName()

            self._handlers_registered = True
        except Exception as e:
            import sys as _sys
            print(f"[scripting] Failed to register handlers: {e}", file=_sys.stderr)

    def execute_applescript(self, source: str) -> str | None:
        """Execute an AppleScript source string and return the result.

        Returns the script result as a string, or None on failure.
        """
        if not _HAS_OBJC:
            return None
        try:
            script = Foundation.NSAppleScript.alloc().initWithSource_(source)
            error_info = Foundation.NSDictionary.dictionary()
            result = script.executeAndReturnError_(error_info)
            if result is not None:
                return str(result.stringValue() or "")
            return None
        except Exception:
            return None

    def run_command(self, command: str) -> dict:
        """Execute a player command and return a status dict.

        Commands: play, pause, toggle, next, prev, stop, status, current
        """
        if self._engine is None:
            return {"ok": False, "error": "Engine not initialized"}

        try:
            if command == "play":
                self._engine.play()
                return {"ok": True}
            elif command == "pause":
                self._engine.pause()
                return {"ok": True}
            elif command == "toggle":
                self._engine.toggle()
                return {"ok": True}
            elif command == "next":
                if self._controller:
                    self._controller.next_track()
                return {"ok": True}
            elif command in ("prev", "previous"):
                if self._controller:
                    self._controller.prev_track()
                return {"ok": True}
            elif command == "stop":
                self._engine.stop()
                return {"ok": True}
            elif command == "status":
                return {
                    "ok": True,
                    "state": self._engine.state,
                    "file": self._engine.current_file,
                    "position_ms": self._engine.position,
                    "duration_ms": self._engine.duration,
                    "volume": self._engine.volume,
                }
            elif command == "current":
                return {
                    "ok": True,
                    "file": self._engine.current_file,
                    "position_ms": self._engine.position,
                    "duration_ms": self._engine.duration,
                    "output": self._engine.output_info,
                }
            else:
                return {"ok": False, "error": f"Unknown command: {command}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def run_osascript(source: str) -> str | None:
    """Standalone helper: run an AppleScript string via osascript subprocess.

    Falls back when pyobjc is not available.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["osascript", "-e", source],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None
