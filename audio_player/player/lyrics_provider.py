"""Lyrics provider abstraction layer with LRCLIB-compatible protocol."""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LyricsResult:
    """Unified result from any lyrics provider."""
    synced_lyrics: str
    plain_lyrics: str
    translated_lyrics: str | None = None
    provider: str | None = None


class LyricsProvider(Protocol):
    """Protocol for lyrics sources."""
    name: str

    def search(self, title: str, artist: str, duration_sec: float,
               timeout: float = 5.0) -> LyricsResult | None: ...


class LRCLIBProvider:
    """Built-in LRCLIB.net source (open API, no auth)."""
    name = "LRCLIB"
    BASE_URL = "https://lrclib.net/api/get"

    def search(self, title: str, artist: str, duration_sec: float,
               timeout: float = 5.0) -> LyricsResult | None:
        params = urllib.parse.urlencode({
            "track_name": title,
            "artist_name": artist,
            "duration": int(duration_sec),
        })
        url = f"{self.BASE_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "VBPlayer/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
            return None

        # Duration filter: ±5 seconds
        api_duration = data.get("duration", 0)
        if abs(api_duration - duration_sec) > 5:
            return None

        synced = data.get("syncedLyrics") or ""
        if not synced:
            return None

        return LyricsResult(
            synced_lyrics=synced,
            plain_lyrics=data.get("plainLyrics") or "",
            translated_lyrics=data.get("translatedLyrics"),
            provider=self.name,
        )


class CustomAPIProvider:
    """User-configured LRCLIB-compatible endpoint."""
    name = "Custom"

    def __init__(self, base_url: str, token: str = ""):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Custom lyrics URL must use http:// or https://, got: {parsed.scheme or '(none)'}")
        self._base_url = base_url.rstrip("/")
        self._token = token

    def search(self, title: str, artist: str, duration_sec: float,
               timeout: float = 5.0) -> LyricsResult | None:
        params = urllib.parse.urlencode({
            "track_name": title,
            "artist_name": artist,
            "duration": int(duration_sec),
        })
        url = f"{self._base_url}?{params}"
        headers = {"User-Agent": "VBPlayer/1.0"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
            return None

        api_duration = data.get("duration", 0)
        if abs(api_duration - duration_sec) > 5:
            return None

        synced = data.get("syncedLyrics") or ""
        if not synced:
            return None

        return LyricsResult(
            synced_lyrics=synced,
            plain_lyrics=data.get("plainLyrics") or "",
            translated_lyrics=data.get("translatedLyrics"),
            provider=self.name,
        )
