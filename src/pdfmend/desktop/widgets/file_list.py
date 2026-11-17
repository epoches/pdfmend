"""The file queue table shown on the convert page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from pdfmend.desktop.state import Workspace

STATUS_TEXT = {
    "pending": "等待",
    "running": "处理中…",
    "done": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}


class FileTable(QTableWidget):
    """Columns: file, size, status, score. Mirrors ``Workspace.files``."""

    selection_changed = Signal(list)

    def __init__(self, workspace: Workspace, parent=None) -> None:
        super().__init__(0, 4, parent)
        self.workspace = workspace
        self.setHorizontalHeaderLabels(["文件", "大小", "状态", "分数"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.itemSelectionChanged.connect(self._emit_selection)
        workspace.files_changed.connect(self.reload)

    # -- model -----------------------------------------------------------
    def _row_for(self, path: Path) -> int:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and item.data(Qt.UserRole) == str(path):
                return row
        return -1

    def reload(self) -> None:
        self.setRowCount(0)
        for path in self.workspace.files:
            self._append(path)
        self._emit_selection()

    def _append(self, path: Path) -> None:
        row = self.rowCount()
        self.insertRow(row)
        name = QTableWidgetItem(path.name)
        name.setData(Qt.UserRole, str(path))
        name.setToolTip(str(path))
        self.setItem(row, 0, name)
        size = path.stat().st_size if path.exists() else 0
        self.setItem(row, 1, QTableWidgetItem(_human(size)))
        self.setItem(row, 2, QTableWidgetItem(STATUS_TEXT["pending"]))
        score = QTableWidgetItem("")
        score.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 3, score)

    def set_status(self, path: Path, status: str, score: int | None = None) -> None:
        row = self._row_for(path)
        if row < 0:
            return
        label = STATUS_TEXT.get(status, status)
        item = self.item(row, 2)
        if item is not None:
            item.setText(label)
        if score is not None:
            cell = self.item(row, 3)
            if cell is not None:
                cell.setText(str(score))

    def selected_paths(self) -> list[Path]:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        paths = []
        for row in rows:
            item = self.item(row, 0)
            if item:
                paths.append(Path(item.data(Qt.UserRole)))
        return paths

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.workspace.remove_files(self.selected_paths())
            return
        super().keyPressEvent(event)

    def _emit_selection(self) -> None:
        self.selection_changed.emit(self.selected_paths())


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
