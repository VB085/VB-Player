"""Output device button with popup for quick device switching.

Shows current output device name + icon in transport bar.
Click to show popup with local + discovered DLNA renderers.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,

    QListWidget, QListWidgetItem, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor

from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _


class DevicePopup(QFrame):
    """Minimal device picker popup."""

    deviceSelected = pyqtSignal(str)  # device id

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("devicePopup")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._list = QListWidget()
        self._list.setObjectName("deviceList")
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Manage link
        self._manage_btn = QPushButton(_("network.connect_nas"))
        self._manage_btn.setObjectName("deviceManageBtn")
        self._manage_btn.clicked.connect(self._on_manage)
        layout.addWidget(self._manage_btn)

        self._apply_style()

    def set_devices(self, devices: list[dict], active_id: str):
        """Populate device list.

        devices: [{id, name, type}]
        active_id: currently active device id
        """
        self._list.clear()
        for d in devices:
            item = QListWidgetItem(d["name"])
            item.setData(Qt.ItemDataRole.UserRole, d["id"])
            if d["id"] == active_id:
                item.setIcon(self._check_icon())
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem):
        device_id = item.data(Qt.ItemDataRole.UserRole)
        if device_id:
            self.deviceSelected.emit(device_id)
            self.close()

    def _on_manage(self):
        # Navigate to network page — emitted signal will be connected by MainWindow
        self.close()

    def _check_icon(self):
        from PyQt6.QtGui import QIcon, QPixmap, QPainter
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setPen(QColor(current_accent()))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "✓")
        p.end()
        return QIcon(pix)

    def _apply_style(self):
        is_light = current_theme_mode() == "light"
        bg = "#ffffff" if is_light else "#12121a"
        border = "#ddd" if is_light else "#2a2a3a"
        text = "#333" if is_light else "#e2e8f0"
        hover = "#f0f0f0" if is_light else "#1a1a2e"

        self.setStyleSheet(
            f"QFrame#devicePopup {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 8px;"
            f"}}"
            f"QListWidget#deviceList {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  color: {text};"
            f"  font-size: 13px;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 6px 8px;"
            f"  border-radius: 4px;"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background: {hover};"
            f"}}"
            f"QPushButton#deviceManageBtn {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  color: {text};"
            f"  font-size: 12px;"
            f"  padding: 4px 8px;"
            f"  text-align: left;"
            f"}}"
            f"QPushButton#deviceManageBtn:hover {{"
            f"  background: {hover};"
            f"  border-radius: 4px;"
            f"}}"
        )


class DeviceButton(QWidget):
    """Output device button for transport bar.

    Shows 📡 icon + current device name. Click to open device picker.
    """

    deviceSelected = pyqtSignal(str)  # device id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_name = _("device.local")
        self._is_casting = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._btn = QPushButton()
        self._btn.setObjectName("deviceBtn")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._show_popup)
        layout.addWidget(self._btn)

        self._update_button_text()

    def set_device_name(self, name: str, is_casting: bool = False):
        """Update displayed device name."""
        self._current_name = name
        self._is_casting = is_casting
        self._update_button_text()

    def _update_button_text(self):
        icon = "📡" if self._is_casting else "🔊"
        self._btn.setText(f"{icon} {self._current_name}")
        self._btn.setToolTip(self._current_name)
        self._apply_style()

    def _show_popup(self):
        popup = DevicePopup(self)

        # Build device list from CastController (connected via MainWindow)
        devices = getattr(self, '_devices', [])
        active_id = getattr(self, '_active_device_id', 'local')
        popup.set_devices(devices, active_id)
        popup.deviceSelected.connect(self.deviceSelected.emit)

        # Position popup below button
        pos = self._btn.mapToGlobal(self._btn.rect().bottomLeft())
        popup.move(pos)
        popup.show()

    def set_devices(self, devices: list[dict], active_id: str):
        """Set available devices (called by MainWindow)."""
        self._devices = devices
        self._active_device_id = active_id

    def _apply_style(self):
        accent = current_accent()
        is_light = current_theme_mode() == "light"
        text = "#555" if is_light else "#94a3b8"
        hover_bg = "#e8e8e8" if is_light else "#1a1a2e"

        if self._is_casting:
            text_color = accent.name()
        else:
            text_color = text

        self._btn.setStyleSheet(
            f"QPushButton#deviceBtn {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  border-radius: 6px;"
            f"  color: {text_color};"
            f"  font-size: 12px;"
            f"  padding: 4px 8px;"
            f"}}"
            f"QPushButton#deviceBtn:hover {{"
            f"  background: {hover_bg};"
            f"}}"
        )

    def refresh_theme(self):
        self._apply_style()
