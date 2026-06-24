"""macOS materials -- NSVisualEffectView vibrancy, native fullscreen, Dock integration.

Provides:
  - enable_vibrancy()      -- insert NSVisualEffectView behind a QWidget
  - apply_dark_titlebar()  -- dark NSWindow titlebar
  - enable_native_fullscreen() / toggle_native_fullscreen()
  - set_dock_badge()       -- Dock tile badge label
  - set_dock_progress()    -- Dock tile progress bar
"""

import sys
from enum import IntEnum

_HAS_OBJC = False
if sys.platform == "darwin":
    try:
        import AppKit
        import Foundation
        import objc
        _HAS_OBJC = True
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Vibrancy material presets
# ---------------------------------------------------------------------------

class VibrancyMaterial(IntEnum):
    """Maps to NSVisualEffectView.Material values."""
    Titlebar           = 3
    Selection          = 4
    Menu               = 5
    Popover            = 6
    Sidebar            = 7
    HeaderView         = 10
    Sheet              = 11
    WindowBackground   = 6   # alias
    HUDWindow          = 13
    FullScreenUI       = 15
    ToolTip            = 17
    ContentBackground  = 18
    UnderWindowBackground = 21
    UnderPageBackground   = 22


# Material name -> enum value  (for settings combo box data)
MATERIAL_PRESETS: dict[str, int] = {
    "sidebar":          VibrancyMaterial.Sidebar,
    "hudWindow":        VibrancyMaterial.HUDWindow,
    "sheet":            VibrancyMaterial.Sheet,
    "popover":          VibrancyMaterial.Popover,
    "headerView":       VibrancyMaterial.HeaderView,
    "selection":        VibrancyMaterial.Selection,
    "menu":             VibrancyMaterial.Menu,
    "titlebar":         VibrancyMaterial.Titlebar,
    "fullScreenUI":     VibrancyMaterial.FullScreenUI,
    "contentBackground": VibrancyMaterial.ContentBackground,
    "underWindow":      VibrancyMaterial.UnderWindowBackground,
    "underPage":        VibrancyMaterial.UnderPageBackground,
}


# ---------------------------------------------------------------------------
# Vibrancy
# ---------------------------------------------------------------------------

