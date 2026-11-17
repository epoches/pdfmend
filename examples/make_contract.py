"""A plain Chinese service contract, for testing contract structure + fields.

It has the shapes real contracts use: a title, a number, two parties, numbered
chapters ("第一条"), clauses ("1.1"), a nested list, an amount in words and in
digits, and a signature block.  Nothing tricky -- it is the baseline a contract
parser must get right before touching scans.

Run ``python examples/make_contract.py`` and the file lands in ``examples/out``.
"""

from __future__ import annotations

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
    for path in FONT_CANDIDATES:
        if path.exists():
            return path
    return None


def main() -> int:
    out = Path(__file__).with_name("out")
    out.mkdir(exist_ok=True)
    font = cjk_font()

    pdf = FPDF()
    pdf.add_page()
    if font:
        pdf.add_font("cjk", "", str(font))
        pdf.set_font("cjk", size=10)
    else:
        pdf.set_font("Helvetica", size=10)

    def line(text: str, size: float | None = None, gap: float = 6) -> None:
        if font:
            pdf.set_font("cjk", size=size or 10)
        else:
            pdf.set_font("Helvetica", size=size or 10)
        pdf.multi_cell(0, gap, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    line("技术服务合同", size=16, gap=10)
    line("合同编号：HT-2026-001")
    line("甲方：北京某某科技有限公司")
    line("乙方：上海某某信息技术有限公司")
    line("甲方统一社会信用代码：91110108MA01ABCD2X")
    line("乙方统一社会信用代码：91310115MA1K3XYZ7Y")
    line("")
    line("第一条 服务内容", size=12)
    line("1.1 乙方向甲方提供软件开发服务。")
    line("1.2 服务内容包括：")
    line("（1）系统架构设计；")
    line("（2）数据库设计；")
    line("（3）接口开发与测试。")
    line("第二条 合同金额", size=12)
    line("本合同总金额为人民币100000元（大写：壹拾万元整），币种为人民币。")
    line("第三条 付款方式", size=12)
    line("1. 合同签订后支付30%。")
    line("2. 项目验收后支付70%。")
    line("第四条 违约责任", size=12)
    line("任何一方违反本合同约定，应承担相应违约责任；争议由甲方所在地人民法院管辖。")
    line("")
    line("甲方（盖章）：")
    line("乙方（盖章）：")
    line("签订日期：2026年11月15日")

    target = out / "contract_sample.pdf"
    pdf.output(str(target))
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
