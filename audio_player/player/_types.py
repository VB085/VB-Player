"""Type definitions shared across player modules — no GStreamer dependency."""

from enum import IntEnum


class PlaybackState(IntEnum):
    Stopped = 0
    Playing = 1
    Paused = 2
