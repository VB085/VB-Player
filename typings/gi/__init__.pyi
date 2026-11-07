"""Minimal stub for PyGObject (Linux-only dependency).

VB Player imports `gi` at runtime on Linux to initialize GStreamer before
Qt (see main.py). On Windows the import is guarded by try/except and never
succeeds; this stub exists only so Pylance/pyright can resolve the names.
"""

from typing import Any

__all__ = ["require_version", "repository"]


def require_version(namespace: str, version: str) -> None:
    """Mimic gi.require_version — no-op for static analysis."""
    return None


class _RepositoryModule:
    """Stand-in for gi.repository.<Namespace> dynamic modules (Gst etc.)."""

    def __getattr__(self, name: str) -> Any:
        raise ImportError(
            "gi.repository is a runtime-only dynamic module (Linux); "
            f"attribute {name!r} is unavailable during static analysis"
        )


def __getattr__(name: str) -> Any:
    if name == "repository":
        return _RepositoryModule()
    raise AttributeError(f"module 'gi' has no attribute {name!r}")
