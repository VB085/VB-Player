import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstApp

from PyQt6.QtCore import QTimer

from audio_player.player.engine_base import _BaseAudioEngine, BAND_FREQUENCIES
from audio_player.player._types import PlaybackState
from audio_player.i18n import _
import sys as _sys
if _sys.platform == "win32":
    import audio_player.platform.windows.asio_backend as _a
else:
    _a = None  # Linux/macOS — no ASIO backend


def enumerate_hw_devices() -> list[dict]:
    """Enumerate audio render devices via GStreamer DeviceMonitor (WASAPI + ASIO)."""
    devices = []

    try:
        mon = Gst.DeviceMonitor()
        caps = Gst.Caps.from_string('audio/x-raw')
        mon.add_filter('Audio/Sink', caps)
        mon.start()

        _BUS_LABELS = {
            "USB": _("engine.bus_usb"),
            "BTHENUM": _("engine.bus_bluetooth"),
            "INTELAUDIO": _("engine.bus_builtin"),
            "TUSBAUDIO_ENUM": "USB Audio",
            "ROOT": _("engine.bus_virtual"),
        }

        for i, d in enumerate(mon.get_devices()):
            props = d.get_properties()
            api = props.get_string('device.api') or ''
            enumerator = props.get_string('device.enumerator-name') or ''
            device_id = props.get_value('device.id') or ''
            clsid = props.get_string('device.clsid') or ''

            if api == 'asio':
                name = props.get_string('asio.device.description') or d.get_display_name()
                hw = f"asio:{clsid}" if clsid else ""
                driver_tag = "ASIO"
            else:
                name = props.get_string('device.description') or d.get_display_name()
                if name and 'microphone' in name.lower():
                    continue
                hw = device_id
                driver_tag = "WASAPI"
                if enumerator:
                    bus_label = _BUS_LABELS.get(enumerator, enumerator)
                    driver_tag = f"WASAPI·{bus_label}"

            if not hw:
                continue

            devices.append({
                "card": i,
                "device": 0,
                "hw": hw,
                "name": name or f"Device {i}",
                "driver": driver_tag,
                "api": api,
            })

        mon.stop()
    except Exception as _e:
        import sys; print(f"[{__name__}] {_e}", file=sys.stderr)

    return devices if devices else [{"card": 0, "device": 0, "hw": "",
                                     "name": _("engine.default_device"), "driver": "WASAPI"}]


