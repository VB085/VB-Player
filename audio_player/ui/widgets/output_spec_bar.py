from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QDialog,
                             QVBoxLayout, QPushButton, QFrame, QGridLayout,
                             QGroupBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter
from audio_player.ui.settings_dialog import _CloseButton
from audio_player.ui.widgets.frameless_resize import FramelessResizeMixin
from audio_player.i18n import _


class _OutputDetailDialog(FramelessResizeMixin, QDialog):
    def __init__(self, meta, output_info: dict | None = None, is_light: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("output.title"))
        self.setMinimumWidth(440)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self._is_light = is_light

        info = output_info or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar_bg = "#f0f0f0" if is_light else "#0a0a0a"
        bar_text = "#666666" if is_light else "#777"
        body_bg = "#ffffff" if is_light else "#0f0f1a"
        group_color = "#666666" if is_light else "#94a3b8"
        group_border = "#e0e0e0" if is_light else "#1e1e32"

        # Title bar
        bar = QWidget()
        bar.setObjectName("outputDetailBar")
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background:{bar_bg};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 0, 10, 0)
        bar_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl = QLabel(_("output.title"))
        lbl.setStyleSheet(f"color:{bar_text};font-size:11px;")
        bar_layout.addWidget(lbl)
        bar_layout.addStretch()
        close_btn = _CloseButton()
        close_btn.clicked.connect(self.accept)
        bar_layout.addWidget(close_btn)
        def _on_bar_press(e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            try:
                wh = self.windowHandle()
                if wh is not None:
                    wh.startSystemMove()
            except Exception as _e:
                import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
        bar.mousePressEvent = _on_bar_press
        layout.addWidget(bar)

        body = QWidget()
        body.setObjectName("outputDetailBody")
        body.setStyleSheet(f"background:{body_bg};")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 20)
        body_layout.setSpacing(16)

        group_ss = (
            f"QGroupBox{{color:{group_color};font-size:11px;font-weight:bold;"
            f"border:1px solid {group_border};border-radius:6px;margin-top:12px;padding-top:18px;}}"
            f"QGroupBox::title{{subcontrol-origin:margin;left:12px;}}"
        )

        # ── 1. Source file section ──
        src = QGroupBox(_("output.src_file"))
        src.setObjectName("outputGroup")
        src.setStyleSheet(group_ss)
        src_grid = QGridLayout(src)
        src_grid.setSpacing(6)
        self._add_row(src_grid, 0, _("output.format"), meta.format or "?")
        self._add_row(src_grid, 1, _("output.sample_rate"), f"{meta.sample_rate} Hz" if meta.sample_rate else "?")
        bits = f"{meta.bits_per_sample} bit" if meta.bits_per_sample else "?"
        self._add_row(src_grid, 2, _("output.bit_depth"), bits)
        ch_str = {1: "Mono", 2: "Stereo"}.get(meta.channels, f"{meta.channels} ch" if meta.channels else "?")
        self._add_row(src_grid, 3, _("output.channels"), ch_str)
        body_layout.addWidget(src)

        # ── 2. SRC / Decode section ──
        is_dsd = (meta.format or "").upper() in ("DSD", "DSF", "DFF")
        pipe_rate = info.get("sample_rate", 0)
        dsd_mode = info.get("dsd_decode_mode", "pcm")

        src_group = QGroupBox(_("output.decode_src"))
        src_group.setObjectName("outputGroup")
        src_group.setStyleSheet(group_ss)
        srcg = QGridLayout(src_group)
        srcg.setSpacing(6)

        orig = f"{meta.sample_rate} Hz" if meta.sample_rate else "?"
        self._add_row(srcg, 0, _("output.orig_sample_rate"), orig)

        if is_dsd:
            if dsd_mode == "native":
                decode_desc = _("output.dsd_native_desc")
                actual_label = "DSD Native"
            elif dsd_mode == "dop":
                decode_desc = _("output.dsd_dop_desc")
                actual_label = "DSD via DoP"
            else:
                decode_desc = _("output.dsd_pcm_desc")
                if pipe_rate:
                    actual_label = f"{pipe_rate} Hz"
                else:
                    actual_label = _("output.system_default_dsd")
            self._add_row(srcg, 1, _("output.decode_method"), decode_desc)
            self._add_row(srcg, 2, _("output.dac_format"), actual_label)
        else:
            if pipe_rate:
                actual = f"{pipe_rate} Hz"
                self._add_row(srcg, 1, _("output.dac_actual_rate"), actual)
                if meta.sample_rate and pipe_rate != meta.sample_rate:
                    self._add_row(srcg, 2, _("output.src_status"), _("output.resample", from_rate=meta.sample_rate, to_rate=pipe_rate))
                else:
                    self._add_row(srcg, 2, _("output.src_status"), _("output.passthrough"))
            else:
                self._add_row(srcg, 1, _("output.dac_actual_rate"), _("output.shared_mode"))
                self._add_row(srcg, 2, _("output.src_status"), _("output.resample_by_stack"))

        pipe_fmt = info.get("pipeline_format", "")
        if pipe_fmt:
            short_fmt = pipe_fmt.split(",")[0].split("/")[-1] if "/" in pipe_fmt else pipe_fmt[:60]
            self._add_row(srcg, 3, _("output.output_format"), short_fmt)

        body_layout.addWidget(src_group)

        # ── 3. Output device section ──
        dev = QGroupBox(_("output.device"))
        dev.setObjectName("outputGroup")
        dev.setStyleSheet(group_ss)
        dev_grid = QGridLayout(dev)
        dev_grid.setSpacing(6)
        self._add_row(dev_grid, 0, _("output.device_name"), info.get("name") or _("output.system_default"))
        self._add_row(dev_grid, 1, _("output.audio_api"), info.get("api", "").upper() if info.get("api") else (info.get("driver") or "?"))
        self._add_row(dev_grid, 2, _("output.driver_detail"), info.get("driver") or "?")
        self._add_row(dev_grid, 3, _("output.work_mode"), info.get("mode") or "?")
        self._add_row(dev_grid, 4, _("output.latency"), info.get("latency") or "?")
        body_layout.addWidget(dev)

        body_layout.addStretch()
        layout.addWidget(body)
        self.setFixedSize(self.sizeHint())

    def _add_row(self, grid, row, label, value):
        label_color = "#666666" if self._is_light else "#64748b"
        value_color = "#333333" if self._is_light else "#e2e8f0"
        l = QLabel(label)
        l.setStyleSheet(f"color:{label_color};font-size:11px;")
        v = QLabel(str(value))
        v.setStyleSheet(f"color:{value_color};font-size:12px;font-weight:bold;")
        v.setWordWrap(True)
        grid.addWidget(l, row, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(v, row, 1, Qt.AlignmentFlag.AlignRight)


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
