"""macOS platform module — CoreAudio, NSVisualEffectView, system integration.

All public APIs gracefully degrade when pyobjc / CoreAudio C APIs are missing;
the rest of the application imports these modules behind ``_HAS_OBJC`` guards.
"""
