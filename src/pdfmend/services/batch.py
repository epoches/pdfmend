"""Batch queue: run the conversion service over many files, report progress.

Framework-free on purpose -- the GUI wraps ``run`` in a QRunnable and the CLI
could reuse it later.  Cancellation is cooperative: the current file finishes,
the rest are marked cancelled.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from pdfmend.services.conversion import (
    DEFAULT_FORMATS,
    ConversionResult,
    convert_file,
)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


@dataclass
class Job:
    source: Path
    status: str = STATUS_PENDING
    result: ConversionResult | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def score(self) -> int:
        return self.result.score if self.result else 0

    def to_dict(self) -> dict:
        data = {
            "source": str(self.source),
            "status": self.status,
            "error": self.error,
        }
        if self.result:
            data["result"] = self.result.to_dict()
        return data


@dataclass
class BatchSummary:
    total: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
    outputs: int = 0
    seconds: float = 0.0
    scores: list[int] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


class BatchRunner:
    """Run ``convert_file`` over a list of jobs, one file at a time."""

    def __init__(self, convert: Callable[..., ConversionResult] = convert_file) -> None:
        self._convert = convert
        self._cancel = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self._cancel.clear()

    def run(
        self,
        jobs: Iterable[Job],
        output_dir=None,
        formats=DEFAULT_FORMATS,
        ocr: str = "never",
        on_job: Callable[[Job], None] | None = None,
        on_progress: Callable[[int, int, Job], None] | None = None,
    ) -> list[Job]:
        items = list(jobs)
        self.reset()
        total = len(items)
        for index, job in enumerate(items, start=1):
            if self.cancelled:
                job.status = STATUS_CANCELLED
                if on_progress:
                    on_progress(index, total, job)
                continue
            job.status = STATUS_RUNNING
            if on_progress:
                on_progress(index, total, job)
            result = self._convert(
                job.source,
                output_dir=output_dir,
                formats=formats,
                ocr=ocr,
            )
            job.result = result
            if result.ok:
                job.status = STATUS_DONE
            else:
                job.status = STATUS_FAILED
                job.error = result.error
            if on_job:
                on_job(job)
            if on_progress:
                on_progress(index, total, job)
        return items


def summarize(jobs: Iterable[Job]) -> BatchSummary:
    items = list(jobs)
    summary = BatchSummary(total=len(items))
    for job in items:
        if job.status == STATUS_DONE:
            summary.done += 1
            summary.outputs += len(job.result.outputs) if job.result else 0
            summary.scores.append(job.score)
        elif job.status == STATUS_FAILED:
            summary.failed += 1
        elif job.status == STATUS_CANCELLED:
            summary.cancelled += 1
        if job.result:
            summary.seconds += job.result.seconds
    return summary
