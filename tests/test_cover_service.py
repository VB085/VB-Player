"""Lazy remote cover loading for online playlist rows."""

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from audio_player.player.cover_service import get_cover_service
from audio_player.player.playlist import PlaylistManager

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)


def test_cover_is_fetched_lazily_and_cached(qapp, qtbot):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/cover.png"

    playlist = PlaylistManager()
    try:
        playlist.set_urls([("http://x/stream", {
            "title": "T", "cover_url": url,
        })])
        index = playlist.index(0, 0)

        with qtbot.waitSignal(get_cover_service().coverReady, timeout=4000):
            assert playlist.data(index, playlist.CoverDataRole) is None

        data = playlist.data(index, playlist.CoverDataRole)
        assert data == PNG
        assert playlist.track_metadata(0).cover_data == PNG
    finally:
        playlist.shutdown()
        server.shutdown()
        server.server_close()
