"""Background workers: conversion batches and AI extraction off the UI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from pdfmend.services import ai_extraction
from pdfmend.services.batch import STATUS_RUNNING, BatchRunner, Job


class BatchSignals(QObject):
    job_started = Signal(object)           # Job
    job_finished = Signal(object)          # Job
    progress = Signal(int, int, object)    # index, total, Job
    done = Signal(list)                    # list[Job]
    failed = Signal(str)


class BatchWorker(QRunnable):
    """Run ``BatchRunner`` in QThreadPool and report through signals."""

    def __init__(
        self,
        jobs: list[Job],
        output_dir: Path | None,
        formats: list[str],
        ocr: str,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = BatchSignals()
        self.jobs = jobs
        self.output_dir = output_dir
        self.formats = formats
        self.ocr = ocr
        self.runner = BatchRunner()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.runner.cancel()

    @Slot()
    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        try:
            runner = self.runner

            def on_job(job: Job) -> None:
                self.signals.job_finished.emit(job)

            def on_progress(index: int, total: int, job: Job) -> None:
                if job.status == STATUS_RUNNING:
                    self.signals.job_started.emit(job)
                self.signals.progress.emit(index, total, job)

            done = runner.run(
                self.jobs,
                output_dir=self.output_dir,
                formats=self.formats,
                ocr=self.ocr,
                on_job=on_job,
                on_progress=on_progress,
            )
            self.signals.done.emit(done)
        except Exception as exc:  # noqa: BLE001 - never crash the pool thread
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class AiSignals(QObject):
    done = Signal(object)   # ai_extraction.ExtractionResult
    failed = Signal(str)


class AiWorker(QRunnable):
    """Run one field-extraction call in the background."""

    def __init__(
        self,
        source: Path,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        ocr: str = "auto",
        vision: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = AiSignals()
        self.source = source
        self.profile = profile
        self.provider = provider
        self.model = model
        self.ocr = ocr
        self.vision = vision

    @Slot()
    def run(self) -> None:
        try:
            result = ai_extraction.extract_fields(
                self.source,
                profile=self.profile,
                provider=self.provider,
                model=self.model,
                ocr=self.ocr,
                vision=self.vision,
            )
            self.signals.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
