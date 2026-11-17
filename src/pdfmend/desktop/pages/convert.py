"""Convert page: the queue, the options and the progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from pdfmend.config.settings import Settings
from pdfmend.desktop.state import Workspace
from pdfmend.desktop.widgets.drop_zone import DropZone
from pdfmend.desktop.widgets.file_list import FileTable
from pdfmend.desktop.workers import BatchWorker
from pdfmend.services.batch import STATUS_DONE, STATUS_FAILED, Job

FORMATS = (("md", "Markdown"), ("xlsx", "Excel"), ("json", "JSON"), ("html", "HTML 报告"))
OCR_MODES = (("auto", "自动（仅扫描页）"), ("always", "总是 OCR"), ("never", "关闭"))


class ConvertPage(QWidget):
    files_added = Signal(list)
    finished = Signal(list)

    def __init__(self, workspace: Workspace, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.settings = settings
        self.pool = QThreadPool.globalInstance()
        self.worker: BatchWorker | None = None
        self._jobs: list[Job] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("文件转换")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.drop = DropZone("把文件或文件夹拖进来")
        self.drop.setMinimumHeight(110)
        layout.addWidget(self.drop)

        self.table = FileTable(workspace)
        layout.addWidget(self.table, 1)

        tools = QHBoxLayout()
        for label, slot in (
            ("添加文件", self.pick_files),
            ("添加文件夹", self.pick_folder),
            ("移除所选", self.remove_selected),
            ("清空", workspace.clear_files),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            tools.addWidget(button)
        tools.addStretch(1)
        self.summary = QLabel("0 个文件")
        self.summary.setObjectName("Muted")
        tools.addWidget(self.summary)
        layout.addLayout(tools)

        options = QGridLayout()
        options.setHorizontalSpacing(10)
        options.setVerticalSpacing(8)
        options.addWidget(QLabel("输出目录"), 0, 0)
        self.outdir = QLineEdit(str(settings.output_dir or ""))
        self.outdir.setPlaceholderText("留空 = 与源文件同目录")
        options.addWidget(self.outdir, 0, 1)
        pick = QPushButton("浏览…")
        pick.clicked.connect(self.pick_outdir)
        options.addWidget(pick, 0, 2)

        options.addWidget(QLabel("导出格式"), 1, 0)
        fmt_row = QHBoxLayout()
        self.fmt_boxes: dict[str, QCheckBox] = {}
        chosen = settings.formats
        for key, label in FORMATS:
            box = QCheckBox(label)
            box.setChecked(key in chosen)
            self.fmt_boxes[key] = box
            fmt_row.addWidget(box)
        fmt_row.addStretch(1)
        options.addLayout(fmt_row, 1, 1, 1, 2)

        options.addWidget(QLabel("OCR"), 2, 0)
        self.ocr = QComboBox()
        for key, label in OCR_MODES:
            self.ocr.addItem(label, key)
        index = max(0, self.ocr.findData(settings.ocr))
        self.ocr.setCurrentIndex(index)
        ocr_hint = QLabel("需要安装 pdfmend[ocr]；首次识别较慢")
        ocr_hint.setObjectName("Muted")
        options.addWidget(self.ocr, 2, 1)
        options.addWidget(ocr_hint, 2, 2)
        options.setColumnStretch(1, 1)
        layout.addLayout(options)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始转换")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.status = QLabel("就绪")
        self.status.setObjectName("Muted")
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.status)
        layout.addLayout(actions)

        self.drop.paths_dropped.connect(self.files_added.emit)
        self.drop.browse_requested.connect(self.pick_files)
        workspace.files_changed.connect(self._sync_summary)
        self._sync_summary()

    # -- file picking ----------------------------------------------------
    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "添加文件", str(self.settings.output_dir or Path.home()),
            "文档 (*.pdf *.docx *.xlsx *.pptx)",
        )
        if files:
            self.files_added.emit(files)

    def pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "添加文件夹", str(Path.home()))
        if folder:
            self.files_added.emit([folder])

    def pick_outdir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", str(Path.home()))
        if folder:
            self.outdir.setText(folder)

    def remove_selected(self) -> None:
        self.workspace.remove_files(self.table.selected_paths())

    # -- conversion ------------------------------------------------------
    def _selected_formats(self) -> list[str]:
        return [key for key, box in self.fmt_boxes.items() if box.isChecked()]

    def _sync_summary(self) -> None:
        count = len(self.workspace.files)
        self.summary.setText(f"{count} 个文件")
        self.start_button.setEnabled(count > 0 or self.worker is not None)

    def sync_settings(self) -> None:
        """Re-read the saved settings after the settings page changes them."""
        self.outdir.setText(str(self.settings.output_dir or ""))
        for key, box in self.fmt_boxes.items():
            box.setChecked(key in self.settings.formats)
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(self.settings.ocr)))

    def start(self) -> None:
        if self.worker is not None:
            return
        if not self.workspace.files:
            self.status.setText("先添加文件")
            return
        formats = self._selected_formats()
        if not formats:
            self.status.setText("至少选一种导出格式")
            return
        outdir = Path(self.outdir.text().strip()) if self.outdir.text().strip() else None
        self.settings.formats = formats
        self.settings.ocr = self.ocr.currentData()
        if outdir:
            self.settings.output_dir = outdir

        self._jobs = [Job(path) for path in self.workspace.files]
        for job in self._jobs:
            self.table.set_status(job.source, "pending")
        self.progress.setValue(0)
        self.progress.setMaximum(len(self._jobs))
        self.status.setText("开始处理…")
        self._set_running(True)

        worker = BatchWorker(self._jobs, outdir, formats, self.ocr.currentData())
        worker.signals.job_started.connect(self._job_started)
        worker.signals.job_finished.connect(self._job_finished)
        worker.signals.progress.connect(self._progress)
        worker.signals.done.connect(self._done)
        worker.signals.failed.connect(self._failed)
        self.worker = worker
        self.pool.start(worker)

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status.setText("正在取消…（当前文件会先做完）")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.drop.setEnabled(not running)

    def _job_started(self, job: Job) -> None:
        self.table.set_status(job.source, "running")
        self.status.setText(f"处理中：{job.source.name}")

    def _job_finished(self, job: Job) -> None:
        status = "done" if job.status == STATUS_DONE else "failed"
        if job.status not in (STATUS_DONE, STATUS_FAILED):
            status = job.status
        self.table.set_status(job.source, status, job.score if job.status == STATUS_DONE else None)

    def _progress(self, index: int, total: int, job: Job) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(index if job.status != "running" else index - 1)

    def _done(self, jobs: list[Job]) -> None:
        self.worker = None
        self._set_running(False)
        results = [job.result for job in jobs if job.result is not None]
        self.workspace.set_results(results)
        done = sum(1 for job in jobs if job.status == STATUS_DONE)
        failed = sum(1 for job in jobs if job.status == STATUS_FAILED)
        self.progress.setValue(self.progress.maximum())
        self.status.setText(f"完成 {done} 个，失败 {failed} 个")
        for result in results:
            if result.ok:
                self.settings.add_recent(result.source)
        self.finished.emit(results)

    def _failed(self, message: str) -> None:
        self.worker = None
        self._set_running(False)
        self.status.setText(f"出错：{message}")
