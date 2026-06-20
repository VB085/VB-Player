from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QDialog,
                             QVBoxLayout, QPushButton, QFrame, QFormLayout,
                             QGroupBox)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QPainter, QPalette, QPainterPath, QPixmap
from PyQt6.QtCore import QRectF
from audio_player.ui.settings_dialog import _CloseButton
from audio_player.ui.widgets.frameless_resize import FramelessResizeMixin
from audio_player.app import current_accent, current_theme_mode
from audio_player.i18n import _
from audio_player.platform import platform_info


_OutputBase = (FramelessResizeMixin, QDialog) if platform_info.policy.titlebar_style == "frameless" else (QDialog,)


class _OutputDetailDialog(*_OutputBase):
    def __init__(self, meta, output_info: dict | None = None, is_light: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("output.title"))
        self.setMinimumSize(520, 440)
        self.resize(540, 560)
        if platform_info.policy.titlebar_style == "frameless":
            self.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self._is_light = is_light
        self._border_radius = 12
        self._mask_dirty = True

        info = output_info or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Drag bar — matches settings dialog
        drag_bar = QWidget()
        drag_bar.setFixedHeight(40)
        drag_bar.setObjectName("settingsDragBar")
        def _on_drag(e):
            if e.button() == Qt.MouseButton.LeftButton and self.windowHandle():
                self.windowHandle().startSystemMove()
        drag_bar.mousePressEvent = _on_drag
        drag_layout = QHBoxLayout(drag_bar)
        drag_layout.setContentsMargins(16, 0, 10, 0)
        drag_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        drag_lbl = QLabel(_("output.title"))
        drag_lbl.setObjectName("settingsDragLabel")
        drag_layout.addWidget(drag_lbl)
        drag_layout.addStretch()
        close_btn = _CloseButton()
        close_btn.clicked.connect(self.accept)
        drag_layout.addWidget(close_btn)
        layout.addWidget(drag_bar)

        # Body — scrollable
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 20)
        body_layout.setSpacing(14)

        # ── 1. Source file ──
        src = QGroupBox(_("output.src_file"))
        src.setObjectName("outputGroup")
        self._style_group(src)
        src_form = QFormLayout(src)
        src_form.setSpacing(8)
        src_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        src_form.addRow(self._rl(_("output.format")), self._rv(meta.format or "?"))
        src_form.addRow(self._rl(_("output.sample_rate")), self._rv(f"{meta.sample_rate} Hz" if meta.sample_rate else "?"))
        src_form.addRow(self._rl(_("output.bit_depth")), self._rv(f"{meta.bits_per_sample} bit" if meta.bits_per_sample else "?"))
        ch_str = {1: "Mono", 2: "Stereo"}.get(meta.channels, f"{meta.channels} ch" if meta.channels else "?")
        src_form.addRow(self._rl(_("output.channels")), self._rv(ch_str))
        body_layout.addWidget(src)

        # ── 2. SRC / Decode ──
        is_dsd = (meta.format or "").upper() in ("DSD", "DSF", "DFF")
        pipe_rate = info.get("sample_rate", 0)
        dsd_mode = info.get("dsd_decode_mode", "pcm")

        src_group = QGroupBox(_("output.decode_src"))
        src_group.setObjectName("outputGroup")
        self._style_group(src_group)
        srcg = QFormLayout(src_group)
        srcg.setSpacing(8)
        srcg.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        srcg.addRow(self._rl(_("output.orig_sample_rate")), self._rv(f"{meta.sample_rate} Hz" if meta.sample_rate else "?"))

        if is_dsd:
            if dsd_mode == "native":
                decode_desc, actual_label = _("output.dsd_native_desc"), "DSD Native"
            elif dsd_mode == "dop":
                decode_desc, actual_label = _("output.dsd_dop_desc"), "DSD via DoP"
            else:
                decode_desc = _("output.dsd_pcm_desc")
                actual_label = f"{pipe_rate} Hz" if pipe_rate else _("output.system_default_dsd")
            srcg.addRow(self._rl(_("output.decode_method")), self._rv(decode_desc))
            srcg.addRow(self._rl(_("output.dac_format")), self._rv(actual_label))
        else:
            if pipe_rate:
                srcg.addRow(self._rl(_("output.dac_actual_rate")), self._rv(f"{pipe_rate} Hz"))
                if meta.sample_rate and pipe_rate != meta.sample_rate:
                    srcg.addRow(self._rl(_("output.src_status")), self._rv(_("output.resample", from_rate=meta.sample_rate, to_rate=pipe_rate)))
                else:
                    srcg.addRow(self._rl(_("output.src_status")), self._rv(_("output.passthrough")))
            else:
                srcg.addRow(self._rl(_("output.dac_actual_rate")), self._rv(_("output.shared_mode")))
                srcg.addRow(self._rl(_("output.src_status")), self._rv(_("output.resample_by_stack")))

        pipe_fmt = info.get("pipeline_format", "")
        if pipe_fmt:
            short_fmt = pipe_fmt.split(",")[0].split("/")[-1] if "/" in pipe_fmt else pipe_fmt[:60]
            srcg.addRow(self._rl(_("output.output_format")), self._rv(short_fmt))
        body_layout.addWidget(src_group)

        # ── 3. Output device ──
        dev = QGroupBox(_("output.device"))
        dev.setObjectName("outputGroup")
        self._style_group(dev)
        dev_form = QFormLayout(dev)
        dev_form.setSpacing(8)
        dev_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        dev_form.addRow(self._rl(_("output.device_name")), self._rv(info.get("name") or _("output.system_default")))
        dev_form.addRow(self._rl(_("output.audio_api")), self._rv(info.get("api", "").upper() if info.get("api") else (info.get("driver") or "?")))
        dev_form.addRow(self._rl(_("output.driver_detail")), self._rv(info.get("driver") or "?"))
        dev_form.addRow(self._rl(_("output.work_mode")), self._rv(info.get("mode") or "?"))
        dev_form.addRow(self._rl(_("output.latency")), self._rv(info.get("latency") or "?"))
        body_layout.addWidget(dev)
        body_layout.addStretch()

        scroll.setWidget(body)
        layout.addWidget(scroll)

    def _rl(self, text: str) -> QLabel:
        """Styled row label."""
        l = QLabel(text)
        l.setObjectName("outputLabel")
        l.setMinimumWidth(80)
        return l

    def _rv(self, text: str) -> QLabel:
        """Styled row value."""
        v = QLabel(text)
        v.setObjectName("outputValue")
        v.setWordWrap(True)
        return v

    def _style_group(self, group):
        """Apply accent border to group box — network-page style."""
        accent = current_accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        group.setStyleSheet(
            f"QGroupBox{{color:#94a3b8;font-size:11px;font-weight:bold;"
            f"border:1px solid rgba({r},{g},{b},0.20);"
            f"border-radius:10px;margin-top:12px;padding-top:18px;}}"
            f"QGroupBox::title{{subcontrol-origin:margin;left:12px;}}"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if platform_info.policy.titlebar_style == "frameless" and self._border_radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._border_radius, self._border_radius)
            painter.fillPath(path, self.palette().color(QPalette.ColorRole.Window))
        else:
            painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        painter.end()
        if self._mask_dirty:
            self._mask_dirty = False
            self._apply_mask()

    def _apply_mask(self):
        if platform_info.policy.titlebar_style != "frameless":
            return
        r = self._border_radius
        w, h = self.width(), self.height()
        if r > 0 and w > 0 and h > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, w, h), r, r)
            pixmap = QPixmap(w, h)
            pixmap.fill(Qt.GlobalColor.transparent)
            pp = QPainter(pixmap)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            pp.fillPath(path, Qt.GlobalColor.black)
            pp.end()
            self.setMask(pixmap.mask())
        else:
            self.clearMask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._mask_dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        self._mask_dirty = True

