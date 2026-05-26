import sys

from audio_player.player.engine_base import PlaybackState  # noqa: F401

if sys.platform == 'win32':
    from audio_player.player.engine_windows import AudioEngine, enumerate_hw_devices  # noqa: F401
else:
    from audio_player.player.engine_linux import AudioEngine, enumerate_hw_devices  # noqa: F401
