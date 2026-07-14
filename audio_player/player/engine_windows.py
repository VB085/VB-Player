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
    import audio_player.platform.windows.asio_bridge as _a
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
                # Skip — GStreamer's ASIO probe may corrupt driver state
                # (we use native COM backend instead)
                continue
                # name = props.get_string('asio.device.description') or d.get_display_name()
                # hw = f"asio:{clsid}" if clsid else ""
                # driver_tag = "ASIO"
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

        # Add ASIO devices from registry (GStreamer probe may corrupt driver)
        if _sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                     r"SOFTWARE\ASIO")
                i = 0
                while True:
                    try:
                        key_name = winreg.EnumKey(key, i)
                        sub = winreg.OpenKey(key, key_name)
                        clsid = winreg.QueryValueEx(sub, "CLSID")[0]  # the actual GUID
                        driver_name = winreg.QueryValueEx(sub, "Description")[0]
                        devices.append({
                            "card": len(devices),
                            "device": 0,
                            "hw": f"asio:{clsid}",
                            "name": driver_name,
                            "driver": "ASIO",
                            "api": "asio",
                        })
                        winreg.CloseKey(sub)
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass
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
        super().pause()

    def stop(self):
        super().stop()

    def play(self):
        if not self._current_file:
            return
        # ASIO: use GStreamer appsink pipeline + ASIO feed thread
        if getattr(self, '_is_asio_gst', False):
            # Start GStreamer pipeline
            if self._pipeline is not None:
                self._pipeline.set_state(Gst.State.PLAYING)
            # Start ASIO feed thread if not already running
            if not getattr(self, '_asio_started', False):
                if self._start_asio():
                    self._asio_started = True
                else:
                    # ASIO failed - fall back to standard pipeline
                    import sys as _s
                    print("[asio] Falling back to standard pipeline", file=_s.stderr)
                    self._is_asio_gst = False
                    self._teardown_pipeline()
                    # Rebuild as standard pipeline
                    if self._current_file:
                        self._build_pipeline(self._current_file)
                        if self._pipeline is not None:
                            self._pipeline.set_state(Gst.State.PLAYING)
                    return
            if not self._poll_timer.isActive():
                self._poll_timer.setInterval(50)
                self._poll_timer.start()
            return
        super().play()

    def _teardown_pipeline(self):
        self._kill_ffmpeg_proc()
        if getattr(self, '_is_asio_gst', False):
            self._stop_asio()
        self._asio_started = False
        self._is_asio_gst = False
        self._appsink = None
        super()._teardown_pipeline()

    def _poll(self):
        # For ASIO with GStreamer pipeline: use GStreamer's position query
        if getattr(self, '_is_asio_gst', False) and self._pipeline is not None:
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
            if self._duration_ms <= 0:
                ok, dur_ns = self._pipeline.query_duration(Gst.Format.TIME)
                if ok:
                    self._duration_ms = dur_ns // 1000000
                    self.durationChanged.emit(self._duration_ms)
            return
        super()._poll()

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
                # Wrap asiosink in a bin with audioconvert+resample+capsfilter→48kHz
                # Most ASIO drivers only support specific rates via GStreamer
                bin = Gst.Bin.new("asio-sink-bin")
                conv = Gst.ElementFactory.make("audioconvert", None)
                resample = Gst.ElementFactory.make("audioresample", None)
                capsf = Gst.ElementFactory.make("capsfilter", None)
                sink = Gst.ElementFactory.make("asiosink", None)
                if any(x is None for x in [conv, resample, capsf, sink]):
                    raise RuntimeError(_("engine.asio_unavailable"))
                capsf.set_property("caps", Gst.Caps.from_string("audio/x-raw,rate=48000"))
                sink.set_property("device-clsid", clsid)
                # Link bin elements
                ghost = Gst.GhostPad.new("sink", conv.get_static_pad("sink"))
                bin.add_pad(ghost)
                bin.add(conv); bin.add(resample); bin.add(capsf); bin.add(sink)
                conv.link(resample); resample.link(capsf); capsf.link(sink)
                return bin
            else:
                sink = Gst.ElementFactory.make("wasapi2sink", None)
                if sink is None:
                    raise RuntimeError(_("engine.wasapi_unavailable"))
                sink.set_property("exclusive", True)
                sink.set_property("low-latency", False)
                sink.set_property("buffer-time", 50000)
                sink.set_property("latency-time", 10000)
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

    # ── ASIO via GStreamer decodebin → appsink → threading.Thread ─────

    def _build_asio_gst_pipeline(self, filepath: str) -> bool:
        """Build GStreamer decodebin→appsink pipeline for ASIO output.

        GStreamer handles all decoding (verified clean with WASAPI).
        Python thread pulls from appsink → asio_write → ring buffer.
        """
        from audio_player.player.metadata import read_metadata
        import sys as _s

        self._teardown_pipeline()

        try:
            meta = read_metadata(filepath)
            target_rate = meta.sample_rate if meta.sample_rate > 0 else 44100
            duration_ms = int(meta.duration_seconds * 1000) if meta.duration_seconds > 0 else 0
        except Exception:
            target_rate = 44100; duration_ms = 0

        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        if ext in ("dsf", "dff"): target_rate = 88200

        pipeline = Gst.Pipeline.new("asio-gst-pipeline")
        try:
            filesrc = Gst.ElementFactory.make("filesrc", None)
            filesrc.set_property("location", filepath)
            decodebin = Gst.ElementFactory.make("decodebin", None)
            decodebin.connect("pad-added", self._on_decodebin_pad_added)
            queue = Gst.ElementFactory.make("queue", None)
            conv = Gst.ElementFactory.make("audioconvert", None)
            resample = Gst.ElementFactory.make("audioresample", None)
            volume = Gst.ElementFactory.make("volume", None)
            volume.set_property("volume", self._volume_level)
            eq = Gst.ElementFactory.make("equalizer-nbands", None)
            eq.set_property("num-bands", 10)
            for i, freq in enumerate(BAND_FREQUENCIES):
                band = eq.get_child_by_index(i)
                band.set_property("freq", float(freq))
                band.set_property("gain", self._eq_gains[i] if self._eq_enabled else 0.0)
            capsf = Gst.ElementFactory.make("capsfilter", None)
            appsink = Gst.ElementFactory.make("appsink", None)

            if any(x is None for x in [filesrc, decodebin, queue, conv, resample, volume, eq, capsf, appsink]):
                raise RuntimeError("GStreamer plugins missing")

            caps_str = f"audio/x-raw,format=F32LE,rate={target_rate},channels=2,layout=interleaved"
            capsf.set_property("caps", Gst.Caps.from_string(caps_str))
            appsink.set_property("caps", Gst.Caps.from_string(caps_str))
            appsink.set_property("sync", False)
            appsink.set_property("max-buffers", 4)
            appsink.set_property("drop", False)

            for e in [filesrc, decodebin, queue, conv, resample, volume, eq, capsf, appsink]:
                pipeline.add(e)
            filesrc.link(decodebin)
            queue.link(conv); conv.link(resample); resample.link(volume); volume.link(eq); eq.link(capsf); capsf.link(appsink)

            self._pipeline = pipeline
            self._appsink = appsink
            self._filesrc = filesrc; self._decodebin = decodebin
            self._audio_queue = queue; self._conv1 = conv
            self._sink = appsink; self._audio_pad_linked = False
            self._pipeline_sample_rate = target_rate
            self._pipeline_output_format = caps_str
            self._source_is_dsd = (ext in ("dsf", "dff"))
            self._duration_ms = duration_ms
            if duration_ms > 0: self.durationChanged.emit(duration_ms)
            self._is_asio_gst = True
            self._asio_bytes_total = 0
            self._volume_elem = volume
            self._eq_elem = eq
            return True
        except Exception as e:
            self._teardown_pipeline()
            self.errorOccurred.emit(str(e))
            return False

    def _start_asio(self) -> bool:
        """Open ASIO device and start GStreamer pipeline + feed thread."""
        hw = self._exclusive_device or ""
        if not hw.startswith("asio:"): return False
        clsid = hw[5:]
        rate = self._pipeline_sample_rate or 44100
        _a.asio_close()
        result = _a.asio_open(clsid, rate, self._asio_sample_type)
        if result is None:
            self.errorOccurred.emit(f"ASIO: failed to open at {rate}Hz")
            return False
        import sys as _s
        print(f"[asio] Opened at {rate}Hz, {result[0]}ch, buffer={result[1]}", file=_s.stderr)

        # Start GStreamer pipeline → PAUSED (preroll)
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.PLAYING)

        # Start feed thread (Python thread, not Qt/QTimer)
        import threading
        self._asio_stop = threading.Event()
        self._asio_thread = threading.Thread(target=self._asio_feed_thread, daemon=True)
        self._asio_thread.start()
        return True

    def _stop_asio(self):
        """Stop feed thread and close ASIO."""
        stop = getattr(self, '_asio_stop', None)
        if stop is not None: stop.set()
        t = getattr(self, '_asio_thread', None)
        if t is not None and t.is_alive(): t.join(timeout=2)
        self._asio_stop = None; self._asio_thread = None
        _a.asio_close()

    def _asio_feed_thread(self):
        """Feed thread: pull from GStreamer appsink, write to ASIO ring buffer."""
        import time
        appsink = self._appsink
        stop = self._asio_stop
        sample = None  # reduce GC pressure

        while not stop.is_set():
            if not _a._running: time.sleep(0.005); continue
            try:
                _a._rpos = _a.rpos()  # sync from callback cell (real-time rpos)
                bs = getattr(_a, '_bs', 2048)
                used = (_a._wpos - _a._rpos) % _a.RING_SAMPLES
                if used >= bs * 4:
                    time.sleep(0.002)
                    continue

                # Pull from appsink
                sample = appsink.emit("pull-sample")
                if sample is None:
                    time.sleep(0.005)
                    continue

                buf = sample.get_buffer()
                ok, info = buf.map(Gst.MapFlags.READ)
                if ok:
                    _a.asio_write(info.data)
                    buf.unmap(info)
            except Exception:
                time.sleep(0.01)

        # EOS handled by _poll timer (GStreamer bus message), not here.
        # Feed thread just waits for ASIO buffer to drain before closing.
        while _a._running and _a._wpos != _a._rpos:
            time.sleep(0.05)

    # ── Override _build_pipeline ───────────────────────────────────────

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

        self._is_asio_gst = True
        self._asio_bytes_total = 0
        return True

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

        # ASIO: GStreamer decodebin → appsink → thread → asio_write
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                self._build_asio_gst_pipeline(filepath)
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
