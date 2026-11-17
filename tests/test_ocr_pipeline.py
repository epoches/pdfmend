"""OCR page pipeline wired into extract(): faked engine, real PDF plumbing."""

from __future__ import annotations

import pytest

from pdfmend import ocr as ocr_mod
from pdfmend import preprocess
from pdfmend import extract as extract_mod
from pdfmend.extract import extract
from pdfmend.quality import score_document


@pytest.fixture
def fake_ocr(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    monkeypatch.setattr(
        preprocess,
        "prepare",
        lambda image, do_deskew=True: (image, {"angle": 0.0, "steps": ["fake"]}),
    )

    def fake_ocr_image(image, lang="ch"):
        return [
            ocr_mod.Line("银行流水第 1 页", conf=0.95, top=20, left=10, height=12),
            ocr_mod.Line("合计 4,530.50", conf=0.9, top=34, left=10, height=12),
        ]

    monkeypatch.setattr(ocr_mod, "ocr_image", fake_ocr_image)


def test_scanned_page_is_read_and_flagged(blank_pdf, fake_ocr):
    doc = extract(blank_pdf, ocr="always")
    assert doc.meta["ocr_pages"] == [1]
    assert doc.scanned_pages == []
    assert "银行流水" in " ".join(b.text for b in doc.blocks if b.text)
    report = score_document(doc)
    assert any("OCR" in reason for reason in report.reasons)


def test_auto_skips_pages_without_an_image(blank_pdf, fake_ocr):
    """A blank/cover page is not worth a 20 s OCR warm-up."""
    doc = extract(blank_pdf, ocr="auto")
    assert doc.meta.get("ocr_pages") is None
    assert doc.scanned_pages == [1]
    assert any("没有文本层" in reason for reason in score_document(doc).reasons)


def test_has_page_image_measures_coverage():
    class Page:
        width, height = 595.0, 842.0

        def __init__(self, images):
            self.images = images

    assert extract_mod._has_page_image(Page([{"x0": 0, "x1": 595, "top": 0, "bottom": 842}]))
    assert not extract_mod._has_page_image(Page([{"x0": 10, "x1": 60, "top": 10, "bottom": 60}]))
    assert not extract_mod._has_page_image(Page([]))
    assert extract_mod._has_page_image(Page([{"x0": "bad"}]))


def test_ocr_never_keeps_the_old_behaviour(blank_pdf, fake_ocr):
    doc = extract(blank_pdf, ocr="never")
    assert doc.scanned_pages == [1]
    assert doc.meta.get("ocr_pages") is None
    assert any("没有文本层" in reason for reason in score_document(doc).reasons)


def test_ocr_failure_is_reported_not_fatal(blank_pdf, monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)

    def explode(image, lang="ch"):
        raise RuntimeError("model missing")

    monkeypatch.setattr(ocr_mod, "ocr_image", explode)
    monkeypatch.setattr(
        preprocess, "prepare", lambda image, do_deskew=True: (image, {"angle": 0.0, "steps": []})
    )
    doc = extract(blank_pdf, ocr="always")
    assert doc.scanned_pages == [1]
    assert any("model missing" in err for err in doc.meta["ocr_errors"])


def test_unavailable_ocr_keeps_scanned_page(blank_pdf, monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: False)
    doc = extract(blank_pdf, ocr="always")
    assert doc.scanned_pages == [1]
    assert doc.meta.get("ocr_errors")
