"""Shared fixtures: build small, realistic documents at test time."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


@pytest.fixture(scope="session")
def cjk_font() -> Path | None:
    if os.environ.get("PDFMEND_NO_CJK_FONT"):
        return None
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


def _labels(zh: bool) -> dict:
    if zh:
        return {
            "title": "2026 Q1 对账明细",
            "title_token": "对账明细",
            "note": "本表由财务系统导出，金额单位为元。",
            "note_token": "财务系统导出",
            "header": ["月份", "收入", "成本", "毛利"],
            "months": ["1月", "2月", "3月"],
            "total": "合计",
            "footer": "制表：张三",
            "page2": "第二页：备注",
        }
    return {
        "title": "2026 Q1 Reconciliation",
        "title_token": "Reconciliation",
        "note": "Exported by the finance system; amounts in CNY.",
        "note_token": "finance system",
        "header": ["Month", "Income", "Cost", "Gross"],
        "months": ["Jan", "Feb", "Mar"],
        "total": "Total",
        "footer": "Prepared by: Zhang San",
        "page2": "Page 2: notes",
    }


@pytest.fixture
def pdf_labels(cjk_font: Path | None) -> dict:
    return _labels(cjk_font is not None)


@pytest.fixture
def sample_pdf(tmp_path: Path, cjk_font: Path | None, pdf_labels: dict) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    if cjk_font:
        pdf.add_font("cjk", "", str(cjk_font))
        pdf.set_font("cjk", size=11)
    else:
        pdf.set_font("Helvetica", size=11)

    pdf.cell(0, 8, pdf_labels["title"], border=0)
    pdf.ln(10)
    pdf.cell(0, 6, pdf_labels["note"], border=0)
    pdf.ln(10)

    header = pdf_labels["header"]
    m1, m2, m3 = pdf_labels["months"]
    data = [
        [m1, "1,200.00", "800.00", "400.00"],
        [m2, "1,350.50", "910.00", "440.50"],
        [m3, "1,980.00", "1,120.30", "859.70"],
        [pdf_labels["total"], "4,530.50", "2,830.30", "1,700.20"],
    ]
    widths = [35, 45, 45, 45]
    for row in [header, *data]:
        for w, cell in zip(widths, row):
            pdf.cell(w, 8, cell, border=1)
        pdf.ln(8)

    pdf.ln(6)
    pdf.cell(0, 6, pdf_labels["footer"], border=0)
    pdf.add_page()
    pdf.cell(0, 6, pdf_labels["page2"], border=0)
    out = tmp_path / "sample.pdf"
    pdf.output(str(out))
    return out


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    out = tmp_path / "blank.pdf"
    pdf.output(str(out))
    return out


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("季度报告", level=1)
    d.add_paragraph("这是一段说明文字。")
    d.add_heading("数据", level=2)
    t = d.add_table(rows=4, cols=3)
    values = [
        ("地区", "销量", "同比"),
        ("华东", "1200", "12%"),
        ("华南", "980", "-3%"),
        ("合计", "2180", ""),
    ]
    for i, row in enumerate(values):
        for j, v in enumerate(row):
            t.cell(i, j).text = v
    t.cell(1, 1).merge(t.cell(1, 2))
    out = tmp_path / "sample.docx"
    d.save(str(out))
    return out


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "流水"
    ws.append(["日期", "摘要", "金额", "占比"])
    ws.append(["2026-01-05", "收款", "1,234.50", "12%"])
    ws.append(["2026-01-06", "付款", "¥8,000", "0.5%"])
    ws.append(["2026-01-07", "手续费", "-6.00", ""])
    out = tmp_path / "sample.xlsx"
    wb.save(str(out))
    return out
