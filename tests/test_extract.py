from __future__ import annotations

from pathlib import Path

import pytest

from pdfmend.extract import extract
from pdfmend.quality import score_document


def test_pdf_extracts_drawn_table(sample_pdf: Path, pdf_labels: dict) -> None:
    doc = extract(sample_pdf)
    assert doc.kind == "pdf"
    assert doc.pages == 2
    assert doc.tables, "应至少识别出一张表"
    t = doc.tables[0]
    assert t.n_rows >= 4
    assert t.n_cols >= 3
    flat = [c for row in t.rows for c in row]
    assert pdf_labels["header"][0] in flat
    assert pdf_labels["total"] in flat


def test_pdf_text_is_kept_outside_tables(sample_pdf: Path, pdf_labels: dict) -> None:
    doc = extract(sample_pdf)
    text = " ".join(b.text for b in doc.blocks if b.kind == "para")
    assert pdf_labels["title_token"] in text
    assert pdf_labels["note_token"] in text


def test_pdf_table_body_not_duplicated_in_text(sample_pdf: Path) -> None:
    doc = extract(sample_pdf)
    text = " ".join(b.text for b in doc.blocks if b.kind == "para")
    assert "1,980.00" not in text, "表格正文不应再出现在段落文本里"


def test_blank_pdf_is_reported_as_scanned(blank_pdf: Path) -> None:
    doc = extract(blank_pdf)
    assert doc.scanned_pages == [1]
    report = score_document(doc)
    assert any("OCR" in r or "扫描" in r for r in report.reasons)


def test_docx_keeps_order_and_headings(sample_docx: Path) -> None:
    doc = extract(sample_docx)
    kinds = [b.kind for b in doc.blocks]
    assert kinds[0] == "heading"
    assert kinds.index("heading") < kinds.index("para") < kinds.index("table")
    levels = [b.level for b in doc.blocks if b.kind == "heading"]
    assert levels == [1, 2]
    t = doc.tables[0]
    assert t.rows[0] == ["地区", "销量", "同比"]
    assert t.rows[1][:2] == ["华东", "1200 12%"]
    assert t.rows[1][2] == ""


def test_docx_merged_cell_is_not_repeated(sample_docx: Path) -> None:
    doc = extract(sample_docx)
    t = doc.tables[0]
    assert t.rows[1].count("1200 12%") == 1


def test_xlsx_reads_sheets_and_keeps_raw_values(sample_xlsx: Path) -> None:
    doc = extract(sample_xlsx)
    assert doc.kind == "xlsx"
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert t.rows[0] == ["日期", "摘要", "金额", "占比"]
    assert "1,234.50" in t.rows[1]
    assert any(f.startswith("sheet:") for f in t.flags)


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        extract(p)
