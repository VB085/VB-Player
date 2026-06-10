"""Type definitions shared across player modules — no GStreamer dependency."""

from enum import IntEnum


class PlaybackState(IntEnum):
    Stopped = 0
    Playing = 1
    Paused = 2


AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".ogg", ".opus",
    ".m4a", ".aac", ".wma", ".aiff", ".ape", ".wv",
    ".alac", ".mpc", ".spx", ".oga",
    ".dsf", ".dff",
}
