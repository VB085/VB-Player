import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_player.player.equalizer import BAND_FREQUENCIES
from audio_player.player._types import PlaybackState

Gst.init(None)


def _map_gst_state(gst_state) -> int:
    if gst_state == Gst.State.PLAYING:
        return PlaybackState.Playing
    elif gst_state == Gst.State.PAUSED:
        return PlaybackState.Paused
    else:
        return PlaybackState.Stopped


class _BaseAudioEngine(QObject):
    """Cross-platform GStreamer audio engine.

    Subclasses must override:
      - _create_sink() -> Gst.Element
      - _default_exclusive_device() -> str
      - _output_info_dict() -> dict
    Subclasses may override:
      - enumerate_hw_devices() -> list[dict]  (static or classmethod)
    """

    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(int)
    trackChanged = pyqtSignal(str)
    trackFinished = pyqtSignal()
    errorOccurred = pyqtSignal(str)
    volumeChanged = pyqtSignal(float)
    exclusiveModeChanged = pyqtSignal(bool)
    outputInfoChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        Gst.init(None)

        self._pipeline: Gst.Pipeline | None = None
        self._volume_elem: Gst.Element | None = None
        self._eq_elem: Gst.Element | None = None
        self._conv1: Gst.Element | None = None
        self._audio_queue: Gst.Element | None = None
        self._filesrc: Gst.Element | None = None
        self._decodebin: Gst.Element | None = None
        self._sink: Gst.Element | None = None
        self._audio_pad_linked = False
        self._stall_ticks = 0
        self._last_position_ms = -1

        self._current_file = ""
        self._app_state = PlaybackState.Stopped
        self._duration_ms = 0
        self._position_ms = 0
        self._volume_level = 0.8

        self._exclusive_mode = False
        self._exclusive_device = self._default_exclusive_device()

        self._eq_enabled = False
        self._eq_gains = [0.0] * 10

        self._pipeline_sample_rate: int = 0
        self._pipeline_output_format: str = ""
        self._source_is_dsd: bool = False
        self._dsd_decode_mode: str = "pcm"  # "pcm" | "native" | "dop"

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    # ------------------------------------------------------------------
    #  Platform hooks — subclasses MUST override
    # ------------------------------------------------------------------

    def _create_sink(self) -> Gst.Element:
        """Return the audio sink element for the current platform/mode."""
        raise NotImplementedError

    def _default_exclusive_device(self) -> str:
        """Return the default exclusive-mode device identifier."""
        raise NotImplementedError

    def _output_info_dict(self) -> dict:
        """Return {name, driver, mode, sample_rate, format, is_exclusive, api,
        dsd_decode_mode} describing the current output."""
        raise NotImplementedError

    def _query_output_caps(self) -> tuple[int, str]:
        """Query negotiated caps — tries sink peer pad first, then sink itself."""
        if self._pipeline is None:
            return 0, ""
        try:
            # Try the element feeding the sink first (more reliable for ASIO)
            if self._sink is not None:
                sink_pad = self._sink.get_static_pad("sink")
                if sink_pad is not None:
                    peer = sink_pad.get_peer()
                    if peer is not None:
                        caps = peer.get_current_caps()
                        if caps is None:
                            caps = peer.get_allowed_caps()
                        if caps is not None and caps.get_size() > 0:
                            struct = caps.get_structure(0)
                            if struct:
                                rate = struct.get_int("rate").value_current if struct.has_field("rate") else 0
                                return rate, struct.to_string()

            # Fallback: query sink pad directly
            if self._sink is not None:
                sink_pad = self._sink.get_static_pad("sink")
                if sink_pad is not None:
                    caps = sink_pad.get_current_caps()
                    if caps is None:
                        caps = sink_pad.get_allowed_caps()
                    if caps is not None and caps.get_size() > 0:
                        struct = caps.get_structure(0)
                        if struct:
                            rate = struct.get_int("rate").value_current if struct.has_field("rate") else 0
                            return rate, struct.to_string()
            return 0, ""
        except Exception:
            return 0, ""

    # ------------------------------------------------------------------
    #  Pipeline construction
    # ------------------------------------------------------------------

    def _build_pipeline(self, filepath: str):
        self._teardown_pipeline()

        try:
            pipeline = Gst.Pipeline.new("audio-pipeline")

            filesrc = Gst.ElementFactory.make("filesrc", None)
            filesrc.set_property("location", filepath)

            decodebin = Gst.ElementFactory.make("decodebin", None)
            decodebin.connect("pad-added", self._on_decodebin_pad_added)

            audio_queue = Gst.ElementFactory.make("queue", None)
            if audio_queue is not None:
                audio_queue.set_property("max-size-time", 2 * Gst.SECOND)
                audio_queue.set_property("max-size-buffers", 0)
                audio_queue.set_property("max-size-bytes", 0)

            conv1 = Gst.ElementFactory.make("audioconvert", None)
            resample1 = Gst.ElementFactory.make("audioresample", None)
            if resample1 is not None:
                resample1.set_property("quality", 10)
            volume = Gst.ElementFactory.make("volume", None)
            volume.set_property("volume", self._volume_level)

            eq = Gst.ElementFactory.make("equalizer-nbands", None)
            eq.set_property("num-bands", 10)
            for i, freq in enumerate(BAND_FREQUENCIES):
                band = eq.get_child_by_index(i)
                band.set_property("freq", float(freq))
                band.set_property("gain", self._eq_gains[i] if self._eq_enabled else 0.0)

            conv2 = Gst.ElementFactory.make("audioconvert", None)
            resample2 = Gst.ElementFactory.make("audioresample", None)
            if resample2 is not None:
                resample2.set_property("quality", 10)

            sink = self._create_sink()
            if sink is None:
                raise RuntimeError("GStreamer 音频输出不可用")

            for elem in [filesrc, decodebin, audio_queue, conv1, resample1, volume, eq, conv2, resample2, sink]:
                if elem is None:
                    raise RuntimeError("GStreamer 插件缺失，无法创建音频管道")
                pipeline.add(elem)

            # Link static chain (decodebin pads linked dynamically)
            filesrc.link(decodebin)
            audio_queue.link(conv1)
            conv1.link(resample1)
            resample1.link(volume)
            volume.link(eq)
            eq.link(conv2)
            conv2.link(resample2)
            resample2.link(sink)

            self._pipeline = pipeline
            self._volume_elem = volume
            self._eq_elem = eq
            self._conv1 = conv1
            self._audio_queue = audio_queue
            self._filesrc = filesrc
            self._decodebin = decodebin
            self._sink = sink
            self._audio_pad_linked = False

            # Detect DSD source from file extension
            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            self._source_is_dsd = ext in ("dsf", "dff", "dsd")
            if self._source_is_dsd:
                self._dsd_decode_mode = "pcm"  # standard pipeline always soft-decodes
            self._pipeline_sample_rate = 0
            self._pipeline_output_format = ""

        except Exception as e:
            self._teardown_pipeline()
            self.errorOccurred.emit(str(e))

    def _teardown_pipeline(self):
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        self._volume_elem = None
        self._eq_elem = None
        self._conv1 = None
        self._audio_queue = None
        self._filesrc = None
        self._decodebin = None
        self._sink = None
        self._audio_pad_linked = False
        if self._position_ms != 0 or self._duration_ms != 0:
            self._position_ms = 0
            self._duration_ms = 0
            self.positionChanged.emit(0)
            self.durationChanged.emit(0)
        self._stall_ticks = 0
        self._last_position_ms = -1
        self._pipeline_sample_rate = 0
        self._pipeline_output_format = ""
        self._app_state = PlaybackState.Stopped

    def _on_decodebin_pad_added(self, decodebin, pad):
        caps = pad.get_current_caps()
        if caps is None or self._audio_queue is None:
            return
        struct = caps.get_structure(0)
        if struct is None or not struct.get_name().startswith("audio/"):
            return
        if self._audio_pad_linked:
            return
        sink_pad = self._audio_queue.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)
            self._audio_pad_linked = True

    # ------------------------------------------------------------------
    #  Bus message handler
    # ------------------------------------------------------------------

    def _handle_message(self, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            self._app_state = PlaybackState.Stopped
            self.stateChanged.emit(PlaybackState.Stopped)
            self.trackFinished.emit()
        elif t == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            text = str(err)
            if debug:
                text = f"{text} ({debug})"
            self.errorOccurred.emit(text)
            self._app_state = PlaybackState.Stopped
            self.stateChanged.emit(PlaybackState.Stopped)
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pending = msg.parse_state_changed()
            if isinstance(msg.src, Gst.Pipeline):
                mapped = _map_gst_state(new)
                if mapped != self._app_state:
                    self._app_state = mapped
                    self.stateChanged.emit(mapped)
                    if mapped == PlaybackState.Playing:
                        self._stall_ticks = 0
                        self._last_position_ms = -1
        elif t == Gst.MessageType.ASYNC_DONE:
            if self._pipeline is not None:
                ok, dur_ns = self._pipeline.query_duration(Gst.Format.TIME)
                if ok:
                    ms = dur_ns // 1000000
                    if ms != self._duration_ms:
                        self._duration_ms = ms
                        self.durationChanged.emit(ms)
                rate, fmt_str = self._query_output_caps()
                if rate:
                    self._pipeline_sample_rate = rate
                if fmt_str:
                    self._pipeline_output_format = fmt_str
                self.outputInfoChanged.emit(self.output_info)

    # ------------------------------------------------------------------
    #  Position / duration / bus polling
    # ------------------------------------------------------------------

    def _poll(self):
        if self._pipeline is None:
            return
        bus = self._pipeline.get_bus()
        while True:
            msg = bus.pop()
            if msg is None:
                break
            self._handle_message(msg)
        ok, pos_ns = self._pipeline.query_position(Gst.Format.TIME)
        if ok:
            ms = pos_ns // 1000000
            if ms != self._position_ms:
                self._position_ms = ms
                self.positionChanged.emit(ms)
            if self._app_state == PlaybackState.Playing:
                if ms == self._last_position_ms:
                    self._stall_ticks += 1
                    # Allow up to ~8s (160 ticks) before declaring stall; ASIO/WASAPI
                    # exclusive startup can take several seconds
                    if self._stall_ticks > 160 and ms < 500:
                        self.errorOccurred.emit("播放引擎卡住 — 请重试或切换输出模式")
                        self._app_state = PlaybackState.Stopped
                        self.stateChanged.emit(PlaybackState.Stopped)
                        self._stall_ticks = 0
                else:
                    self._stall_ticks = 0
                    self._last_position_ms = ms
        ok, dur_ns = self._pipeline.query_duration(Gst.Format.TIME)
        if ok:
            ms = dur_ns // 1000000
            if ms != self._duration_ms:
                self._duration_ms = ms
                self.durationChanged.emit(ms)

    # ------------------------------------------------------------------
    #  Public API — playback control
    # ------------------------------------------------------------------

    def load(self, filepath: str):
        self._current_file = filepath
        self._build_pipeline(filepath)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.PAUSED)
        self.trackChanged.emit(filepath)

    def play(self):
        if not self._current_file:
            return
        if self._pipeline is None:
            self._build_pipeline(self._current_file)
        if self._pipeline is not None:
            # Check actual pipeline state, not tracked _app_state (may be stale)
            ok, state, pending = self._pipeline.get_state(0)
            if ok == Gst.StateChangeReturn.SUCCESS and state != Gst.State.PLAYING:
                self._pipeline.set_state(Gst.State.PLAYING)
            elif ok == Gst.StateChangeReturn.FAILURE:
                pass  # pipeline failed — don't try to play

    def pause(self):
        if self._pipeline is not None and self._app_state == PlaybackState.Playing:
            self._pipeline.set_state(Gst.State.PAUSED)

    def stop(self):
        self._teardown_pipeline()
        if self._app_state != PlaybackState.Stopped:
            self._app_state = PlaybackState.Stopped
            self.stateChanged.emit(PlaybackState.Stopped)

    def toggle(self):
        if not self._current_file:
            self.errorOccurred.emit("没有加载音频文件")
            return
        if self._app_state == PlaybackState.Playing:
            self.pause()
        else:
            self.play()

    def seek(self, position_ms: int):
        if self._pipeline is None:
            return
        target = max(0, min(position_ms, self._duration_ms))
        self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            target * 1000000
        )

    def seek_ratio(self, ratio: float):
        self.seek(int(ratio * self._duration_ms))

    # ------------------------------------------------------------------
    #  Public properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> int:
        return self._position_ms

    @property
    def duration(self) -> int:
        return self._duration_ms

    @property
    def state(self) -> int:
        return self._app_state

    @property
    def is_playing(self) -> bool:
        return self._app_state == PlaybackState.Playing

    @property
    def volume(self) -> float:
        return self._volume_level

    @volume.setter
    def volume(self, value: float):
        self._volume_level = max(0.0, min(1.0, value))
        if self._volume_elem is not None:
            self._volume_elem.set_property("volume", self._volume_level)
        self.volumeChanged.emit(self._volume_level)

    @property
    def current_file(self) -> str:
        return self._current_file

    @property
    def audio_output(self):
        return self.output_info

    @property
    def output_info(self) -> dict:
        info = self._output_info_dict()
        info["sample_rate"] = self._pipeline_sample_rate
        info["pipeline_format"] = self._pipeline_output_format
        info["source_is_dsd"] = self._source_is_dsd
        info["dsd_decode_mode"] = self._dsd_decode_mode
        return info

    @property
    def dsd_mode(self) -> str:
        return self._dsd_decode_mode

    @dsd_mode.setter
    def dsd_mode(self, mode: str):
        if mode not in ("pcm", "native", "dop"):
            raise ValueError(f"Invalid DSD mode: {mode}")
        if mode == self._dsd_decode_mode:
            return
        self._dsd_decode_mode = mode
        if self._current_file and self._source_is_dsd:
            pos = self._position_ms
            self._build_pipeline(self._current_file)
            if self._pipeline is not None:
                self._pipeline.set_state(Gst.State.PAUSED)
                if pos > 0:
                    self.seek(pos)

    # ------------------------------------------------------------------
    #  Exclusive mode
    # ------------------------------------------------------------------

    @property
    def exclusive_mode(self) -> bool:
        return self._exclusive_mode

    @exclusive_mode.setter
    def exclusive_mode(self, enabled: bool):
        if enabled == self._exclusive_mode:
            return
        self._exclusive_mode = enabled
        if self._current_file:
            pos = self._position_ms
            self._build_pipeline(self._current_file)
            if self._pipeline is not None:
                self._pipeline.set_state(Gst.State.PAUSED)
                if pos > 0:
                    self.seek(pos)
        self.exclusiveModeChanged.emit(enabled)

    @property
    def exclusive_device(self) -> str:
        return self._exclusive_device

    @exclusive_device.setter
    def exclusive_device(self, hw: str):
        if hw == self._exclusive_device:
            return
        self._exclusive_device = hw
        if self._exclusive_mode and self._current_file:
            pos = self._position_ms
            self._build_pipeline(self._current_file)
            if self._pipeline is not None:
                self._pipeline.set_state(Gst.State.PAUSED)
                if pos > 0:
                    self.seek(pos)

    # ------------------------------------------------------------------
    #  Equalizer live control
    # ------------------------------------------------------------------

    def set_eq_enabled(self, enabled: bool):
        self._eq_enabled = enabled
        if self._eq_elem is not None:
            for i in range(10):
                band = self._eq_elem.get_child_by_index(i)
                band.set_property("gain", self._eq_gains[i] if enabled else 0.0)

    def set_eq_band_gain(self, band_idx: int, db: float):
        if 0 <= band_idx < 10:
            self._eq_gains[band_idx] = db
        if self._eq_elem is not None and self._eq_enabled:
            child = self._eq_elem.get_child_by_index(band_idx)
            child.set_property("gain", db)

    def set_eq_all_gains(self, gains: list[float]):
        for i, g in enumerate(gains[:10]):
            self._eq_gains[i] = g
        if self._eq_elem is not None:
            for i in range(10):
                band = self._eq_elem.get_child_by_index(i)
                band.set_property("gain", self._eq_gains[i] if self._eq_enabled else 0.0)
