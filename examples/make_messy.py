"""Demo PDFs that break the usual "just dump the text layer" converters.

Each file targets one failure mode:

* borderless.pdf — a table drawn with whitespace only, no rules at all
* twocol.pdf     — body text in two columns, so a naive text dump interleaves
* headfoot.pdf   — a running head and footer repeated on every page
* continued.pdf  — one table split over two pages, header repeated

Run ``python examples/make_messy.py`` and the files land in ``examples/out``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


def cjk_font() -> Path | None:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


def _pdf(font: Path | None) -> FPDF:
    pdf = FPDF()
    if font:
        pdf.add_font("cjk", "", str(font))
    return pdf


def _font(pdf: FPDF, font: Path | None, size: float) -> None:
    if font:
        pdf.set_font("cjk", size=size)
    else:
        pdf.set_font("Helvetica", size=size)


def borderless(path: Path, font: Path | None) -> None:
    pdf = _pdf(font)
    pdf.add_page()
    _font(pdf, font, 10)
    pdf.cell(0, 8, "2026年一季度费用明细（无表格线）" if font else "Q1 2026 expenses (no rules)")
    pdf.ln(12)
    header = ["项目", "预算", "实际", "差异"] if font else ["Item", "Budget", "Actual", "Variance"]
    rows = [
        ["人工", "120,000", "131,500", "-11,500"],
        ["差旅", "36,000", "28,400", "7,600"],
        ["市场", "80,000", "82,300", "-2,300"],
        ["办公", "12,000", "11,850", "150"],
        ["合计", "248,000", "254,050", "-6,050"],
    ]
    if not font:
        rows = [["Labour", "120,000", "131,500", "-11,500"], ["Travel", "36,000", "28,400", "7,600"],
                ["Ads", "80,000", "82,300", "-2,300"], ["Office", "12,000", "11,850", "150"],
                ["Total", "248,000", "254,050", "-6,050"]]
    xs = [20, 75, 115, 155]
    for row in [header, *rows]:
        for x, cell in zip(xs, row):
            pdf.set_xy(x, pdf.get_y())
            pdf.cell(40, 7, cell)
        pdf.ln(7)
    pdf.output(str(path))


def twocol(path: Path, font: Path | None) -> None:
    pdf = _pdf(font)
    pdf.add_page()
    _font(pdf, font, 9)
    if font:
        left = ["第一条 本表用于核对二季度", "的费用支出情况，所有金额", "均以人民币元为单位。",
                "第二条 表中的合计数应当", "与总账保持一致。"]
        right = ["第三条 差异超过五千元的", "项目需要单独说明原因。", "第四条 本表由财务部编制，",
                 "经负责人签字后生效。"]
    else:
        left = ["Clause 1: this table reconciles", "all expenses for the quarter,",
                "amounts are in CNY.", "Clause 2: the totals must agree",
                "with the general ledger."]
        right = ["Clause 3: differences over five", "thousand yuan need a reason.",
                 "Clause 4: prepared by finance,", "effective after sign-off."]
    for x, lines in ((15, left), (115, right)):
        y = 20
        for line in lines:
            pdf.set_xy(x, y)
            pdf.cell(80, 6, line)
            y += 6
    pdf.output(str(path))


def headfoot(path: Path, font: Path | None) -> None:
    pdf = _pdf(font)
    for page in range(1, 4):
        pdf.add_page()
        _font(pdf, font, 8)
        pdf.set_xy(15, 8)
        pdf.cell(0, 5, "某某公司 2026 年一季度报告" if font else "ACME Corp Q1 2026 Report")
        _font(pdf, font, 10)
        pdf.set_xy(15, 40)
        pdf.cell(0, 6, f"第{page}节正文内容，说明本季度经营情况。" if font else f"Section {page} body text about the quarter.")
        _font(pdf, font, 8)
        pdf.set_xy(15, 280)
        pdf.cell(0, 5, f"第 {page} 页 / 共 3 页" if font else f"Page {page} of 3")
    pdf.output(str(path))


def continued(path: Path, font: Path | None) -> None:
    pdf = _pdf(font)
    header = ["客户", "金额", "账期"] if font else ["Client", "Amount", "Terms"]
    rows = [
        ["甲公司", "120,000", "30"],
        ["乙公司", "88,000", "45"],
        ["丙公司", "46,500", "60"],
        ["丁公司", "31,200", "30"],
        ["戊公司", "77,900", "90"],
    ]
    if not font:
        rows = [["Alpha", "120,000", "30"], ["Beta", "88,000", "45"], ["Gamma", "46,500", "60"],
                ["Delta", "31,200", "30"], ["Epsilon", "77,900", "90"]]
    for chunk in (rows[:3], rows[3:]):
        pdf.add_page()
        _font(pdf, font, 10)
        y = 30
        for row in [header, *chunk]:
            for i, cell in enumerate(row):
                pdf.set_xy(20 + i * 45, y)
                pdf.cell(45, 8, cell, border=1)
            y += 8
    pdf.output(str(path))


def main() -> None:
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    font = cjk_font()
    for name, build in [
        ("messy_borderless.pdf", borderless),
        ("messy_twocol.pdf", twocol),
        ("messy_headfoot.pdf", headfoot),
        ("messy_continued.pdf", continued),
    ]:
        target = out / name
        build(target, font)
        print(f"wrote {target}")
    if font is None:
        print("note: no CJK font found, samples are in English", file=sys.stderr)


if __name__ == "__main__":
    main()
