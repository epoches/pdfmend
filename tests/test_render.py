from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook

from pdfmend.extract import extract
from pdfmend.quality import score_document
from pdfmend.render import markdown_table, to_html, to_json, to_markdown, to_xlsx


def test_markdown_table_escapes_pipes_and_newlines() -> None:
    out = markdown_table([["a|b", "c"], ["1\n2", "3"]])
    assert "a\\|b" in out
    assert "1<br>2" in out
    assert out.splitlines()[1] == "| --- | --- |"


def test_markdown_has_score_table_and_page_markers(
    sample_pdf: Path, pdf_labels: dict
) -> None:
    report = score_document(extract(sample_pdf))
    md = to_markdown(report)
    assert "质量分" in md
    assert pdf_labels["header"][0] in md
    assert "<!-- page 2 -->" in md
    assert "置信度" in md


def test_xlsx_roundtrip_converts_numbers(sample_xlsx: Path, tmp_path: Path) -> None:
    report = score_document(extract(sample_xlsx))
    out = to_xlsx(report, tmp_path / "out.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames[0] == "_report"
    assert len(wb.sheetnames) == 2
    ws = wb[wb.sheetnames[1]]
    assert ws["C2"].value == 1234.5
    assert ws["D2"].value == 0.12
    assert ws["D2"].number_format == "0.00%"
    assert ws["C3"].value == 8000


def test_json_report_is_valid(sample_pdf: Path, tmp_path: Path) -> None:
    report = score_document(extract(sample_pdf))
    p = to_json(report, tmp_path / "r.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["tool"] == "pdfmend"
    assert data["file"] == "sample.pdf"
    assert isinstance(data["tables"], list) and data["tables"]


def test_html_is_self_contained_and_escaped(sample_pdf: Path) -> None:
    report = score_document(extract(sample_pdf))
    report.tables[0].rows[0][0] = "<script>"
    html = to_html(report)
    assert "&lt;script&gt;" in html
    assert "<style>" in html
    assert "http" not in html.split("<body>")[0]
