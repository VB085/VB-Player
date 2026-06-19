"""Linux-recommended audio sink for GStreamer."""

import os


def get_recommended_audio_sink() -> str:
    """Return the recommended GStreamer audio sink for Linux."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return "pipewiresink"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "pipewiresink"
    return "pulsesink"
