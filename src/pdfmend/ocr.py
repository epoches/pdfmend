"""PaddleOCR adapter (optional).

PaddleOCR is optional and heavy (paddlepaddle is ~100 MB).  ``pdfmend`` only
calls into it when a page has no text layer and the user asked for OCR
(``--ocr auto`` / ``--ocr always``).  If it is missing we say so instead of
silently returning nothing.

The parsing helpers are pure functions so they can be tested without paddle
installed; PaddleOCR 2.x and 3.x return different shapes and both are handled.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


class OcrUnavailable(RuntimeError):
    """PaddleOCR (or paddlepaddle) is not installed."""


@dataclass(frozen=True)
class Line:
    text: str
    conf: float = 0.0
    top: float = 0.0
    left: float = 0.0
    height: float = 0.0


_ENGINES: dict[str, object] = {}


def available() -> bool:
    try:
        import paddleocr  # noqa: F401
    except Exception:
        return False
    return True


def _engine(lang: str = "ch"):
    if lang in _ENGINES:
        return _ENGINES[lang]
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # pragma: no cover - depends on install
        raise OcrUnavailable('PaddleOCR 未安装：pip install "pdfmend[ocr]"') from exc
    try:
        engine = PaddleOCR(lang=lang, use_angle_cls=True, show_log=False)
    except (TypeError, ValueError):  # 3.x dropped these kwargs
        engine = PaddleOCR(lang=lang)
    _ENGINES[lang] = engine
    return engine


def _line_from_points(points, text: str, conf: float) -> Line:
    box = np.asarray(points, dtype=float).reshape(-1, 2)
    top = float(box[:, 1].min())
    left = float(box[:, 0].min())
    bottom = float(box[:, 1].max())
    return Line(str(text), float(conf), top, left, max(0.0, bottom - top))


def _is_entry(obj) -> bool:
    """2.x entry: [four_points, (text, score)]."""
    return (
        isinstance(obj, (list, tuple))
        and len(obj) == 2
        and isinstance(obj[0], (list, tuple, np.ndarray))
        and isinstance(obj[1], (list, tuple))
        and len(obj[1]) == 2
        and isinstance(obj[1][0], str)
    )


def _from_dict(item: dict) -> list[Line]:
    """3.x shape: {'rec_texts': [...], 'rec_scores': [...], 'rec_boxes': ...}."""
    texts = item.get("rec_texts") or []
    scores = item.get("rec_scores") or []
    boxes = item.get("rec_boxes")
    lines: list[Line] = []
    for index, text in enumerate(texts):
        if not str(text).strip():
            continue
        conf = float(scores[index]) if index < len(scores) else 0.0
        if boxes is not None and index < len(boxes):
            lines.append(_line_from_points(boxes[index], text, conf))
        else:
            lines.append(Line(str(text), conf))
    return lines


def _walk_raw(raw, out: list[Line]) -> None:
    if raw is None:
        return
    if isinstance(raw, dict):
        out.extend(_from_dict(raw))
        return
    if _is_entry(raw):
        points, payload = raw[0], raw[1]
        if str(payload[0]).strip():
            out.append(_line_from_points(points, payload[0], payload[1]))
        return
    if isinstance(raw, (list, tuple)):
        for child in raw:
            _walk_raw(child, out)


def parse_result(raw) -> list[Line]:
    """Normalise whatever the installed PaddleOCR version returned."""
    lines: list[Line] = []
    _walk_raw(raw, lines)
    return lines


def ocr_image(image: Image.Image, lang: str = "ch") -> list[Line]:
    """Run OCR on a PIL image; returns lines with pixel coordinates."""
    engine = _engine(lang)
    array = np.asarray(image.convert("RGB"))
    try:
        raw = engine.ocr(array, cls=True)
    except TypeError:  # 3.x signature
        raw = engine.ocr(array)
    return parse_result(raw)


def _is_cjk(char: str) -> bool:
    return (
        "\u4e00" <= char <= "\u9fff"
        or "\u3000" <= char <= "\u303f"
        or "\uff00" <= char <= "\uffef"
    )


def _join(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if _is_cjk(left[-1]) or _is_cjk(right[0]):
        return left + right
    if left.endswith("-"):
        return left[:-1] + right
    return left + " " + right


def to_paragraphs(lines: list[Line], page_height: float = 0.0) -> list[dict]:
    """Group OCR lines into paragraphs, keeping reading order.

    ``top`` stays in the pixel space of the input lines; the caller scales it
    to PDF points once it knows the render resolution.
    """
    usable = [line for line in lines if line.text.strip()]
    if not usable:
        return []
    ordered = sorted(usable, key=lambda line: (round(line.top, 1), line.left))
    heights = [line.height for line in ordered if line.height > 0] or [10.0]
    typical = sum(heights) / len(heights)
    paragraphs: list[dict] = []
    start = ordered[0]
    previous = ordered[0]
    text = previous.text
    for line in ordered[1:]:
        gap = line.top - (previous.top + previous.height)
        if gap > 1.6 * max(typical, previous.height, 1.0):
            paragraphs.append({"text": text, "top": start.top})
            start = line
            text = line.text
        else:
            text = _join(text, line.text)
        previous = line
    paragraphs.append({"text": text, "top": start.top})
    return paragraphs
