"""PaddleOCR adapter (optional).

PaddleOCR is optional and heavy (paddlepaddle is ~100 MB).  ``pdfmend`` only
calls into it when a page has no text layer and the user asked for OCR
(``--ocr auto`` / ``--ocr always``).  If it is missing we say so instead of
silently returning nothing.

The parsing helpers are pure functions so they can be tested without paddle
installed; PaddleOCR 2.x and 3.x return different shapes and both are handled.
"""

from __future__ import annotations

import contextlib
import os
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
_AVAILABLE: bool | None = None


def available() -> bool:
    """Cheap probe: finds the package without importing paddle (which is slow)."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import importlib.util

            _AVAILABLE = importlib.util.find_spec("paddleocr") is not None
        except Exception:  # pragma: no cover - broken install
            _AVAILABLE = False
    return bool(_AVAILABLE)


def _mkldnn_default() -> bool:
    """MKLDNN is on unless the user says otherwise.

    paddlepaddle 3.3.x ships oneDNN kernels that abort on Windows with
    "ConvertPirAttribute2RuntimeAttribute not support", so mkldnn stays off
    there; 3.2.x is both correct and ~3x faster than the naive CPU path.
    """
    env = os.environ.get("PDFMEND_OCR_MKLDNN")
    if env is not None:
        return env == "1"
    try:
        from importlib.metadata import version

        major, minor, *_ = (int(part) for part in version("paddlepaddle").split(".")[:2])
    except Exception:
        return True
    return (major, minor) < (3, 3)


def _paddleocr_major() -> int:
    try:
        from importlib.metadata import version

        return int(version("paddleocr").split(".")[0])
    except Exception:
        return 2


@contextlib.contextmanager
def _quiet():
    """Silence paddle's C++ chatter (oneDNN probes, model banners).

    Paddle writes those lines straight to fd 1, so redirecting ``sys.stdout``
    is not enough; the file descriptor itself has to be swapped for a moment.
    """
    try:
        saved = os.dup(1)
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:  # pragma: no cover - no fd juggling on this host
        yield
        return
    try:
        os.dup2(devnull, 1)
        yield
    finally:
        os.dup2(saved, 1)
        os.close(devnull)
        os.close(saved)


def _engine(lang: str = "ch"):
    if lang in _ENGINES:
        return _ENGINES[lang]
    mkldnn = _mkldnn_default()
    if _paddleocr_major() >= 3:
        attempts = (
            {"lang": lang, "use_textline_orientation": True, "enable_mkldnn": mkldnn},
            {"lang": lang, "enable_mkldnn": mkldnn},
            {"lang": lang},
        )
    else:  # pragma: no cover - 2.x
        attempts = (
            {"lang": lang, "use_angle_cls": True, "show_log": False},
            {"lang": lang},
        )
    last: Exception | None = None
    with _quiet():
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - depends on install
            raise OcrUnavailable('PaddleOCR 未安装：pip install "pdfmend[ocr]"') from exc
        for kwargs in attempts:
            try:
                engine = PaddleOCR(**kwargs)
            except (TypeError, ValueError) as exc:  # 3.x drops old kwargs
                last = exc
                continue
            _ENGINES[lang] = engine
            return engine
    raise OcrUnavailable(f"PaddleOCR 初始化失败：{last}")


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
    with _quiet():
        if hasattr(engine, "predict"):  # 3.x: .ocr() only forwards to .predict()
            raw = engine.predict(array)
        else:  # pragma: no cover - 2.x
            try:
                raw = engine.ocr(array, cls=True)
            except TypeError:
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


def _visual_rows(lines: list[Line]) -> list[list[Line]]:
    """Group lines that sit on the same baseline band, left to right."""
    ordered = sorted(lines, key=lambda line: (line.top, line.left))
    rows: list[list[Line]] = []
    band_top = 0.0
    band_height = 1.0
    for line in ordered:
        if rows and abs(line.top - band_top) <= 0.5 * max(band_height, line.height, 1.0):
            rows[-1].append(line)
        else:
            rows.append([line])
            band_top = line.top
            band_height = line.height
    return [sorted(row, key=lambda line: line.left) for row in rows]


def to_paragraphs(lines: list[Line], page_height: float = 0.0) -> list[dict]:
    """Group OCR lines into paragraphs, keeping reading order.

    Lines sharing a baseline become one row whose cells are joined with ``|``
    so column order survives the trip through plain text (it is not a table:
    nothing here validates the columns).  ``top`` stays in the pixel space of
    the input lines; the caller scales it to PDF points.
    """
    usable = [line for line in lines if line.text.strip()]
    if not usable:
        return []
    rows = _visual_rows(usable)
    heights = [line.height for line in usable if line.height > 0] or [10.0]
    typical = sum(heights) / len(heights)
    paragraphs: list[dict] = []
    text = ""
    start = rows[0][0].top
    previous_bottom = rows[0][0].top
    for row in rows:
        cells = [line.text.strip() for line in row]
        row_text = " | ".join(cells) if len(cells) > 1 else cells[0]
        top = min(line.top for line in row)
        bottom = max(line.top + line.height for line in row)
        gap = top - previous_bottom
        if len(cells) > 1:
            # a row with columns is its own line; keep the reading order
            if text:
                paragraphs.append({"text": text, "top": start})
                text = ""
            paragraphs.append({"text": row_text, "top": top})
            start = top
        elif gap > 1.6 * max(typical, 1.0):
            if text:
                paragraphs.append({"text": text, "top": start})
            text = row_text
            start = top
        else:
            text = _join(text, row_text) if text else row_text
        previous_bottom = bottom
    if text:
        paragraphs.append({"text": text, "top": start})
    return paragraphs
