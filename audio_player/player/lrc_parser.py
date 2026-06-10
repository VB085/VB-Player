"""LRC format parser, merger, and exporter."""

from __future__ import annotations

import re
from audio_player.player.audio_analyzer import LyricsLine


def parse_lrc(text: str) -> list[LyricsLine]:
    """Parse LRC format text into LyricsLine list.

    Supports [mm:ss.xx] and [mm:ss.xxx] timestamps.
    Multiple timestamps per line are expanded.
    Consecutive same-timestamp lines are merged as original + translation.
    """
    lines: list[LyricsLine] = []
    for line in text.splitlines():
        matches = list(re.finditer(r'\[(\d+):(\d+(?:\.\d+)?)\]', line))
        if not matches:
            continue
        lyric_text = line[matches[-1].end():].strip()
        if not lyric_text:
            continue
        for m in matches:
            minutes = int(m.group(1))
            seconds = float(m.group(2))
            time_ms = int((minutes * 60 + seconds) * 1000)
            lines.append(LyricsLine(time_ms, lyric_text))

    lines.sort(key=lambda x: x.time_ms)

    # Merge same-timestamp lines as original + translation pairs
    merged: list[LyricsLine] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and lines[i].time_ms == lines[i + 1].time_ms:
            merged.append(LyricsLine(lines[i].time_ms, lines[i].text, lines[i + 1].text))
            i += 2
        else:
            merged.append(lines[i])
            i += 1
    return merged


def merge_translation(lines: list[LyricsLine], translation_text: str) -> None:
    """Merge translation into existing lines by index (not by time).

    Avoids issues with inaccurate timestamps in translated lyrics.
    Mutates lines in-place.
    """
    trans_lines = parse_lrc(translation_text)
    for i, line in enumerate(lines):
        if i < len(trans_lines):
            line.translation = trans_lines[i].text


def export_lrc(lines: list[LyricsLine]) -> str:
    """Export LyricsLine list back to LRC format text."""
    parts: list[str] = []
    for line in lines:
        if line.time_ms < 0:
            continue
        mins = line.time_ms // 60000
        secs = (line.time_ms % 60000) / 1000.0
        tag = f"[{mins:02d}:{secs:05.2f}]"
        parts.append(f"{tag}{line.text}")
        if line.translation:
            parts.append(f"{tag}{line.translation}")
    return "\n".join(parts) + "\n"
