from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QDialog,
                             QVBoxLayout, QPushButton, QFrame, QGridLayout,
                             QGroupBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainter
from audio_player.ui.settings_dialog import _CloseButton


class _OutputDetailDialog(QDialog):
    def __init__(self, meta, output_info: dict | None = None, is_light: bool = False, parent=None):
        super().__init__(None)
        self.setWindowTitle("音频输出流程")
        self.setMinimumWidth(440)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
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
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background:{bar_bg};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 0, 10, 0)
        bar_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl = QLabel("音频输出流程")
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
            except Exception:
                pass
        bar.mousePressEvent = _on_bar_press
        layout.addWidget(bar)

        body = QWidget()
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
        src = QGroupBox("源文件")
        src.setStyleSheet(group_ss)
        src_grid = QGridLayout(src)
        src_grid.setSpacing(6)
        self._add_row(src_grid, 0, "格式", meta.format or "?")
        self._add_row(src_grid, 1, "采样率", f"{meta.sample_rate} Hz" if meta.sample_rate else "?")
        bits = f"{meta.bits_per_sample} bit" if meta.bits_per_sample else "?"
        self._add_row(src_grid, 2, "位深度", bits)
        ch_str = {1: "Mono", 2: "Stereo"}.get(meta.channels, f"{meta.channels} ch" if meta.channels else "?")
        self._add_row(src_grid, 3, "声道", ch_str)
        body_layout.addWidget(src)

        # ── 2. SRC / Decode section ──
        is_dsd = (meta.format or "").upper() in ("DSD", "DSF", "DFF")
        pipe_rate = info.get("sample_rate", 0)
        dsd_mode = info.get("dsd_decode_mode", "pcm")

        src_group = QGroupBox("解码与采样率转换 (Decode & SRC)")
        src_group.setStyleSheet(group_ss)
        srcg = QGridLayout(src_group)
        srcg.setSpacing(6)

        orig = f"{meta.sample_rate} Hz" if meta.sample_rate else "?"
        self._add_row(srcg, 0, "原始采样率", orig)

        if is_dsd:
            if dsd_mode == "native":
                decode_desc = "DSD 直通 → DAC 原生解码 (硬解)"
                actual_label = "DSD 原生"
            elif dsd_mode == "dop":
                decode_desc = "DSD over PCM (DoP) → DAC 硬解"
                actual_label = "DSD via DoP"
            else:
                decode_desc = "DSD → PCM (软件解码)"
                if pipe_rate:
                    actual_label = f"{pipe_rate} Hz"
                else:
                    actual_label = "系统默认 (由音频栈重采样)"
            self._add_row(srcg, 1, "解码方式", decode_desc)
            self._add_row(srcg, 2, "DAC 接收格式", actual_label)
        else:
            if pipe_rate:
                actual = f"{pipe_rate} Hz"
                self._add_row(srcg, 1, "DAC 实际采样率", actual)
                if meta.sample_rate and pipe_rate != meta.sample_rate:
                    self._add_row(srcg, 2, "SRC 状态", f"重采样 {meta.sample_rate} → {pipe_rate} Hz")
                else:
                    self._add_row(srcg, 2, "SRC 状态", "直通 (无需转换)")
            else:
                self._add_row(srcg, 1, "DAC 实际采样率", "系统默认 (共享模式)")
                self._add_row(srcg, 2, "SRC 状态", "由系统音频栈重采样")

        pipe_fmt = info.get("pipeline_format", "")
        if pipe_fmt:
            short_fmt = pipe_fmt.split(",")[0].split("/")[-1] if "/" in pipe_fmt else pipe_fmt[:60]
            self._add_row(srcg, 3, "输出格式", short_fmt)

        body_layout.addWidget(src_group)

        # ── 3. Output device section ──
        dev = QGroupBox("输出设备")
        dev.setStyleSheet(group_ss)
        dev_grid = QGridLayout(dev)
        dev_grid.setSpacing(6)
        self._add_row(dev_grid, 0, "设备名称", info.get("name") or "系统默认")
        self._add_row(dev_grid, 1, "音频 API", info.get("api", "").upper() if info.get("api") else (info.get("driver") or "?"))
        self._add_row(dev_grid, 2, "驱动详情", info.get("driver") or "?")
        self._add_row(dev_grid, 3, "工作模式", info.get("mode") or "?")
        self._add_row(dev_grid, 4, "延迟特征", info.get("latency") or "?")
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
        self._label.setStyleSheet(
            "color:#555;font-size:10px;font-family:monospace;"
            "padding:2px 10px;border-radius:4px;background:transparent;"
        )
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
        self.setToolTip("点击查看完整输出流程")

    def set_audio_device(self, info):
        if isinstance(info, dict):
            self._output_info = info
        else:
            self._output_info = {
                "name": str(info) if info else "",
                "driver": "PipeWire / PulseAudio",
                "mode": "共享模式 (Shared)",
            }

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._meta is not None:
            self._show_detail()

    def enterEvent(self, event):
        hover_color = "#333333" if self._is_light else "#c0c0c0"
        hover_bg = "#e8e8e8" if self._is_light else "#1a1a2e"
        self._label.setStyleSheet(
            f"color:{hover_color};font-size:10px;font-family:monospace;"
            f"padding:2px 10px;border-radius:4px;background:{hover_bg};"
        )

    def leaveEvent(self, event):
        text_color = "#555555" if self._is_light else "#555"
        self._label.setStyleSheet(
            f"color:{text_color};font-size:10px;font-family:monospace;"
            f"padding:2px 10px;border-radius:4px;background:transparent;"
        )

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
        text_color = "#555555" if is_light else "#555"
        self._label.setStyleSheet(
            f"color:{text_color};font-size:10px;font-family:monospace;"
            f"padding:2px 10px;border-radius:4px;background:transparent;"
        )
