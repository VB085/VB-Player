"""Bluetooth device detail card — codec info, parameters, supported codecs."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QProgressBar, QSizePolicy, QPushButton, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QColor

from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _


class _Chip(QLabel):
    """Small rounded tag label."""
    def __init__(self, text="", active=False, parent=None):
        super().__init__(text, parent)
        self._active = active
        self._update_style()

    def set_active(self, active: bool):
        self._active = active
        self._update_style()

    def _update_style(self):
        accent = current_accent()
        if self._active:
            self.setStyleSheet(
                f"QLabel{{background:{accent.name()};color:#fff;"
                f"border:none;border-radius:4px;padding:2px 8px;font-size:11px;}}"
            )
        else:
            is_light = current_theme_mode() == "light"
            bg = "rgba(0,0,0,0.06)" if not is_light else "rgba(0,0,0,0.04)"
            fg = "#e2e8f0" if not is_light else "#333"
            self.setStyleSheet(
                f"QLabel{{background:{bg};color:{fg};"
                f"border:1px solid rgba(255,255,255,0.08);"
                f"border-radius:4px;padding:2px 8px;font-size:11px;}}"
            )


class _ParamRow(QWidget):
    """Key-value parameter row."""
    def __init__(self, label: str, value: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        key_lbl = QLabel(label)
        key_lbl.setStyleSheet("color:#64748b;font-size:11px;min-width:60px;")
        layout.addWidget(key_lbl)
        self._val_lbl = QLabel(value)
        self._val_lbl.setStyleSheet("color:#e2e8f0;font-size:11px;font-weight:bold;")
        layout.addWidget(self._val_lbl, 1)
        layout.addStretch()

    def set_value(self, val: str):
        self._val_lbl.setText(val)


class _ProgressMixin:
    """Custom paint for rounded progress bar."""
    @staticmethod
    def style_bar(bar: QProgressBar):
        accent = current_accent()
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            f"QProgressBar{{background:rgba(255,255,255,0.06);border:none;border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{accent.name()};border-radius:4px;}}"
        )


class BluetoothCard(QFrame):
    """Graphical Bluetooth device detail card."""

    codecSwitchRequested = pyqtSignal(str, str)  # address, codec

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bluetoothCard")
        self._setup_ui()
        self._has_device = False
        self._address = ""
        self._host_codecs = []

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # ── Header: icon + name + MAC ──
        header = QHBoxLayout()
        header.setSpacing(10)

        self._icon_label = QLabel("🎧")
        self._icon_label.setFixedSize(44, 44)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        is_light = current_theme_mode() == "light"
        icon_bg = "rgba(0,0,0,0.06)" if not is_light else "rgba(0,0,0,0.04)"
        self._icon_label.setStyleSheet(
            f"QLabel{{background:{icon_bg};border-radius:10px;font-size:22px;}}"
        )
        header.addWidget(self._icon_label)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self._name_label = QLabel(_("bt.no_device"))
        self._name_label.setStyleSheet("font-size:15px;font-weight:bold;color:#e2e8f0;")
        name_col.addWidget(self._name_label)
        self._mac_label = QLabel("")
        self._mac_label.setStyleSheet("font-size:11px;color:#64748b;")
        name_col.addWidget(self._mac_label)
        header.addLayout(name_col, 1)

        layout.addLayout(header)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame{background:rgba(255,255,255,0.06);max-height:1px;}")
        layout.addWidget(sep)

        # ── Current codec highlight box ──
        codec_row = QHBoxLayout()
        codec_row.setSpacing(8)
        self._codec_label = QLabel(_("bt.codec"))
        self._codec_label.setStyleSheet("color:#64748b;font-size:11px;")
        codec_row.addWidget(self._codec_label)
        self._codec_chip = _Chip("", active=True)
        codec_row.addWidget(self._codec_chip)
        self._codec_switch_btn = QPushButton("▼")
        self._codec_switch_btn.setFixedSize(18, 18)
        self._codec_switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._codec_switch_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#64748b;border:none;font-size:7px;padding:0;}"
            "QPushButton:hover{color:#e2e8f0;}"
        )
        self._codec_switch_btn.clicked.connect(self._show_codec_menu)
        codec_row.addWidget(self._codec_switch_btn)
        self._state_chip = _Chip("", active=False)
        codec_row.addWidget(self._state_chip)
        codec_row.addStretch()
        layout.addLayout(codec_row)

        # ── Parameters grid ──
        params_grid = QHBoxLayout()
        params_grid.setSpacing(24)
        self._sample_rate = _ParamRow(_("bt.sample_rate"))
        params_grid.addWidget(self._sample_rate)
        self._channels = _ParamRow(_("bt.channels"))
        params_grid.addWidget(self._channels)
        self._bitrate = _ParamRow(_("bt.bitrate"))
        params_grid.addWidget(self._bitrate)
        self._bitpool = _ParamRow(_("bt.bitpool"))
        params_grid.addWidget(self._bitpool)
        params_grid.addStretch()
        layout.addLayout(params_grid)

        # ── Supported codecs chips ──
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)
        # Device supported
        dev_col = QVBoxLayout()
        dev_col.setSpacing(4)
        self._dev_sup_label = QLabel(_("bt.device_supported"))
        self._dev_sup_label.setStyleSheet("color:#64748b;font-size:10px;")
        dev_col.addWidget(self._dev_sup_label)
        self._dev_chips = QHBoxLayout()
        self._dev_chips.setSpacing(4)
        dev_col.addLayout(self._dev_chips)
        chips_layout.addLayout(dev_col)
        chips_layout.addStretch()
        # Host supported
        host_col = QVBoxLayout()
        host_col.setSpacing(4)
        self._host_sup_label = QLabel(_("bt.host_supported"))
        self._host_sup_label.setStyleSheet("color:#64748b;font-size:10px;")
        host_col.addWidget(self._host_sup_label)
        self._host_chips = QHBoxLayout()
        self._host_chips.setSpacing(4)
        host_col.addLayout(self._host_chips)
        chips_layout.addLayout(host_col)
        chips_layout.addStretch()
        layout.addLayout(chips_layout)

        # ── Battery bar ──
        battery_row = QHBoxLayout()
        battery_row.setSpacing(8)
        self._battery_label = QLabel(_("bt.battery"))
        self._battery_label.setStyleSheet("color:#64748b;font-size:11px;")
        battery_row.addWidget(self._battery_label)
        self._battery_bar = QProgressBar()
        self._battery_bar.setRange(0, 100)
        self._battery_bar.setFixedWidth(120)
        self._battery_bar.setTextVisible(False)
        battery_row.addWidget(self._battery_bar)
        self._battery_pct = QLabel("")
        self._battery_pct.setStyleSheet("color:#e2e8f0;font-size:11px;min-width:36px;")
        battery_row.addWidget(self._battery_pct)
        battery_row.addStretch()
        layout.addLayout(battery_row)
        self._battery_label.setVisible(False)
        self._battery_bar.setVisible(False)
        self._battery_pct.setVisible(False)

        layout.addStretch()

    def set_device(self, name: str, mac: str):
        """Update device identity."""
        self._has_device = True
        self._address = mac
        self._name_label.setText(name)
        self._mac_label.setText(f"{_('bt.mac')}  {mac}")
        self._mac_label.setVisible(True)

    def set_switchable_codecs(self, codecs: list[str]):
        self._host_codecs = list(codecs)

    def _show_codec_menu(self):
        if not self._host_codecs or not self._address:
            return
        menu = QMenu(self)
        current = self._codec_chip.text()
        for c in self._host_codecs:
            action = menu.addAction(c)
            action.setCheckable(True)
            action.setChecked(c == current)
            action.triggered.connect(lambda checked, codec=c: (
                self.codecSwitchRequested.emit(self._address, codec)
            ))
        menu.exec(self._codec_switch_btn.mapToGlobal(
            self._codec_switch_btn.rect().bottomLeft()))

    def set_codec(self, codec: str, state: str = ""):
        self._codec_chip.setText(codec)
        state_map = {
            "idle": _("bt.state.idle"),
            "pending": _("bt.state.pending"),
            "active": _("bt.state.active"),
        }
        if state:
            self._state_chip.setText(state_map.get(state, state))
            self._state_chip.set_active(state == "active")
            self._state_chip.setVisible(True)
        else:
            self._state_chip.setVisible(False)

    def set_params(self, sample_rate: str = "", channels: str = "",
                   bitrate: str = "", bitpool: str = ""):
        if sample_rate:
            self._sample_rate.set_value(sample_rate)
        if channels:
            self._channels.set_value(channels)
        if bitrate:
            self._bitrate.set_value(bitrate)
        if bitpool:
            self._bitpool.set_value(bitpool)

    def set_supported(self, device_codecs: list[str], host_codecs: list[str]):
        # Clear old chips
        for layout in (self._dev_chips, self._host_chips):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        current = self._codec_chip.text()
        for codec in device_codecs:
            chip = _Chip(codec, active=(codec == current))
            self._dev_chips.addWidget(chip)
        self._dev_chips.addStretch()

        for codec in host_codecs:
            chip = _Chip(codec, active=(codec == current))
            self._host_chips.addWidget(chip)
        self._host_chips.addStretch()

    def set_battery(self, level: int | None):
        if level is not None:
            self._battery_bar.setValue(level)
            self._battery_pct.setText(f"{level}%")
            _ProgressMixin.style_bar(self._battery_bar)
            self._battery_label.setVisible(True)
            self._battery_bar.setVisible(True)
            self._battery_pct.setVisible(True)

    def clear(self):
        self._has_device = False
        self._name_label.setText(_("bt.no_device"))
        self._mac_label.setVisible(False)
        self._codec_chip.setText("")
        self._state_chip.setVisible(False)
        self._sample_rate.set_value("")
        self._channels.set_value("")
        self._bitrate.set_value("")
        self._bitpool.set_value("")
        self._battery_label.setVisible(False)
        self._battery_bar.setVisible(False)
        self._battery_pct.setVisible(False)

    def refresh_accent(self):
        """Update chip and bar accent colors."""
        if self._has_device:
            self._codec_chip._update_style()
            self._state_chip._update_style()
            if self._battery_bar.isVisible():
                _ProgressMixin.style_bar(self._battery_bar)

    def refresh_language(self):
        self._codec_label.setText(_("bt.codec"))
        self._dev_sup_label.setText(_("bt.device_supported"))
        self._host_sup_label.setText(_("bt.host_supported"))
        self._battery_label.setText(_("bt.battery"))
        if not self._has_device:
            self._name_label.setText(_("bt.no_device"))
