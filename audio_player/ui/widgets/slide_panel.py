from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QStackedWidget, QListWidget,
                             QListWidgetItem, QAbstractItemView, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QColor, QFont


_NAV_ITEMS = [
    ("🎵  全部歌曲", "songs"),
    ("💿  专辑", "albums"),
    ("⚙  音频管理", "manage"),
    ("🔧  设置", "settings"),
]


class SlidePanel(QWidget):
    navigateAlbum = pyqtSignal()
    navigateManage = pyqtSignal()
    navigateSettings = pyqtSignal()
    importFolder = pyqtSignal()
    importFiles = pyqtSignal()
    reloadAlbums = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("slidePanel")
        self.setFixedWidth(0)  # starts hidden
        self._expanded = False
        self._panel_width = 300

        self._setup_ui()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Top bar with close button
        top = QHBoxLayout()
        top.setContentsMargins(12, 12, 12, 8)
        lbl = QLabel("导航")
        lbl.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:bold;letter-spacing:2px;")
        top.addWidget(lbl)
        top.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#888;border:none;font-size:14px;border-radius:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.1);color:#fff;}"
        )
        close_btn.clicked.connect(self.hide_panel)
        top.addWidget(close_btn)
        main.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#141414;max-height:1px;")
        main.addWidget(sep)

        # Navigation list (Page 0)
        self._nav_list = QListWidget()
        self._nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._nav_list.setStyleSheet(
            "QListWidget{background:transparent;border:none;font-size:13px;padding:8px 4px;}"
            "QListWidget::item{color:#888;padding:12px 14px;border-radius:6px;margin:1px 6px;}"
            "QListWidget::item:selected{color:#d0d0d0;background:rgba(124,58,237,0.15);}"
            "QListWidget::item:hover{color:#bbb;}"
        )
        for label, key in _NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._nav_list.addItem(item)
        self._nav_list.currentRowChanged.connect(self._on_nav_select)
        main.addWidget(self._nav_list)

        # Audio management page (hidden, shown by navigation)
        self._manage_page = self._build_manage_page()
        self._manage_page.hide()
        main.addWidget(self._manage_page)

        main.addStretch()

    def _build_manage_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(10)

        title = QLabel("音频管理")
        title.setStyleSheet("color:#e2e8f0;font-size:14px;font-weight:bold;")
        layout.addWidget(title)

        folder_btn = QPushButton("📂  导入文件夹")
        folder_btn.setStyleSheet(
            "QPushButton{background:rgba(124,58,237,0.15);color:#a78bfa;border:none;"
            "border-radius:6px;padding:10px;font-size:12px;text-align:left;}"
            "QPushButton:hover{background:rgba(124,58,237,0.25);}"
        )
        folder_btn.clicked.connect(self.importFolder)
        layout.addWidget(folder_btn)

        files_btn = QPushButton("📁  导入文件")
        files_btn.setStyleSheet(
            "QPushButton{background:rgba(124,58,237,0.15);color:#a78bfa;border:none;"
            "border-radius:6px;padding:10px;font-size:12px;text-align:left;}"
            "QPushButton:hover{background:rgba(124,58,237,0.25);}"
        )
        files_btn.clicked.connect(self.importFiles)
        layout.addWidget(files_btn)

        layout.addSpacing(6)

        self._track_count_label = QLabel("当前加载: 0 首歌曲")
        self._track_count_label.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(self._track_count_label)

        self._album_count_label = QLabel("识别到: 0 张专辑")
        self._album_count_label.setStyleSheet("color:#94a3b8;font-size:11px;")
        layout.addWidget(self._album_count_label)

        layout.addSpacing(6)

        reload_btn = QPushButton("🔄  重新加载专辑")
        reload_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:#fff;border:none;border-radius:6px;"
            "padding:10px;font-size:12px;}"
            "QPushButton:hover{background:#8b5cf6;}"
        )
        reload_btn.clicked.connect(self.reloadAlbums)
        layout.addWidget(reload_btn)

        layout.addStretch()
        return w

    def _on_nav_select(self, row: int):
        item = self._nav_list.item(row)
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == "songs":
            self.hide_panel()
        elif key == "albums":
            self.navigateAlbum.emit()
        elif key == "manage":
            self.navigateManage.emit()
            self._show_manage_page()
        elif key == "settings":
            self.navigateSettings.emit()
            self.hide_panel()

    def _show_manage_page(self):
        self._manage_page.show()
        self._nav_list.hide()

    def show_nav(self):
        self._manage_page.hide()
        self._nav_list.show()

    def update_stats(self, track_count: int, album_count: int):
        self._track_count_label.setText(f"当前加载: {track_count} 首歌曲")
        self._album_count_label.setText(f"识别到: {album_count} 张专辑")

    def toggle(self):
        if self._expanded:
            self.hide_panel()
        else:
            self.show_panel()

    def show_panel(self):
        self._expanded = True
        self.show_nav()
        self.setFixedWidth(self._panel_width)
        self.show()
        self.raise_()

    def hide_panel(self):
        self._expanded = False
        self.setFixedWidth(0)
        self.hide()

    def is_expanded(self) -> bool:
        return self._expanded
