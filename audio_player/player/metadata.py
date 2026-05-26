from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass
class TrackMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: int | None = None
    genre: str = ""
    track_number: int | None = None
    disc_number: int | None = None
    duration_seconds: float = 0.0
    bitrate: int = 0
    sample_rate: int = 0
    bits_per_sample: int = 0
    channels: int = 0
    format: str = ""
    cover_data: bytes | None = None
    file_size: int = 0


def read_metadata(filepath: str) -> TrackMetadata:
    path = Path(filepath)
    meta = TrackMetadata()
    meta.file_size = path.stat().st_size
    meta.title = path.stem  # fallback

    suffix = path.suffix.lower()

    try:
        import mutagen
        mf = mutagen.File(filepath)
        if mf is not None:
            _read_mutagen_meta(mf, meta, suffix)
    except Exception:
        pass

    # Fallback for WAV header
    if meta.duration_seconds == 0 and suffix == ".wav":
        _read_wav_header(filepath, meta)

    if not meta.title:
        meta.title = path.stem
    if not meta.format:
        meta.format = suffix.lstrip(".").upper() if suffix else "?"

    return meta


def _read_mutagen_meta(mf, meta: TrackMetadata, suffix: str):
    info = getattr(mf, 'info', None)
    if info:
        meta.duration_seconds = getattr(info, 'length', 0) or 0
        meta.bitrate = getattr(info, 'bitrate', 0) or 0
        meta.sample_rate = getattr(info, 'sample_rate', 0) or 0
        meta.bits_per_sample = getattr(info, 'bits_per_sample', 0) or 0
        meta.channels = getattr(info, 'channels', 0) or 0

    fmt_map = {".mp3": "MP3", ".flac": "FLAC", ".ogg": "OGG", ".opus": "Opus",
               ".m4a": "AAC", ".aac": "AAC", ".wma": "WMA", ".aiff": "AIFF",
               ".ape": "APE", ".wv": "WavPack", ".spx": "Speex",
               ".dsf": "DSD", ".dff": "DSD"}
    meta.format = fmt_map.get(suffix, suffix.lstrip(".").upper())

    tags = {}
    if hasattr(mf, 'tags') and mf.tags:
        tags = mf.tags

    if tags:
        meta.title = _tag_str(tags, 'title', '©nam', 'TIT2') or meta.title
        meta.artist = _tag_str(tags, 'artist', '©ART', 'TPE1') or ""
        meta.album_artist = _tag_str(tags, 'albumartist', 'aART', 'TPE2') or ""
        meta.album = _tag_str(tags, 'album', '©alb', 'TALB') or ""
        meta.genre = _tag_str(tags, 'genre', '©gen', 'TCON') or ""
        year_s = _tag_str(tags, 'date', '©day', 'TDRC', 'TYER')
        if year_s:
            try:
                meta.year = int(year_s[:4])
            except ValueError:
                pass
        tn_s = _tag_str(tags, 'tracknumber', 'trkn', 'TRCK')
        if tn_s:
            try:
                meta.track_number = int(tn_s.split("/")[0])
            except ValueError:
                pass
        dn_s = _tag_str(tags, 'discnumber', 'disk', 'TPOS')
        if dn_s:
            try:
                meta.disc_number = int(dn_s.split("/")[0])
            except ValueError:
                pass

    # Cover art
    if hasattr(mf, 'pictures') and mf.pictures:
        meta.cover_data = mf.pictures[0].data
    elif tags:
        # Try APIC frame for MP3
        cover = _tag_bytes(tags, 'APIC:', 'APIC')
        if cover:
            meta.cover_data = cover


def _tag_str(tags, *keys) -> str:
    for key in keys:
        val = tags.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            val = val[0] if val else None
        if val is None:
            continue
        if hasattr(val, 'text'):
            val = val.text
            if isinstance(val, list):
                val = val[0] if val else None
        if isinstance(val, str):
            return val
        if isinstance(val, bytes):
            for enc in ('utf-8', 'latin-1', 'gbk'):
                try:
                    return val.decode(enc).rstrip('\x00')
                except (UnicodeDecodeError, LookupError):
                    pass
    return ""


def _tag_bytes(tags, *keys) -> bytes | None:
    for key in keys:
        val = tags.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            val = val[0] if val else None
        if val is None:
            continue
        if hasattr(val, 'data'):
            return val.data
        if isinstance(val, bytes):
            return val
    return None


def _read_wav_header(filepath: str, meta: TrackMetadata):
    try:
        with open(filepath, 'rb') as f:
            header = f.read(44)
            if len(header) < 44:
                return
            channels = struct.unpack_from('<H', header, 22)[0]
            sample_rate = struct.unpack_from('<I', header, 24)[0]
            byte_rate = struct.unpack_from('<I', header, 28)[0]
            bits_per_sample = struct.unpack_from('<H', header, 34)[0]
            data_size = struct.unpack_from('<I', header, 40)[0]
            meta.channels = channels
            meta.sample_rate = sample_rate
            meta.bits_per_sample = bits_per_sample
            meta.bitrate = int(byte_rate * 8 / 1000) if byte_rate else 0
            meta.format = "WAV"
            if byte_rate > 0 and data_size > 0:
                meta.duration_seconds = data_size / byte_rate
    except Exception:
        pass
