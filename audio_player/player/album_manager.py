from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class AlbumInfo:
    name: str
    artist: str
    cover_path: str = ""
    cover_data: bytes | None = None
    tracks: list = field(default_factory=list)  # list of (row_index, filepath) tuples
    year: int | None = None
    disc_count: int = 1
    total_duration: float = 0.0
    formats: str = ""
    track_count: int = 0
    total_size: int = 0


class AlbumManager:
    def group_by_album(self, tracks: list[dict], read_missing: bool = True) -> list[AlbumInfo]:
        """Group tracks by (album, artist). Falls back to folder grouping.

        *read_missing*=False skips tracks whose metadata hasn't loaded yet
        (they group by folder name, no disk I/O) — used during the startup
        incremental refresh so the GUI thread never blocks on reads.
        """
        from audio_player.player.metadata import read_metadata

        # Phase 1: group by (album_name, album_artist)
        groups: dict[tuple[str, str], list[tuple[int, str, dict]]] = {}
        for i, t in enumerate(tracks):
            filepath = t.get("path", "")
            meta = t.get("metadata")
            if meta is None and filepath and read_missing:
                meta = read_metadata(filepath)

            album = (meta.album or "") if meta else ""
            # Use album_artist for grouping, fall back to track artist
            album_artist = (meta.album_artist or meta.artist or "") if meta else ""

            if not album:
                folder = os.path.basename(os.path.dirname(filepath)) if filepath else "Unknown"
                album = folder or "Unknown"

            key = (album.strip(), album_artist.strip())
            if key not in groups:
                groups[key] = []
            # Store (index, filepath, metadata_object_or_None)
            groups[key].append((i, filepath, meta))

        # Phase 2: build AlbumInfo for each group
        albums: list[AlbumInfo] = []
        for (album_name, album_artist), items in groups.items():
            # Sort by disc_number then track_number
            def sort_key(item):
                _, _, m = item
                dn = getattr(m, 'disc_number', None) if m else None
                tn = getattr(m, 'track_number', None) if m else None
                return ((dn or 1) * 10000) + (tn or 0)
            items.sort(key=sort_key)

            info = AlbumInfo(name=album_name, artist=album_artist)

            # Determine disc count
            discs: set[int] = set()
            total_dur = 0.0
            formats_seen: set[str] = set()
            cover_data = None
            cover_path = ""
            year = None

            first_meta = None
            first_fp = ""
            for idx, fp, meta in items:
                if meta:
                    if first_meta is None:
                        first_meta, first_fp = meta, fp
                    if meta.cover_data:
                        cover_data = meta.cover_data
                        cover_path = fp
                    if meta.year:
                        year = year or meta.year
                    if meta.disc_number:
                        discs.add(meta.disc_number)
                    total_dur += meta.duration_seconds or 0
                    if meta.format:
                        formats_seen.add(meta.format)
                    info.total_size += meta.file_size or 0
                info.tracks.append((idx, fp))

            # lazy covers: bulk loads skip cover bytes — fetch the album
            # cover for the card only on final/full refreshes (bounded: one
            # read per album; incremental passes show placeholders)
            if not cover_data and first_meta is not None and read_missing:
                from audio_player.player.metadata import ensure_cover
                ensure_cover(first_fp, first_meta)
                if first_meta.cover_data:
                    cover_data = first_meta.cover_data
                    cover_path = first_fp

            info.disc_count = max(len(discs), 1)
            info.total_duration = total_dur
            info.track_count = len(items)
            info.formats = " / ".join(sorted(formats_seen)) if formats_seen else ""
            info.cover_data = cover_data
            info.cover_path = cover_path
            info.year = year

            albums.append(info)

        # Sort albums by name
        albums.sort(key=lambda a: a.name.lower())
        return albums
