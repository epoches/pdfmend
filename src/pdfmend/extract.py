"""Format-specific extraction.

Design rule: extraction never guesses silently. If a page has no text layer we
say so; if a table looks like it collapsed we keep it and let the scorer flag it.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import Block, Document, Table

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

LINE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "intersection_tolerance": 4,
}
TEXT_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "text_x_tolerance": 3,
    "text_y_tolerance": 3,
    "intersection_tolerance": 5,
}


def _clean(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u00a0", " ").split())


def _damaged(text: str) -> int:
    n = 0
    for ch in text:
        o = ord(ch)
        if ch == "\ufffd" or 0xE000 <= o <= 0xF8FF or (o < 32 and ch not in "\n\t\r"):
            n += 1
    return n


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def _filled(row: list[str]) -> int:
    return sum(1 for c in row if c)


def _trim_text_bailout(rows, bboxes):
    """Drop leading/trailing rows that are really running text, not table data.

    pdfplumber's text strategy happily glues the paragraph above a table into
    the first column, producing a grid whose bbox swallows the heading. A row
    with at most one filled cell is not table data; trim such rows at the edges
    so both the data and the bbox stay honest.
    """
    rows = list(rows)
    bboxes = list(bboxes)
    while rows and _filled(rows[0]) <= 1:
        rows.pop(0)
        bboxes.pop(0)
    while rows and _filled(rows[-1]) <= 1:
        rows.pop()
        bboxes.pop()
    return rows, bboxes


def _union(bboxes, fallback):
    boxes = [b for b in bboxes if b]
    if not boxes:
        return fallback
    return (
        round(min(b[0] for b in boxes), 2),
        round(min(b[1] for b in boxes), 2),
        round(max(b[2] for b in boxes), 2),
        round(max(b[3] for b in boxes), 2),
    )


def _shares_rows(text_rows: list[list[str]], lined_rows: list[list[str]]) -> bool:
    """True when most rows of a lines candidate also appear in a text candidate."""
    want = [tuple(r) for r in lined_rows if any(r)]
    if not want:
        return False
    have = {tuple(r) for r in text_rows}
    hits = sum(1 for r in want if r in have)
    return hits >= 0.8 * len(want)


def _tables_from_page(page, page_no: int, prefix: str) -> list[Table]:
    found: list[tuple[str, list[list[str]], tuple]] = []
    page_area = (page.width or 1) * (page.height or 1)
    for origin, settings in (("lines", LINE_SETTINGS), ("text", TEXT_SETTINGS)):
        try:
            raw = page.find_tables(table_settings=settings)
        except Exception:
            continue
        for t in raw:
            try:
                data = t.extract()
                row_boxes = [getattr(r, "bbox", None) for r in t.rows]
            except Exception:
                continue
            pairs = [
                (row, box)
                for row, box in zip(data, row_boxes)
                if row and any(_clean(c) for c in row)
            ]
            if not pairs:
                continue
            rows = [[_clean(c) for c in row] for row, _ in pairs]
            boxes = [box for _, box in pairs]
            rows, boxes = _trim_text_bailout(rows, boxes)
            if len(rows) < 2:
                continue
            width = max(len(r) for r in rows)
            if width < 2:
                continue
            bbox = _union(boxes, tuple(round(float(v), 2) for v in t.bbox))
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            if area > 0.92 * page_area and width <= 2:
                continue  # page frame, not a table
            found.append((origin, rows, bbox))

    # A bordered grid found by the "lines" strategy beats a text candidate that
    # merely re-covers it: text candidates glue surrounding prose into extra
    # columns and stretch the bbox over the heading (see docs/why.md).
    lined = [c for c in found if c[0] == "lines" and len(c[1]) >= 2 and max(len(r) for r in c[1]) >= 2]
    if lined:
        found = [
            c
            for c in found
            if not (
                c[0] == "text"
                and any(_iou(c[2], l[2]) > 0.2 and _shares_rows(c[1], l[1]) for l in lined)
            )
        ]

    # prefer the candidate that explains more cells; lines beat text on a tie
    found.sort(key=lambda c: (-(len(c[1]) * max(len(r) for r in c[1])), c[0] != "lines"))

    kept: list[tuple[str, list[list[str]], tuple]] = []
    for cand in found:
        if any(_iou(cand[2], k[2]) > 0.5 for k in kept):
            continue
        kept.append(cand)
    kept.sort(key=lambda c: (round(c[2][1], 1), round(c[2][0], 1)))

    tables = []
    for i, (origin, rows, bbox) in enumerate(kept, 1):
        tables.append(
            Table(id=f"{prefix}t{i}", rows=rows, page=page_no, bbox=bbox, origin=origin)
        )
    return tables


def _pdf(path: Path) -> Document:
    import pdfplumber

    doc = Document(path=path, kind="pdf")
    with pdfplumber.open(str(path)) as pdf:
        doc.pages = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, 1):
            raw_chars = getattr(page, "chars", []) or []
            text_raw = ""
            try:
                text_raw = page.extract_text() or ""
            except Exception:
                text_raw = ""
            doc.text_chars += len(text_raw)
            doc.cjk_chars += len(CJK_RE.findall(text_raw))
            doc.damaged_chars += _damaged(text_raw)
            if len(raw_chars) < 10:
                doc.scanned_pages.append(page_no)

            tables = _tables_from_page(page, page_no, prefix=f"p{page_no}")
            doc.tables.extend(tables)
            doc.blocks.append(Block(kind="page", page=page_no))

            remaining = page
            for t in tables:
                if t.bbox:
                    try:
                        remaining = remaining.outside_bbox(t.bbox)
                    except Exception:
                        pass
            try:
                body = remaining.extract_text() or ""
            except Exception:
                body = ""
            if body.strip():
                doc.blocks.append(Block(kind="para", text=body.strip(), page=page_no))
            for t in tables:
                doc.blocks.append(Block(kind="table", table=t, page=page_no))
    return doc


def _docx(path: Path) -> Document:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph

    doc = Document(path=path, kind="docx")
    d = docx.Document(str(path))
    idx = 0
    text = []
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower()
            if style.startswith("heading"):
                m = re.search(r"(\d+)", style)
                doc.blocks.append(Block(kind="heading", text=t, level=int(m.group(1)) if m else 1))
            elif style in ("title", "subtitle"):
                doc.blocks.append(Block(kind="heading", text=t, level=1))
            else:
                prefix = "- " if style.startswith("list") else ""
                doc.blocks.append(Block(kind="para", text=prefix + t))
            text.append(t)
        elif child.tag == qn("w:tbl"):
            tbl = DocxTable(child, d)
            rows = []
            seen = set()
            for row in tbl.rows:
                cells = []
                for cell in row.cells:
                    tc = cell._tc  # keep a reference so lxml proxy identity stays stable
                    if tc in seen:
                        cells.append("")
                    else:
                        seen.add(tc)
                        cells.append(_clean(cell.text))
                rows.append(cells)
            rows = [r for r in rows if any(c for c in r)]
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                idx += 1
                t = Table(id=f"t{idx}", rows=rows, origin="docx")
                doc.tables.append(t)
                doc.blocks.append(Block(kind="table", table=t))
    doc.text_chars = sum(len(t) for t in text)
    doc.cjk_chars = len(CJK_RE.findall("".join(text)))
    doc.damaged_chars = _damaged("".join(text))
    return doc


def _xlsx(path: Path) -> Document:
    import openpyxl

    doc = Document(path=path, kind="xlsx")
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    doc.pages = len(wb.worksheets)
    for ws in wb.worksheets:
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 500:
                break
            cells = [_clean(c) for c in row]
            if any(cells):
                rows.append(cells)
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue
        t = Table(id=f"t{len(doc.tables) + 1}", rows=rows, origin="xlsx")
        t.flags.append(f"sheet:{ws.title}")
        doc.tables.append(t)
        doc.blocks.append(Block(kind="heading", text=ws.title, level=2))
        doc.blocks.append(Block(kind="table", table=t))
    wb.close()
    all_text = " ".join(c for t in doc.tables for r in t.rows for c in r)
    doc.text_chars = len(all_text)
    doc.cjk_chars = len(CJK_RE.findall(all_text))
    return doc


def _pptx(path: Path) -> Document:
    from pptx import Presentation

    doc = Document(path=path, kind="pptx")
    prs = Presentation(str(path))
    doc.pages = len(prs.slides)
    for n, slide in enumerate(prs.slides, 1):
        doc.blocks.append(Block(kind="page", page=n))
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                txt = "\n".join(p.text for p in shape.text_frame.paragraphs if p.text.strip())
                if txt.strip():
                    doc.blocks.append(Block(kind="para", text=txt.strip(), page=n))
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[_clean(c.text) for c in row.cells] for row in shape.table.rows]
                rows = [r for r in rows if any(c for c in r)]
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    t = Table(id=f"t{len(doc.tables) + 1}", rows=rows, page=n, origin="pptx")
                    doc.tables.append(t)
                    doc.blocks.append(Block(kind="table", table=t, page=n))
    all_text = " ".join(b.text for b in doc.blocks if b.kind == "para")
    doc.text_chars = len(all_text)
    doc.cjk_chars = len(CJK_RE.findall(all_text))
    return doc


EXTRACTORS = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}


def extract(path: Path) -> Document:
    suffix = path.suffix.lower()
    if suffix not in EXTRACTORS:
        raise ValueError(f"unsupported file type: {suffix} (支持 .pdf .docx .xlsx .pptx)")
    doc = EXTRACTORS[suffix](path)
    doc.meta["source_bytes"] = path.stat().st_size
    return doc
