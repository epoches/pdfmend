"""Results page: quality card, Markdown/JSON preview, outputs and AI fields."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pdfmend.config.settings import Settings
from pdfmend.desktop.state import Workspace
from pdfmend.desktop.widgets.quality_card import QualityCard
from pdfmend.desktop.workers import AiWorker
from pdfmend.services.conversion import ConversionResult

PROFILES = (
    ("", "通用（不套模板）"),
    ("resume", "简历 resume"),
    ("contract", "合同 contract"),
    ("research_report", "研报 research_report"),
)


class ResultsPage(QWidget):
    ai_requested = Signal(object)   # ConversionResult

    def __init__(self, workspace: Workspace, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.settings = settings
        self.pool = QThreadPool.globalInstance()
        self.ai_worker: AiWorker | None = None
        self.current: ConversionResult | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title = QLabel("结果预览")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("处理结果"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show_row)
        left_layout.addWidget(self.list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.card = QualityCard()
        right_layout.addWidget(self.card)

        self.tabs = QTabWidget()
        self.markdown = _text_view()
        self.report_json = _text_view()
        self.tabs.addTab(self.markdown, "Markdown 预览")
        self.tabs.addTab(self.report_json, "报告 JSON")

        outputs = QWidget()
        out_layout = QVBoxLayout(outputs)
        out_layout.setContentsMargins(0, 0, 0, 0)
        self.files = QListWidget()
        out_layout.addWidget(self.files, 1)
        buttons = QHBoxLayout()
        open_file = QPushButton("打开文件")
        open_file.clicked.connect(self._open_selected_file)
        open_dir = QPushButton("打开所在文件夹")
        open_dir.clicked.connect(self._open_selected_dir)
        buttons.addWidget(open_file)
        buttons.addWidget(open_dir)
        buttons.addStretch(1)
        out_layout.addLayout(buttons)
        self.tabs.addTab(outputs, "输出文件")
        right_layout.addWidget(self.tabs, 1)

        ai_box = QWidget()
        ai_layout = QVBoxLayout(ai_box)
        ai_layout.setContentsMargins(0, 8, 0, 0)
        ai_row = QHBoxLayout()
        ai_row.addWidget(QLabel("AI 字段抽取"))
        self.profile = QComboBox()
        for key, label in PROFILES:
            self.profile.addItem(label, key)
        ai_row.addWidget(self.profile)
        self.ai_button = QPushButton("抽取字段")
        self.ai_button.clicked.connect(self.start_ai)
        ai_row.addWidget(self.ai_button)
        self.ai_status = QLabel("使用设置里的 API Key；没有 Key 不影响本地功能")
        self.ai_status.setObjectName("Muted")
        ai_row.addWidget(self.ai_status, 1)
        ai_layout.addLayout(ai_row)
        self.ai_preview = _text_view()
        self.ai_preview.setMaximumHeight(160)
        ai_layout.addWidget(self.ai_preview)
        right_layout.addWidget(ai_box)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        workspace.results_changed.connect(self.refresh)
        self.refresh()

    # -- list ------------------------------------------------------------
    def refresh(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for result in self.workspace.results:
            if result.ok:
                label = f"{result.source.name}  ·  {result.score}/100  {result.verdict}"
            else:
                label = f"{result.source.name}  ·  失败"
            item = QListWidgetItem(label)
            item.setData(0x0100, result)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.workspace.results:
            self.list.setCurrentRow(0)
        else:
            self.current = None
            self.card.clear()
            self.markdown.clear()
            self.report_json.clear()
            self.files.clear()

    def _show_row(self, row: int) -> None:
        if row < 0 or row >= self.list.count():
            return
        item = self.list.item(row)
        result = item.data(0x0100)
        if isinstance(result, ConversionResult):
            self.show_result(result)

    def show_result(self, result: ConversionResult) -> None:
        self.current = result
        self.card.show_result(result)
        md_path = result.outputs.get("md")
        self.markdown.setPlainText(md_path.read_text(encoding="utf-8") if md_path and md_path.exists() else "")
        json_path = result.outputs.get("json")
        if json_path and json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                self.report_json.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
            except ValueError:
                self.report_json.setPlainText(json_path.read_text(encoding="utf-8"))
        else:
            self.report_json.setPlainText(result.error or "")
        self.files.clear()
        for fmt, path in result.outputs.items():
            item = QListWidgetItem(f"{fmt.upper():<5} {path}")
            item.setData(0x0100, str(path))
            self.files.addItem(item)
        self.ai_preview.clear()
        self.ai_status.setText("使用设置里的 API Key；没有 Key 不影响本地功能")
        self.ai_button.setEnabled(result.ok)

    # -- outputs ---------------------------------------------------------
    def _selected_output(self) -> Path | None:
        item = self.files.currentItem()
        if item is None:
            return None
        return Path(item.data(0x0100))

    def _open_selected_file(self) -> None:
        path = self._selected_output()
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_selected_dir(self) -> None:
        path = self._selected_output()
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    # -- AI --------------------------------------------------------------
    def start_ai(self) -> None:
        if self.current is None or self.ai_worker is not None:
            return
        profile = self.profile.currentData() or None
        self.ai_button.setEnabled(False)
        self.ai_status.setText("抽取中…")
        self.ai_preview.clear()

        worker = AiWorker(
            self.current.source,
            profile=profile,
            ocr=self.settings.ocr,
        )
        worker.signals.done.connect(self._ai_done)
        worker.signals.failed.connect(self._ai_failed)
        self.ai_worker = worker
        self.pool.start(worker)

    def _ai_done(self, result) -> None:
        self.ai_worker = None
        self.ai_button.setEnabled(True)
        if result.ok:
            stats = result.stats or {}
            self.ai_status.setText(
                f"完成：找到 {stats.get('found', 0)}/{stats.get('fields', 0)} 个字段"
                f"，冲突 {stats.get('conflicts', 0)}，用时 {result.seconds:.1f}s"
            )
            self.ai_preview.setPlainText(
                json.dumps(result.fields, ensure_ascii=False, indent=2)[:20000]
            )
        else:
            self.ai_status.setText(f"失败：{result.error}")
            self.ai_preview.setPlainText(result.error or "")

    def _ai_failed(self, message: str) -> None:
        self.ai_worker = None
        self.ai_button.setEnabled(True)
        self.ai_status.setText(f"失败：{message}")


def _text_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.NoWrap)
    fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    fixed.setPointSize(9)
    view.setFont(fixed)
    return view
