"""Drop target used on the home and convert pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from pdfmend.services.conversion import supported


class DropZone(QFrame):
    """Dashed area: drop files here, or click to browse."""

    paths_dropped = Signal(list)
    browse_requested = Signal()

    def __init__(self, hint: str = "把 PDF / Word / Excel / PPT 拖到这里", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)
        self.title = QLabel("＋ 添加文件")
        self.title.setObjectName("DropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName("DropHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    # -- drag & drop -----------------------------------------------------
    @staticmethod
    def _files(event) -> list[Path]:
        paths: list[Path] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths.extend(sorted(p for p in path.rglob("*") if supported(p)))
            elif supported(path):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt API
        files = self._files(event)
        if files:
            self.paths_dropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self.browse_requested.emit()
        super().mouseReleaseEvent(event)
