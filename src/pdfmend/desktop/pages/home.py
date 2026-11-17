"""Home: drop files, pick a folder, see what the app does."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdfmend.config.settings import Settings
from pdfmend.desktop.state import Workspace
from pdfmend.desktop.widgets.drop_zone import DropZone

FILTER = "文档 (*.pdf *.docx *.xlsx *.pptx);;所有文件 (*.*)"


class HomePage(QWidget):
    files_added = Signal(list)
    browse_requested = Signal()

    def __init__(self, workspace: Workspace, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("PDFMend")
        title.setObjectName("PageTitle")
        hint = QLabel("本地文档解析与质量检测：PDF / Word / Excel / PPT → Markdown、Excel、JSON、HTML。文件不出本机。")
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        self.drop = DropZone("支持 PDF · DOCX · XLSX · PPTX，可拖入文件夹")
        layout.addWidget(self.drop)

        row = QHBoxLayout()
        add_file = QPushButton("添加文件")
        add_folder = QPushButton("添加文件夹")
        add_file.clicked.connect(self.pick_files)
        add_folder.clicked.connect(self.pick_folder)
        row.addWidget(add_file)
        row.addWidget(add_folder)
        row.addStretch(1)
        layout.addLayout(row)

        steps = QLabel(
            "1 拖入文件 → 2 选导出格式 → 3 看质量分与错误提示 → 4 拿去用\n"
            "转换是纯本地的；只有「AI 抽取字段」会把文字发给你配置的模型。"
        )
        steps.setObjectName("Muted")
        steps.setWordWrap(True)
        layout.addWidget(steps)

        recent_title = QLabel("最近处理")
        recent_title.setObjectName("PageHint")
        self.recent = QListWidget()
        self.recent.setMaximumHeight(180)
        self.recent.itemDoubleClicked.connect(self._open_recent)
        layout.addWidget(recent_title)
        layout.addWidget(self.recent)
        layout.addStretch(1)

        self.drop.paths_dropped.connect(self.files_added.emit)
        self.drop.browse_requested.connect(self.pick_files)
        workspace.files_changed.connect(self.refresh)

    # -- actions ---------------------------------------------------------
    def pick_files(self) -> None:
        start = str(self.settings.output_dir or Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, "添加文件", start, FILTER)
        if files:
            self.files_added.emit(files)

    def pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加文件夹", str(Path.home()))
        if folder:
            self.files_added.emit([folder])

    def _open_recent(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path and Path(path).exists():
            self.files_added.emit([path])

    def refresh(self) -> None:
        self.recent.clear()
        for path in self.settings.recent_files:
            if not Path(path).exists():
                continue
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.recent.addItem(item)
        if self.recent.count() == 0:
            item = QListWidgetItem("还没有记录，先处理一个文件吧。")
            item.setFlags(Qt.NoItemFlags)
            self.recent.addItem(item)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.refresh()
        super().showEvent(event)
