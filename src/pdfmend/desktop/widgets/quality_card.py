"""Quality card: the 0-100 score, verdict and the reasons behind it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

from pdfmend.services.conversion import ConversionResult

COLOR_OK = "#1a7f37"
COLOR_WARN = "#b26a00"
COLOR_BAD = "#b42318"


def score_color(score: int) -> str:
    if score >= 85:
        return COLOR_OK
    if score >= 60:
        return COLOR_WARN
    return COLOR_BAD


class QualityCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("QualityCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        grid = QGridLayout()
        self.score = QLabel("—")
        self.score.setObjectName("ScoreValue")
        self.score.setAlignment(Qt.AlignCenter)
        self.verdict = QLabel("先添加文件并转换")
        self.verdict.setObjectName("ScoreVerdict")
        self.file_label = QLabel("")
        self.file_label.setObjectName("ScoreFile")
        self.file_label.setWordWrap(True)
        grid.addWidget(self.score, 0, 0, 2, 1)
        grid.addWidget(self.verdict, 0, 1, 1, 1, Qt.AlignBottom)
        grid.addWidget(self.file_label, 1, 1, 1, 1, Qt.AlignTop)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setObjectName("Muted")
        layout.addWidget(self.meta)

        self.reasons = QListWidget()
        self.reasons.setObjectName("Reasons")
        self.reasons.setMaximumHeight(130)
        layout.addWidget(self.reasons)

    def clear(self) -> None:
        self.score.setText("—")
        self.score.setStyleSheet("")
        self.verdict.setText("先添加文件并转换")
        self.file_label.setText("")
        self.meta.setText("")
        self.reasons.clear()

    def show_result(self, result: ConversionResult) -> None:
        if not result.ok or result.report is None:
            self.score.setText("!")
            self.score.setStyleSheet(f"color:{COLOR_BAD};")
            self.verdict.setText("处理失败")
            self.file_label.setText(result.source.name)
            self.meta.setText(result.error or "")
            self.reasons.clear()
            return

        report = result.report
        self.score.setText(str(report.score))
        self.score.setStyleSheet(f"color:{score_color(report.score)};")
        self.verdict.setText(report.verdict)
        self.file_label.setText(str(result.source))

        tables = report.tables
        good = sum(1 for t in tables if t.confidence >= 0.85)
        meta = f"{report.document.pages} 页 · {len(tables)} 张表（{good} 张高置信）"
        steps = list(dict.fromkeys(report.document.meta.get("ocr_steps") or []))
        if steps:
            meta += " · 预处理：" + "、".join(steps)
        if report.document.meta.get("ocr_pages"):
            meta += " · OCR 页：" + "、".join(str(p) for p in report.document.meta["ocr_pages"])
        self.meta.setText(meta)

        self.reasons.clear()
        for reason in report.reasons:
            self.reasons.addItem(reason)
        for warning in result.warnings:
            self.reasons.addItem(warning)
        if not report.reasons and not result.warnings:
            self.reasons.addItem("未发现明显问题。")