def enable_vibrancy(widget, material: str = "hudWindow",
                    blending_mode: str = "behindWindow") -> object | None:
    """Insert an NSVisualEffectView behind *widget*'s native NSView.

    Returns the NSVisualEffectView on success, None on failure.

    Parameters
    ----------
    widget : QWidget
        The Qt widget to decorate.  Must already be shown (`winId()` valid).
    material : str
        Material name from MATERIAL_PRESETS (e.g. `"hudWindow"`, `"sidebar"`).
    blending_mode : str
        `"behindWindow"` (default) or `"withinWindow"`.
    """
    if not _HAS_OBJC:
        return None
    try:
        ns_view = widget.winId().__int__()
        ns_view_obj = AppKit.NSView.alloc().initWithTag_(0)
        # Retrieve the actual NSView via objc
        ns_view_obj = objc.objc_object(c_void_p=ns_view)
        if ns_view_obj is None:
            return None

        bounds = ns_view_obj.bounds()

        vibrancy = AppKit.NSVisualEffectView.alloc().initWithFrame_(bounds)
        mat_value = MATERIAL_PRESETS.get(material, VibrancyMaterial.HUDWindow)
        vibrancy.setMaterial_(mat_value)
        vibrancy.setBlendingMode_(
            0 if blending_mode == "behindWindow" else 1  # NSVisualEffectBlendingMode
        )
        vibrancy.setState_(1)  # NSVisualEffectViewStateActive
        vibrancy.setAutoresizingMask_(18)  # Width + Height flexible

        # Insert as the first subview (behind all Qt content)
        ns_view_obj.addSubview_positioned_relativeTo_(
            vibrancy, AppKit.NSWindowBelow, None
        )
        return vibrancy
    except Exception as e:
        import sys as _sys
        print(f"[materials] enable_vibrancy failed: {e}", file=_sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Dark titlebar
# ---------------------------------------------------------------------------

def apply_dark_titlebar(widget) -> bool:
    """Apply dark-mode appearance to the window's NSWindow titlebar."""
    if not _HAS_OBJC:
        return False
    try:
        window = widget.windowHandle()
        if window is None:
            return False
        nswin = objc.objc_object(c_void_p=window.winId().__int__())
        appearance = AppKit.NSAppearance.appearanceNamed_(
            "NSAppearanceNameDarkAqua"
        )
        nswin.setAppearance_(appearance)
        return True
    except Exception:
        return False


def apply_appearance(widget, theme: str) -> bool:
    """Set the window appearance to match the given theme ('dark' or 'light')."""
    if not _HAS_OBJC:
        return False
    try:
        window = widget.windowHandle()
        if window is None:
            return False
        nswin = objc.objc_object(c_void_p=window.winId().__int__())
        if theme == "dark":
            appearance = AppKit.NSAppearance.appearanceNamed_(
                "NSAppearanceNameDarkAqua"
            )
        else:
            appearance = AppKit.NSAppearance.appearanceNamed_(
                "NSAppearanceNameAqua"
            )
        nswin.setAppearance_(appearance)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Native fullscreen
# ---------------------------------------------------------------------------

def enable_native_fullscreen(widget) -> bool:
    """Add the full-screen button and collection behavior to the widget's NSWindow.

    Call once after the widget has a valid `winId()` (e.g. after `show()`).
    """
    if not _HAS_OBJC:
        return False
    try:
        window = widget.windowHandle()
        if window is None:
            return False
        nswin = objc.objc_object(c_void_p=window.winId().__int__())

        # Add fullscreen collection behavior
        NSWindowCollectionBehaviorFullScreenPrimary = 1 << 7
        NSWindowCollectionBehaviorFullScreenAuxiliary = 1 << 8
        current = nswin.collectionBehavior()
        nswin.setCollectionBehavior_(
            current | NSWindowCollectionBehaviorFullScreenPrimary
        )

        # Add full-screen button to title bar (if not already present)
        button = nswin.standardWindowButton_(2)  # NSWindowFullScreenButton
        if button is not None:
            try:
                nswin.contentView().superview().addSubview_(button)
            except Exception:
                pass
        return True
    except Exception:
        return False


def toggle_native_fullscreen(widget) -> bool:
    """Toggle native macOS fullscreen via NSWindow.toggleFullScreen_.

    Returns True on success.
    """
    if not _HAS_OBJC:
        return False
    try:
        window = widget.windowHandle()
        if window is None:
            return False
        nswin = objc.objc_object(c_void_p=window.winId().__int__())
        nswin.toggleFullScreen_(None)
        return True
    except Exception:
        return False


def is_native_fullscreen(widget) -> bool:
    """Check if the widget's NSWindow is currently in fullscreen."""
    if not _HAS_OBJC:
        return False
    try:
        window = widget.windowHandle()
        if window is None:
            return False
        nswin = objc.objc_object(c_void_p=window.winId().__int__())
        NSWindowStyleMaskFullScreen = 1 << 14
        return bool(nswin.styleMask() & NSWindowStyleMaskFullScreen)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dock integration
# ---------------------------------------------------------------------------

def set_dock_badge(text: str) -> bool:
    """Set the Dock tile badge label (e.g. track count or state icon)."""
    if not _HAS_OBJC:
        return False
    try:
        dock_tile = AppKit.NSApplication.sharedApplication().dockTile()
        dock_tile.setBadgeLabel_(text if text else None)
        return True
    except Exception:
        return False


def set_dock_progress(fraction: float | None) -> bool:
    """Show/hide a progress bar on the Dock tile.

    *fraction* in [0.0, 1.0] shows the bar; `None` hides it.
    """
    if not _HAS_OBJC:
        return False
    try:
        app = AppKit.NSApplication.sharedApplication()
        dock_tile = app.dockTile()
        if fraction is None:
            dock_tile.setContentView_(None)
            dock_tile.display()
            return True

        # Create an NSProgressIndicator
        import objc
        frame = Foundation.NSMakeRect(0, 0, dock_tile.size().width, 10)
        progress = AppKit.NSProgressIndicator.alloc().initWithFrame_(frame)
        progress.setIndeterminate_(False)
        progress.setMinValue_(0.0)
        progress.setMaxValue_(1.0)
        progress.setDoubleValue_(max(0.0, min(1.0, fraction)))
        progress.setStyle_(0)  # NSProgressIndicatorStyleBar
        progress.setAutoresizingMask_(2)  # Width flexible

        # Background view
        bg = AppKit.NSView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, dock_tile.size().width, dock_tile.size().height)
        )
        bg.addSubview_(progress)
        dock_tile.setContentView_(bg)
        dock_tile.display()
        return True
    except Exception:
        return False
