from dataclasses import dataclass
from pathlib import Path
import struct
import hashlib
import os

# LRU cache: {filepath: (mtime, TrackMetadata)}
_metadata_cache: dict[str, tuple[float, TrackMetadata]] = {}
_CACHE_MAX = 512

# Cover art disk cache
_COVER_CACHE_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "VBPlayer" / "covers"
_COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cover_cache_path(filepath: str) -> Path:
    h = hashlib.sha256(filepath.encode("utf-8")).hexdigest()[:16]
    return _COVER_CACHE_DIR / f"{h}.jpg"


def _get_cached_cover(filepath: str) -> bytes | None:
    p = _cover_cache_path(filepath)
    if p.is_file():
        try:
            return p.read_bytes()
        except OSError:
            return None
    return None


def _put_cached_cover(filepath: str, data: bytes):
    try:
        _cover_cache_path(filepath).write_bytes(data)
    except OSError:
        pass


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


def read_stream_metadata(tags: dict) -> TrackMetadata:
    """Build TrackMetadata from GStreamer tag messages (ICY/HLS streams)."""
    meta = TrackMetadata()
    meta.title = tags.get("title", "") or tags.get("organization", "")
    meta.artist = tags.get("artist", "")
    meta.album = tags.get("album", "")
    meta.genre = tags.get("genre", "")
    meta.format = tags.get("audio-codec-name", "") or "Stream"
    try:
        meta.bitrate = int(tags.get("bitrate", 0)) // 1000
    except (ValueError, TypeError):
        pass
    return meta


def read_metadata(filepath: str) -> TrackMetadata:
    # URL streams — return minimal metadata (real metadata comes from GStreamer tags)
    if filepath.startswith(("http://", "https://", "smb://")):
        return TrackMetadata(title=filepath, format="Stream")

    path = Path(filepath)

    # Check cache — mtime-aware invalidation
    try:
        st = path.stat()
        mtime = st.st_mtime
    except OSError:
        mtime = 0.0

    cached = _metadata_cache.get(filepath)
    if cached and cached[0] == mtime:
        return cached[1]

    meta = TrackMetadata()
    try:
        meta.file_size = st.st_size
    except (OSError, NameError):
        meta.file_size = 0
    meta.title = path.stem
    suffix = path.suffix.lower()

    _mutagen_ok = False
    try:
        import mutagen
        _mutagen_ok = True
    except ImportError:
        import sys
        print("[metadata] mutagen not installed — metadata will be limited", file=sys.stderr)

    if _mutagen_ok:
        try:
            mf = mutagen.File(filepath)
            if mf is not None:
                _read_mutagen_meta(mf, meta, suffix)
        except ValueError as e:
            # Python 3.14 incompatibility — mutagen uses APIs that changed
            import sys
            if not getattr(read_metadata, '_warned_valueerror', False):
                print(f"[metadata] mutagen ValueError (Python 3.14 compat issue), "
                      f"using extension-based fallback: {e}", file=sys.stderr)
                read_metadata._warned_valueerror = True  # type: ignore
        except Exception as e:
            import sys
            print(f"[metadata] mutagen error for {filepath}: {type(e).__name__}: {e}", file=sys.stderr)

    # Fallback for WAV header
    if meta.duration_seconds == 0 and suffix == ".wav":
        _read_wav_header(filepath, meta)

    # Cover art: check disk cache first, skip all I/O if hit
    cached_cover = _get_cached_cover(filepath)
    if cached_cover:
        meta.cover_data = cached_cover
    elif not meta.cover_data:
        meta.cover_data = _find_cover_in_dir(path.parent)
    if meta.cover_data and not cached_cover:
        _put_cached_cover(filepath, meta.cover_data)

    if not meta.title:
        meta.title = path.stem
    if not meta.format:
        meta.format = suffix.lstrip(".").upper() if suffix else "?"

    # Evict oldest entry if cache is full
    if len(_metadata_cache) >= _CACHE_MAX:
        oldest_key = next(iter(_metadata_cache))
        del _metadata_cache[oldest_key]

    _metadata_cache[filepath] = (mtime, meta)
    return meta


def _evict_cache(filepath: str):
    _metadata_cache.pop(filepath, None)


