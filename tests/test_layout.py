"""Non-standard PDFs: without rules, in columns, with running heads, split pages."""

from __future__ import annotations

from pathlib import Path

import pytest


def _new_pdf(font_path: Path | None):
    from fpdf import FPDF

    pdf = FPDF()
    if font_path:
        pdf.add_font("cjk", "", str(font_path))
    return pdf


def _set_font(pdf, font_path: Path | None, size: float = 10) -> None:
    if font_path:
        pdf.set_font("cjk", size=size)
    else:
        pdf.set_font("Helvetica", size=size)


def build_borderless(path: Path, font_path: Path | None, zh: bool) -> None:
    pdf = _new_pdf(font_path)
    pdf.add_page()
    _set_font(pdf, font_path)
    header = ["项目", "预算", "实际", "差异"] if zh else ["Item", "Budget", "Actual", "Variance"]
    rows = [
        ["人工", "120,000", "131,500", "-11,500"] if zh else ["Labour", "120,000", "131,500", "-11,500"],
        ["差旅", "36,000", "28,400", "7,600"] if zh else ["Travel", "36,000", "28,400", "7,600"],
        ["市场", "80,000", "82,300", "-2,300"] if zh else ["Ads", "80,000", "82,300", "-2,300"],
        ["办公", "12,000", "11,850", "150"] if zh else ["Office", "12,000", "11,850", "150"],
        ["合计", "248,000", "254,050", "-6,050"] if zh else ["Total", "248,000", "254,050", "-6,050"],
    ]
    xs = [20, 75, 115, 155]
    for row in [header, *rows]:
        for x, cell in zip(xs, row):
            pdf.set_xy(x, pdf.get_y())
            pdf.cell(40, 7, cell)
        pdf.ln(7)
    pdf.output(str(path))


def build_two_columns(path: Path) -> None:
    pdf = _new_pdf(None)
    pdf.add_page()
    _set_font(pdf, None, 9)
    left = [
        "Clause 1: this table reconciles",
        "all expenses for the quarter,",
        "amounts are in CNY.",
        "Clause 2: the totals must agree",
        "with the general ledger.",
    ]
    right = [
        "Clause 3: differences over five",
        "thousand yuan need a reason.",
        "Clause 4: prepared by finance,",
        "effective after sign-off.",
    ]
    for x, lines in ((15, left), (115, right)):
        y = 20
        for line in lines:
            pdf.set_xy(x, y)
            pdf.cell(80, 6, line)
            y += 6
    pdf.output(str(path))


def build_running_head(path: Path, pages: int = 3) -> None:
    pdf = _new_pdf(None)
    for page in range(1, pages + 1):
        pdf.add_page()
        _set_font(pdf, None, 8)
        pdf.set_xy(15, 8)
        pdf.cell(0, 5, "ACME Corp Q1 2026 Report")
        _set_font(pdf, None, 10)
        pdf.set_xy(15, 40)
        pdf.cell(0, 6, f"Section {page} body text about the quarter.")
        _set_font(pdf, None, 8)
        pdf.set_xy(15, 280)
        pdf.cell(0, 5, f"Page {page} of {pages}")
    pdf.output(str(path))


def build_continued(path: Path) -> None:
    pdf = _new_pdf(None)
    header = ["Client", "Amount", "Terms"]
    rows = [
        ["Alpha", "120,000", "30"],
        ["Beta", "88,000", "45"],
        ["Gamma", "46,500", "60"],
        ["Delta", "31,200", "30"],
        ["Epsilon", "77,900", "90"],
    ]
    for chunk in (rows[:3], rows[3:]):
        pdf.add_page()
        _set_font(pdf, None, 10)
        y = 30
        for row in [header, *chunk]:
            for i, cell in enumerate(row):
                pdf.set_xy(20 + i * 45, y)
                pdf.cell(45, 8, cell, border=1)
            y += 8
    pdf.output(str(path))


@pytest.fixture
def borderless_pdf(tmp_path: Path, cjk_font, pdf_labels) -> Path:
    out = tmp_path / "borderless.pdf"
    build_borderless(out, cjk_font, zh="对账明细" in pdf_labels["title_token"])
    return out


def test_borderless_table_is_recovered(borderless_pdf: Path) -> None:
    from pdfmend.extract import extract
    from pdfmend.quality import score_document

    doc = extract(borderless_pdf)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.origin == "cluster"
    assert table.shape == "6x4"
    assert table.rows[0][1] in {"Budget", "预算"}
    assert table.rows[5][1] == "248,000"
    report = score_document(doc)
    assert report.score >= 90


def test_two_column_prose_is_not_a_table(tmp_path: Path) -> None:
    from pdfmend.extract import extract

    path = tmp_path / "twocol.pdf"
    build_two_columns(path)
    doc = extract(path)
    assert doc.tables == []
    text = "\n".join(b.text for b in doc.blocks if b.kind == "para")
    assert "Clause 1" in text and "Clause 2" in text
    # reading order: the left column is read before the right one
    assert text.index("Clause 2") < text.index("Clause 3")


def test_running_heads_are_dropped_but_body_kept(tmp_path: Path) -> None:
    from pdfmend.extract import extract

    path = tmp_path / "headfoot.pdf"
    build_running_head(path)
    doc = extract(path)
    body = "\n".join(b.text for b in doc.blocks if b.kind == "para")
    assert "Section 1 body" in body and "Section 3 body" in body
    assert "ACME Corp" not in body
    assert "Page 1 of 3" not in body
    assert doc.meta.get("running_heads")


def test_table_continued_on_next_page_is_merged(tmp_path: Path) -> None:
    from pdfmend.extract import extract

    path = tmp_path / "continued.pdf"
    build_continued(path)
    doc = extract(path)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.shape == "6x3"
    assert table.page == 1 and table.page_end == 2
    assert "continued" in table.flags
    assert table.rows[-1][0] == "Epsilon"


def test_wide_gap_between_runs_gets_a_visible_break() -> None:
    from pdfmend.layout import _gap_text

    # a column gap is not a word space: "2026.2" + "法学" must not fuse
    assert _gap_text("2026.2", "法学", 60.0, 11.0) == "2026.2 法学"
    # normal CJK spacing stays untouched
    assert _gap_text("法学", "硕士", 0.4, 11.0) == "法学硕士"


def test_resume_style_row_keeps_date_and_school_apart(tmp_path: Path) -> None:
    from fpdf import FPDF

    from pdfmend.extract import extract

    path = tmp_path / "resume_row.pdf"
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    pdf.set_xy(15, 30)
    pdf.cell(50, 8, "2025.2 - 2026.2")
    pdf.set_xy(120, 30)
    pdf.cell(60, 8, "Law LLM UNSW")
    pdf.output(str(path))

    doc = extract(path)
    text = "\n".join(b.text for b in doc.blocks if b.kind == "para")
    assert "2026.2" in text and "Law LLM UNSW" in text
    assert "2026.2Law" not in text
    assert "2026.2 Law LLM UNSW" in text
