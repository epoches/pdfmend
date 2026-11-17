"""Build an image-only "scan" PDF so OCR can be tested end to end.

The page is rasterised at 200 dpi, rotated slightly and grained, then embedded
into a PDF with no text layer.  When PaddleOCR is installed:

    python examples/make_scan.py
    pdfmend examples/out/scan_sample.pdf --ocr auto -o examples/out

The ground truth is printed at the end so the OCR output can be compared.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DPI = 200
A4 = (int(8.27 * DPI), int(11.69 * DPI))

LINES = [
    "2026 年第一季度对账明细",
    "本表由财务系统导出，金额单位为元。",
    "月份        收入          成本",
    "1月         1,200.00      800.00",
    "2月         1,350.50      910.00",
    "3月         1,980.00      1,120.30",
    "合计        4,530.50      2,830.30",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build(target: Path, angle: float = -1.8) -> Path:
    image = Image.new("RGB", A4, "white")
    draw = ImageDraw.Draw(image)
    font = _font(46)
    y = 220
    for line in LINES:
        draw.text((180, y), line, fill=(25, 25, 25), font=font)
        y += 90
    image = image.rotate(angle, resample=Image.BICUBIC, fillcolor="white", expand=False)

    # a little sensor grain so denoise has something to do
    pixels = image.load()
    rng = random.Random(7)
    for _ in range(6000):
        x, y = rng.randrange(A4[0]), rng.randrange(A4[1])
        shade = rng.choice((180, 200, 235))
        pixels[x, y] = (shade, shade, shade)

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "scan_sample.png"
    image.save(png, "PNG")

    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.image(str(png), x=0, y=0, w=210, h=297)
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(target))
    return target


if __name__ == "__main__":
    path = build(OUT / "scan_sample.pdf")
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")
    print("ground truth:")
    for line in LINES:
        print("  " + line)
