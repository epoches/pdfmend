"""Image cleanup before OCR: denoise, deskew, contrast.

Scans and phone photos arrive rotated, grainy and greyish.  PaddleOCR is much
better on upright, high-contrast text, so we normalise the page first.

OpenCV is an optional dependency (``pip install "pdfmend[ocr]"``).  Nothing in
here is imported by the default install path, so ``pdfmend`` keeps working
without it.
"""

from __future__ import annotations

try:  # numpy ships with the ocr extra; keep the module importable without it
    import numpy as np
except ImportError:  # pragma: no cover - depends on install
    np = None  # type: ignore[assignment]

from PIL import Image


class DependencyError(RuntimeError):
    """Optional imaging stack is missing."""


def _np():
    if np is None:
        raise DependencyError('图像预处理需要 numpy：pip install "pdfmend[ocr]"')
    return np


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - depends on install
        raise DependencyError(
            '图像预处理需要 OpenCV：pip install "pdfmend[ocr]"'
        ) from exc
    return cv2


def to_rgb(image: Image.Image) -> np.ndarray:
    _np()
    return np.asarray(image.convert("RGB"))


def _gray(image: Image.Image) -> np.ndarray:
    cv2 = _cv2()
    return cv2.cvtColor(to_rgb(image), cv2.COLOR_RGB2GRAY)


def estimate_skew(image: Image.Image, max_angle: float = 10.0, step: float = 0.25) -> float:
    """Return the rotation (degrees) that makes text lines horizontal.

    Uses a projection profile: rotate a downscaled binarised copy through a
    range of angles and keep the one with the sharpest row histogram.  The
    correction angle is returned, i.e. rotate the page by ``-estimate`` if you
    rotate clockwise.
    """
    cv2 = _cv2()
    _np()
    gray = _gray(image)
    h, w = gray.shape[:2]
    if h == 0 or w == 0:
        return 0.0
    scale = min(1.0, 900.0 / max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    hh, ww = binary.shape[:2]
    center = (ww / 2.0, hh / 2.0)
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 1e-9, step):
        matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        rotated = cv2.warpAffine(
            binary, matrix, (ww, hh), flags=cv2.INTER_NEAREST, borderValue=0
        )
        projection = rotated.sum(axis=1, dtype=np.float64)
        score = float(((projection[1:] - projection[:-1]) ** 2).sum())
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def rotate(image: Image.Image, angle: float) -> Image.Image:
    """Rotate around the centre and grow the canvas so nothing is clipped."""
    cv2 = _cv2()
    _np()
    if abs(angle) < 1e-6:
        return image
    gray = _gray(image)
    h, w = gray.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
    matrix[0, 2] += new_w / 2.0 - center[0]
    matrix[1, 2] += new_h / 2.0 - center[1]
    out = cv2.warpAffine(
        gray, matrix, (new_w, new_h), flags=cv2.INTER_CUBIC, borderValue=255
    )
    return Image.fromarray(out)


def denoise(image: Image.Image, strength: float = 7.0) -> Image.Image:
    """Non-local means: removes sensor grain without eating thin strokes."""
    cv2 = _cv2()
    _np()
    gray = _gray(image)
    out = cv2.fastNlMeansDenoising(
        gray, None, h=float(strength), templateWindowSize=7, searchWindowSize=21
    )
    return Image.fromarray(out)


def enhance(image: Image.Image, clip: float = 2.0) -> Image.Image:
    """CLAHE for uneven lighting, then a light unsharp mask."""
    cv2 = _cv2()
    _np()
    gray = _gray(image)
    clahe = cv2.createCLAHE(clipLimit=float(clip), tileGridSize=(8, 8))
    equalised = clahe.apply(gray)
    blurred = cv2.GaussianBlur(equalised, (0, 0), 1.0)
    sharpened = cv2.addWeighted(equalised, 1.5, blurred, -0.5, 0)
    return Image.fromarray(sharpened)


def prepare(image: Image.Image, do_deskew: bool = True) -> tuple[Image.Image, dict]:
    """Denoise -> deskew -> enhance.  Returns the image and what was done."""
    steps: list[str] = []
    page = denoise(image)
    steps.append("denoise")
    angle = 0.0
    if do_deskew:
        angle = estimate_skew(page)
        if abs(angle) >= 0.25:
            page = rotate(page, angle)
            steps.append(f"deskew {angle:+.2f}deg")
    page = enhance(page)
    steps.append("enhance")
    return page, {"angle": round(angle, 2), "steps": steps}
