"""Desktop GUI tests: they run offscreen and skip when PySide6 is missing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp) -> "MainWindow":
    from pdfmend.config import settings as config
    from pdfmend.desktop.main_window import MainWindow

    store = config.memory_store()
    settings = config.Settings(store)
    win = MainWindow(settings)
    yield win
    win.close()
    win.deleteLater()


def test_window_has_four_pages(window) -> None:
    assert window.stack.count() == 4
    assert window.windowTitle().startswith("PDFMend ")
    assert window.stack.currentIndex() == 0


def test_nav_switches_pages(window) -> None:
    window.go(3)
    assert window.stack.currentIndex() == 3
    assert window.nav_group.button(3).isChecked()
    window.go(0)
    assert window.stack.currentIndex() == 0


def test_adding_a_file_fills_the_queue(window, sample_pdf: Path) -> None:
    window._add_files([str(sample_pdf)])
    assert window.workspace.files == [sample_pdf]
    assert window.stack.currentIndex() == 1
    assert window.convert.table.rowCount() == 1
    assert "1 个文件" in window.convert.summary.text()


def test_convert_through_the_gui(window, sample_pdf: Path, tmp_path: Path) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    outdir = tmp_path / "out"
    window._add_files([str(sample_pdf)])
    window.convert.outdir.setText(str(outdir))
    window.convert.start()

    loop = QEventLoop()
    window.convert.finished.connect(lambda _results: loop.quit())
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    assert window.workspace.results, "GUI produced no result"
    result = window.workspace.results[0]
    assert result.ok, result.error
    assert set(result.outputs) == {"md", "xlsx", "json", "html"}
    assert window.stack.currentIndex() == 2
    assert window.results.markdown.toPlainText()
    assert window.results.ai_button.isEnabled()


def test_failed_document_still_lands_in_results(window, tmp_path: Path) -> None:
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf")
    window._add_files([str(bad)])
    window.convert.outdir.setText(str(tmp_path / "out"))
    window.convert.start()

    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    window.convert.finished.connect(lambda _results: loop.quit())
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    assert window.workspace.results
    assert window.results.card is not None


def test_settings_page_saves_into_the_store(window, tmp_path: Path) -> None:
    page = window.settings_page
    page.outdir.setText(str(tmp_path))
    page.ocr.setCurrentIndex(page.ocr.findData("never"))
    page.theme.setCurrentIndex(page.theme.findData("dark"))
    page.save()
    assert window.settings.output_dir == tmp_path
    assert window.settings.ocr == "never"
    assert window.settings.theme == "dark"


def test_donation_dialog_builds(qapp) -> None:
    from pdfmend.desktop.dialogs.donation import DonationDialog

    dialog = DonationDialog()
    assert dialog.windowTitle() == "支持作者"
    dialog.close()
