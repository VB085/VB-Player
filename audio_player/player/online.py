"""Generic online-provider discovery for the Online page.

A provider is a local HTTP service registered by dropping a JSON file into
``$XDG_CONFIG_HOME/vbplayer/providers/*.json``::

    {"name": "QQ 音乐", "base_url": "http://127.0.0.1:8765"}

The player never knows which music service this is; it only calls the
provider's documented HTTP endpoints. This keeps service-specific code (and
cookies) out of the player project.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


@dataclass
class OnlineProvider:
    name: str
    base_url: str
    capabilities: list[str] = field(default_factory=list)
    healthy: bool = False
    quality: str = ""

    def _url(self, path: str, params: dict | None = None) -> str:
        url = self.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _get_json(self, path: str, params: dict | None = None,
                  timeout: float = 8.0) -> dict:
        request = urllib.request.Request(
            self._url(path, params),
            headers={"User-Agent": "VBPlayer/online"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def health(self, timeout: float = 2.5) -> bool:
        try:
            data = self._get_json("/health", timeout=timeout)
            self.quality = str(data.get("quality") or "")
            return bool(data.get("ok"))
        except Exception:
            return False

    def search(self, keyword: str, limit: int = 30) -> list[dict]:
        data = self._get_json("/search", {"w": keyword, "n": int(limit)})
        return data.get("songs") or []

    def playlists(self) -> list[dict]:
        data = self._get_json("/playlists")
        return data.get("playlists") or []

    def quality(self) -> str:
        return str(self._get_json("/quality").get("quality") or "auto")

    def set_quality(self, quality: str) -> str:
        request = urllib.request.Request(
            self._url("/quality", {"q": quality}),
            headers={"User-Agent": "VBPlayer/online"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data.get("quality") or quality)

    def playlist_songs(self, dissid: str, limit: int = 500) -> list[dict]:
        quoted = urllib.parse.quote(str(dissid), safe="")
        data = self._get_json(f"/playlist/{quoted}", {"n": int(limit)})
        return data.get("songs") or []

    def recommend(self, kind: str, limit: int) -> list[dict]:
        data = self._get_json(f"/recommend/{kind}", {"n": int(limit)})
        return data.get("songs") or []

    def stream_url(self, song_mid: str) -> str:
        quoted = urllib.parse.quote(song_mid, safe="")
        return f"{self.base_url.rstrip('/')}/stream/{quoted}"

    def meta_url(self, song_mid: str) -> str:
        quoted = urllib.parse.quote(song_mid, safe="")
        return f"{self.base_url.rstrip('/')}/meta/{quoted}"


def provider_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "vbplayer" / "providers"


def discover_providers() -> list[OnlineProvider]:
    providers: list[OnlineProvider] = []
    directory = provider_dir()
    if not directory.is_dir():
        return providers
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        base_url = str(data.get("base_url") or "").strip()
        if not base_url.startswith(("http://", "https://")):
            continue
        providers.append(OnlineProvider(
            name=str(data.get("name") or path.stem),
            base_url=base_url,
            capabilities=list(data.get("capabilities") or []),
        ))
    return providers


class ProviderMonitor(QObject):
    """Periodically discovers provider files and refreshes their health."""

    providersChanged = pyqtSignal(list)

    def __init__(self, parent=None, interval_ms: int = 5000):
        super().__init__(parent)
        self._checking = False
        self._last: list[OnlineProvider] = []
        self._failures: dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check)

    def start(self):
        self.check()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def check(self):
        if self._checking:
            return
        self._checking = True
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        providers = discover_providers()
        alive: list[OnlineProvider] = []
        seen: set[str] = set()
        for provider in providers:
            seen.add(provider.base_url)
            provider.healthy = provider.health()
            if provider.healthy:
                self._failures.pop(provider.base_url, None)
                alive.append(provider)
            else:
                count = self._failures.get(provider.base_url, 0) + 1
                self._failures[provider.base_url] = count
                # Hide the tab after ~15s of consecutive failures, but keep a
                # short grace period for transient hiccups.
                if count < 3:
                    alive.append(provider)
        for base_url in list(self._failures):
            if base_url not in seen:
                self._failures.pop(base_url, None)
        self._last = alive
        self.providersChanged.emit(alive)
        self._checking = False
