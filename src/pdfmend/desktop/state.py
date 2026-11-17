"""Shared UI state: the file queue and the results both pages read."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pdfmend.services.conversion import ConversionResult, supported


class Workspace(QObject):
    """A tiny observable model; pages never talk to each other directly."""

    files_changed = Signal()
    results_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.files: list[Path] = []
        self.results: list[ConversionResult] = []

    # -- files -----------------------------------------------------------
    def add_files(self, paths) -> int:
        known = {p.resolve() for p in self.files}
        added = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or not supported(path):
                continue
            if path.resolve() in known:
                continue
            known.add(path.resolve())
            self.files.append(path)
            added += 1
        if added:
            self.files_changed.emit()
        return added

    def remove_files(self, paths) -> None:
        drop = {Path(p).resolve() for p in paths}
        before = len(self.files)
        self.files = [p for p in self.files if p.resolve() not in drop]
        if len(self.files) != before:
            self.files_changed.emit()

    def clear_files(self) -> None:
        if self.files:
            self.files = []
            self.files_changed.emit()

    # -- results ---------------------------------------------------------
    def set_results(self, results: list[ConversionResult]) -> None:
        self.results = list(results)
        self.results_changed.emit()

    def clear_results(self) -> None:
        if self.results:
            self.results = []
            self.results_changed.emit()

    def result_for(self, path: Path) -> ConversionResult | None:
        for result in self.results:
            if result.source.resolve() == Path(path).resolve():
                return result
        return None

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)
