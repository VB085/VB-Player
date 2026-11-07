"""QML-based HiFi Now Playing page.

渲染架构：QQuickWindow + QWidget.createWindowContainer（原生子窗口合成）。
不用 QQuickWidget——后者每帧把整页 FBO 回读进 backing store 再整体拷贝
到 X11（DPR2 下极重，实测歌词滚动仅 ~22fps 且 GUI 线程一旦被阻塞渲染
即停）；原生容器走独立渲染线程 + 真垂直同步，GUI 卡顿不影响渲染节奏。
"""
import bisect
import math
import os
import queue
import sys
import tempfile
from pathlib import Path
from PyQt6.QtCore import (Qt, pyqtSignal, QUrl, QThread, QTimer, QObject,
                          QEasingCurve, QPropertyAnimation, QRect,
                          QAbstractAnimation, pyqtProperty)
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath
from PyQt6.QtQml import QQmlComponent, QQmlEngine
from PyQt6.QtQuick import QQuickWindow
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget


class _QmlOpacityHelper(QObject):
    """Animation target for the hero transition progress (0..1)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 1.0

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, value):
        self._opacity = max(0.0, min(1.0, value))

    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)


def _anim_running(anim) -> bool:
    """动画对象可能已被 C++ 侧删除而 Python 引用仍在（曾致关窗崩溃）。"""
    try:
        return anim is not None and anim.state() == QAbstractAnimation.State.Running
    except RuntimeError:
        return False


class _CoverWorker(QThread):
    """Prepares cover art off the UI thread: decode → blur → JPEG export.

    Mirrors the _MetaLoader pattern (persistent thread + queue). Uses only
    QImage/numpy — no QPixmap, which is not usable outside the GUI thread.
    Results carry a generation counter so stale entries (user switched tracks
    mid-blur) are dropped by the consumer.
    """
    coverReady = pyqtSignal(int, str, str)  # generation, cover_path, bg_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._running = True

    def enqueue(self, gen: int, data: bytes):
        self._queue.put((gen, data))
        if not self.isRunning():
            self.start()

    def stop(self):
        self._running = False
        self._queue.put((-1, None))
        self.wait(2000)

    def run(self):
        from audio_player.ui.widgets.hifi_now_playing import _blur_qimage
        while self._running:
            try:
                gen, data = self._queue.get(timeout=1)
            except Exception:
                continue
            if not self._running or gen < 0:
                break
            try:
                img = QImage.fromData(data)
                if img.isNull():
                    continue
                small = img.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                blurred = _blur_qimage(small, radius=8)
                bg = blurred.scaled(img.width(), img.height(),
                                    Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                cover_path = os.path.join(tempfile.gettempdir(),
                                          f"vbplayer_hifi_cover_{gen}.png")
                bg_path = os.path.join(tempfile.gettempdir(),
                                       f"vbplayer_hifi_bg_{gen}.jpg")
                # 封面预圆角：QML Rectangle 的 clip 只裁矩形不裁圆角，
                # 方形角会在圆角边框外露出（暗色封面即"黑色直角边"）。
                # 半径按显示比例（显示 ≈380px 时 12px）在源尺寸上等效预圆角，
                # 缩放显示时圆角比例保持一致。PNG 带 alpha 通道。
                iw, ih = img.width(), img.height()
                rr = max(4.0, iw * 12.0 / 380.0)
                rounded = QImage(iw, ih, QImage.Format.Format_ARGB32)
                rounded.fill(Qt.GlobalColor.transparent)
                rp = QPainter(rounded)
                rp.setRenderHint(QPainter.RenderHint.Antialiasing)
                rpath = QPainterPath()
                rpath.addRoundedRect(0.0, 0.0, float(iw), float(ih), rr, rr)
                rp.setClipPath(rpath)
                rp.drawImage(0, 0, img)
                rp.end()
                rounded.save(cover_path, "PNG")
                bg.save(bg_path, "JPG", 85)
                # Best-effort cleanup of the previous generation's files
                for old in (f"vbplayer_hifi_cover_{gen - 1}.jpg",
                            f"vbplayer_hifi_cover_{gen - 1}.png",
                            f"vbplayer_hifi_bg_{gen - 1}.jpg"):
                    try:
                        os.unlink(os.path.join(tempfile.gettempdir(), old))
                    except OSError:
                        pass
                self.coverReady.emit(gen, cover_path, bg_path)
            except Exception:
                continue


class HiFiQmlPage(QWidget):
    collapseRequested = pyqtSignal()
    fullscreenRequested = pyqtSignal()
    playPauseClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    prevClicked = pyqtSignal()
    seekRequested = pyqtSignal(int)
    lyricsToggled = pyqtSignal(bool)
    outputDetailRequested = pyqtSignal()

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("hifiQmlPage")

        # 独立 QQuickWindow + 原生窗口容器：渲染线程 + 垂直同步，
        # 绕开 QQuickWidget 的 FBO 回读/backing store 逐帧拷贝
        self._quick_win = QQuickWindow()
        self._quick_win.setColor(QColor("#0d0d1a"))

        # Export icons
        import tempfile
        self._icon_dir = os.path.join(tempfile.gettempdir(), "vbplayer_qml_icons")
        os.makedirs(self._icon_dir, exist_ok=True)
        self._export_icons()

        # Load QML（本地文件同步创建，根对象即最终对象，无重建时序问题）
        qml_path = Path(__file__).resolve().parent.parent / "qml" / "HiFiNowPlaying.qml"
        self._engine = QQmlEngine(self)
        self._component = QQmlComponent(self._engine,
                                        QUrl.fromLocalFile(str(qml_path)))
        self._root_item = None
        if self._component.status() == self._component.Status.Error:
            for err in self._component.errors():
                print(f"[qml] {err.toString()}", file=sys.stderr)
        else:
            item = self._component.create()
            if item is None:
                for err in self._component.errors():
                    print(f"[qml] {err.toString()}", file=sys.stderr)
            else:
                item.setParentItem(self._quick_win.contentItem())
                item.setParent(self._quick_win)
                self._root_item = item

        self._container = QWidget.createWindowContainer(self._quick_win, self)
        self._container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._container.setObjectName("hifiQmlContainer")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._container)

        # 自愈式接线：每次访问前校验根对象身份（防御性保留，直接创建的
        # 根对象是稳定引用，正常情况下只触发一次）
        self._wired_root = None
        self._component.statusChanged.connect(self._on_qml_status)
        self._ensure_root_wired()

        self._position_ms = 0
        self._duration_ms = 0
        self._is_playing = False
        self._cover_worker: _CoverWorker | None = None
        self._cover_gen = 0
        self._lyrics_times: list[int] = []
        self._last_lyrics_idx = -2
        self._lyrics_layout_progress = 0.0
        # ---- Hero 过渡状态（数学与 widget 版逐位一致，见规格文档）----
        self._enter_progress = 1.0
        self._enter_global_rect: QRect | None = None
        self._enter_direction = "in"
        self._exit_done = None
        self._underlay_path: str | None = None
        self._enter_easing: QEasingCurve.Type | None = None
        self._enter_helper = _QmlOpacityHelper(self)
        self._enter_anim: QPropertyAnimation | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_cover_worker)

    def _stop_cover_worker(self):
        if self._cover_worker is not None:
            self._cover_worker.stop()
            self._cover_worker = None

    # ---- QQuickWidget 兼容面 ----

    def rootObject(self):
        return self._root_item

    def quickWindow(self):
        return self._quick_win

    def status(self):
        return self._component.status()

    def errors(self):
        return self._component.errors()

    def _on_qml_status(self, status):
        Status = self._component.Status
        if status == Status.Ready:
            self._ensure_root_wired()
        elif status == Status.Error:
            for err in self.errors():
                print(f"[qml] {err.toString()}", file=sys.stderr)

    def showEvent(self, e):
        super().showEvent(e)
        # 根对象可能在页面显示前后被重建，显示时再校验一次
        self._ensure_root_wired()

    def _ensure_root_wired(self):
        """连接 QML 根对象信号并设置图标。

        根对象被重建后旧连接随之失效，按身份比对幂等重做；图标每次
        重设（代价为 4 次 setProperty，可忽略）。
        """
        root = self.rootObject()
        if root is None:
            return
        if self._wired_root is root:
            return
        self._wired_root = root
        root.collapseRequested.connect(self.collapseRequested.emit)
        root.fullscreenRequested.connect(self.fullscreenRequested.emit)
        root.playPauseClicked.connect(self.playPauseClicked.emit)
        root.nextClicked.connect(self.nextClicked.emit)
        root.prevClicked.connect(self.prevClicked.emit)
        root.seekRequested.connect(self.seekRequested.emit)
        root.lyricsToggled.connect(self._on_lyrics_toggled)
        for name in ('prev', 'play', 'pause', 'next'):
            root.setProperty(f"icon{name.capitalize()}",
                QUrl.fromLocalFile(os.path.join(self._icon_dir, f"{name}.png")).toString())
        if os.environ.get("VB_QML_DEBUG"):
            print(f"[qml-wire] wired root at status={self.status()}, "
                  f"rootid={id(root)}, "
                  f"iconPrev={str(root.property('iconPrev'))[:40]!r}",
                  file=sys.stderr, flush=True)

    def sizeHint(self):
        return self._container.sizeHint() if self._container is not None else super().sizeHint()

    def _export_icons(self):
        from audio_player.ui.icons import TRANSPORT_PREV, TRANSPORT_PLAY, TRANSPORT_PAUSE, TRANSPORT_NEXT, _icon
        icon_map = {'prev': (TRANSPORT_PREV, '#cccccc'), 'play': (TRANSPORT_PLAY, '#ffffff'),
                    'pause': (TRANSPORT_PAUSE, '#ffffff'), 'next': (TRANSPORT_NEXT, '#cccccc')}
        for name, (icon_name, color) in icon_map.items():
            path = os.path.join(self._icon_dir, f"{name}.png")
            if not os.path.exists(path):
                icon = _icon(icon_name, color=color)
                pix = icon.pixmap(64, 64)
                pix.save(path, "PNG")

    def set_track_info(self, title: str, artist: str, album: str):
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("trackTitle", title or "")
        if root: root.setProperty("trackArtist", artist or "")
        if root: root.setProperty("trackAlbum", album or "")

    def set_cover(self, cover_data: bytes | None):
        """Queue cover preparation on the worker thread — the UI thread only
        hands over bytes and applies the finished URLs (see _on_cover_ready)."""
        if not cover_data:
            return
        if self._cover_worker is None:
            self._cover_worker = _CoverWorker(self)
            self._cover_worker.coverReady.connect(self._on_cover_ready)
        self._cover_gen += 1
        self._cover_worker.enqueue(self._cover_gen, cover_data)

    def _on_cover_ready(self, gen: int, cover_path: str, bg_path: str):
        if gen != self._cover_gen:
            return  # stale — a newer track already took over
        self._ensure_root_wired()
        root = self.rootObject()
        if root:
            # Unique per-generation filenames, so no cache-buster query needed
            root.setProperty("coverPath", QUrl.fromLocalFile(cover_path).toString())
            root.setProperty("bgPath", QUrl.fromLocalFile(bg_path).toString())

    def set_position(self, ms: int):
        self._position_ms = ms
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("positionMs", ms)

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("durationMs", ms)

    def set_playing(self, playing: bool):
        self._is_playing = playing
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("isPlaying", playing)


    def set_quality(self, text: str):
        self._ensure_root_wired()
        root = self.rootObject()
        if root:
            root.setProperty("qualityText", text or "")
            if text and " · " in text:
                root.setProperty("qualitySimple", " · ".join(text.split(" · ")[:2]))
            else:
                root.setProperty("qualitySimple", text or "")

    def set_lyrics_visible(self, visible: bool):
        self._lyrics_layout_progress = 1.0 if visible else 0.0
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("lyricsLayoutProgress", self._lyrics_layout_progress)

    def set_lyrics(self, lines: list):
        self._ensure_root_wired()
        root = self.rootObject()
        dict_lines = []
        for line in (lines or []):
            if hasattr(line, '__dataclass_fields__'):
                dict_lines.append({'timeMs': line.time_ms, 'text': line.text, 'translation': line.translation or ''})
            elif isinstance(line, dict):
                dict_lines.append(line)
        self._lyrics_times = [d.get('timeMs', d.get('time_ms', 0)) for d in dict_lines]
        self._last_lyrics_idx = -2
        if root:
            root.setProperty("lyricsModel", dict_lines)

    def set_lyrics_position(self, ms: int):
        """Binary-search the active line over cached timestamps — avoids
        re-converting the whole lyrics model on every position update."""
        if not self._lyrics_times:
            return
        new_idx = bisect.bisect_right(self._lyrics_times, ms) - 1
        if new_idx == self._last_lyrics_idx:
            return
        self._last_lyrics_idx = new_idx
        self._ensure_root_wired()
        root = self.rootObject()
        if root:
            root.setProperty("lyricsActiveIdx", new_idx)

    def refresh_accent(self):
        from audio_player.app import current_accent
        accent = current_accent()
        self._ensure_root_wired()
        root = self.rootObject()
        if root: root.setProperty("accentColor", accent)

    # ---- Hero enter/exit 过渡（参数与 widget 版一致，逐帧推送给 QML）----

    def begin_enter_transition(self, cover_global_rect: QRect,
                               duration: int = 560, underlay=None):
        self._begin_transition(cover_global_rect, "in", duration, underlay)

    def begin_exit_transition(self, cover_global_rect: QRect,
                              on_done=None, duration: int = 460, underlay=None):
        self._exit_done = on_done
        self._begin_transition(cover_global_rect, "out", duration, underlay)

    def _begin_transition(self, cover_global_rect, direction, duration, underlay):
        self._ensure_root_wired()
        root = self.rootObject()
        if root is None:
            # QML 未就绪：直接落到终态，保证功能不中断
            if direction == "out" and self._exit_done:
                done, self._exit_done = self._exit_done, None
                done()
            return
        if _anim_running(self._enter_anim):
            self._enter_anim.stop()
        self._enter_global_rect = QRect(cover_global_rect)
        self._enter_direction = direction
        self._enter_easing = (QEasingCurve.Type.OutExpo if direction == "in"
                              else QEasingCurve.Type.InCubic)
        # 快照 QPixmap → 临时文件（QML Image 走文件路径）
        if underlay is not None:
            path = os.path.join(tempfile.gettempdir(), "vbplayer_hifi_underlay.png")
            try:
                underlay.save(path, "PNG")
                self._underlay_path = path
                root.setProperty("underlayPath", QUrl.fromLocalFile(path).toString())
            except Exception:
                self._underlay_path = None
        root.setProperty("transitionActive", True)
        root.setProperty("enterDirection", direction)
        # 右上角按钮：进入瞬间隐藏、退场随 Behavior 300ms 淡出
        root.setProperty("topbarOpacity", 0.0)
        self._enter_helper.opacity = 0.0 if direction == "in" else 1.0
        self._enter_progress = self._enter_helper.opacity
        anim = QPropertyAnimation(self._enter_helper, b"opacity")
        anim.setDuration(duration)
        anim.setStartValue(self._enter_progress)
        anim.setEndValue(1.0 if direction == "in" else 0.0)
        anim.setEasingCurve(self._enter_easing)
        anim.valueChanged.connect(self._on_enter_tick)
        anim.finished.connect(self._on_enter_finished)
        anim.start()
        self._enter_anim = anim
        self._push_transition_props()

    def _enter_time(self) -> float:
        """过渡的未缓动墙钟进度（与 widget 版同式）。"""
        p = max(0.0, min(1.0, self._enter_progress))
        if self._enter_easing == QEasingCurve.Type.InCubic:
            return (1.0 - p) ** (1.0 / 3.0)
        if p >= 1.0:
            return 1.0
        if p <= 0.0:
            return 0.0
        return max(0.0, min(1.0, -math.log2(1.0 - p) / 10.0))

    @staticmethod
    def _smoothstep(a: float) -> float:
        a = max(0.0, min(1.0, a))
        return a * a * (3.0 - 2.0 * a)

    def _enter_alpha(self, delay: float) -> float:
        """错峰透明度：进入淡入 / 退场镜像淡出（与 widget 版同式）。"""
        if self._enter_global_rect is None:
            return 1.0
        t = self._enter_time()
        if self._enter_direction == "out":
            return self._smoothstep(1.0 - t / max(0.001, 1.0 - delay))
        return self._smoothstep((t - delay) / max(0.001, 1.0 - delay))

    def _push_transition_props(self):
        """把本帧的过渡数值推给 QML（背景淡化/文字错峰/封面飞行矩形）。"""
        self._ensure_root_wired()
        root = self.rootObject()
        if root is None:
            return
        p = max(0.0, min(1.0, self._enter_progress))
        t = self._enter_time()
        if self._enter_direction == "in":
            bg_alpha = self._smoothstep(t / 0.4)
        else:
            bg_alpha = 1.0 - self._smoothstep(1.0 - p)
        root.setProperty("bgFadeAlpha", bg_alpha)
        root.setProperty("titleAlpha", self._enter_alpha(0.20))
        root.setProperty("metaAlpha", self._enter_alpha(0.28))
        root.setProperty("ctrlAlpha", self._enter_alpha(0.38))
        root.setProperty("lyricsPreviewAlpha", self._enter_alpha(0.25))
        # 封面飞行矩形：底栏缩略图 → 当前布局封面位置（QML 同套公式）
        if (self._enter_global_rect is not None and p < 0.999
                and self.width() > 1 and self.height() > 1):
            tl = self.mapFromGlobal(self._enter_global_rect.topLeft())
            sx, sy = float(tl.x()), float(tl.y())
            sw = float(self._enter_global_rect.width())
            sh = float(self._enter_global_rect.height())
            ss = min(sw, sh) if min(sw, sh) > 0 else 56.0
            w, h = float(self.width()), float(self.height())
            lp = self._lyrics_layout_progress
            cw_art = min(h * 0.38, w * 0.35, 380.0)
            cw_lyr = min(h * 0.22, w * 0.18, 240.0)
            cw = cw_art + (cw_lyr - cw_art) * lp
            cx_art = (w - cw_art) / 2.0
            cx_lyr = w * 0.08
            cx = (cx_art + (cx_lyr - cx_art) * lp) - (cw_art - cw) / 2.0
            cy = h * (0.15 + (0.08 - 0.15) * lp)
            root.setProperty("covX", sx + (cx - sx) * p)
            root.setProperty("covY", sy + (cy - sy) * p)
            root.setProperty("covW", ss + (cw - ss) * p)
            root.setProperty("covR", 6.0 + 6.0 * p)
            root.setProperty("coverOverrideActive", True)
        else:
            root.setProperty("coverOverrideActive", False)

    def _on_enter_tick(self, value):
        self._enter_progress = value
        self._push_transition_props()

    def _on_enter_finished(self):
        done = self._exit_done
        exiting = self._enter_helper.opacity <= 0.001
        self._enter_progress = 1.0
        self._enter_global_rect = None
        self._exit_done = None
        self._ensure_root_wired()
        root = self.rootObject()
        if root:
            root.setProperty("transitionActive", False)
            root.setProperty("coverOverrideActive", False)
            root.setProperty("topbarOpacity", 1.0)
        if self._underlay_path:
            try:
                os.unlink(self._underlay_path)
            except OSError:
                pass
            self._underlay_path = None
            if root:
                root.setProperty("underlayPath", "")
        if exiting:
            self._enter_helper.opacity = 1.0
            if done:
                done()

    def toggle_lyrics(self):
        self._ensure_root_wired()
        root = self.rootObject()
        if root:
            to_lyrics = root.property("lyricsLayoutProgress") < 0.5
            self.set_lyrics_visible(to_lyrics)
            self.lyricsToggled.emit(to_lyrics)

    def _on_lyrics_toggled(self, visible: bool):
        """QML 内部按钮切换布局时同步 Python 侧镜像（封面飞行目标需要）。"""
        self._lyrics_layout_progress = 1.0 if visible else 0.0
        self.lyricsToggled.emit(visible)
