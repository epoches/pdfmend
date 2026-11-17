"""Build the demo files shown in the README.

    python examples/make_demo.py

Writes examples/out/demo_statement.pdf and examples/out/demo_scanned.pdf.
Uses a CJK font when one is installed; falls back to Latin text otherwise.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

FONTS = [
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/Deng.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]

HEADER1 = ["科目", "本期发生额", "", "上期发生额", "", "变动"]
HEADER2 = ["", "借方", "贷方", "借方", "贷方", "比例"]
ROWS = [
    ["营业收入", "1,284,300.00", "0.00", "1,102,450.00", "0.00", "16.5%"],
    ["营业成本", "612,800.00", "0.00", "588,300.00", "0.00", "4.2%"],
    ["销售费用", "98,400.00", "0.00", "87,100.00", "0.00", "13.0%"],
    ["管理费用", "143,200.00", "0.00", "151,900.00", "0.00", "-5.7%"],
    ["财务费用", "12,600.00", "0.00", "9,800.00", "0.00", "28.6%"],
    ["利润总额", "417,300.00", "0.00", "265,350.00", "0.00", "57.3%"],
]
WIDTHS = [40, 32, 32, 32, 32, 22]


def font(pdf: FPDF) -> None:
    for f in FONTS:
        if f.exists():
            pdf.add_font("cjk", "", str(f))
            pdf.set_font("cjk", size=10)
            return
    pdf.set_font("Helvetica", size=10)


def statement(path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    font(pdf)
    pdf.set_font_size(14)
    pdf.cell(0, 10, "2026 年度利润表（节选）")
    pdf.ln(12)
    font(pdf)
    pdf.cell(0, 8, "编制单位：示例科技有限公司    单位：元")
    pdf.ln(12)

    for row in (HEADER1, HEADER2):
        for w, c in zip(WIDTHS, row):
            pdf.cell(w, 8, c, border=1)
        pdf.ln(8)
    for row in ROWS:
        for w, c in zip(WIDTHS, row):
            pdf.cell(w, 8, c, border=1, align="R")
        pdf.ln(8)

    pdf.ln(6)
    pdf.cell(0, 6, "注：本表未经审计，金额单位为人民币元。")
    pdf.add_page()
    font(pdf)
    pdf.cell(0, 8, "附注")
    pdf.ln(10)
    pdf.multi_cell(0, 6, "营业收入较上期增长 16.5%，主要来自华东区新签合同。\n营业成本增速低于收入增速，毛利率提升 2.1 个百分点。")
    out = path / "demo_statement.pdf"
    pdf.output(str(out))
    print(out)


def scanned(path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_fill_color(230, 230, 230)
    pdf.rect(20, 30, 170, 220, style="DF")
    pdf.set_fill_color(120, 120, 120)
    for i in range(8):
        pdf.rect(30, 50 + i * 20, 150, 12, style="DF")
    out = path / "demo_scanned.pdf"
    pdf.output(str(out))
    print(out)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    statement(out)
    scanned(out)
