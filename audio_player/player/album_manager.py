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
    def group_by_album(self, tracks: list[dict]) -> list[AlbumInfo]:
        """Group tracks by (album, artist). Falls back to folder grouping."""
        from audio_player.player.metadata import read_metadata

        # Phase 1: group by (album_name, album_artist)
        groups: dict[tuple[str, str], list[tuple[int, str, dict]]] = {}
        for i, t in enumerate(tracks):
            filepath = t.get("path", "")
            meta = t.get("metadata")
            if meta is None and filepath:
                meta = read_metadata(filepath)

            album = (meta.album or "") if meta else ""
            artist = (meta.artist or meta.album_artist or "") if meta else ""

            if not album:
                # Fallback: group by parent folder name
                folder = os.path.basename(os.path.dirname(filepath)) if filepath else "Unknown"
                album = folder or "Unknown"

            key = (album.strip(), artist.strip())
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

            for idx, fp, meta in items:
                if meta:
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
