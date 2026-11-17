"""Quality scoring.

The whole point of pdfmend is to not pretend. Every table gets a confidence
number derived from observable properties of the extracted grid, plus explicit
flags for the failure modes we have actually seen:

  - a table collapsed into a single column (markitdown's classic failure)
  - ragged rows (merged cells spilling, or a column that failed to split)
  - mixed types in a numeric column (a footer or a note landed in the data)
  - duplicated adjacent cells (vertical merge rendered as repeated values)

The score is a heuristic, not a measurement. It is calibrated to be pessimistic:
a table that looks fine but has 40% empty cells should not score 0.95.
"""

from __future__ import annotations

import re

from .model import Document, Report, Table

NUM_RE = re.compile(
    r"^[¥$€£]?\s*[-+]?\d[\d,，]*(\.\d+)?\s*(%|元|万元|亿元|万|亿|笔|个|件|人|天|月|年)?$"
)
DATE_RE = re.compile(r"^\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}日?$")
EMPTYISH = {"", "-", "—", "–", "/", "n/a", "na", "无", "空", "—", "..."}


def _norm_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(r) for r in rows), default=0)
    return [(r + [""] * (width - len(r)))[:width] for r in rows]


def _is_number(v: str) -> bool:
    return bool(NUM_RE.match(v.strip()))


def _is_date(v: str) -> bool:
    return bool(DATE_RE.match(v.strip()))


