"""SMB/NAS directory scanner using smbprotocol library."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse, unquote

from audio_player.player.playlist import AUDIO_EXTENSIONS


def is_smb_available() -> bool:
    try:
        import smbclient  # noqa: F401
        return True
    except ImportError:
        return False


def parse_smb_uri(uri: str) -> tuple[str, str, str]:
    """Parse smb://server/share/path into (server, share, relative_path)."""
    parsed = urlparse(uri)
    server = parsed.hostname or ""
    parts = parsed.path.lstrip("/").split("/", 1)
    share = parts[0] if parts else ""
    rel_path = unquote(parts[1]) if len(parts) > 1 else ""
    return server, share, rel_path


def list_shares(server: str, username: str = "", password: str = "") -> list[str]:
    """List available SMB shares on a server."""
    import smbclient
    if username:
        smbclient.register_session(server, username=username, password=password)
    else:
        smbclient.register_session(server)
    shares = []
    for entry in smbclient.listdir(f"\\\\{server}"):
        if not entry.startswith("$") and not entry.startswith("IPC"):
            shares.append(entry)
    return shares


def scan_folder(
    server: str,
    share: str,
    path: str = "",
    username: str = "",
    password: str = "",
) -> list[dict]:
    """Recursively scan an SMB share for audio files.

    Returns list of {"smb_uri": str, "name": str, "size": int}.
    """
    import smbclient

    if username:
        smbclient.register_session(server, username=username, password=password)
    else:
        smbclient.register_session(server)

    base = f"\\\\{server}\\{share}"
    if path:
        base = f"\\{base}\\{path}"

    results = []
    _scan_recursive(base, server, share, path, results)
    return results


def _scan_recursive(
    current_path: str,
    server: str,
    share: str,
    rel_path: str,
    results: list[dict],
):
    import smbclient
    import stat as stat_module

    try:
        for entry in smbclient.scandir(current_path):
            name = entry.name
            is_dir = entry.is_dir()
            if is_dir:
                sub_rel = f"{rel_path}/{name}" if rel_path else name
                _scan_recursive(
                    f"{current_path}\\{name}",
                    server,
                    share,
                    sub_rel,
                    results,
                )
            else:
                ext = PurePosixPath(name).suffix.lower()
                if ext in AUDIO_EXTENSIONS:
                    smb_uri = f"smb://{server}/{share}/{rel_path}/{name}" if rel_path else f"smb://{server}/{share}/{name}"
                    size = 0
                    try:
                        size = entry.stat().st_size
                    except Exception:
                        pass
                    results.append({"smb_uri": smb_uri, "name": name, "size": size})
    except Exception:
        pass


def smb_uri_to_local(smb_uri: str, mount_point: str) -> str | None:
    """Convert smb:// URI to local path if the share is mounted.

    mount_point: the local directory where the share is mounted.
    Returns the local path, or None if not applicable.
    """
    server, share, rel_path = parse_smb_uri(smb_uri)
    if not server or not share:
        return None
    from pathlib import Path
    mp = Path(mount_point)
    if mp.exists():
        local = mp / rel_path if rel_path else mp
        if local.exists():
            return str(local)
    return None
