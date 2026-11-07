"""Tests for online provider discovery and local/online context separation."""

import json
from pathlib import Path

from PyQt6.QtCore import QObject

from audio_player.player.online import OnlineProvider, discover_providers
from audio_player.player.playlist import PlaylistManager
from audio_player.ui.controllers.playback_controller import PlaybackController


class _DummyBackend(QObject):
    duration = 0


class _DummyAnalyzer:
    def analyze(self, path):
        pass


def test_discover_providers(tmp_path, monkeypatch):
    providers_dir = tmp_path / "vbplayer" / "providers"
    providers_dir.mkdir(parents=True)
    (providers_dir / "qqmusic.json").write_text(json.dumps({
        "name": "QQ 音乐",
        "base_url": "http://127.0.0.1:8765",
        "capabilities": ["search"],
    }), encoding="utf-8")
    (providers_dir / "broken.json").write_text("{", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    providers = discover_providers()

    assert len(providers) == 1
    assert providers[0].name == "QQ 音乐"
    assert providers[0].stream_url("a b") == "http://127.0.0.1:8765/stream/a%20b"
    assert providers[0].meta_url("abc") == "http://127.0.0.1:8765/meta/abc"


def test_controller_keeps_local_and_online_playlists_apart(qapp):
    local = PlaylistManager()
    online = PlaylistManager()
    ctrl = PlaybackController(
        _DummyBackend(), local, _DummyAnalyzer(),
        online_playlist=online,
    )
    try:
        ctrl.open_external_playlist([
            ("http://127.0.0.1:8765/stream/a", {"title": "A"}),
            ("http://127.0.0.1:8765/stream/b", {"title": "B"}),
        ], 1)

        assert ctrl.active_context == "online"
        assert ctrl.active_playlist is online
        assert online.count == 2
        assert online.current_index == 1
        assert local.count == 0

        ctrl.set_active_context("local")
        assert ctrl.active_playlist is local
        assert local.count == 0
        assert online.count == 2
    finally:
        local.shutdown()
        online.shutdown()


def test_online_provider_search_uses_http(tmp_path):
    # URL construction only; no network.
    provider = OnlineProvider("QQ", "http://127.0.0.1:8765")
    assert provider.stream_url("0039") == "http://127.0.0.1:8765/stream/0039"
    assert provider.meta_url("0039") == "http://127.0.0.1:8765/meta/0039"
