"""Embedded HTTP server for serving local files to DLNA renderers.

ThreadingHTTPServer on random port, auto-select LAN IPv4.
UUID-based stream mapping, token-gated access, HEAD + GET + Range support.
"""

from __future__ import annotations

import os
import secrets
import socket
import uuid
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# MIME type mapping
_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".wma": "audio/x-ms-wma",
    ".aiff": "audio/aiff",
    ".ape": "audio/ape",
    ".wv": "audio/wavpack",
    ".dsf": "audio/dsd",
    ".dff": "audio/dsd",
}


def _guess_mime(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    return _MIME_MAP.get(ext, "application/octet-stream")


def _get_lan_ip() -> str:
    """Auto-detect LAN IPv4 address via default route."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        import sys; print(f"[http] 本机 IP 获取失败，使用 127.0.0.1: {e}", file=sys.stderr)
        return "127.0.0.1"


class _StreamHandler(BaseHTTPRequestHandler):
    """Handle GET/HEAD for /stream/<uuid> with Range support."""

    # Suppress default stderr logging
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self._handle_head()

    def do_GET(self):
        self._handle_get()

    def _parse_uuid(self) -> str | None:
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "stream":
            return parts[1]
        return None

    def _check_token(self) -> bool:
        """Validate the access token from query string."""
        server: EmbeddedHttpServer = self.server._embed_ref  # type: ignore
        if not server._token:
            return True
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        t = params.get("t", [None])[0]
        return secrets.compare_digest(t or "", server._token)

    def _handle_head(self):
        if not self._check_token():
            self.send_error(403)
            return
        stream_id = self._parse_uuid()
        if not stream_id:
            self.send_error(404)
            return

        server: EmbeddedHttpServer = self.server._embed_ref  # type: ignore
        entry = server._streams.get(stream_id)
        if not entry:
            self.send_error(404)
            return

        filepath, mime = entry
        try:
            size = os.path.getsize(filepath)
        except OSError:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def _handle_get(self):
        if not self._check_token():
            self.send_error(403)
            return
        stream_id = self._parse_uuid()
        if not stream_id:
            self.send_error(404)
            return

        server: EmbeddedHttpServer = self.server._embed_ref  # type: ignore
        entry = server._streams.get(stream_id)
        if not entry:
            self.send_error(404)
            return

        filepath, mime = entry
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            self.send_error(404)
            return

        # Parse Range header
        range_header = self.headers.get("Range")
        start, end = 0, file_size - 1

        if range_header:
            # Range: bytes=start-end
            try:
                range_spec = range_header.replace("bytes=", "").strip()
                if "-" in range_spec:
                    parts = range_spec.split("-", 1)
                    if parts[0]:
                        start = int(parts[0])
                    if parts[1]:
                        end = int(parts[1])
            except (ValueError, IndexError):
                self.send_error(416)
                return

            if start >= file_size or end >= file_size or start > end:
                self.send_error(416)
                return

            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        # Stream file bytes
        try:
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                chunk_size = 64 * 1024
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    data = f.read(read_size)
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected
        except OSError:
            pass


class EmbeddedHttpServer:
    """HTTP server that serves local audio files to DLNA renderers.

    Usage:
        server = EmbeddedHttpServer()
        server.start()
        uuid = server.add_stream("/path/to/file.flac")
        url = server.get_url(uuid)  # http://192.168.x.x:PORT/stream/uuid
        server.stop()
    """

    def __init__(self, localhost_only: bool = False):
        self._streams: dict[str, tuple[str, str]] = {}  # uuid -> (filepath, mime)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._host: str = ""
        self._port: int = 0
        self._token: str = secrets.token_urlsafe(32)
        self._localhost_only = localhost_only

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        if self._host and self._port:
            return f"http://{self._host}:{self._port}"
        return ""

    def start(self) -> None:
        """Start HTTP server on random port in background thread."""
        if self._httpd is not None:
            return

        bind_addr = "127.0.0.1" if self._localhost_only else ""
        self._host = "127.0.0.1" if self._localhost_only else _get_lan_ip()
        self._httpd = ThreadingHTTPServer((bind_addr, 0), _StreamHandler)
        self._httpd._embed_ref = self  # type: ignore
        self._port = self._httpd.server_address[1]

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop HTTP server and clean up."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        self._thread = None
        self._streams.clear()
        self._host = ""
        self._port = 0

    def add_stream(self, filepath: str) -> str:
        """Register a file for serving. Returns stream UUID."""
        stream_id = uuid.uuid4().hex
        mime = _guess_mime(filepath)
        self._streams[stream_id] = (filepath, mime)
        return stream_id

    def remove_stream(self, stream_id: str) -> None:
        """Unregister a stream."""
        self._streams.pop(stream_id, None)

    def get_url(self, stream_id: str) -> str:
        """Get the HTTP URL for a registered stream (includes access token)."""
        return f"{self.base_url}/stream/{stream_id}?t={self._token}"
