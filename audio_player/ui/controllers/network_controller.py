"""Network controller — manages SMB connections and stream URL history."""

from PyQt6.QtCore import QObject, pyqtSignal, QThreadPool, QRunnable


class _SmbScanWorker(QRunnable):
    """Background worker for SMB folder scanning."""

    def __init__(self, server, share, path, username, password, callback):
        super().__init__()
        self.server = server
        self.share = share
        self.path = path
        self.username = username
        self.password = password
        self.callback = callback

    def run(self):
        try:
            from audio_player.player.smb_scanner import scan_folder
            results = scan_folder(
                self.server, self.share, self.path,
                self.username, self.password,
            )
            self.callback(results)
        except Exception as e:
            self.callback([])


class NetworkController(QObject):
    """Controller for network streaming and NAS operations."""

    smbScanComplete = pyqtSignal(list)
    smbError = pyqtSignal(str)
    streamHistoryChanged = pyqtSignal(list)

    def __init__(self, library_mgr, parent=None):
        super().__init__(parent)
        self._library = library_mgr
        self._pool = QThreadPool.globalInstance()
        self._stream_history: list[str] = []
        self._load_history()

    def _load_history(self):
        """Load stream URL history from library."""
        data = self._library._data if hasattr(self._library, '_data') else {}
        self._stream_history = data.get("stream_history", [])

    def _save_history(self):
        """Persist stream URL history to library."""
        if hasattr(self._library, '_data'):
            self._library._data["stream_history"] = self._stream_history
            if hasattr(self._library, '_save'):
                self._library._save()

    def add_stream_to_history(self, url: str):
        """Add a URL to the stream history."""
        if url in self._stream_history:
            self._stream_history.remove(url)
        self._stream_history.insert(0, url)
        if len(self._stream_history) > 50:
            self._stream_history = self._stream_history[:50]
        self._save_history()
        self.streamHistoryChanged.emit(self._stream_history)

    def get_stream_history(self) -> list[str]:
        return list(self._stream_history)

    def scan_smb_folder(self, server, share, path="", username="", password=""):
        """Start async SMB folder scan."""
        worker = _SmbScanWorker(
            server, share, path, username, password,
            self._on_scan_complete,
        )
        self._pool.start(worker)

    def _on_scan_complete(self, results):
        self.smbScanComplete.emit(results)
