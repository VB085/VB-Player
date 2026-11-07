"""Lazy remote thumbnail loader for online playlist rows.

Only covers that are actually painted get requested. Results are cached in
memory (bounded) and broadcast once, so multiple playlist models showing the
same album share one download.
"""

from __future__ import annotations

import queue
import threading
import urllib.request
from collections import OrderedDict

from PyQt6.QtCore import QObject, pyqtSignal

MAX_CACHE = 400
WORKERS = 3


class CoverService(QObject):
    coverReady = pyqtSignal(str, bytes)  # (url, image bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._queue: queue.Queue[str] = queue.Queue()
        for i in range(WORKERS):
            threading.Thread(
                target=self._worker, name=f"cover-{i}", daemon=True
            ).start()

    def get(self, url: str) -> bytes | None:
        data = self._cache.get(url)
        if data is not None:
            self._cache.move_to_end(url)
        return data

    def request(self, url: str) -> None:
        if not url or url in self._cache or url in self._pending or url in self._failed:
            return
        self._pending.add(url)
        self._queue.put(url)

    def _worker(self):
        while True:
            url = self._queue.get()
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://y.qq.com/"}
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                if not data or len(data) > 2 * 1024 * 1024:
                    raise ValueError("cover too large or empty")
            except Exception:
                self._pending.discard(url)
                self._failed.add(url)
                continue

            self._cache[url] = data
            self._cache.move_to_end(url)
            while len(self._cache) > MAX_CACHE:
                self._cache.popitem(last=False)
            self._pending.discard(url)
            self.coverReady.emit(url, data)


_service: CoverService | None = None


def get_cover_service() -> CoverService:
    global _service
    if _service is None:
        _service = CoverService()
    return _service