def _header_ok(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    head = [c.strip() for c in rows[0]]
    if not any(head):
        return False
    if sum(1 for c in head if c) < max(2, len(head) // 2):
        return False
    # a data row used as header is usually all numbers/dates
    return not all(_is_number(c) or _is_date(c) for c in head if c)


def _data_start(rows: list[list[str]]) -> int:
    """Index of the first data row; skips multi-row headers.

    Two-level headers are common in Chinese financial tables: the first two
    rows are pure text ("科目 / 本期发生额 / ..."), which would otherwise be
    counted as a type inconsistency in every numeric column.

    A continuation header row must leave at least one cell empty (the columns
    that were merged vertically, e.g. "科目" spanning two rows). A full text
    row with every cell filled is data, not a header -- otherwise a table of
    names and statuses loses its first record.
    """
    if not rows:
        return 1
    start = 1
    n_cols = max(len(r) for r in rows)
    for i in range(min(3, len(rows) - 1)):
        filled = [c for c in rows[i] if c.strip()]
        if not filled:
            break
        if i == 0:
            continue  # row 0 is the header by definition
        has_num = any(_is_number(c) or _is_date(c) for c in filled)
        if not has_num and len(filled) < n_cols:
            start = i + 1
        else:
            break
    return start


def score_table(table: Table) -> None:
    """Mutate table.confidence and table.flags in place."""
    orig = [len(r) for r in table.rows]
    rows = _norm_rows(table.rows)
    table.rows = rows
    flags: list[str] = []

    if not rows or not rows[0]:
        table.confidence = 0.0
        table.flags = ["empty_table"]
        return

    n_rows, n_cols = len(rows), len(rows[0])
    cells = [c.strip() for r in rows for c in r]
    filled = sum(1 for c in cells if c not in EMPTYISH)
    fill = filled / max(1, len(cells))

    ragged = sum(1 for w in orig if w and w != n_cols)
    ragged_ratio = ragged / max(1, n_rows)

    # type consistency per column, only for columns that look numeric
    mixed_cols = 0
    numeric_cols = 0
    start = _data_start(rows)
    for j in range(n_cols):
        col = [rows[i][j].strip() for i in range(start, n_rows)]
        col = [c for c in col if c not in EMPTYISH]
        if len(col) < 3:
            continue
        nums = sum(1 for c in col if _is_number(c) or _is_date(c))
        ratio = nums / len(col)
        if ratio >= 0.7:
            numeric_cols += 1
            if ratio < 0.95:
                mixed_cols += 1

    type_consistency = 1.0 if numeric_cols == 0 else 1.0 - 0.25 * mixed_cols / numeric_cols
    header = 1.0 if _header_ok(rows) else 0.0

    # merged-cell signature: equal text neighbours repeated down a row. Numeric
    # repeats (0.00 next to 0.00) are normal in financial tables, so skip them.
    dup_ratio = 0.0
    if n_cols > 1:
        dup = 0
        total = 0
        for r in rows[start:]:
            for j in range(1, n_cols):
                prev, cur = r[j - 1].strip(), r[j].strip()
                if not cur or cur in EMPTYISH or _is_number(cur):
                    continue
                total += 1
                if cur == prev:
                    dup += 1
        dup_ratio = dup / max(1, total)

    conf = 0.45 * fill + 0.25 * (1 - ragged_ratio) + 0.20 * type_consistency + 0.10 * header

    # A cell whose text wrapped inside the PDF often comes out as *extra rows*
    # with most cells blank. The table still looks fine on paper, so say so
    # instead of pretending the row count is right.
    body_rows = rows[start:]
    sparse = sum(
        1 for r in body_rows if sum(1 for c in r if c.strip() not in EMPTYISH) <= max(1, n_cols - 2)
    )
    sparse_ratio = sparse / max(1, len(body_rows))

    if n_cols <= 1 and n_rows >= 3:
        flags.append("collapsed_single_column")
        conf = min(conf, 0.30)
    if ragged_ratio > 0:
        flags.append("ragged_rows")
        conf -= 0.10
    if fill < 0.6:
        flags.append("empty_cells")
    if mixed_cols:
        flags.append("mixed_types")
    if n_cols >= 3 and sparse_ratio > 0.30:
        flags.append("sparse_rows")
        conf -= 0.08
    if dup_ratio > 0.20:
        flags.append("merged_cells_suspected")
        conf -= 0.10
    if not header:
        flags.append("no_header")
    if n_rows < 2 or n_cols < 2:
        flags.append("too_small")

    table.confidence = max(0.05, min(0.99, conf))
    table.header_rows = max(1, start)
    table.flags = sorted(set(flags))


def score_document(doc: Document) -> Report:
    for t in doc.tables:
        score_table(t)

    reasons: list[str] = []
    total_chars = max(1, doc.text_chars + doc.damaged_chars)
    damage_ratio = doc.damaged_chars / total_chars
    scan_ratio = len(doc.scanned_pages) / max(1, doc.pages)
    text_health = max(0.0, 1.0 - 2.0 * damage_ratio - 0.6 * scan_ratio)

    if doc.damaged_chars:
        reasons.append(f"{doc.damaged_chars} 个字符无法正确解码（可能是 CID 字体或编码问题）")
    if doc.scanned_pages:
        shown = ", ".join(str(p) for p in doc.scanned_pages[:8])
        more = "..." if len(doc.scanned_pages) > 8 else ""
        reasons.append(
            f"第 {shown}{more} 页没有文本层（扫描件）：安装 pdfmend[ocr] 后加 --ocr auto 可识别"
        )
    ocr_pages = list(doc.meta.get("ocr_pages") or [])
    if ocr_pages:
        shown = ", ".join(str(p) for p in ocr_pages[:8])
        more = "..." if len(ocr_pages) > 8 else ""
        reasons.append(f"第 {shown}{more} 页由 OCR 识别（扫描/手写），数字与专有名词请核对")
        text_health = max(0.0, text_health - 0.2 * len(ocr_pages) / max(1, doc.pages))
    ocr_errors = list(doc.meta.get("ocr_errors") or [])
    if ocr_errors:
        first = str(ocr_errors[0]).splitlines()[0][:120]
        reasons.append(
            f"OCR 未完成（{len(ocr_errors)} 页）：{first}；这些页仍按「没有文本层」处理"
        )

    if doc.tables:
        weight = sum(max(1, t.n_rows) for t in doc.tables)
        table_score = sum(t.confidence * max(1, t.n_rows) for t in doc.tables) / weight
        weak = [t for t in doc.tables if t.confidence < 0.6]
        if weak:
            reasons.append(f"{len(weak)}/{len(doc.tables)} 张表置信度低于 0.6，建议人工抽查")
        sparse = [t for t in doc.tables if "sparse_rows" in t.flags]
        if sparse:
            reasons.append(
                f"{len(sparse)} 张表有大量空白格（单元格换行或纵向合并被拆开），建议对照原文件抽查"
            )
        score = 100 * (0.75 * table_score + 0.25 * text_health)
    else:
        if doc.text_chars == 0:
            reasons.append("没有提取到任何文本")
        score = 100 * text_health

    score = int(round(max(0, min(100, score))))
    if score >= 85:
        verdict = "可直接使用"
    elif score >= 60:
        verdict = "需抽查"
    else:
        verdict = "建议人工复核"
    if not reasons:
        reasons.append("未发现明显问题")

    return Report(document=doc, score=score, verdict=verdict, reasons=reasons, tables=doc.tables)