def write_tags(filepath: str, tags: dict[str, str | int | None]) -> None:
    """Write metadata tags to an audio file via mutagen.

    *tags* keys match TrackMetadata field names:
        title, artist, album, album_artist, year, genre,
        track_number, disc_number

    Raises on failure (Unsupported format, permission error, etc.).
    """
    import mutagen
    from pathlib import Path

    mf = mutagen.File(filepath)
    if mf is None:
        raise ValueError(f"Unsupported audio format: {filepath}")

    suffix = Path(filepath).suffix.lower()

    # Determine tag family and build a {mutagen_key: value} mapping
    is_mp4 = suffix in (".m4a", ".aac", ".alac")
    is_id3 = suffix == ".mp3"

    # Field → mutagen key mapping (same keys as _tag_str)
    if is_mp4:
        key_map = {
            "title": "©nam", "artist": "©ART", "album": "©alb",
            "album_artist": "aART", "year": "©day", "genre": "©gen",
        }
    elif is_id3:
        key_map = {
            "title": "TIT2", "artist": "TPE1", "album": "TALB",
            "album_artist": "TPE2", "year": "TDRC", "genre": "TCON",
            "track_number": "TRCK", "disc_number": "TPOS",
        }
    else:
        # Vorbis (FLAC, OGG, Opus, APE, WavPack, etc.)
        key_map = {
            "title": "title", "artist": "artist", "album": "album",
            "album_artist": "albumartist", "year": "date", "genre": "genre",
            "track_number": "tracknumber", "disc_number": "discnumber",
        }

    # Ensure tags exist
    if mf.tags is None:
        try:
            mf.add_tags()
        except Exception:
            pass

    for field, value in tags.items():
        if field in ("track_number", "disc_number", "year"):
            # Integer fields
            if value is None or value == "":
                _tag_delete(mf, key_map.get(field, field), is_id3, is_mp4)
                continue
            try:
                int_val = int(value)
            except (ValueError, TypeError):
                continue
            if is_mp4:
                if field == "track_number":
                    mf.tags["trkn"] = [(int_val, 0)]
                elif field == "disc_number":
                    mf.tags["disk"] = [(int_val, 0)]
                else:
                    mf.tags[key_map[field]] = [str(int_val)]
            elif is_id3:
                _id3_set(mf, key_map[field], str(int_val))
            else:
                mf.tags[key_map[field]] = [str(int_val)]
        else:
            # String fields
            str_val = str(value).strip() if value else ""
            mkey = key_map.get(field)
            if not mkey:
                continue
            if not str_val:
                _tag_delete(mf, mkey, is_id3, is_mp4)
                continue
            if is_mp4:
                mf.tags[mkey] = [str_val]
            elif is_id3:
                _id3_set(mf, mkey, str_val)
            else:
                mf.tags[mkey] = [str_val]

    mf.save()
    _evict_cache(filepath)


def _id3_set(mf, frame_id: str, value: str):
    """Set an ID3 frame, updating existing or adding new."""
    import mutagen.id3
    frame_cls = getattr(mutagen.id3, frame_id, None)
    if frame_cls is None:
        return
    existing = mf.tags.get(frame_id)
    if existing:
        existing.text = [value]
    else:
        mf.tags.add(frame_cls(encoding=3, text=[value]))


def _tag_delete(mf, key: str, is_id3: bool, is_mp4: bool):
    """Delete a tag key if present."""
    try:
        if is_id3:
            if mf.tags and mf.tags.get(key):
                del mf.tags[key]
        elif is_mp4:
            if mf.tags and key in mf.tags:
                del mf.tags[key]
        else:
            if mf.tags and key in mf.tags:
                del mf.tags[key]
    except Exception:
        pass


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
        # ID3TimeStamp and similar objects expose .text
        if hasattr(val, 'text') and not isinstance(val, (str, bytes)):
            val = val.text
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


_COVER_NAMES = (
    "cover.jpg", "cover.png", "cover.jpeg", "cover.webp", "cover.bmp",
    "folder.jpg", "folder.png", "Folder.jpg", "Folder.png",
    "front.jpg", "front.png", "Front.jpg", "Front.png",
    "album.jpg", "album.png", "Album.jpg", "Album.png",
    "albumart.jpg", "albumart.png",
    "artwork.jpg", "artwork.png",
)


def _find_cover_in_dir(directory: Path) -> bytes | None:
    """Look for external cover image files in the given directory."""
    try:
        for name in _COVER_NAMES:
            p = directory / name
            try:
                if p.is_file():
                    return p.read_bytes()
            except OSError:
                continue
    except Exception:
        pass
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
