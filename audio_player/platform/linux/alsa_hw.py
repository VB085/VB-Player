"""Locale-independent ALSA playback device enumeration.

``/proc/asound/cards`` only gives one name per card, so every PCM device on
the same card used to look identical (e.g. five entries named "sofhdadsp").
``/proc/asound/pcm`` carries the per-device PCM name, which is what users
actually recognise: "HDA Analog", "HDMI 1", "USB Audio", ...
"""

from __future__ import annotations

import re
from pathlib import Path


def _parse_cards(text: str) -> dict[int, tuple[str, str]]:
    """Return {card: (short_id, model)} from /proc/asound/cards text."""
    cards: dict[int, tuple[str, str]] = {}
    for line in (text or "").splitlines():
        match = re.match(r"\s*(\d+)\s*\[([^\]]+)\]\s*:\s*(.+)", line)
        if not match:
            continue
        card = int(match.group(1))
        card_id = match.group(2).strip()
        desc = match.group(3).strip()
        model = desc.split(" - ", 1)[1].strip() if " - " in desc else card_id
        cards[card] = (card_id, model or card_id)
    return cards


def _read_cards() -> dict[int, tuple[str, str]]:
    try:
        return _parse_cards(Path("/proc/asound/cards").read_text())
    except OSError:
        return {}


def _clean_pcm_name(name: str) -> str:
    name = re.sub(r"\s*\(\*\)\s*$", "", (name or "").strip())
    # "HDMI1" -> "HDMI 1"
    name = re.sub(r"^(HDMI)(\d+)$", r"\1 \2", name)
    return name.strip()


def _parse_pcm(text: str, cards: dict[int, tuple[str, str]]) -> list[dict]:
    devices: list[dict] = []
    for line in (text or "").splitlines():
        # 02-03: HDMI1 (*) : HDMI 1 : playback 1 : capture 1
        match = re.match(
            r"(\d+)-(\d+):\s*(.*?)\s*:\s*(.*?)\s*:\s*playback\s+(\d+)", line
        )
        if not match:
            continue
        card, dev = int(match.group(1)), int(match.group(2))
        if int(match.group(5)) < 1:
            continue
        pcm_name = _clean_pcm_name(match.group(3)) or _clean_pcm_name(match.group(4))
        card_id, card_model = cards.get(card, (f"card{card}", f"Card {card}"))
        if pcm_name and pcm_name.lower() != card_model.lower():
            label = f"{card_model} · {pcm_name}"
        else:
            label = card_model
        hw = f"hw:{card},{dev}"
        devices.append({
            "card": card,
            "device": dev,
            "hw": hw,
            "name": f"{label} ({hw})",
            "card_id": card_id,
            "card_name": card_model,
            "pcm_name": pcm_name,
            "description": f"{card_model} / {pcm_name}" if pcm_name else card_model,
            "driver": "ALSA",
        })
    return devices


def enumerate_alsa_playback_devices() -> list[dict]:
    """Return playback devices with human-readable card + PCM names.

    Each dict: card, device, hw, name, card_id, card_name, pcm_name,
    description, driver.
    """
    cards = _read_cards()
    try:
        pcm_text = Path("/proc/asound/pcm").read_text()
    except OSError:
        pcm_text = ""
    devices = _parse_pcm(pcm_text, cards)

    # Fallback when /proc/asound/pcm is unavailable.
    if not devices:
        for card, (card_id, model) in sorted(cards.items()):
            hw = f"hw:{card},0"
            devices.append({
                "card": card,
                "device": 0,
                "hw": hw,
                "name": f"{model} ({hw})",
                "card_id": card_id,
                "card_name": model,
                "pcm_name": "",
                "description": model,
                "driver": "ALSA",
            })

    if not devices:
        devices.append({
            "card": 0,
            "device": 0,
            "hw": "hw:0,0",
            "name": "hw:0,0",
            "card_id": "",
            "card_name": "",
            "pcm_name": "",
            "description": "",
            "driver": "ALSA",
        })

    return devices
