"""Format-specific extraction.

Design rule: extraction never guesses silently. If a page has no text layer we
say so; if a table looks like it collapsed we keep it and let the scorer flag it.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import structure
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


def _tables_from_page(page, page_no: int, chars=None) -> list[Table]:
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
            if origin == "text":
                from .layout import looks_like_prose

                # The text strategy happily reads two columns of prose as a
                # table; those become paragraphs instead.
                if looks_like_prose(rows):
                    continue
            bbox = _union(boxes, tuple(round(float(v), 2) for v in t.bbox))
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            if area > 0.92 * page_area and width <= 2:
                continue  # page frame, not a table
            found.append((origin, rows, bbox))

    # Rule-less tables: columns only exist as whitespace. pdfplumber's text
    # strategy guesses from word positions and happily glues prose into extra
    # columns, so recover these from geometry instead.
    lines_boxes = [b for origin, _, b in found if origin == "lines"]
    clustered: list[tuple[str, list[list[str]], tuple]] = []
    for cand in _cluster_candidates(chars):
        if any(_iou(cand[2], b) > 0.25 for b in lines_boxes):
            continue
        if any(_iou(cand[2], b) > 0.4 for _, _, b in clustered):
            continue
        clustered.append(cand)
    found.extend(clustered)

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

    rank = {"lines": 0, "cluster": 1, "text": 2}
    # prefer the candidate that explains more cells; lines beat text on a tie
    found.sort(key=lambda c: (-(len(c[1]) * max(len(r) for r in c[1])), rank.get(c[0], 3)))

    kept: list[tuple[str, list[list[str]], tuple]] = []
    for cand in found:
        if any(_iou(cand[2], k[2]) > 0.5 for k in kept):
            continue
        kept.append(cand)
    kept.sort(key=lambda c: (round(c[2][1], 1), round(c[2][0], 1)))

    tables = []
    for i, (origin, rows, bbox) in enumerate(kept, 1):
        tables.append(
            Table(id=f"{prefix_for(page_no)}t{i}", rows=rows, page=page_no, bbox=bbox, origin=origin)
        )
    return tables


def _cluster_candidates(chars) -> list[tuple[str, list[list[str]], tuple]]:
    if not chars:
        return []
    from .layout import cluster_tables

    out = []
    for cand in cluster_tables(chars):
        out.append(("cluster", cand["rows"], cand["bbox"]))
    return out


def prefix_for(page_no: int) -> str:
    return f"p{page_no}"


def _inside_boxes(ch: dict, boxes) -> bool:
    x = ch.get("x0", 0.0)
    y = ch.get("top", 0.0)
    for x0, y0, x1, y1 in boxes:
        if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1:
            return True
    return False


def _same_row(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b):
        return False
    return all("".join(x.split()).lower() == "".join(y.split()).lower() for x, y in zip(a, b))


def _promote_title(doc: Document) -> None:
    """The largest heading on the first page is the document title, level 1.

    A 16pt title over 10pt body is only 1.6x, which the size rule can read as a
    section heading once other 12pt headings pull the median up.
    """
    headings = [b for b in doc.blocks if b.kind == "heading" and b.text]
    if not headings:
        return
    first = headings[0]
    biggest = max((b.size or 0.0) for b in headings)
    if (first.size or 0.0) >= biggest and first.level > 1:
        first.level = 1


def _merge_continued(pages: list[dict]) -> set[str]:
    """Join a table that continues on the next page (header repeated).

    Statements, bank exports and tender documents split tables over pages and
    repeat the header; leaving them apart makes the user stitch them by hand.
    """
    flat = [t for p in pages for t in p["tables"]]
    merged: set[str] = set()
    prev = None
    for t in flat:
        t.page_end = t.page
        if (
            prev is not None
            and prev.page_end == (t.page or 0) - 1
            and prev.n_cols == t.n_cols
            and prev.n_cols >= 2
            and prev.n_rows >= 2
            and t.n_rows >= 2
            and _same_row(prev.rows[0], t.rows[0])
        ):
            prev.rows.extend(t.rows[1:])
            prev.page_end = t.page
            if "continued" not in prev.flags:
                prev.flags.append("continued")
            merged.add(t.id)
            continue
        prev = t
    return merged


def _has_page_image(page) -> bool:
    """True when raster images cover a decent part of the page (i.e. a scan)."""
    width = page.width or 1.0
    height = page.height or 1.0
    covered = 0.0
    for image in getattr(page, "images", []) or []:
        try:
            box_w = float(image["x1"]) - float(image["x0"])
            box_h = float(image["bottom"]) - float(image["top"])
        except (KeyError, TypeError, ValueError):
            return True
        covered += max(0.0, box_w) * max(0.0, box_h)
    return covered > 0.3 * width * height


def _ocr_paragraphs(page, page_no: int, doc: Document, dpi: int = 200) -> list[dict] | None:
    """Render one page and read it with PaddleOCR; None means "not available"."""
    from . import ocr as ocr_mod
    from . import preprocess

    if not ocr_mod.available():
        return None
    try:
        image = page.to_image(resolution=dpi).original
        cleaned, info = preprocess.prepare(image)
        paras = ocr_mod.to_paragraphs(ocr_mod.ocr_image(cleaned))
    except Exception as exc:  # optional stack: never take the whole run down
        doc.meta.setdefault("ocr_errors", []).append(f"page {page_no}: {exc}")
        return None
    # OCR coordinates are pixels; convert to PDF points so blocks sort correctly.
    scale = (page.height or 1.0) / max(1, cleaned.height)
    for para in paras:
        para["top"] = para["top"] * scale
    doc.meta.setdefault("ocr_pages", []).append(page_no)
    doc.meta.setdefault("ocr_steps", []).extend(info.get("steps") or [])
    return paras


def _pdf(path: Path, ocr: str = "never") -> Document:
    import pdfplumber

    from . import layout

    doc = Document(path=path, kind="pdf")
    pages: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        doc.pages = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, 1):
            chars = layout.usable(getattr(page, "chars", []) or [])
            if len(chars) < 10:
                doc.scanned_pages.append(page_no)
            tables = _tables_from_page(page, page_no, chars)
            boxes = [t.bbox for t in tables if t.bbox]
            body_chars = [c for c in chars if not _inside_boxes(c, boxes)]
            paras = layout.body_blocks(body_chars, page.width or 1.0)
            if len(chars) < 10 and ocr in ("auto", "always"):
                # auto means "this page is a picture of a document": a scan has
                # one image covering the page.  A near-empty text page (cover,
                # divider, signature block) is not worth a 20 s OCR warm-up.
                if ocr == "always" or _has_page_image(page):
                    read = _ocr_paragraphs(page, page_no, doc)
                    if read:
                        paras = read
                        if page_no in doc.scanned_pages:
                            doc.scanned_pages.remove(page_no)
                    elif ocr == "always":
                        doc.meta.setdefault("ocr_errors", []).append(
                            f"page {page_no}: OCR 不可用（安装 pdfmend[ocr] 后重试）"
                        )
            pages.append(
                {
                    "no": page_no,
                    "paras": paras,
                    "tables": tables,
                    "height": page.height or 1.0,
                    "width": page.width or 1.0,
                }
            )
            doc.tables.extend(tables)

    heads = layout.running_heads([p["paras"] for p in pages], pages[0]["height"] if pages else 0.0)
    merged = _merge_continued(pages)
    if merged:
        doc.tables = [t for t in doc.tables if t.id not in merged]

    text_parts: list[str] = []
    para_sizes: list[float] = []
    for p in pages:
        for para in p["paras"]:
            if layout.normalise_running_head(para["text"]) in heads:
                continue
            text_parts.append(para["text"])
            if para.get("size"):
                para_sizes.append(float(para["size"]))
    body_size = layout._median(para_sizes, 10.0) if para_sizes else 10.0
    doc.meta["body_size"] = round(body_size, 2)
    multi_pages = 0
    order_violations = 0

    for p in pages:
        doc.blocks.append(Block(kind="page", page=p["no"]))
        items: list[tuple[float, int, Block]] = []
        kept = [para for para in p["paras"] if layout.normalise_running_head(para["text"]) not in heads]
        columns = 1 + max((int(para.get("col") or 0) for para in kept), default=0)
        if columns > 1:
            doc.meta.setdefault("columns", {})[p["no"]] = columns
        for block in structure.classify(kept, body_size, page=p["no"], source="pdf"):
            col = 0
            if columns > 1:
                col = 0 if (block.x0 or 0.0) < 0.5 * p["width"] else 1
            items.append((col, block.top or 0.0, block))
        for t in p["tables"]:
            if t.id in merged:
                continue
            top = t.bbox[1] if t.bbox else p["height"]
            col = 0
            if columns > 1 and t.bbox:
                col = 0 if (t.bbox[0] + t.bbox[2]) / 2 < 0.5 * p["width"] else 1
            items.append((col, top, Block(kind="table", table=t, page=t.page)))
            text_parts.extend(c for r in t.rows for c in r)
        items.sort(key=lambda it: (it[0], it[1]))
        if columns > 1:
            multi_pages += 1
            # a page we called multi-column must actually yield two groups,
            # otherwise the split was a false positive and the order is suspect
            groups = {it[0] for it in items}
            if len(groups) < 2 and len(items) > 3:
                order_violations += 1
        doc.blocks.extend(b for _, _, b in items)

    doc.structure = structure.tree(doc.blocks)
    doc.meta["structure"] = structure.counts(doc.blocks)
    _promote_title(doc)
    if multi_pages:
        doc.meta["reading_order"] = {"multi": multi_pages, "violations": order_violations}

    text = "\n".join(text_parts)
    doc.text_chars = len(text)
    doc.cjk_chars = len(CJK_RE.findall(text))
    doc.damaged_chars = _damaged(text)
    if heads:
        doc.meta["running_heads"] = sorted(heads)[:10]
    if merged:
        doc.meta["continued_tables"] = sorted(merged)
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
    list_kind = ""
    list_items: list[str] = []

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if list_items:
            doc.blocks.append(Block(kind=list_kind or "bullet_list", items=list(list_items), source="docx"))
            list_items = []
            list_kind = ""

    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower()
            if style.startswith("heading"):
                flush_list()
                m = re.search(r"(\d+)", style)
                doc.blocks.append(Block(kind="heading", text=t, level=int(m.group(1)) if m else 1,
                                        source="docx"))
            elif style in ("title", "subtitle"):
                flush_list()
                doc.blocks.append(Block(kind="heading", text=t, level=1, source="docx"))
            elif style.startswith("list"):
                # Word's own list styles already tell us the structure; grouping
                # them here keeps Markdown output as real lists, not "- " text.
                kind = "numbered_list" if "number" in style else "bullet_list"
                if list_kind and kind != list_kind:
                    flush_list()
                list_kind = kind
                list_items.append(_strip_bullet(t))
            else:
                flush_list()
                doc.blocks.append(Block(kind="para", text=t, source="docx"))
            text.append(t)
        elif child.tag == qn("w:tbl"):
            flush_list()
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
    flush_list()
    doc.text_chars = sum(len(t) for t in text)
    doc.cjk_chars = len(CJK_RE.findall("".join(text)))
    doc.damaged_chars = _damaged("".join(text))
    doc.meta["structure"] = structure.counts(doc.blocks)
    doc.structure = structure.tree(doc.blocks)
    return doc


def _strip_bullet(text: str) -> str:
    return re.sub(r"^\s*(?:[•●○▪◦■□◆◇✓✔☑·]|[-–—*]|\d+[.)、])\s*", "", text)


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


def extract(path: Path, ocr: str = "never") -> Document:
    suffix = path.suffix.lower()
    if suffix not in EXTRACTORS:
        raise ValueError(f"unsupported file type: {suffix} (支持 .pdf .docx .xlsx .pptx)")
    if ocr not in ("auto", "always", "never"):
        raise ValueError(f"ocr must be auto/always/never, got {ocr!r}")
    doc = _pdf(path, ocr=ocr) if suffix == ".pdf" else EXTRACTORS[suffix](path)
    doc.meta["source_bytes"] = path.stat().st_size
    return doc
