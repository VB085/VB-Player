"""Network page — stream URL input + NAS browser + scan results."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QScrollArea, QSplitter,
    QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from audio_player.i18n import _, languageChanged
from audio_player.app import current_theme_mode, current_accent


class NetworkPage(QWidget):
    """Network streaming and NAS browsing page."""

    playRequested = pyqtSignal(list)    # list of paths/URLs to play
    streamAdded = pyqtSignal(str)       # single stream URL added
    smbBrowseRequested = pyqtSignal(str, str, str)  # server, user, pass
    deviceSelected = pyqtSignal(str)    # device id for output switching

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recent_streams: list[str] = []
        self._devices: list[dict] = []
        self._active_device_id = "local"
        self._setup_ui()
        languageChanged.connect(self._refresh_language)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        self._title_label = QLabel(_("page.network"))
        self._title_label.setObjectName("pageTitle")
        header.addWidget(self._title_label)
        header.addStretch()
        layout.addLayout(header)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(12)

        # --- Stream URL section ---
        self._stream_group = QGroupBox(_("network.add_stream"))
        self._stream_group.setObjectName("networkGroup")
        stream_layout = QVBoxLayout(self._stream_group)

        url_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText(_("network.url_placeholder"))
        self._url_input.setObjectName("networkUrlInput")
        self._url_input.returnPressed.connect(self._on_play_stream)
        url_row.addWidget(self._url_input, 1)

        self._play_btn = QPushButton(_("network.play"))
        self._play_btn.setObjectName("networkPlayBtn")
        self._play_btn.clicked.connect(self._on_play_stream)
        url_row.addWidget(self._play_btn)
        stream_layout.addLayout(url_row)

        # Recent streams
        self._recent_label = QLabel(_("network.recent_streams"))
        self._recent_label.setObjectName("networkSectionLabel")
        stream_layout.addWidget(self._recent_label)

        self._recent_list = QListWidget()
        self._recent_list.setObjectName("networkRecentList")
        self._recent_list.setMaximumHeight(120)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_clicked)
        stream_layout.addWidget(self._recent_list)

        content_layout.addWidget(self._stream_group)

        # --- Output device section ---
        self._device_group = QGroupBox(_("network.output_device"))
        self._device_group.setObjectName("networkGroup")
        device_layout = QVBoxLayout(self._device_group)

        self._device_label = QLabel(_("network.current_device"))
        self._device_label.setObjectName("networkSectionLabel")
        device_layout.addWidget(self._device_label)

        self._device_list = QListWidget()
        self._device_list.setObjectName("networkDeviceList")
        self._device_list.setMaximumHeight(150)
        self._device_list.itemClicked.connect(self._on_device_clicked)
        device_layout.addWidget(self._device_list)

        content_layout.addWidget(self._device_group)

        # --- NAS section ---
        self._nas_group = QGroupBox(_("network.connect_nas"))
        self._nas_group.setObjectName("networkGroup")
        nas_layout = QVBoxLayout(self._nas_group)

        # Connection form
        form_layout = QHBoxLayout()
        self._server_input = QLineEdit()
        self._server_input.setPlaceholderText(_("network.server"))
        self._server_input.setObjectName("networkNasInput")
        form_layout.addWidget(self._server_input)

        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText(_("network.username"))
        self._user_input.setObjectName("networkNasInput")
        form_layout.addWidget(self._user_input)

        self._pass_input = QLineEdit()
        self._pass_input.setPlaceholderText(_("network.password"))
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setObjectName("networkNasInput")
        form_layout.addWidget(self._pass_input)

        self._connect_btn = QPushButton(_("network.connect"))
        self._connect_btn.setObjectName("networkConnectBtn")
        self._connect_btn.clicked.connect(self._on_connect_nas)
        form_layout.addWidget(self._connect_btn)
        nas_layout.addLayout(form_layout)

        # Share tree
        self._share_tree = QTreeWidget()
        self._share_tree.setObjectName("networkShareTree")
        self._share_tree.setHeaderHidden(True)
        self._share_tree.itemDoubleClicked.connect(self._on_share_double_click)
        nas_layout.addWidget(self._share_tree)

        content_layout.addWidget(self._nas_group)

        # --- Scan results section ---
        self._results_group = QGroupBox(_("network.scan_results"))
        self._results_group.setObjectName("networkGroup")
        results_layout = QVBoxLayout(self._results_group)

        self._results_label = QLabel(_("network.no_results"))
        self._results_label.setObjectName("networkResultsLabel")
        self._results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self._results_label)

        self._results_list = QListWidget()
        self._results_list.setObjectName("networkResultsList")
        self._results_list.itemDoubleClicked.connect(self._on_result_clicked)
        results_layout.addWidget(self._results_list)

        self._play_all_btn = QPushButton(_("network.play"))
        self._play_all_btn.setObjectName("networkPlayBtn")
        self._play_all_btn.clicked.connect(self._on_play_all_results)
        self._play_all_btn.setVisible(False)
        results_layout.addWidget(self._play_all_btn)

        content_layout.addWidget(self._results_group)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self._apply_style()

    # --- Public API ---

    def add_recent_stream(self, url: str):
        if url not in self._recent_streams:
            self._recent_streams.insert(0, url)
            if len(self._recent_streams) > 20:
                self._recent_streams.pop()
            self._refresh_recent_list()

    def set_recent_streams(self, urls: list[str]):
        self._recent_streams = list(urls)
        self._refresh_recent_list()

    def set_scan_results(self, results: list[dict]):
        """results: list of {"smb_uri": str, "name": str, "size": int}"""
        self._results_list.clear()
        if not results:
            self._results_label.setText(_("network.no_results"))
            self._results_label.show()
            self._play_all_btn.setVisible(False)
            return
        self._results_label.hide()
        self._play_all_btn.setVisible(True)
        for r in results:
            item = QListWidgetItem(r["name"])
            item.setData(Qt.ItemDataRole.UserRole, r["smb_uri"])
            size_mb = r.get("size", 0) / (1024 * 1024)
            item.setToolTip(f"{r['smb_uri']}\n{size_mb:.1f} MB")
            self._results_list.addItem(item)

    def add_share_items(self, items: list[str]):
        """Add share/folder items to the tree."""
        self._share_tree.clear()
        for name in items:
            item = QTreeWidgetItem([f"\U0001f4c1 {name}"])
            self._share_tree.addTopLevelItem(item)

    def clear_results(self):
        self._results_list.clear()
        self._results_label.setText(_("network.no_results"))
        self._results_label.show()
        self._play_all_btn.setVisible(False)

    # --- Handlers ---

    def _on_play_stream(self):
        url = self._url_input.text().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        self.add_recent_stream(url)
        self._url_input.clear()
        self.streamAdded.emit(url)
        self.playRequested.emit([url])

    def _on_recent_clicked(self, item: QListWidgetItem):
        url = item.text()
        self.streamAdded.emit(url)
        self.playRequested.emit([url])

    # --- Output device management ---

    def set_devices(self, devices: list[dict], active_id: str):
        """Update the output device list."""
        self._devices = devices
        self._active_device_id = active_id
        self._refresh_device_list()

    def _refresh_device_list(self):
        self._device_list.clear()
        for d in self._devices:
            name = d["name"]
            if d["id"] == self._active_device_id:
                name = f"✓ {name}"
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, d["id"])
            self._device_list.addItem(item)
        # Update label
        active_name = next((d["name"] for d in self._devices if d["id"] == self._active_device_id), "")
        if active_name:
            self._device_label.setText(f"{_('network.current_device')}: {active_name}")

    def _on_device_clicked(self, item: QListWidgetItem):
        device_id = item.data(Qt.ItemDataRole.UserRole)
        if device_id:
            self.deviceSelected.emit(device_id)

    def _on_connect_nas(self):
        server = self._server_input.text().strip()
        user = self._user_input.text().strip()
        password = self._pass_input.text().strip()
        if not server:
            return
        self.smbBrowseRequested.emit(server, user, password)

    def _on_share_double_click(self, item: QTreeWidgetItem, column: int):
        name = item.text(0).replace("\U0001f4c1 ", "")
        # TODO: trigger folder scan
        pass

    def _on_result_clicked(self, item: QListWidgetItem):
        uri = item.data(Qt.ItemDataRole.UserRole)
        if uri:
            self.playRequested.emit([uri])

    def _on_play_all_results(self):
        uris = []
        for i in range(self._results_list.count()):
            uri = self._results_list.item(i).data(Qt.ItemDataRole.UserRole)
            if uri:
                uris.append(uri)
        if uris:
            self.playRequested.emit(uris)

    # --- Styling ---

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        accent = current_accent()
        bg = "rgba(0,0,0,0.10)" if not is_light else "rgba(0,0,0,0.03)"
        card_bg = "rgba(0,0,0,0.08)" if not is_light else "rgba(0,0,0,0.02)"
        border = f"rgba({accent.red()},{accent.green()},{accent.blue()},0.15)"
        text = "#e2e8f0" if not is_light else "#333"
        text_dim = "#888" if not is_light else "#999"

        self.setStyleSheet(
            f"QGroupBox#networkGroup {{"
            f"  background: {card_bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 10px;"
            f"  margin-top: 8px;"
            f"  padding: 12px 8px 8px 8px;"
            f"  font-weight: bold;"
            f"  color: {text};"
            f"}}"
            f"QGroupBox::title {{"
            f"  subcontrol-origin: margin;"
            f"  left: 12px;"
            f"  padding: 0 6px;"
            f"}}"
            f"QLineEdit#networkUrlInput, QLineEdit#networkNasInput {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"  padding: 8px 10px;"
            f"  color: {text};"
            f"  font-size: 13px;"
            f"}}"
            f"QLineEdit:focus {{"
            f"  border-color: {accent.name()};"
            f"}}"
            f"QPushButton#networkPlayBtn, QPushButton#networkConnectBtn {{"
            f"  background: {accent.name()};"
            f"  color: #fff;"
            f"  border: none;"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  font-size: 13px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {accent.lighter(115).name()};"
            f"}}"
            f"QLabel#pageTitle {{"
            f"  font-size: 20px;"
            f"  font-weight: bold;"
            f"  color: {text};"
            f"}}"
            f"QLabel#networkSectionLabel {{"
            f"  color: {text_dim};"
            f"  font-size: 12px;"
            f"  margin-top: 4px;"
            f"}}"
            f"QLabel#networkResultsLabel {{"
            f"  color: {text_dim};"
            f"  font-size: 13px;"
            f"  padding: 20px;"
            f"}}"
            f"QListWidget#networkRecentList, QListWidget#networkResultsList, QListWidget#networkDeviceList {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"  color: {text};"
            f"  font-size: 13px;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 4px 8px;"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background: {accent.name()}22;"
            f"}}"
            f"QTreeWidget#networkShareTree {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"  color: {text};"
            f"  font-size: 13px;"
            f"}}"
        )

    def refresh_theme(self):
        self._apply_style()

    def _refresh_language(self, _code: str = ""):
        self._title_label.setText(_("page.network"))
        self._stream_group.setTitle(_("network.add_stream"))
        self._url_input.setPlaceholderText(_("network.url_placeholder"))
        self._play_btn.setText(_("network.play"))
        self._recent_label.setText(_("network.recent_streams"))
        self._device_group.setTitle(_("network.output_device"))
        self._nas_group.setTitle(_("network.connect_nas"))
        self._server_input.setPlaceholderText(_("network.server"))
        self._user_input.setPlaceholderText(_("network.username"))
        self._pass_input.setPlaceholderText(_("network.password"))
        self._connect_btn.setText(_("network.connect"))
        self._results_group.setTitle(_("network.scan_results"))
        self._play_all_btn.setText(_("network.play"))

    def _refresh_recent_list(self):
        self._recent_list.clear()
        for url in self._recent_streams:
            self._recent_list.addItem(url)
