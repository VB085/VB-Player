"""UPnP AVTransport service client.

Provides play, pause, stop, seek, and state query for DLNA renderers.
"""

from __future__ import annotations

from audio_player.player.dlna.upnp import soap_request, UPnPError

AVT_SERVICE = "urn:schemas-upnp-org:service:AVTransport:1"

# Transport state values from UPnP spec
TRANSPORT_STATES = {
    "STOPPED": 0,
    "PLAYING": 1,
    "TRANSITIONING": 2,
    "PAUSED_PLAYBACK": 3,
    "PAUSED_RECORDING": 4,
    "RECORDING": 5,
    "NO_MEDIA_PRESENT": 6,
}


class AVTransport:
    """UPnP AVTransport service client for a single renderer."""

    def __init__(self, control_url: str, instance_id: int = 0):
        self._control_url = control_url
        self._instance_id = str(instance_id)

    def set_av_transport_uri(self, uri: str, metadata: str = "") -> None:
        """Set the URI to play.

        Args:
            uri: HTTP URL of the audio stream
            metadata: DIDL-Lite XML metadata (optional)
        """
        args = {
            "InstanceID": self._instance_id,
            "CurrentURI": uri,
            "CurrentURIMetaData": metadata or "",
        }
        soap_request(self._control_url, AVT_SERVICE, "SetAVTransportURI", args)

    def play(self) -> None:
        """Start playback."""
        args = {
            "InstanceID": self._instance_id,
            "Speed": "1",
        }
        soap_request(self._control_url, AVT_SERVICE, "Play", args)

    def pause(self) -> None:
        """Pause playback."""
        args = {"InstanceID": self._instance_id}
        soap_request(self._control_url, AVT_SERVICE, "Pause", args)

    def stop(self) -> None:
        """Stop playback."""
        args = {"InstanceID": self._instance_id}
        soap_request(self._control_url, AVT_SERVICE, "Stop", args)

    def seek(self, target: str) -> None:
        """Seek to position.

        Args:
            target: Position in "HH:MM:SS" format or "+/-" relative
        """
        args = {
            "InstanceID": self._instance_id,
            "Unit": "REL_TIME",
            "Target": target,
        }
        soap_request(self._control_url, AVT_SERVICE, "Seek", args)

    def seek_seconds(self, seconds: int) -> None:
        """Seek to position given in seconds."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        self.seek(f"{h:02d}:{m:02d}:{s:02d}")

    def get_transport_info(self) -> dict:
        """Get current transport state.

        Returns dict with keys:
            CurrentTransportState: PLAYING, PAUSED_PLAYBACK, STOPPED, etc.
            CurrentTransportStatus: OK or ERROR
            CurrentSpeed: playback speed (usually "1")
        """
        args = {"InstanceID": self._instance_id}
        return soap_request(self._control_url, AVT_SERVICE, "GetTransportInfo", args)

    def get_position_info(self) -> dict:
        """Get current position information.

        Returns dict with keys:
            Track: track number
            TrackDuration: "HH:MM:SS"
            TrackMetaData: DIDL-Lite XML
            TrackURI: current URI
            RelTime: "HH:MM:SS" current position
            AbsTime: "HH:MM:SS" or NOT_IMPLEMENTED
            RelCount: integer or MAX_VALUE
            AbsCount: integer or MAX_VALUE
        """
        args = {"InstanceID": self._instance_id}
        return soap_request(self._control_url, AVT_SERVICE, "GetPositionInfo", args)

    def get_media_info(self) -> dict:
        """Get media information.

        Returns dict with keys:
            NrTracks: number of tracks
            MediaDuration: "HH:MM:SS"
            CurrentURI: current URI
            CurrentURIMetaData: DIDL-Lite XML
            NextURI: next URI (or empty)
            PlayMedium: playback medium
            RecordMedium: record medium
            WriteStatus: write status
        """
        args = {"InstanceID": self._instance_id}
        return soap_request(self._control_url, AVT_SERVICE, "GetMediaInfo", args)


def parse_duration(time_str: str) -> int:
    """Parse UPnP duration string "HH:MM:SS" to milliseconds.

    Returns 0 if parsing fails.
    """
    if not time_str or time_str == "NOT_IMPLEMENTED" or time_str == "0:00:00":
        return 0
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            # Handle fractional seconds
            s_float = float(s)
            total = int(h) * 3600 + int(m) * 60 + s_float
            return int(total * 1000)
    except (ValueError, IndexError):
        pass
    return 0


def parse_position(time_str: str) -> int:
    """Parse UPnP position string "HH:MM:SS" to milliseconds.

    Returns 0 if parsing fails.
    """
    return parse_duration(time_str)
