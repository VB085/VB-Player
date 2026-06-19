import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from audio_player.player.equalizer import BAND_FREQUENCIES
from audio_player.player._types import PlaybackState
from audio_player.i18n import _

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
    streamMetadataChanged = pyqtSignal(dict)
    bufferingProgress = pyqtSignal(int)

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
        self._replaygain_enabled = False
        self._rgvolume_elem: Gst.Element | None = None

        self._pipeline_sample_rate: int = 0
        self._pipeline_output_format: str = ""
        self._source_is_dsd: bool = False
        self._dsd_decode_mode: str = "pcm"  # "pcm" | "native" | "dop"

        # URL/stream playback state
        self._is_stream = False
        self._playbin: Gst.Element | None = None
        self._stream_buffering = False

        # Windows DSD ffmpeg fallback state (initialized here for _handle_message guard)
        self._ffmpeg_playing_event = None

        # Gapless playback state
        self._gapless_enabled = False
        self._preload_pipeline: Gst.Pipeline | None = None
        self._preload_file = ""
        self._preload_sink: Gst.Element | None = None
        self._preload_volume: Gst.Element | None = None
        self._preload_eq: Gst.Element | None = None
        self._preload_rgvolume: Gst.Element | None = None
        self._preload_conv1: Gst.Element | None = None
        self._preload_audio_queue: Gst.Element | None = None
        self._preload_filesrc: Gst.Element | None = None
        self._preload_decodebin: Gst.Element | None = None
        self._preload_audio_pad_linked = False
        self._preload_sample_rate = 0
        self._preload_output_format = ""
        self._preload_is_dsd = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll)
        # Timer starts on play(), stops on pause/stop to avoid idle polling

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

        def _get_rate(struct):
            """Extract sample rate from caps structure."""
            if not struct.has_field("rate"):
                return 0
            result = struct.get_int("rate")
            # GStreamer Python bindings return (bool, int) tuple
            if isinstance(result, tuple) and len(result) == 2:
                return result[1] if result[0] else 0
            # Legacy API: object with .value_current
            return getattr(result, 'value_current', 0)

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
                                rate = _get_rate(struct)
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
                            rate = _get_rate(struct)
                            return rate, struct.to_string()
            return 0, ""
        except Exception as e:
            import sys; print(f"[engine] caps 解析失败: {e}", file=sys.stderr)
            return 0, ""

    # ------------------------------------------------------------------
    #  URL detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_url(source: str) -> bool:
        return source.startswith(("http://", "https://", "smb://"))

    # ------------------------------------------------------------------
    #  Pipeline construction
    # ------------------------------------------------------------------

    def _build_pipeline(self, filepath: str):
        self._teardown_pipeline()

        try:
            result = self._create_audio_pipeline(
                "audio-pipeline", filepath, self._on_decodebin_pad_added,
            )
            if result is None:
                raise RuntimeError(_("engine.gst_unavailable"))

            pipeline, elems = result
            filesrc, decodebin, audio_queue, conv1, resample1, rgvolume, volume, eq, conv2, resample2, sink = elems

            self._pipeline = pipeline
            self._volume_elem = volume
            self._eq_elem = eq
            self._rgvolume_elem = rgvolume
            self._conv1 = conv1
            self._audio_queue = audio_queue
            self._filesrc = filesrc
            self._decodebin = decodebin
            self._sink = sink
            self._audio_pad_linked = False

            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            self._source_is_dsd = ext in ("dsf", "dff", "dsd")
            if self._source_is_dsd:
                self._dsd_decode_mode = "pcm"
            self._pipeline_sample_rate = 0
            self._pipeline_output_format = ""

        except Exception as e:
            self._teardown_pipeline()
            self.errorOccurred.emit(str(e))

    def _create_audio_pipeline(self, name: str, filepath: str, pad_added_cb):
        """Create a GStreamer audio pipeline with the standard element chain.

        Returns (pipeline, (filesrc, decodebin, audio_queue, conv1, resample1,
        rgvolume, volume, eq, conv2, resample2, sink)) or None on failure.
        Raises RuntimeError if critical plugins are missing.
        """
        pipeline = Gst.Pipeline.new(name)

        filesrc = Gst.ElementFactory.make("filesrc", None)
        filesrc.set_property("location", filepath)

        decodebin = Gst.ElementFactory.make("decodebin", None)
        decodebin.connect("pad-added", pad_added_cb)

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

        rgvolume = None
        if self._replaygain_enabled:
            rgvolume = Gst.ElementFactory.make("rgvolume", None)

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
            return None

        elems = [filesrc, decodebin, audio_queue, conv1, resample1]
        if rgvolume is not None:
            elems.append(rgvolume)
        elems.extend([volume, eq, conv2, resample2, sink])
        for elem in elems:
            if elem is None:
                raise RuntimeError(_("engine.gst_plugins_missing"))
            pipeline.add(elem)

        filesrc.link(decodebin)
        audio_queue.link(conv1)
        conv1.link(resample1)
        if rgvolume is not None:
            resample1.link(rgvolume)
            rgvolume.link(volume)
        else:
            resample1.link(volume)
        volume.link(eq)
        eq.link(conv2)
        conv2.link(resample2)
        resample2.link(sink)

        return pipeline, (filesrc, decodebin, audio_queue, conv1, resample1,
                          rgvolume, volume, eq, conv2, resample2, sink)

    def _build_url_pipeline(self, uri: str):
        """Build a playbin-based pipeline for HTTP/HLS/ICY streams."""
        self._teardown_pipeline()

        try:
            playbin = Gst.ElementFactory.make("playbin", "stream-pipeline")
            if playbin is None:
                raise RuntimeError(_("engine.gst_plugins_missing"))

            playbin.set_property("uri", uri)
            playbin.set_property("volume", self._volume_level)

            # Disable video output — audio only
            playbin.set_property("flags", 0x01)  # GST_PLAY_FLAG_AUDIO

            self._pipeline = playbin
            self._playbin = playbin
            self._is_stream = True
            self._stream_buffering = False
            self._source_is_dsd = False
            self._pipeline_sample_rate = 0
            self._pipeline_output_format = ""

        except Exception as e:
            self._teardown_pipeline()
            self.errorOccurred.emit(str(e))

    def _teardown_pipeline(self):
        self._cleanup_preloaded()
        if self._pipeline is not None:
            old = self._pipeline
            self._pipeline = None
            old.set_state(Gst.State.NULL)
            # Poll until NULL — don't block longer than 100ms on main thread
            for _ in range(20):
                ok, state, _ = old.get_state(5 * Gst.MSECOND)
                if ok == Gst.StateChangeReturn.SUCCESS and state == Gst.State.NULL:
                    break
        self._playbin = None
        self._is_stream = False
        self._stream_buffering = False
        self._volume_elem = None
        self._eq_elem = None
        self._rgvolume_elem = None
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
            if self._preload_pipeline is not None:
                self._gapless_transition()
            else:
                self._poll_timer.stop()
                self._app_state = PlaybackState.Stopped
                self.stateChanged.emit(PlaybackState.Stopped)
                self.trackFinished.emit()
        elif t == Gst.MessageType.ERROR:
            self._poll_timer.stop()
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
            if self._pipeline is not None and not self._is_stream:
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
        elif t == Gst.MessageType.TAG and self._is_stream:
            tag_list = msg.parse_tag()
            tags = {}
            for i in range(tag_list.n_tags()):
                key = tag_list.nth_tag_name(i)
                ok, val = tag_list.get_value(key, 0)
                if ok and val is not None:
                    tags[key] = str(val)
            if tags:
                self.streamMetadataChanged.emit(tags)
        elif t == Gst.MessageType.BUFFERING and self._is_stream:
            percent = msg.parse_buffering()
            self.bufferingProgress.emit(percent)
            if percent < 100 and not self._stream_buffering:
                self._stream_buffering = True
                if self._pipeline is not None:
                    self._pipeline.set_state(Gst.State.PAUSED)
            elif percent >= 100 and self._stream_buffering:
                self._stream_buffering = False
                if self._pipeline is not None:
                    self._pipeline.set_state(Gst.State.PLAYING)

    # ------------------------------------------------------------------
    #  Position / duration / bus polling
    # ------------------------------------------------------------------

    def _poll(self):
        if self._pipeline is None:
            return
        # Always drain the bus to catch EOS / errors / state changes
        bus = self._pipeline.get_bus()
        while True:
            msg = bus.pop()
            if msg is None:
                break
            self._handle_message(msg)
        # Skip position/duration queries when not playing or buffering
        if self._app_state != PlaybackState.Playing or self._stream_buffering:
            return
        ok, pos_ns = self._pipeline.query_position(Gst.Format.TIME)
        if ok:
            ms = pos_ns // 1000000
            if ms != self._position_ms:
                self._position_ms = ms
                self.positionChanged.emit(ms)
                if not self._is_stream:
                    self._check_preload(ms, self._duration_ms)
            if not self._is_stream:
                if ms == self._last_position_ms:
                    self._stall_ticks += 1
                    # Allow up to ~8s (160 ticks) before declaring stall; ASIO/WASAPI
                    # exclusive startup can take several seconds
                    if self._stall_ticks > 160 and ms < 500:
                        self._poll_timer.stop()
                        self.errorOccurred.emit(_("engine.stalled"))
                        self._app_state = PlaybackState.Stopped
                        self.stateChanged.emit(PlaybackState.Stopped)
                        self._stall_ticks = 0
                else:
                    self._stall_ticks = 0
                    self._last_position_ms = ms
        # Duration query — skip for streams (may return 0 or unreliable values)
        if not self._is_stream:
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
        if self._is_url(filepath):
            self._build_url_pipeline(filepath)
        else:
            self._build_pipeline(filepath)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.PAUSED)
        self.trackChanged.emit(filepath)

    def play(self):
        if not self._current_file:
            return
        if self._pipeline is None:
            if self._is_url(self._current_file):
                self._build_url_pipeline(self._current_file)
            else:
                self._build_pipeline(self._current_file)
        if self._pipeline is not None:
            # Check actual pipeline state, not tracked _app_state (may be stale)
            ok, state, pending = self._pipeline.get_state(0)
            if ok == Gst.StateChangeReturn.SUCCESS and state != Gst.State.PLAYING:
                self._pipeline.set_state(Gst.State.PLAYING)
            elif ok == Gst.StateChangeReturn.FAILURE:
                pass  # pipeline failed — don't try to play
            if not self._poll_timer.isActive():
                self._poll_timer.setInterval(50)
                self._poll_timer.start()

    def pause(self):
        if self._pipeline is not None and self._app_state == PlaybackState.Playing:
            self._pipeline.set_state(Gst.State.PAUSED)
            self._poll_timer.stop()
            self._app_state = PlaybackState.Paused
            self.stateChanged.emit(PlaybackState.Paused)

    def stop(self):
        self._poll_timer.stop()
        self._teardown_pipeline()
        if self._app_state != PlaybackState.Stopped:
            self._app_state = PlaybackState.Stopped
            self.stateChanged.emit(PlaybackState.Stopped)

    def toggle(self):
        if not self._current_file:
            self.errorOccurred.emit(_("engine.no_file"))
            return
        if self._app_state == PlaybackState.Playing:
            self.pause()
        else:
            self.play()

    def seek(self, position_ms: int):
        if self._pipeline is None:
            return
        # Live streams may not support seeking
        if self._is_stream and self._duration_ms <= 0:
            return
        target = max(0, min(position_ms, self._duration_ms))
        try:
            self._pipeline.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                target * 1000000
            )
        except Exception as e:
            import sys; print(f"[engine] seek 不支持: {e}", file=sys.stderr)

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
        if self._playbin is not None:
            self._playbin.set_property("volume", self._volume_level)
        elif self._volume_elem is not None:
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

    @property
    def replaygain_enabled(self) -> bool:
        return self._replaygain_enabled

    @replaygain_enabled.setter
    def replaygain_enabled(self, enabled: bool):
        if enabled == self._replaygain_enabled:
            return
        self._replaygain_enabled = enabled
        if self._current_file:
            pos = self._position_ms
            was_playing = self._app_state == PlaybackState.Playing
            self._build_pipeline(self._current_file)
            if self._pipeline is not None:
                target = Gst.State.PLAYING if was_playing else Gst.State.PAUSED
                self._pipeline.set_state(target)
                if pos > 0:
                    self.seek(pos)

    @property
    def gapless_enabled(self) -> bool:
        return self._gapless_enabled

    @gapless_enabled.setter
    def gapless_enabled(self, enabled: bool):
        if enabled == self._gapless_enabled:
            return
        self._gapless_enabled = enabled
        if not enabled:
            self._cleanup_preloaded()

    # ------------------------------------------------------------------
    #  Gapless playback
    # ------------------------------------------------------------------

    def _check_preload(self, position_ms: int, duration_ms: int):
        """Check if we should preload the next track for gapless transition."""
        if not self._gapless_enabled:
            return
        if self._preload_pipeline is not None:
            return  # already preloaded
        if duration_ms <= 4000 or position_ms < duration_ms - 2000:
            return  # not near the end yet
        # Get next track path from playlist (set externally by PlaybackController)
        next_path = getattr(self, '_gapless_next_path', None)
        if next_path:
            self._preload_next_track(next_path)

    def _preload_next_track(self, filepath: str):
        """Build the next track's pipeline in PAUSED state for gapless transition."""
        try:
            result = self._create_audio_pipeline(
                "audio-pipeline-gapless", filepath,
                self._on_preload_decodebin_pad_added,
            )
            if result is None:
                return

            pipeline, elems = result
            filesrc, decodebin, audio_queue, conv1, resample1, rgvolume, volume, eq, conv2, resample2, sink = elems

            self._preload_pipeline = pipeline
            self._preload_file = filepath
            self._preload_sink = sink
            self._preload_volume = volume
            self._preload_eq = eq
            self._preload_rgvolume = rgvolume
            self._preload_conv1 = conv1
            self._preload_audio_queue = audio_queue
            self._preload_filesrc = filesrc
            self._preload_decodebin = decodebin
            self._preload_audio_pad_linked = False

            ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
            self._preload_is_dsd = ext in ("dsf", "dff", "dsd")
            self._preload_sample_rate = 0
            self._preload_output_format = ""

            pipeline.set_state(Gst.State.PAUSED)

        except Exception as e:
            import sys; print(f"[engine] 预加载管道失败: {e}", file=sys.stderr)
            self._cleanup_preloaded()

    def _on_preload_decodebin_pad_added(self, decodebin, pad):
        """Pad-added handler for the preloaded pipeline's decodebin."""
        caps = pad.get_current_caps()
        if caps is None or self._preload_audio_queue is None:
            return
        struct = caps.get_structure(0)
        if struct is None or not struct.get_name().startswith("audio/"):
            return
        if self._preload_audio_pad_linked:
            return
        sink_pad = self._preload_audio_queue.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)
            self._preload_audio_pad_linked = True

    def _cleanup_preloaded(self):
        """Destroy the preloaded pipeline if it exists."""
        if self._preload_pipeline is not None:
            old = self._preload_pipeline
            self._preload_pipeline = None
            old.set_state(Gst.State.NULL)
            for _ in range(10):
                ok, state, _ = old.get_state(5 * Gst.MSECOND)
                if ok == Gst.StateChangeReturn.SUCCESS and state == Gst.State.NULL:
                    break
        self._preload_file = ""
        self._preload_sink = None
        self._preload_volume = None
        self._preload_eq = None
        self._preload_rgvolume = None
        self._preload_conv1 = None
        self._preload_audio_queue = None
        self._preload_filesrc = None
        self._preload_decodebin = None
        self._preload_audio_pad_linked = False
        self._preload_sample_rate = 0
        self._preload_output_format = ""
        self._preload_is_dsd = False

    def _gapless_transition(self):
        """Swap preloaded pipeline to active and start playing."""
        old_pipeline = self._pipeline
        # Swap all refs from preload to active
        self._pipeline = self._preload_pipeline
        self._sink = self._preload_sink
        self._volume_elem = self._preload_volume
        self._eq_elem = self._preload_eq
        self._rgvolume_elem = self._preload_rgvolume
        self._conv1 = self._preload_conv1
        self._audio_queue = self._preload_audio_queue
        self._filesrc = self._preload_filesrc
        self._decodebin = self._preload_decodebin
        self._audio_pad_linked = self._preload_audio_pad_linked
        self._current_file = self._preload_file
        self._pipeline_sample_rate = self._preload_sample_rate
        self._pipeline_output_format = self._preload_output_format
        self._source_is_dsd = self._preload_is_dsd
        # Clear preload refs without destroying the pipeline (it's now active)
        self._preload_pipeline = None
        self._preload_sink = None
        self._preload_volume = None
        self._preload_eq = None
        self._preload_rgvolume = None
        self._preload_conv1 = None
        self._preload_audio_queue = None
        self._preload_filesrc = None
        self._preload_decodebin = None
        # Tear down old pipeline
        if old_pipeline is not None:
            old_pipeline.set_state(Gst.State.NULL)
            for _ in range(10):
                ok, state, _ = old_pipeline.get_state(5 * Gst.MSECOND)
                if ok == Gst.StateChangeReturn.SUCCESS and state == Gst.State.NULL:
                    break
        # Reset position/duration for new track
        self._position_ms = 0
        self._duration_ms = 0
        self.positionChanged.emit(0)
        self.durationChanged.emit(0)
        self._stall_ticks = 0
        self._last_position_ms = -1
        # Start playing the new pipeline
        self._pipeline.set_state(Gst.State.PLAYING)
        self._app_state = PlaybackState.Playing
        self.stateChanged.emit(PlaybackState.Playing)
        self.trackChanged.emit(self._current_file)
        # Restart poll timer
        self._poll_timer.setInterval(50)
        self._poll_timer.start()

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
