import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from audio_player.player.engine_base import _BaseAudioEngine, BAND_FREQUENCIES


def enumerate_hw_devices() -> list[dict]:
    """Enumerate audio render devices via GStreamer DeviceMonitor (WASAPI + ASIO)."""
    devices = []

    try:
        mon = Gst.DeviceMonitor()
        caps = Gst.Caps.from_string('audio/x-raw')
        mon.add_filter('Audio/Sink', caps)
        mon.start()

        _BUS_LABELS = {
            "USB": "USB",
            "BTHENUM": "蓝牙",
            "INTELAUDIO": "内置",
            "TUSBAUDIO_ENUM": "USB Audio",
            "ROOT": "虚拟",
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
    except Exception:
        pass

    return devices if devices else [{"card": 0, "device": 0, "hw": "",
                                     "name": "默认设备 (WASAPI Shared)", "driver": "WASAPI"}]


class AudioEngine(_BaseAudioEngine):
    """Windows audio engine — WASAPI2 + ASIO via GStreamer.

    Supports DSD playback via three paths:
      - gst-libav: avdemux_dsf → avdec_dsd_msbf (if plugins available)
      - Native DSD: direct DSD passthrough to ASIO/WASAPI sink (experimental)
      - ffmpeg fallback: external ffmpeg → appsrc (always available)
    """

    def _default_exclusive_device(self) -> str:
        return ""

    def _teardown_pipeline(self):
        self._kill_ffmpeg_proc()
        super()._teardown_pipeline()

    def _create_sink(self) -> Gst.Element:
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                clsid = hw[5:]
                sink = Gst.ElementFactory.make("asiosink", None)
                if sink is None:
                    raise RuntimeError("asiosink 不可用 — 请安装 GStreamer ASIO 插件")
                sink.set_property("device-clsid", clsid)
            else:
                sink = Gst.ElementFactory.make("wasapi2sink", None)
                if sink is None:
                    raise RuntimeError("wasapi2sink 不可用 — 请安装 GStreamer WASAPI 插件")
                sink.set_property("low-latency", True)
                sink.set_property("buffer-time", 10000)
                sink.set_property("latency-time", 3333)
                if hw:
                    sink.set_property("device", hw)
        else:
            sink = Gst.ElementFactory.make("autoaudiosink", None)
            if sink is None:
                raise RuntimeError("autoaudiosink 不可用")
        return sink

    def _output_info_dict(self) -> dict:
        if self._exclusive_mode:
            hw = self._exclusive_device or ""
            if hw.startswith("asio:"):
                return {
                    "name": hw,
                    "driver": "ASIO (低延迟模式)",
                    "mode": "ASIO 独占",
                    "is_exclusive": True,
                    "api": "asio",
                    "latency": "ASIO 驱动决定",
                }
            return {
                "name": hw or "WASAPI 默认设备",
                "driver": "WASAPI (低延迟模式)",
                "mode": "低延迟模式 (Low-Latency)",
                "is_exclusive": True,
                "api": "wasapi",
                "latency": "buffer=10ms, latency≈3.3ms",
            }
        return {
            "name": "系统默认",
            "driver": "WASAPI Shared",
            "mode": "共享模式 (Shared)",
            "is_exclusive": False,
            "api": "wasapi",
            "latency": "系统混音器控制",
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

        except Exception:
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

            elems = [filesrc, demux, audio_queue, capsfilter, resample, conv1,
                     volume, eq, conv2, resample2, sink]
            for elem in elems:
                if elem is None:
                    return False
                pipeline.add(elem)

            filesrc.link(demux)
            # demux uses dynamic pad-added → decoder → audio_queue
            audio_queue.link(capsfilter)
            capsfilter.link(resample)
            resample.link(conv1)
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

        except Exception:
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
        """Stream DSD→PCM via external ffmpeg + GStreamer appsrc."""
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
        except Exception:
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

        elems = [appsrc, audio_queue, conv1, resample1, volume, eq, conv2, resample2, sink]
        for elem in elems:
            if elem is None:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc = None
                return False
            pipeline.add(elem)

        appsrc.link(audio_queue)
        audio_queue.link(conv1)
        conv1.link(resample1)
        resample1.link(volume)
        volume.link(eq)
        eq.link(conv2)
        conv2.link(resample2)
        resample2.link(sink)

        # Feed thread
        stop_flag = threading.Event()

        def _feed_loop():
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

    def _kill_ffmpeg_proc(self):
        if getattr(self, '_ffmpeg_proc', None) is not None:
            if getattr(self, '_ffmpeg_stop_flag', None) is not None:
                self._ffmpeg_stop_flag.set()
            try:
                self._ffmpeg_proc.stdout.close()
            except Exception:
                pass
            try:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=3)
            except Exception:
                pass
            self._ffmpeg_proc = None
            self._ffmpeg_stop_flag = None

    # ── Override _build_pipeline to add DSD support ──────────────────

    def _build_pipeline(self, filepath: str):
        ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
        is_dsd = ext in ("dsf", "dff")
        self._source_is_dsd = is_dsd

        # DSD passthrough (native / DoP) — exclusive mode only
        if is_dsd and self._dsd_decode_mode in ("native", "dop") and self._exclusive_mode:
            if self._build_dsd_passthrough(filepath):
                return
            self._dsd_decode_mode = "pcm"

        # Manual DSD→PCM for DSF (bypasses decodebin, caps max rate at 768kHz)
        if ext == "dsf":
            if self._build_dsd_pcm_pipeline(filepath):
                return

        # DSD ffmpeg fallback — pipe DSD→PCM via external ffmpeg + appsrc
        if is_dsd:
            if self._build_dsd_ffmpeg_fallback(filepath):
                return
            import sys
            print("[engine] DSD playback requires ffmpeg with DSD support", file=sys.stderr)

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
                raise RuntimeError("GStreamer 音频输出不可用")

            for elem in [filesrc, decodebin, audio_queue, conv1, resample1, volume, eq, conv2, resample2, sink]:
                if elem is None:
                    raise RuntimeError("GStreamer 插件缺失，无法创建音频管道")
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