class OutputSpecBar(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._meta = None
        self._output_info: dict = {}
        self._is_light = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        self._label = QLabel()
        self._label.setObjectName("specLabel")
        layout.addWidget(self._label)
        layout.addStretch()

    def set_meta(self, meta):
        self._meta = meta
        if meta is None or not meta.format:
            self._label.setText("")
            self.setToolTip("")
            return
        fmt = meta.format
        if fmt in ("DSD", "DSF", "DFF"):
            fmt = "DSD → PCM"
        parts = [fmt]
        if meta.bits_per_sample:
            parts.append(f"{meta.bits_per_sample} bit")
        if meta.sample_rate:
            parts.append(f"{int(meta.sample_rate / 1000)} kHz" if meta.sample_rate >= 1000
                         else f"{meta.sample_rate} Hz")
        ch = {1: "Mono", 2: "Stereo"}.get(meta.channels)
        if ch:
            parts.append(ch)
        self._label.setText("  |  ".join(parts))
        self.setToolTip(_("output.title"))

    def set_audio_device(self, info):
        if isinstance(info, dict):
            self._output_info = info
        else:
            self._output_info = {
                "name": str(info) if info else "",
                "driver": "PipeWire / PulseAudio",
                "mode": _("engine.shared_mode"),
            }

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._meta is not None:
            self.clicked.emit()
            self._show_detail()

    def _show_detail(self):
        if self._meta is None:
            return
        dlg = _OutputDetailDialog(self._meta, self._output_info,
                                  self._is_light, self)
        dlg.exec()

    def refresh_accent(self):
        pass

    def refresh_theme_mode(self, is_light: bool):
        self._is_light = is_light