class AudioEngine(_BaseAudioEngine):
    """Windows audio engine — WASAPI2 + ASIO via GStreamer.

    Supports DSD playback via three paths:
      - gst-libav: avdemux_dsf → avdec_dsd_msbf (if plugins available)
      - Native DSD: direct DSD passthrough to ASIO/WASAPI sink (experimental)
      - ffmpeg fallback: external ffmpeg → appsrc (always available)
    """

    def _default_exclusive_device(self) -> str:
        return ""

    def pause(self):
        if getattr(self, '_is_asio_ffmpeg', False):
            # Stop feeding but keep ASIO open (ring buffer drains → silence)
            t = getattr(self, '_asio_feed_timer', None)
            if t is not None:
                t.stop()
            self._poll_timer.stop()
            self._app_state = PlaybackState.Paused
            self.stateChanged.emit(PlaybackState.Paused)
            return
        super().pause()

    def stop(self):
        if getattr(self, '_is_asio_ffmpeg', False):
            self._stop_asio()
            self._kill_ffmpeg_proc()
            super().stop()
            return
        super().stop()

    def play(self):
        if not self._current_file:
            return
        # ASIO ffmpeg path: no GStreamer pipeline
        if (self._exclusive_mode
                and (self._exclusive_device or "").startswith("asio:")):
            # Build ffmpeg pipe if first play after load
            if not getattr(self, '_is_asio_ffmpeg', False):
                self._build_asio_ffmpeg_pipe(self._current_file)
            elif getattr(self, '_ffmpeg_proc', None) is None:
                self._build_asio_ffmpeg_pipe(self._current_file)
            if not self._poll_timer.isActive():
                self._poll_timer.setInterval(50)
                self._poll_timer.start()
            if not getattr(self, '_asio_started', False):
                if self._start_asio():
                    self._asio_started = True
            else:
                # Resume from pause: restart feed timer
                t = getattr(self, '_asio_feed_timer', None)
                if t is not None and not t.isActive():
                    t.start()
            # Set state — base class requires Gst pipeline for this
            if self._app_state != PlaybackState.Playing:
                self._app_state = PlaybackState.Playing
                self.stateChanged.emit(PlaybackState.Playing)
            return
        # Standard GStreamer path
        super().play()

    def _teardown_pipeline(self):
        self._kill_ffmpeg_proc()
        self._stop_asio()
        self._asio_started = False
        self._is_asio_ffmpeg = False
        self._appsink = None
        super()._teardown_pipeline()

    def seek(self, position_ms: int):
        if getattr(self, '_is_asio_ffmpeg', False):
            self._seek_asio_ffmpeg(position_ms)
            return
        super().seek(position_ms)

    def _seek_asio_ffmpeg(self, position_ms: int):
        """Seek: restart ffmpeg with -ss, reopen ASIO."""
        filepath = self._current_file
        if not filepath:
            return
        self._stop_asio()
        self._kill_ffmpeg_proc()
        # Rebuild with seek offset
        import subprocess
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return
        rate = self._pipeline_sample_rate or 44100
        seek_sec = position_ms / 1000.0
        ffmpeg_cmd = [
            ffmpeg, "-ss", str(seek_sec), "-i", filepath,
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ar", str(rate), "-ac", "2",
            "-loglevel", "quiet",
            "pipe:1",
        ]
        try:
            self._ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception:
            return
        self._asio_bytes_total = position_ms * rate * 2 * 4 // 1000
        self._start_asio()

    def _cleanup_preloaded(self):
        """Kill any ffmpeg subprocess from the preloaded pipeline."""
        # The preloaded pipeline might have used the DSD ffmpeg fallback path
        # which spawns a subprocess. Kill it if present.
        if getattr(self, '_preload_ffmpeg_proc', None) is not None:
            try:
                self._preload_ffmpeg_proc.kill()
                self._preload_ffmpeg_proc.wait(timeout=3)
            except Exception as _e:
                import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
            self._preload_ffmpeg_proc = None
        super()._cleanup_preloaded()

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                clsid = hw[5:]
                sink = Gst.ElementFactory.make("asiosink", None)
                if sink is None:
                    raise RuntimeError(_("engine.asio_unavailable"))
                sink.set_property("device-clsid", clsid)
            else:
                sink = Gst.ElementFactory.make("wasapi2sink", None)
                if sink is None:
                    raise RuntimeError(_("engine.wasapi_unavailable"))
                sink.set_property("exclusive", True)
                sink.set_property("low-latency", True)
                sink.set_property("buffer-time", 10000)
                sink.set_property("latency-time", 3333)
                if hw:
                    sink.set_property("device", hw)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError(_("engine.auto_unavailable"))
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                return {
                    "name": hw,
                    "driver": _("engine.asio_driver"),
                    "mode": _("engine.asio_exclusive"),
                    "is_exclusive": True,
                    "api": "asio",
                    "latency": _("engine.asio_latency"),
                }
            return {
                "name": hw or _("engine.wasapi_default"),
                "driver": _("engine.wasapi_driver"),
                "mode": _("engine.low_latency"),
                "is_exclusive": True,
                "api": "wasapi",
                "latency": "buffer=10ms, latency≈3.3ms",
            }
        return {
            "name": _("output.system_default"),
            "driver": "WASAPI Shared",
            "mode": _("engine.shared_mode"),
            "is_exclusive": False,
            "api": "wasapi",
            "latency": _("engine.mixer_control"),
        }

    # ── DSD pipeline (native / DoP / PCM decode) ─────────────────────

    def _build_dsd_passthrough(self, filepath: str) -> bool:
        """Build native DSD passthrough pipeline using avdemux_dsf + dsdconvert.

        Raw DSD stream linked directly to the audio sink (ASIO/WASAPI exclusive).
        Falls back to PCM decode if any element is missing or caps negotiation fails.
        """
        pipeline = Gst.Pipeline.new("dsd-passthrough")

        def _fail():
            pipeline.set_state(Gst.State.NULL)
            return False

        try:
            filesrc = Gst.ElementFactory.make("filesrc", None)
            demux = Gst.ElementFactory.make("avdemux_dsf", None)
            dsdconv = Gst.ElementFactory.make("dsdconvert", None)
            queue = Gst.ElementFactory.make("queue", None)
            sink = self._create_sink()

            for elem in [filesrc, demux, dsdconv, queue, sink]:
                if elem is None:
                    return _fail()
                pipeline.add(elem)

            filesrc.link(demux)
            # demux → dsdconvert → queue → sink (all DSD caps, link in order)
            dsdconv.link(queue)
            queue.link(sink)

            # Store refs needed by _on_dsd_demux_pad for linking demux→dsdconvert
            self._dsd_demux = demux
            self._dsd_conv = dsdconv
            demux.connect("pad-added", self._on_dsd_demux_pad)

            self._teardown_pipeline()
            self._pipeline = pipeline
            self._sink = sink
            self._audio_queue = queue
            self._filesrc = filesrc
            self._decodebin = None
            self._audio_pad_linked = False
            return True

        except Exception as e:
            import sys; print(f"[engine] DSD 直通管道失败: {e}", file=sys.stderr)
            return _fail()

    def _on_dsd_demux_pad(self, demux, pad):
        caps = pad.get_current_caps()
        if caps is None:
            return
        struct = caps.get_structure(0)
        if struct is None or not struct.get_name().startswith("audio/"):
            return
        dsdconv_sink = self._dsd_conv.get_static_pad("sink")
        if dsdconv_sink and not dsdconv_sink.is_linked():
            pad.link(dsdconv_sink)

    def _build_dsd_pcm_pipeline(self, filepath: str) -> bool:
        """Manual DSD→PCM pipeline for DSF files with rate capping.

        Uses avdemux_dsf → avdec_dsd_msbf → capsfilter(max 768kHz) →
        audioresample → standard processing chain. Bypasses decodebin to avoid
        issues with ultra-high decoded PCM rates (e.g. DSD512 → 2.8 MHz PCM).
        """
        self._teardown_pipeline()

        try:
            pipeline = Gst.Pipeline.new("audio-pipeline")

            filesrc = Gst.ElementFactory.make("filesrc", None)
            filesrc.set_property("location", filepath)

            demux = Gst.ElementFactory.make("avdemux_dsf", None)
            if demux is None:
                return False

            # Verify decoder is available before building pipeline
            if Gst.ElementFactory.make("avdec_dsd_msbf", None) is None:
                return False

            audio_queue = Gst.ElementFactory.make("queue", None)
            if audio_queue is not None:
                audio_queue.set_property("max-size-time", 2 * Gst.SECOND)
                audio_queue.set_property("max-size-buffers", 0)
                audio_queue.set_property("max-size-bytes", 0)

            # Cap decoded PCM to 768 kHz max to prevent ultra-high rates from
            # DSD512 (which decodes to ~2.8 MHz PCM) blowing up downstream
            capsfilter = Gst.ElementFactory.make("capsfilter", None)
            if capsfilter is not None:
                capsfilter.set_property("caps",
                    Gst.Caps.from_string("audio/x-raw, rate=(int)[1, 768000]"))

            resample = Gst.ElementFactory.make("audioresample", None)
            if resample is not None:
                resample.set_property("quality", 10)
            conv1 = Gst.ElementFactory.make("audioconvert", None)
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
                return False

            elems = [filesrc, demux, audio_queue, capsfilter, resample, conv1]
            if rgvolume is not None:
                elems.append(rgvolume)
            elems.extend([volume, eq, conv2, resample2, sink])
            for elem in elems:
                if elem is None:
                    return False
                pipeline.add(elem)

            filesrc.link(demux)
            # demux uses dynamic pad-added → decoder → audio_queue
            audio_queue.link(capsfilter)
            capsfilter.link(resample)
            resample.link(conv1)
            if rgvolume is not None:
                conv1.link(rgvolume)
                rgvolume.link(volume)
            else:
                conv1.link(volume)
            volume.link(eq)
            eq.link(conv2)
            conv2.link(resample2)
            resample2.link(sink)

            # Store refs for _on_dsd_pcm_pad
            self._dsd_demux = demux
            self._dsd_audio_queue = audio_queue
            demux.connect("pad-added", self._on_dsd_pcm_pad)

            self._pipeline = pipeline
            self._volume_elem = volume
            self._eq_elem = eq
            self._conv1 = conv1
            self._audio_queue = audio_queue
            self._filesrc = filesrc
            self._decodebin = None
            self._sink = sink
            self._audio_pad_linked = False
            self._pipeline_sample_rate = 0
            self._pipeline_output_format = ""

            return True

        except Exception as e:
            import sys; print(f"[engine] DSD PCM 管道失败: {e}", file=sys.stderr)
            self._teardown_pipeline()
            return False

    def _on_dsd_pcm_pad(self, demux, pad):
        """Pad-added from avdemux_dsf — insert decoder, link to audio_queue."""
        caps = pad.get_current_caps()
        if caps is None or self._audio_pad_linked:
            return
        struct = caps.get_structure(0)
        if struct is None or not struct.get_name().startswith("audio/"):
            return

        decoder = Gst.ElementFactory.make("avdec_dsd_msbf", None)
        if decoder is None:
            return

        self._pipeline.add(decoder)
        decoder_sink = decoder.get_static_pad("sink")
        queue_sink = self._dsd_audio_queue.get_static_pad("sink")
        if decoder_sink is None or queue_sink is None:
            return
        if decoder_sink.is_linked() or queue_sink.is_linked():
            return

        pad.link(decoder_sink)
        decoder.sync_state_with_parent()
        decoder_src = decoder.get_static_pad("src")
        if decoder_src:
            decoder_src.link(queue_sink)
            self._audio_pad_linked = True

    # ── DSD ffmpeg fallback (appsrc pipeline) ────────────────────────

    @staticmethod
    def _find_ffmpeg() -> str | None:
        import shutil
        import os as _os

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        candidates = [
            _os.path.join("C:", _os.sep, "msys64", "mingw64", "bin", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("APPDATA", ""), "bilibili", "ffmpeg", "ffmpeg.exe"),
            _os.path.join(_os.environ.get("ProgramFiles", ""), "ffmpeg", "bin", "ffmpeg.exe"),
        ]
        for p in candidates:
            if _os.path.isfile(p):
                return p
        return None

    def _build_dsd_ffmpeg_fallback(self, filepath: str) -> bool:
        """Stream DSD→PCM via external ffmpeg + GStreamer appsrc.

        The feed thread waits for the pipeline to reach PLAYING state
        before pushing buffers, avoiding the appsrc race condition.
        """
        import subprocess
        import os
        import threading

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            return False

        self._teardown_pipeline()

        # Use 88.2 kHz (2×44.1k) — clean integer ratio for all DSD rates
        target_rate = 88200

        ffmpeg_cmd = [
            ffmpeg, "-i", filepath,
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ar", str(target_rate), "-ac", "2",
            "-loglevel", "quiet",
            "pipe:1",
        ]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except Exception as e:
            import sys; print(f"[engine] ffmpeg 启动失败: {e}", file=sys.stderr)
            return False

        pipeline = Gst.Pipeline.new("dsd-ffmpeg-pipeline")

        appsrc = Gst.ElementFactory.make("appsrc", None)
        if appsrc is None:
            self._ffmpeg_proc.kill()
            self._ffmpeg_proc = None
            return False

        caps_str = (f"audio/x-raw,format=F32LE,rate={target_rate},"
                    f"channels=2,layout=interleaved")
        appsrc.set_property("caps", Gst.Caps.from_string(caps_str))
        appsrc.set_property("format", Gst.Format.TIME)
        appsrc.set_property("is-live", False)
        appsrc.set_property("do-timestamp", True)
        appsrc.set_property("max-bytes", 65536 * 4)

        audio_queue = Gst.ElementFactory.make("queue", None)
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
        if eq is not None:
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
            self._ffmpeg_proc.kill()
            self._ffmpeg_proc = None
            return False

        elems = [appsrc, audio_queue, conv1, resample1]
        if rgvolume is not None:
            elems.append(rgvolume)
        elems.extend([volume, eq, conv2, resample2, sink])
        for elem in elems:
            if elem is None:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc = None
                return False
            pipeline.add(elem)

        appsrc.link(audio_queue)
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

        # Feed thread — gated: waits for pipeline PLAYING before pushing
        stop_flag = threading.Event()
        playing_event = threading.Event()

        def _feed_loop():
            # Wait until pipeline reaches PLAYING state (signaled by _poll)
            if not playing_event.wait(timeout=10):
                # Timeout — pipeline never reached PLAYING
                appsrc.emit("end-of-stream")
                return
            chunk_size = 65536
            while not stop_flag.is_set():
                data = self._ffmpeg_proc.stdout.read(chunk_size)
                if not data:
                    break
                buf = Gst.Buffer.new_allocate(len(data))
                buf.fill(0, data)
                ret = appsrc.emit("push-buffer", buf)
                if ret != Gst.FlowReturn.OK:
                    break
            appsrc.emit("end-of-stream")

        self._ffmpeg_stop_flag = stop_flag
        self._ffmpeg_playing_event = playing_event
        self._ffmpeg_thread = threading.Thread(target=_feed_loop, daemon=True)
        self._ffmpeg_thread.start()

        self._pipeline = pipeline
        self._volume_elem = volume
        self._eq_elem = eq
        self._conv1 = conv1
        self._audio_queue = audio_queue
        self._filesrc = None
        self._decodebin = None
        self._sink = sink
        self._audio_pad_linked = True

        self._pipeline_sample_rate = target_rate
        self._pipeline_output_format = caps_str

        return True

    def _handle_message(self, msg):
        super()._handle_message(msg)
        # Signal the ffmpeg feed thread once pipeline reaches PLAYING
        if (msg.type == Gst.MessageType.STATE_CHANGED
                and isinstance(msg.src, Gst.Pipeline)
                and self._ffmpeg_playing_event is not None):
            old, new, pending = msg.parse_state_changed()
            if new == Gst.State.PLAYING:
                self._ffmpeg_playing_event.set()

    def _kill_ffmpeg_proc(self):
        if getattr(self, '_ffmpeg_proc', None) is not None:
            if getattr(self, '_ffmpeg_stop_flag', None) is not None:
                self._ffmpeg_stop_flag.set()
            # Unblock feed thread if it's still waiting for PLAYING
            if getattr(self, '_ffmpeg_playing_event', None) is not None:
                self._ffmpeg_playing_event.set()
            try:
                self._ffmpeg_proc.stdout.close()
            except Exception as _e:
                import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
            try:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=3)
            except Exception as _e:
                import sys; print(f"[{__name__}] {_e}", file=sys.stderr)
            self._ffmpeg_proc = None
            self._ffmpeg_stop_flag = None
            self._ffmpeg_playing_event = None

    # ── ASIO: ffmpeg → pipe → asio_write (zero GStreamer threads) ────

    def _build_asio_ffmpeg_pipe(self, filepath: str) -> bool:
        """Decode audio via ffmpeg → asio_write (no GStreamer at all).

        ffmpeg subprocess stdout → QTimer reads → asio_write → ring buffer.
        Duration from metadata, position from byte counting.
        """
        import subprocess
        from audio_player.player.metadata import read_metadata

        self._teardown_pipeline()

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            self.errorOccurred.emit(_("engine.ffmpeg_not_found"))
            return False

        # Read metadata for duration
        try:
            meta = read_metadata(filepath)
            duration_ms = int(meta.duration_seconds * 1000) if meta.duration_seconds > 0 else 0
        except Exception:
            duration_ms = 0

        # Force 44100 — same as verified standalone beep test
        target_rate = 44100
        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""

        # Build ffmpeg command — explicit format, no stdin interaction
        ffmpeg_cmd = [
            ffmpeg, "-nostdin", "-i", filepath,
            "-f", "f32le",
            "-ar", str(target_rate), "-ac", "2",
            "-loglevel", "error",
            "pipe:1",
        ]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Drain stderr after 500ms to catch ffmpeg errors
            QTimer.singleShot(500, lambda: self._check_ffmpeg_errors())
        except Exception as e:
            import sys as _s; print(f"[asio] ffmpeg start failed: {e}", file=_s.stderr)
            return False

        # No GStreamer pipeline needed — use metadata for duration
        self._pipeline = None
        self._current_file = filepath
        self._pipeline_sample_rate = target_rate
        self._pipeline_output_format = f"F32LE,{target_rate}Hz,stereo"
        self._source_is_dsd = (ext in ("dsf", "dff"))
        self._duration_ms = duration_ms
        if duration_ms > 0:
            self.durationChanged.emit(duration_ms)

        self._is_asio_ffmpeg = True
        self._asio_bytes_total = 0
        return True

    # ── ASIO Lifecycle ────────────────────────────────────────────────

    def _start_asio(self) -> bool:
        """Open ASIO device and start the PCM feed timer."""
        hw = self._exclusive_device or ""
        if not hw.startswith("asio:"):
            return False
        clsid = hw[5:]
        rate = self._pipeline_sample_rate or 44100

        _a.asio_close()
        result = _a.asio_open(clsid, rate)
        if result is None:
            self.errorOccurred.emit(
                _("engine.asio_open_failed", rate=rate, clsid=clsid[:12]))
            return False

        channels, buf_size = result
        import sys as _s
        print(f"[asio] Opened {clsid[:12]}... at {rate}Hz, "
              f"{channels}ch, buffer={buf_size}", file=_s.stderr)

        # TEST: pre-fill ring buffer with 440Hz beep before starting feed
        # (standalone test pattern: write data → callback plays it)
        import math, struct as _st
        ns = _a.RING_SAMPLES // 4  # fill quarter = ~1.5s at 44.1kHz
        data = bytearray(ns * _a._ch * 4)
        phase = 0.0
        for i in range(ns):
            val = math.sin(phase) * 0.3
            _st.pack_into('<f', data, i * 8, val)       # L
            _st.pack_into('<f', data, i * 8 + 4, val)   # R
            phase += 2.0 * math.pi * 440.0 / rate
        _a.asio_write(bytes(data))
        print(f"[asio] pre-filled {ns} beep frames, wpos={_a._wpos}", file=_s.stderr)

        t = getattr(self, '_asio_feed_timer', None)
        if t is None:
            t = QTimer(self)
            t.timeout.connect(self._asio_feed)
            self._asio_feed_timer = t
        t.setInterval(15)  # ~66Hz — faster response, avoids buffer drain
        t.start()
        return True

    def _check_ffmpeg_errors(self):
        """Read ffmpeg stderr for any error messages."""
        proc = getattr(self, '_ffmpeg_proc', None)
        if proc is None:
            return
        try:
            import select, sys as _s
            import os as _os
            # Non-blocking read of stderr
            fd = proc.stderr.fileno()
            if fd >= 0:
                _os.set_blocking(fd, False)
            err = proc.stderr.read()
            if err:
                _s.stderr.write(f"[ffmpeg-err] {err.decode('utf-8', errors='replace')}\n")
                _s.stderr.flush()
        except Exception:
            pass

    def _stop_asio(self):
        """Stop ASIO feed timer and close device."""
        t = getattr(self, '_asio_feed_timer', None)
        if t is not None:
            t.stop()
            self._asio_feed_timer = None

        _a.asio_close()

    def _asio_feed(self):
        """Read PCM from ffmpeg stdout, write to ASIO ring buffer (throttled)."""
        if getattr(self, '_ffmpeg_proc', None) is None:
            return

        if not _a._running:
            return

        try:
            # Keep ring buffer well ahead of ASIO consumption
            bs = getattr(_a, '_bs', 2048)
            target = bs * 6
            used = (_a._wpos - _a._rpos) % _a.RING_SAMPLES
            if used >= target:
                return
            want_samples = target - used + bs
            max_bytes = want_samples * _a._ch * 4

            data = self._ffmpeg_proc.stdout.read(min(max_bytes, 65536))
            if not data:
                self._ffmpeg_proc = None
                return

            # DUMP: save raw F32LE as 16-bit PCM WAV for verification
            _dump_total = getattr(self, '_asio_dump_total', 0)
            _dump_max = 256 * 1024
            if _dump_total < _dump_max:
                if not hasattr(self, '_asio_dump_buf'):
                    self._asio_dump_buf = bytearray()
                self._asio_dump_buf.extend(data)
                _dump_total += len(data)
                self._asio_dump_total = _dump_total
                if _dump_total >= _dump_max:
                    import struct as _st, os, array as _arr
                    buf = bytes(self._asio_dump_buf)
                    # F32LE → S16LE
                    f32 = _arr.array('f')
                    f32.frombytes(buf)
                    s16 = _arr.array('h', (int(max(-1., min(1., s)) * 32767) for s in f32))
                    wav_data = s16.tobytes()
                    data_len = len(wav_data)
                    rate = self._pipeline_sample_rate or 44100
                    wav = bytearray(44 + data_len)
                    wav[0:4] = b'RIFF'
                    _st.pack_into('<I', wav, 4, 36 + data_len)
                    wav[8:16] = b'WAVEfmt '
                    _st.pack_into('<I', wav, 16, 16)
                    _st.pack_into('<H', wav, 20, 1)
                    _st.pack_into('<H', wav, 22, 2)
                    _st.pack_into('<I', wav, 24, rate)
                    _st.pack_into('<I', wav, 28, rate * 4)
                    _st.pack_into('<H', wav, 32, 4)
                    _st.pack_into('<H', wav, 34, 16)
                    wav[36:40] = b'data'
                    _st.pack_into('<I', wav, 40, data_len)
                    wav[44:] = wav_data
                    desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop')
                    with open(os.path.join(desktop, 'asio_dump.wav'), 'wb') as f:
                        f.write(bytes(wav))
                    import sys as _s
                    print(f"[asio] WAV: Desktop/asio_dump.wav", file=_s.stderr)

            _a.asio_write(data)
            # Track position (deferred)
            rate = self._pipeline_sample_rate or 44100
            self._asio_bytes_total = getattr(self, '_asio_bytes_total', 0) + len(data)
            pos_ms = int(self._asio_bytes_total / (rate * 2 * 4) * 1000)
            if abs(pos_ms - self._position_ms) > 200:
                self._position_ms = pos_ms
                QTimer.singleShot(0, lambda p=pos_ms: self.positionChanged.emit(p))

            if (getattr(self, '_ffmpeg_proc', None) is None
                    and _a._wpos == _a._rpos):
                self.trackFinished.emit()
        except Exception:
            pass

    def _poll(self):
        if getattr(self, '_is_asio_ffmpeg', False):
            # ASIO ffmpeg: position tracked in _asio_feed via byte counting.
            # Duration already set from metadata in _build_asio_ffmpeg_pipe.
            # No GStreamer pipeline to query.
            return
        super()._poll()

    # ── Override _build_pipeline to add DSD support + ASIO native ─────

    def _build_pipeline(self, filepath: str):
        # URL streams — delegate to base class playbin pipeline
        if self._is_url(filepath):
            self._build_url_pipeline(filepath)
            return

        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        is_dsd = ext in ("dsf", "dff")
        self._source_is_dsd = is_dsd

        # DSD passthrough (native / DoP) — exclusive mode only
        if is_dsd and self._dsd_decode_mode in ("native", "dop") and self._exclusive_mode:
            if self._build_dsd_passthrough(filepath):
                return
            self._dsd_decode_mode = "pcm"

        # Manual DSD→PCM (bypasses decodebin, caps max rate at 768kHz)
        if is_dsd:
            if self._build_dsd_pcm_pipeline(filepath):
                return

        # DSD ffmpeg fallback — pipe DSD→PCM via external ffmpeg + appsrc
        if is_dsd:
            if self._build_dsd_ffmpeg_fallback(filepath):
                return
            import sys
            print("[engine] DSD playback requires ffmpeg with DSD support", file=sys.stderr)

        # ASIO: ffmpeg pipe → asio_write (zero GStreamer threads)
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                self._build_asio_ffmpeg_pipe(filepath)
                return

        # Standard PCM pipeline (decodebin-based, used for non-DSD files)
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
                raise RuntimeError(_("engine.gst_unavailable"))

            for elem in [filesrc, decodebin, audio_queue, conv1, resample1, volume, eq, conv2, resample2, sink]:
                if elem is None:
                    raise RuntimeError(_("engine.gst_plugins_missing"))
                pipeline.add(elem)

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

            self._pipeline_sample_rate = 0
            self._pipeline_output_format = ""

        except Exception as e:
            self._teardown_pipeline()
            self.errorOccurred.emit(str(e))
