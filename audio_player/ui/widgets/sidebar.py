from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QTextEdit)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from audio_player.app import current_theme_mode, current_accent
from audio_player.i18n import _, languageChanged

NAV_ITEMS = [
    ("📋", "nav.all_songs", "songs"),
    ("💿", "nav.albums", "albums"),
    ("⚙", "nav.manage", "manage"),
    ("🔧", "nav.settings", "settings"),
]


class Sidebar(QWidget):
    """Left-side collapsible navigation sidebar."""
    navChanged = pyqtSignal(str)       # emits key: songs/albums/manage/settings
    reloadAlbums = pyqtSignal()
    widthToggled = pyqtSignal(int)     # emits target width when collapsed/expanded

    COLLAPSED_W = 52
    EXPANDED_MIN_W = 140
    EXPANDED_W = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self._collapsed = False
        self._current_nav = "songs"
        self._expanded_width = self.EXPANDED_W
        self._track_count = 0
        self._album_count = 0

        self._setup_ui()
        languageChanged.connect(self.refresh_language)

    def _setup_ui(self):
        self._is_light = current_theme_mode() == "light"

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Toggle button row
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(10, 8, 4, 4)
        self._toggle_btn = QPushButton("☰")
        self._toggle_btn.setObjectName("sidebarToggle")
        self._toggle_btn.setFixedSize(40, 40)
        self._toggle_btn.setToolTip(_("sidebar.collapse"))
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_toggle_btn_style()
        self._toggle_btn.clicked.connect(self.toggle)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch()
        main.addLayout(toggle_row)

        # Nav items — row-per-item: icon-btn + label
        self._nav_rows: list[dict] = []
        self._nav_layout = QVBoxLayout()
        self._nav_layout.setContentsMargins(4, 4, 4, 4)
        self._nav_layout.setSpacing(2)

        for icon, tr_key, nav_key in NAV_ITEMS:
            row = QHBoxLayout()
            row.setContentsMargins(6, 2, 6, 2)
            row.setSpacing(10)

            btn = QPushButton(icon)
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(_(tr_key))
            btn.clicked.connect(lambda checked, k=nav_key: self._on_nav(k))
            row.addWidget(btn)

            lbl = QLabel(_(tr_key))
            row.addWidget(lbl, 1)
            row.addStretch()

            self._nav_layout.addLayout(row)
            self._nav_rows.append({"key": nav_key, "tr_key": tr_key, "btn": btn, "lbl": lbl})

        main.addLayout(self._nav_layout)

        # Separator
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        self._apply_sep_style()
        main.addWidget(self._sep)

        # Stats
        muted = "#555555" if self._is_light else "#64748b"
        self._track_count_label = QLabel(_("stats.tracks", count=0))
        self._track_count_label.setStyleSheet(f"color:{muted};font-size:12px;padding:4px 10px;")
        main.addWidget(self._track_count_label)

        self._album_count_label = QLabel(_("stats.albums", count=0))
        self._album_count_label.setStyleSheet(f"color:{muted};font-size:12px;padding:0px 10px;")
        main.addWidget(self._album_count_label)

        # Reload button
        self._reload_btn = QPushButton(_("manage.reload_albums"))
        self._reload_btn.clicked.connect(self.reloadAlbums)
        self._apply_reload_btn_style()
        main.addWidget(self._reload_btn)

        # Log text box
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setMaximumHeight(120)
        self._apply_log_style()
        self._log_box.hide()
        main.addWidget(self._log_box)

        main.addStretch()

        self.setMinimumWidth(self.COLLAPSED_W)
        self.setMaximumWidth(420)
        self._apply_collapsed_state()
        self._update_nav_highlight()

    def _on_nav(self, key: str):
        self._current_nav = key
        self._update_nav_highlight()
        self.navChanged.emit(key)

    def _update_nav_highlight(self):
        """Apply accent-colored background to selected item, like settings-page tabs."""
        accent = current_accent()
        r, g, b = accent.red(), accent.green(), accent.blue()
        is_light = current_theme_mode() == "light"
        icon_inactive = "#555" if is_light else "#888"
        lbl_inactive = "#555" if is_light else "#94a3b8"
        lbl_active = "#333" if is_light else "#e2e8f0"
        hover_bg = "#e8e8e8" if is_light else "#1a1a2e"
        cur_bg = accent.darker(160).name()
        cur_hover_bg = accent.darker(140).name()

        for row in self._nav_rows:
            is_current = row["key"] == self._current_nav
            btn = row["btn"]
            lbl = row["lbl"]

            btn.setStyleSheet(
                f"QPushButton{{"
                f"background:{cur_bg if is_current else 'transparent'};"
                f"color:{accent.lighter(160).name() if is_current else icon_inactive};"
                f"border:none;border-radius:8px;font-size:18px;"
                f"}}"
                f"QPushButton:hover{{"
                f"background:{cur_hover_bg if is_current else hover_bg};"
                f"}}"
            )
            lbl.setStyleSheet(f"color:{lbl_active if is_current else lbl_inactive};font-size:14px;")

    def toggle(self):
        self._collapsed = not self._collapsed
        self._apply_collapsed_state()
        self._toggle_btn.setText("☰" if not self._collapsed else "→")

    def expand(self):
        self._collapsed = False
        self._apply_collapsed_state()
        self._toggle_btn.setText("☰")

    def collapse(self):
        self._collapsed = True
        self._apply_collapsed_state()
        self._toggle_btn.setText("→")

    def _apply_collapsed_state(self):
        if self._collapsed:
            self.setMinimumWidth(self.COLLAPSED_W)
            self.setMaximumWidth(self.COLLAPSED_W)
            for row in self._nav_rows:
                row["lbl"].hide()
            self._track_count_label.hide()
            self._album_count_label.hide()
            self._reload_btn.hide()
            self.widthToggled.emit(self.COLLAPSED_W)
        else:
            self.setMinimumWidth(self.EXPANDED_MIN_W)
            self.setMaximumWidth(420)
            for row in self._nav_rows:
                row["lbl"].show()
            self._track_count_label.show()
            self._album_count_label.show()
            self._reload_btn.show()
            self.widthToggled.emit(self._expanded_width)
        self._update_nav_highlight()

    def update_stats(self, track_count: int, album_count: int):
        self._track_count = track_count
        self._album_count = album_count
        self._track_count_label.setText(_("stats.tracks", count=track_count))
        self._album_count_label.setText(_("stats.albums", count=album_count))

    def expanded_width(self) -> int:
        return self._expanded_width

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def refresh_language(self, _code: str = ""):
        """Re-apply all translatable text."""
        self._toggle_btn.setToolTip(_("sidebar.collapse"))
        self._reload_btn.setText(_("manage.reload_albums"))
        self._track_count_label.setText(_("stats.tracks", count=self._track_count))
        self._album_count_label.setText(_("stats.albums", count=self._album_count))
        for row in self._nav_rows:
            tr_key = row["tr_key"]
            row["btn"].setToolTip(_(tr_key))
            row["lbl"].setText(_(tr_key))

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------

    def _apply_toggle_btn_style(self):
        toggle_color = "#555555" if self._is_light else "#aaaaaa"
        toggle_hover_bg = "#e0e0e0" if self._is_light else "#1a1a2e"
        toggle_hover_color = "#333" if self._is_light else "#fff"
        self._toggle_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{toggle_color};border:none;"
            f"font-size:20px;border-radius:6px;}}"
            f"QPushButton:hover{{background:{toggle_hover_bg};color:{toggle_hover_color};}}"
        )

    def _apply_sep_style(self):
        sep_color = "#d0d0d0" if self._is_light else "#141414"
        self._sep.setStyleSheet(f"background:{sep_color};max-height:1px;margin:4px 8px;")

    def _apply_log_style(self):
        log_bg = "#f5f5f5" if self._is_light else "#050508"
        log_text = "#555555" if self._is_light else "#555555"
        log_border = "#d0d0d0" if self._is_light else "#141414"
        self._log_box.setStyleSheet(
            f"QTextEdit{{background:{log_bg};color:{log_text};"
            f"border:1px solid {log_border};border-radius:4px;"
            f"font-size:10px;font-family:monospace;padding:4px;}}"
        )

    def _apply_reload_btn_style(self):
        accent = current_accent()
        self._reload_btn.setStyleSheet(
            f"QPushButton{{background:{accent.name()};color:#fff;border:none;border-radius:5px;"
            f"padding:8px;font-size:13px;margin:4px 6px;}}"
            f"QPushButton:hover{{background:{accent.lighter(115).name()};}}"
        )

    def refresh_accent(self):
        self._apply_reload_btn_style()
        self._update_nav_highlight()

    def refresh_theme_mode(self, is_light: bool):
        self._is_light = is_light
        muted = "#555555" if is_light else "#64748b"

        self._apply_toggle_btn_style()
        self._apply_sep_style()
        self._apply_log_style()
        self._track_count_label.setStyleSheet(f"color:{muted};font-size:12px;padding:4px 10px;")
        self._album_count_label.setStyleSheet(f"color:{muted};font-size:12px;padding:0px 10px;")
        self._update_nav_highlight()

    def append_log(self, message: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.append(f"[{ts}] {message}")
        lines = self._log_box.toPlainText().splitlines()
        if len(lines) > 200:
            self._log_box.setPlainText("\n".join(lines[-200:]))

    def set_log_visible(self, visible: bool):
        self._log_box.setVisible(visible)
