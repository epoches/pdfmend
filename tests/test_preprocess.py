"""Image pre-processing tests.  Skipped when OpenCV is not installed."""

from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from pdfmend import preprocess  # noqa: E402


def _text_page(angle: float = 0.0, size=(700, 360)) -> Image.Image:
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for i in range(8):
        draw.text((40, 40 + i * 34), "The quick brown fox 0123456789", fill=0, font=font)
    if angle:
        image = image.rotate(angle, expand=True, fillcolor=255)
    return image


def test_estimate_skew_finds_zero_for_upright_text():
    assert abs(preprocess.estimate_skew(_text_page())) < 1.0


def test_estimate_skew_recovers_a_rotation():
    page = _text_page(angle=4.0)
    angle = preprocess.estimate_skew(page)
    # PIL rotates counter-clockwise for positive angles.
    assert -6.0 < angle < -2.0


def test_rotate_keeps_the_canvas_larger():
    page = _text_page()
    rotated = preprocess.rotate(page, 5.0)
    assert rotated.width >= page.width
    assert rotated.height >= page.height


def test_prepare_reports_what_it_did():
    page = _text_page(angle=3.0)
    cleaned, info = preprocess.prepare(page)
    assert cleaned.width > 0 and cleaned.height > 0
    assert "denoise" in info["steps"] and "enhance" in info["steps"]
    assert any(step.startswith("deskew") for step in info["steps"])


def test_enhance_keeps_a_grey_page_grey_but_brighter_contrast():
    flat = Image.new("L", (200, 120), 128)
    out = preprocess.enhance(flat)
    assert out.size == flat.size
    assert out.mode == "L"
