"""First-run dependency installer — runs before the app starts.

Checks for platform-specific system media control dependencies and
installs them via pip if missing. Shows a minimal splash dialog so
the user knows what's happening.
"""

import subprocess
import sys
from importlib import util as _il_util

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


def _module_installed(name: str) -> bool:
    return _il_util.find_spec(name) is not None


def _check_and_install() -> list[str]:
    """Return list of packages that were installed (empty if nothing needed)."""
    missing: list[tuple[str, str, str]] = []
    for mod, (pkg, desc) in _PLATFORM_DEPS.items():
        if not _module_installed(mod):
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
            )
            installed.append(pkg)
            print(f"[bootstrap] {desc} installed successfully", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"[bootstrap] Failed to install {desc}: {e}", file=sys.stderr)

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
