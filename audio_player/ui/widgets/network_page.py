"""Network page — stream URL input + NAS browser + audio output settings."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QScrollArea, QSplitter,
    QSizePolicy, QFrame, QCheckBox, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont

from audio_player.i18n import _, languageChanged
from audio_player.app import current_theme_mode, current_accent, rgba_hex


class _NoWheelComboBox(QComboBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def wheelEvent(self, e):
        e.ignore()


class NetworkPage(QWidget):
    """Network streaming, NAS browsing, and audio output settings."""

    playRequested = pyqtSignal(list)
    streamAdded = pyqtSignal(str)
    smbBrowseRequested = pyqtSignal(str, str, str)
    deviceSelected = pyqtSignal(str)
    exclusiveModeToggled = pyqtSignal(bool)
    exclusiveDeviceChanged = pyqtSignal(str)
    dsdModeChanged = pyqtSignal(str)
    asioFormatChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("networkPage")
        self._recent_streams: list[str] = []
        self._devices: list[dict] = []
        self._active_device_id = "local"
        self._device_watcher = None
        self._setup_ui()
        languageChanged.connect(self._refresh_language)
        languageChanged.connect(lambda _: [c.refresh_language() for c in self._bt_cards])

    def _start_device_watcher(self):
        """Start real-time GStreamer device monitor (only once)."""
        if self._device_watcher is not None:
            return
        import sys
        if sys.platform != "win32":
            return
        try:
            from audio_player.platform.windows.audio_devices import DeviceWatcher
            self._device_watcher = DeviceWatcher()
            self._device_watcher.on_change(lambda action, dev: self.refresh_device_list())
            self._device_watcher.start()
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        self._title_label = QLabel(_("page.output"))
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
        content_layout.setContentsMargins(12, 8, 12, 100)  # bottom clears pill bar
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
        self._device_list.setMinimumHeight(150)
        self._device_list.itemClicked.connect(self._on_device_clicked)
        device_layout.addWidget(self._device_list)

        content_layout.addWidget(self._device_group)

        # --- Bluetooth detail cards ---
        self._bt_group = QGroupBox(_("bt.title"))
        self._bt_group.setObjectName("networkGroup")
        self._bt_layout = QVBoxLayout(self._bt_group)
        self._bt_layout.setSpacing(8)
        self._bt_cards: list = []
        self._bt_group.setVisible(False)
        content_layout.addWidget(self._bt_group)

        # --- Audio output settings (exclusive mode, DSD) ---
        self._audio_out_group = QGroupBox(_("settings.exclusive_mode"))
        self._audio_out_group.setObjectName("networkGroup")
        ao_layout = QVBoxLayout(self._audio_out_group)

        self._exclusive_cb = QCheckBox(_("settings.exclusive_mode"))
        self._exclusive_cb.setToolTip(_("settings.exclusive_tooltip"))
        self._exclusive_cb.toggled.connect(self._on_exclusive_toggled)
        ao_layout.addWidget(self._exclusive_cb)

        self._device_combo = _NoWheelComboBox()
        self._device_combo.setEnabled(False)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        ao_layout.addWidget(self._device_combo)

        self._dsd_combo = _NoWheelComboBox()
        self._dsd_combo.addItem(_("settings.dsd_pcm"), "pcm")
        from audio_player.platform import platform_info
        if platform_info.capabilities.supports_dsd_native:
            self._dsd_combo.addItem(_("settings.dsd_native"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop"), "dop")
        else:
            self._dsd_combo.addItem(_("settings.dsd_native") + "  " + _("settings.dsd_windows_only"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop") + "  " + _("settings.dsd_windows_only"), "dop")
            self._dsd_combo.model().item(1).setEnabled(False)
            self._dsd_combo.model().item(2).setEnabled(False)
        self._dsd_combo.setToolTip(_("settings.dsd_tooltip"))
        self._dsd_combo.currentIndexChanged.connect(self._on_dsd_mode_changed)
        ao_layout.addWidget(self._dsd_combo)

        # ASIO sample format override
        self._asio_format_label = QLabel(_("settings.asio_format"))
        self._asio_format_label.setObjectName("settingsLabel")
        ao_layout.addWidget(self._asio_format_label)
        self._asio_format_combo = _NoWheelComboBox()
        self._asio_format_combo.addItem(_("settings.asio_format_auto"), "auto")
        self._asio_format_combo.addItem("Float32", "float32")
        self._asio_format_combo.addItem("Int32", "int32")
        self._asio_format_combo.addItem("Int24", "int24")
        self._asio_format_combo.addItem("Int16", "int16")
        self._asio_format_combo.setToolTip(_("settings.asio_format_tooltip"))
        self._asio_format_combo.currentIndexChanged.connect(self._on_asio_format_changed)
        ao_layout.addWidget(self._asio_format_combo)

        # Show/hide ASIO format based on exclusive mode
        def _update_asio_format_visibility(checked):
            self._asio_format_label.setVisible(checked)
            self._asio_format_combo.setVisible(checked)
        self._exclusive_cb.toggled.connect(_update_asio_format_visibility)
        _update_asio_format_visibility(self._exclusive_cb.isChecked())

        content_layout.addWidget(self._audio_out_group)

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

        # Scan results (inside NAS group)
        self._results_label = QLabel(_("network.no_results"))
        self._results_label.setObjectName("networkResultsLabel")
        self._results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nas_layout.addWidget(self._results_label)

        self._results_list = QListWidget()
        self._results_list.setObjectName("networkResultsList")
        self._results_list.itemDoubleClicked.connect(self._on_result_clicked)
        nas_layout.addWidget(self._results_list)

        self._play_all_btn = QPushButton(_("network.play"))
        self._play_all_btn.setObjectName("networkPlayBtn")
        self._play_all_btn.clicked.connect(self._on_play_all_results)
        self._play_all_btn.setVisible(False)
        nas_layout.addWidget(self._play_all_btn)

        content_layout.addWidget(self._nas_group)
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
        self.refresh_device_list()

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
        bg = "#19000000" if not is_light else "#07000000"
        card_bg = "#14000000" if not is_light else "#05000000"
        border = rgba_hex(accent.red(), accent.green(), accent.blue(), 0.15)
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
            f"  background: {rgba_hex(accent.red(), accent.green(), accent.blue(), 0.13)};"
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

    def refresh_accent(self):
        self._apply_style()
        for card in self._bt_cards:
            card.refresh_accent()

    def _refresh_language(self, _code: str = ""):
        self._title_label.setText(_("page.output"))
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
        self._bt_group.setTitle(_("bt.title"))
        self._play_all_btn.setText(_("network.play"))
        self._audio_out_group.setTitle(_("settings.exclusive_mode"))
        self._exclusive_cb.setText(_("settings.exclusive_mode"))
        self._exclusive_cb.setToolTip(_("settings.exclusive_tooltip"))
        # DSD combo refresh
        self._dsd_combo.blockSignals(True)
        self._dsd_combo.clear()
        self._dsd_combo.addItem(_("settings.dsd_pcm"), "pcm")
        from audio_player.platform import platform_info
        if platform_info.capabilities.supports_dsd_native:
            self._dsd_combo.addItem(_("settings.dsd_native"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop"), "dop")
        else:
            self._dsd_combo.addItem(_("settings.dsd_native") + "  " + _("settings.dsd_windows_only"), "native")
            self._dsd_combo.addItem(_("settings.dsd_dop") + "  " + _("settings.dsd_windows_only"), "dop")
            self._dsd_combo.model().item(1).setEnabled(False)
            self._dsd_combo.model().item(2).setEnabled(False)
        self._dsd_combo.setToolTip(_("settings.dsd_tooltip"))
        dsd_mode = str(QSettings("VBPlayer", "VB Player").value("dsd_mode", "pcm") or "pcm")
        idx = self._dsd_combo.findData(dsd_mode)
        if idx >= 0:
            self._dsd_combo.setCurrentIndex(idx)
        self._dsd_combo.blockSignals(False)

    def _refresh_recent_list(self):
        self._recent_list.clear()
        for url in self._recent_streams:
            self._recent_list.addItem(url)

    # ── Audio output handlers ──────────────────────────────────

    def _on_exclusive_toggled(self, checked: bool):
        if checked:
            self._load_hw_devices()
        self._device_combo.setEnabled(checked)
        s = QSettings("VBPlayer", "VB Player")
        s.setValue("exclusive_mode", checked)
        self.refresh_device_list(exclusive_on=checked)
        self.exclusiveModeToggled.emit(checked)

    def _on_device_changed(self, idx: int):
        hw = self._device_combo.itemData(idx)
        if hw:
            s = QSettings("VBPlayer", "VB Player")
            s.setValue("exclusive_device", hw)
            self.exclusiveDeviceChanged.emit(hw)

    def _on_dsd_mode_changed(self, idx: int):
        mode = self._dsd_combo.itemData(idx)
        if mode:
            s = QSettings("VBPlayer", "VB Player")
            s.setValue("dsd_mode", mode)
            self.dsdModeChanged.emit(mode)

    def _on_asio_format_changed(self, idx: int):
        fmt = self._asio_format_combo.itemData(idx)
        if fmt:
            s = QSettings("VBPlayer", "VB Player")
            s.setValue("asio_sample_type", fmt)
            self.asioFormatChanged.emit(fmt)

    def _load_hw_devices(self):
        if getattr(self, '_hw_loaded', False):
            return
        self._hw_loaded = True
        from audio_player.player.engine import enumerate_hw_devices
        try:
            devices = enumerate_hw_devices()
        except Exception as e:
            import sys; print(f"[output] device enum failed: {e}", file=sys.stderr)
            devices = [{"name": _("engine.default_device"), "hw": "", "driver": "WASAPI"}]
        self._device_combo.clear()
        for dev in devices:
            driver_tag = dev.get("driver", "")
            label = f"{dev['name']}  [{driver_tag}]" if driver_tag else dev["name"]
            self._device_combo.addItem(label, dev["hw"])

    def set_exclusive_state(self, mode: bool, device: str):
        self._exclusive_cb.blockSignals(True)
        self._exclusive_cb.setChecked(mode)
        self._exclusive_cb.blockSignals(False)
        self._device_combo.setEnabled(mode)
        if mode and not getattr(self, '_hw_loaded', False):
            self._hw_loaded = True
        idx = self._device_combo.findData(device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
        self.refresh_device_list(exclusive_on=mode)

    def set_dsd_mode(self, mode: str):
        idx = self._dsd_combo.findData(mode)
        if idx >= 0:
            self._dsd_combo.setCurrentIndex(idx)

    def set_asio_format(self, fmt: str):
        idx = self._asio_format_combo.findData(fmt)
        if idx >= 0:
            self._asio_format_combo.setCurrentIndex(idx)

    def refresh_device_list(self, exclusive_on: bool = False):
        """Rebuild unified device list: local, wired, BT, network."""
        self._start_device_watcher()
        import sys
        if sys.platform == "win32":
            from audio_player.platform.windows.audio_devices import (
                get_local_device, get_alsa_hw_devices, get_wired_devices, AudioDevice,
            )
        else:
            from audio_player.platform.linux.audio_devices import (
                get_local_device, get_alsa_hw_devices, get_wired_devices, AudioDevice,
            )

        # Gather all devices
        all_devs: list[AudioDevice] = []

        # Local
        local = get_local_device(active=self._active_device_id == "local")
        local.available = not exclusive_on
        all_devs.append(local)

        # Wired (ALSA hw devices)
        if exclusive_on:
            hw_devs = get_alsa_hw_devices()
            for d in hw_devs:
                d.available = True
                d.active = (self._active_device_id == d.id)
                d.description = "ALSA 硬件直通"
            all_devs.extend(hw_devs)

        # Bluetooth
        bt_devs = []
        host_codecs = []
        try:
            import sys
            if sys.platform == "win32":
                from audio_player.platform.windows.bluetooth import (
                    get_bluetooth_devices, get_device_codecs, get_host_codecs)
            else:
                from audio_player.platform.linux.bluetooth import (
                    get_bluetooth_devices, get_device_codecs, get_host_codecs)
            bt_devs = get_bluetooth_devices()
            host_codecs = get_host_codecs()
        except Exception:
            bt_devs = []
            host_codecs = []
        # Clear old BT cards
        for card in self._bt_cards:
            card.setParent(None)
            card.deleteLater()
        self._bt_cards.clear()

        if bt_devs:
            from audio_player.ui.widgets.bluetooth_card import BluetoothCard
            for bt in bt_devs:
                dev = AudioDevice(
                    id=f"bt:{bt.address}",
                    name=bt.name,
                    device_type="bluetooth",
                    description=f"{bt.codec}  {bt.frequency}  {bt.channels}",
                    available=True,
                    active=(self._active_device_id == f"bt:{bt.address}"),
                    codec=bt.codec,
                    sample_rate=bt.frequency,
                    detail=f"{bt.name}\n{bt.codec}\n{bt.frequency}\n{bt.channels}",
                )
                all_devs.append(dev)
                card = BluetoothCard()
                card.set_device(bt.name, bt.address)
                card.set_codec(bt.codec, bt.state)
                card.set_params(bt.frequency, bt.channels, bt.bitrate,
                                f"{bt.bitpool_min}-{bt.bitpool_max}" if bt.bitpool_max else "")
                dev_codecs = get_device_codecs(bt.address)
                # Switchable = intersection of host + device
                switchable = [c for c in host_codecs
                              if c in dev_codecs
                              or (c == "SBC" and "SBC" in dev_codecs)]
                card.set_switchable_codecs(switchable)
                card.set_supported(dev_codecs, host_codecs)
                card.set_battery(bt.battery)
                card.codecSwitchRequested.connect(self._on_codec_switch)
                self._bt_layout.addWidget(card)
                self._bt_cards.append(card)
            self._bt_group.setVisible(True)
        else:
            # Always show — display empty state
            self._bt_group.setVisible(True)
            empty_lbl = QLabel(_("bt.no_device"))
            empty_lbl.setStyleSheet("color:#64748b;font-size:12px;padding:8px 0;")
            self._bt_layout.addWidget(empty_lbl)

        # Network devices (from stored data, not old list items)
        net_devs = [(d["name"], d["id"]) for d in self._devices]

        # Rebuild list
        self._device_list.clear()
        for d in all_devs:
            icon = {"local": "🔊", "wired": "🔌", "bluetooth": "🎧"}.get(d.device_type, "📡")
            prefix = "✓ " if d.active else ("✗ " if not d.available else "  ")
            label = f"{prefix}{icon}  {d.name}"
            if d.description:
                label += f"  [{d.description}]" if d.device_type == "wired" else f"  ({d.description})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, d.id)
            item.setToolTip(d.detail or d.description)
            if not d.available:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._device_list.addItem(item)

        # Network devices at bottom
        for text, did in net_devs:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, did)
            self._device_list.addItem(item)

    def _on_codec_switch(self, address: str, codec: str):
        """Write PipeWire config + reconnect device to switch codec (Linux only)."""
        import sys
        if sys.platform == "win32":
            # Windows manages Bluetooth codec negotiation automatically
            return
        import subprocess, os
        # Map display name to PipeWire codec name
        codec_map = {
            "SBC": "sbc", "SBC XQ": "sbc_xq", "AAC": "aac",
            "aptX": "aptx", "aptX HD": "aptx_hd", "LDAC": "ldac",
        }
        pw_codec = codec_map.get(codec, codec.lower().replace(" ", "_"))
        # Read current host codecs and reorder with selected first
        from audio_player.platform.linux.bluetooth import get_host_codecs
        host = get_host_codecs()
        ordered = [codec_map.get(c, c).lower() for c in host if codec_map.get(c)]
        ordered.insert(0, ordered.pop(ordered.index(pw_codec)))

        # Write PipeWire config
        config_dir = os.path.expanduser("~/.config/pipewire/pipewire.conf.d")
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "99-bluetooth-codec.conf")
        with open(config_path, "w") as f:
            f.write(f'bluez5.codecs = [ {" ".join(ordered)} ]\n')

        # Reconnect via bluetoothctl
        subprocess.run(
            ["bluetoothctl", "disconnect", address],
            capture_output=True, timeout=3
        )
        subprocess.run(
            ["bluetoothctl", "connect", address],
            capture_output=True, timeout=5
        )
        # Refresh after renegotiation
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self.refresh_device_list(
            exclusive_on=self._exclusive_cb.isChecked()))

    def load_output_settings(self):
        """Restore exclusive mode + DSD from QSettings."""
        s = QSettings("VBPlayer", "VB Player")
        self._hw_loaded = False
        exclusive = str(s.value("exclusive_mode", "false")).lower() == "true"
        exclusive_dev = str(s.value("exclusive_device", "hw:0,0") or "hw:0,0")
        self._exclusive_cb.blockSignals(True)
        self._exclusive_cb.setChecked(exclusive)
        self._device_combo.setEnabled(exclusive)
        self._exclusive_cb.blockSignals(False)
        # Update ASIO format visibility based on exclusive mode
        self._asio_format_label.setVisible(exclusive)
        self._asio_format_combo.setVisible(exclusive)
        if exclusive:
            self._load_hw_devices()
            idx = self._device_combo.findData(exclusive_dev)
            if idx >= 0:
                self._device_combo.setCurrentIndex(idx)
        dsd_mode = str(s.value("dsd_mode", "pcm") or "pcm")
        dsd_idx = self._dsd_combo.findData(dsd_mode)
        if dsd_idx >= 0:
            self._dsd_combo.setCurrentIndex(dsd_idx)
        # Restore ASIO sample format
        asio_fmt = str(s.value("asio_sample_type", "auto") or "auto")
        asio_idx = self._asio_format_combo.findData(asio_fmt)
        if asio_idx >= 0:
            self._asio_format_combo.setCurrentIndex(asio_idx)
        self.refresh_device_list(exclusive_on=exclusive)
