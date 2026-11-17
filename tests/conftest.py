"""Shared fixtures: build small, realistic documents at test time."""

from __future__ import annotations

from pathlib import Path

import pytest

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


@pytest.fixture(scope="session")
def cjk_font() -> Path | None:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


@pytest.fixture
def sample_pdf(tmp_path: Path, cjk_font: Path | None) -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    if cjk_font:
        pdf.add_font("cjk", "", str(cjk_font))
        pdf.set_font("cjk", size=11)
    else:
        pdf.set_font("Helvetica", size=11)

    pdf.cell(0, 8, "2026 Q1 对账明细", border=0)
    pdf.ln(10)
    pdf.cell(0, 6, "本表由财务系统导出，金额单位为元。", border=0)
    pdf.ln(10)

    header = ["月份", "收入", "成本", "毛利"]
    data = [
        ["1月", "1,200.00", "800.00", "400.00"],
        ["2月", "1,350.50", "910.00", "440.50"],
        ["3月", "1,980.00", "1,120.30", "859.70"],
        ["合计", "4,530.50", "2,830.30", "1,700.20"],
    ]
    widths = [35, 45, 45, 45]
    for row in [header, *data]:
        for w, cell in zip(widths, row):
            pdf.cell(w, 8, cell, border=1)
        pdf.ln(8)

    pdf.ln(6)
    pdf.cell(0, 6, "制表：张三", border=0)
    pdf.add_page()
    pdf.cell(0, 6, "第二页：备注", border=0)
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
