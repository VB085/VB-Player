"""Tag editor dialog — edit audio file metadata via mutagen."""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)
from PyQt6.QtCore import Qt

from audio_player.i18n import _
from audio_player.app import current_accent, current_theme_mode
from audio_player.player.metadata import TrackMetadata
from audio_player.ui.utils import is_light_mode as _is_light_mode


class TagEditorDialog(QDialog):
    """Frameless dialog for editing audio file tags."""

    def __init__(self, filepath: str, meta: TrackMetadata, parent=None):
        super().__init__(parent)
        self._filepath = filepath
        self.setWindowTitle(_("tags.edit_title"))
        self.setMinimumWidth(420)
        from audio_player.platform import platform_info
        if platform_info.policy.titlebar_style == "frameless":
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        is_light = _is_light_mode()
        bg = "#ffffff" if is_light else "#0f0f0f"
        border = "#e0e0e0" if is_light else "#222222"
        text_c = "#333333" if is_light else "#e2e8f0"
        sub_c = "#666666" if is_light else "#94a3b8"
        input_bg = "#f8f8f8" if is_light else "#141418"
        accent = current_accent()

        self.setStyleSheet(
            f"QDialog{{background:{bg};border:1px solid {border};border-radius:12px;}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title
        title = QLabel(_("tags.edit_title"))
        title.setStyleSheet(f"color:{text_c};font-size:16px;font-weight:bold;")
        layout.addWidget(title)

        # Filename subtitle
        fname = QLabel(os.path.basename(filepath))
        fname.setStyleSheet(f"color:{sub_c};font-size:11px;")
        layout.addWidget(fname)

        # Fields
        self._fields: dict[str, QLineEdit] = {}
        field_defs = [
            ("title", meta.title),
            ("artist", meta.artist),
            ("album", meta.album),
            ("album_artist", meta.album_artist),
            ("year", str(meta.year) if meta.year is not None else ""),
            ("genre", meta.genre),
            ("track_number", str(meta.track_number) if meta.track_number is not None else ""),
            ("disc_number", str(meta.disc_number) if meta.disc_number is not None else ""),
        ]

        for key, value in field_defs:
            lbl = QLabel(_(f"tags.{key}"))
            lbl.setStyleSheet(f"color:{sub_c};font-size:11px;")
            layout.addWidget(lbl)
            edit = QLineEdit(value)
            edit.setStyleSheet(
                f"QLineEdit{{background:{input_bg};color:{text_c};border:1px solid {border};"
                f"border-radius:6px;padding:8px 10px;font-size:13px;}}"
                f"QLineEdit:focus{{border:1px solid {accent.name()};}}"
            )
            layout.addWidget(edit)
            self._fields[key] = edit

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(_("settings.cancel"))
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{sub_c};border:1px solid {border};"
            f"border-radius:6px;padding:8px 20px;font-size:12px;}}"
            f"QPushButton:hover{{color:{text_c};border-color:{text_c};}}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton(_("settings.ok"))
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;"
            f"border-radius:6px;padding:8px 20px;font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def get_tags(self) -> dict[str, str | int | None]:
        """Return edited tags as a dict matching TrackMetadata field names."""
        result: dict[str, str | int | None] = {}
        for key, edit in self._fields.items():
            text = edit.text().strip()
            if key in ("year", "track_number", "disc_number"):
                if text:
                    try:
                        result[key] = int(text)
                    except ValueError:
                        result[key] = None
                else:
                    result[key] = None
            else:
                result[key] = text
        return result
