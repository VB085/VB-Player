"""Stub for gi.repository dynamic submodule (Linux-only at runtime)."""

from typing import Any


class Gst:
    """Minimal GStreamer surface used by VB Player (main.py: Gst.init)."""

    @staticmethod
    def init(argv: list[str] | None) -> None: ...
