"""First-run dependency installer — runs before the app starts.

Checks for platform-specific system media control dependencies and
installs them via pip if missing. Failed installations are cached for
24 hours to avoid retrying on every launch.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from importlib import util as _il_util
from pathlib import Path

# Cache file for failed installations: {pkg: timestamp_of_failure}
_FAIL_CACHE = Path(tempfile.gettempdir()) / "vbplayer_bootstrap_fails.json"
_FAIL_CACHE_TTL = 86400  # 24 hours

# {module_name: (pip_package, description)}
_PLATFORM_DEPS: dict[str, tuple[str, str]] = {}

if sys.platform == "linux":
    # PyGObject is system-managed; just warn if missing
    _PLATFORM_DEPS["gi"] = ("", "PyGObject (apt install python3-gi)")
elif sys.platform == "darwin":
    _PLATFORM_DEPS["MediaPlayer"] = (
        "pyobjc-framework-MediaPlayer>=10.0",
        "macOS Now Playing (pyobjc)",
    )
elif sys.platform == "win32":
    _PLATFORM_DEPS["winsdk.windows.media"] = (
        "winsdk>=1.0.0b9",
        "Windows SMTC (winsdk)",
    )


def _read_fail_cache() -> dict[str, float]:
    """Read the failed-installation cache, pruning expired entries."""
    try:
        raw = _FAIL_CACHE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}

    now = time.time()
    # Prune expired entries
    fresh = {k: v for k, v in data.items() if now - v < _FAIL_CACHE_TTL}
    if len(fresh) != len(data):
        try:
            _FAIL_CACHE.write_text(json.dumps(fresh), encoding="utf-8")
        except OSError:
            pass
    return fresh


def _write_fail_cache(cache: dict[str, float]):
    """Persist the failed-installation cache."""
    try:
        _FAIL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FAIL_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _module_installed(name: str) -> bool:
    try:
        return _il_util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _check_and_install() -> list[str]:
    """Return list of packages that were installed (empty if nothing needed)."""
    fail_cache = _read_fail_cache()

    missing: list[tuple[str, str, str]] = []
    for mod, (pkg, desc) in _PLATFORM_DEPS.items():
        if _module_installed(mod):
            continue
        # Skip if installation failed within the TTL window
        if pkg and pkg in fail_cache:
            print(f"[bootstrap] {desc} — install failed recently, skipping retry",
                  file=sys.stderr)
            continue
        missing.append((mod, pkg, desc))

    if not missing:
        return []

    # Can't install system packages
    pip_missing = [(m, p, d) for m, p, d in missing if p]
    warn_missing = [(m, p, d) for m, p, d in missing if not p]

    if warn_missing:
        for _, _, desc in warn_missing:
            print(f"[bootstrap] Warning: {desc} not found — system media controls disabled",
                  file=sys.stderr)

    if not pip_missing:
        return []

    installed: list[str] = []
    for mod, pkg, desc in pip_missing:
        print(f"[bootstrap] Installing {desc}...", file=sys.stderr)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", pkg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            installed.append(pkg)
            print(f"[bootstrap] {desc} installed successfully", file=sys.stderr)
            # Remove from fail cache on success
            fail_cache.pop(pkg, None)
        except subprocess.CalledProcessError:
            print(f"[bootstrap] {desc} not available — system media controls disabled",
                  file=sys.stderr)
            fail_cache[pkg] = time.time()

    _write_fail_cache(fail_cache)
    return installed


def ensure_dependencies():
    """Check and install missing platform deps. Call before app import."""
    # Skip if running from a frozen/packaged binary
    if getattr(sys, "frozen", False):
        return

    installed = _check_and_install()

    if installed:
        # Invalidate import caches so newly installed packages are visible
        import importlib
        importlib.invalidate_caches()
