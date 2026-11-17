"""Main window: sidebar navigation plus a stacked page area."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pdfmend import __version__
from pdfmend.config.settings import Settings
from pdfmend.desktop.dialogs.donation import open_donation
from pdfmend.desktop.pages.convert import ConvertPage
from pdfmend.desktop.pages.home import HomePage
from pdfmend.desktop.pages.results import ResultsPage
from pdfmend.desktop.pages.settings import SettingsPage
from pdfmend.desktop.state import Workspace
from pdfmend.desktop.theme import apply_theme
from pdfmend.services.conversion import scan_files

NAV = (
    ("首页", 0),
    ("文件转换", 1),
    ("结果预览", 2),
    ("设置", 3),
)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"PDFMend {__version__}")
        self.resize(1180, 760)
        self.settings = settings or Settings()
        self.workspace = Workspace(self)

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.home = HomePage(self.workspace, self.settings)
        self.convert = ConvertPage(self.workspace, self.settings)
        self.results = ResultsPage(self.workspace, self.settings)
        self.settings_page = SettingsPage(self.settings)
        for page in (self.home, self.convert, self.results, self.settings_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self._wire()
        self.apply_theme(self.settings.theme)

    # -- build -----------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(208)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        brand = QLabel("PDFMend")
        brand.setObjectName("Brand")
        layout.addWidget(brand)
        tagline = QLabel("本地文档解析与质检")
        tagline.setObjectName("Muted")
        layout.addWidget(tagline)
        layout.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (label, page) in enumerate(NAV):
            button = QPushButton(label)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _=False, page=page: self.go(page))
            self.nav_group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)

        support = QPushButton("支持作者")
        support.setObjectName("Ghost")
        support.clicked.connect(lambda: open_donation(self))
        layout.addWidget(support)

        version = QLabel(f"v{__version__} · MIT")
        version.setObjectName("Muted")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        return side

    def _wire(self) -> None:
        self.home.files_added.connect(self._add_files)
        self.home.browse_requested.connect(self._browse_files)
        self.convert.finished.connect(lambda: self.go(2))
        self.settings_page.theme_changed.connect(self.apply_theme)
        self.settings_page.saved.connect(self._settings_saved)

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)

    # -- actions ---------------------------------------------------------
    def go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button is not None:
            button.setChecked(True)

    def _add_files(self, paths: list[str]) -> None:
        added = scan_files([Path(p) for p in paths])
        if added:
            self.workspace.add_files(added)
            self.convert.table.reload()
            self.go(1)

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文档",
            str(self.settings.last_open_dir or Path.home()),
            "文档 (*.pdf *.docx *.xlsx *.pptx)",
        )
        if files:
            self.settings.last_open_dir = str(Path(files[0]).parent)
            self._add_files(files)

    def _settings_saved(self) -> None:
        self.convert.sync_settings()
