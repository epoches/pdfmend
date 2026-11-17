"""Layout-aware recovery for PDFs whose text layer is not a tidy grid.

pdfplumber is good at two things: tables drawn with rules, and dumping a page's
characters in reading order. Non-standard files break both assumptions:

* a table drawn without any rules (only whitespace between columns),
* a page whose text is arranged in columns or text boxes, so the character
  stream interleaves two sentences,
* repeated running heads/footers that end up inside the body,
* a table that continues on the next page.

This module works directly on pdfplumber's ``chars`` (each has text/x0/x1/top/
bottom/size/upright) and rebuilds rows, runs and columns from geometry, so the
output does not depend on how the producer ordered its text stream.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

# A cell that is a number (optionally currency/percent) is strong evidence the
# cluster really is a table rather than two columns of prose.
NUM_RE = re.compile(r"^[¥$€£]?\s*[-+]?\d[\d,\s]*\.?\d*\s*%?$")
# Sentence punctuation inside a cell is strong evidence it is prose (a cell that
# merely *ends* in a comma/period counts too: wrapping prose lines do that).
PROSE_PUNCT = re.compile(r"[。；！？，、：;]|[.,]$")

CJK_RANGES = (
    (0x3000, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
)


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in CJK_RANGES)


def _gap_text(left: str, right: str, gap: float, size: float) -> str:
    """Join two runs: CJK runs butt together, Latin runs get a space."""
    if not left:
        return right
    if not right:
        return left
    if is_cjk(left[-1]) or is_cjk(right[0]):
        return left + right
    return left + (" " if gap > 0.15 * size else "") + right


def _run_text(chars: list[dict]) -> str:
    out = ""
    prev = None
    for c in chars:
        if prev is not None:
            out = _gap_text(out, c["text"], c["x0"] - prev["x1"], c.get("size") or 10)
        else:
            out = c["text"]
        prev = c
    return out.strip()


@dataclass
class Run:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def width(self) -> float:
        return max(0.1, self.x1 - self.x0)


@dataclass
class Row:
    top: float
    bottom: float
    chars: list[dict] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)

    @property
    def height(self) -> float:
        return max(0.5, self.bottom - self.top)


def _v_overlap(a_top: float, a_bottom: float, b_top: float, b_bottom: float) -> float:
    return max(0.0, min(a_bottom, b_bottom) - max(a_top, b_top))


def usable(chars) -> list[dict]:
    return [
        c
        for c in chars or []
        if (c.get("text") or "").strip() and c.get("upright", True)
    ]


def rows(chars, gap_factor: float = 0.55) -> list[Row]:
    """Group characters into text rows, then split each row into runs."""
    out: list[Row] = []
    for c in sorted(usable(chars), key=lambda c: (c["top"], c["x0"])):
        h = max(0.5, c["bottom"] - c["top"])
        for row in reversed(out[-2:]):
            if _v_overlap(row.top, row.bottom, c["top"], c["bottom"]) >= 0.5 * min(row.height, h):
                row.chars.append(c)
                row.top = min(row.top, c["top"])
                row.bottom = max(row.bottom, c["bottom"])
                break
        else:
            out.append(Row(c["top"], c["bottom"], [c]))
    out.sort(key=lambda r: r.top)
    for row in out:
        row.chars.sort(key=lambda c: c["x0"])
        row.runs = _split_runs(row.chars, gap_factor)
    return out


def _split_runs(chars: list[dict], gap_factor: float) -> list[Run]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for c in chars:
        if cur:
            prev = cur[-1]
            thr = max(1.2, gap_factor * max(prev.get("size") or 10, c.get("size") or 10))
            if c["x0"] - prev["x1"] > thr:
                groups.append(cur)
                cur = []
        cur.append(c)
    if cur:
        groups.append(cur)
    runs = []
    for g in groups:
        runs.append(
            Run(
                text=_run_text(g),
                x0=min(c["x0"] for c in g),
                x1=max(c["x1"] for c in g),
                top=min(c["top"] for c in g),
                bottom=max(c["bottom"] for c in g),
            )
        )
    return [r for r in runs if r.text]


def _median(values, default: float = 10.0) -> float:
    return statistics.median(values) if values else default


def looks_like_prose(rows_: list[list[str]]) -> bool:
    """Do these cells read like body text instead of table content?

    Two columns of prose line up on x exactly like two columns of a table; the
    difference is that their "cells" are sentences and no column holds numbers.
    """
    filled = [c for r in rows_ for c in r if c]
    if not filled:
        return True
    n_cols = max(len(r) for r in rows_)
    numeric_cols = sum(
        1
        for j in range(n_cols)
        if sum(1 for r in rows_ if j < len(r) and NUM_RE.match(r[j])) >= 0.4 * len(rows_)
    )
    if numeric_cols:
        return False
    punct = sum(1 for c in filled if PROSE_PUNCT.search(c)) / len(filled)
    if punct >= 0.2:
        return True
    return _median([len(c) for c in filled], 0) > 10


def cluster_tables(chars, min_rows: int = 3, min_cols: int = 2) -> list[dict]:
    """Recover rule-less tables: columns are runs that keep landing on the same x."""
    rows_ = rows(chars)
    if len(rows_) < min_rows:
        return []
    sizes = [c.get("size") or 10 for r in rows_ for c in r.chars]
    size = _median(sizes, 10.0)
    tol = max(4.0, 0.6 * size)

    # global column anchors, built left to right over all rows
    anchors: list[dict] = []
    for row in rows_:
        for run in row.runs:
            best = None
            for a in anchors:
                d = abs(run.cx - a["cx"])
                if d <= tol and (best is None or d < best[1]):
                    best = (a, d)
            if best is None:
                anchors.append({"cx": run.cx, "w": run.width, "n": 1})
            else:
                a = best[0]
                a["cx"] = (a["cx"] * a["n"] + run.cx) / (a["n"] + 1)
                a["w"] = max(a["w"], run.width)
                a["n"] += 1
    anchors.sort(key=lambda a: a["cx"])

    # drop anchors that are almost on top of each other (split words in one column)
    merged: list[dict] = []
    for a in anchors:
        if merged and a["cx"] - merged[-1]["cx"] < max(6.0, 0.5 * (a["w"] + merged[-1]["w"]) * 0.6):
            merged[-1]["n"] += a["n"]
            merged[-1]["cx"] = (merged[-1]["cx"] + a["cx"]) / 2
            merged[-1]["w"] = max(merged[-1]["w"], a["w"])
        else:
            merged.append(dict(a))
    anchors = merged
    if len(anchors) < min_cols:
        return []

    rows_out: list[list[str]] = []
    used_rows: list[Row] = []
    for row in rows_:
        cells = ["" for _ in anchors]
        filled = 0
        for run in row.runs:
            idx = min(range(len(anchors)), key=lambda i: abs(run.cx - anchors[i]["cx"]))
            if cells[idx]:
                cells[idx] = cells[idx] + " " + run.text
            else:
                cells[idx] = run.text
                filled += 1
        if filled >= 2:
            rows_out.append(cells)
            used_rows.append(row)
    if len(rows_out) < min_rows:
        return []

    # every column must be used by at least two rows, else it is stray text
    widths = max(len(r) for r in rows_out)
    keep = [
        j
        for j in range(widths)
        if sum(1 for r in rows_out if r[j]) >= 2
    ]
    if len(keep) < min_cols:
        return []
    rows_out = [[r[j] for j in keep] for r in rows_out]

    filled_cells = [c for r in rows_out for c in r if c]
    fill = len(filled_cells) / (len(rows_out) * len(keep))
    median_len = _median([len(c) for c in filled_cells], 0)
    # prose columns are wide and wordy; a table's cells are short labels/values
    if fill < 0.45 or median_len > 24:
        return []

    # Two columns of body text also line up on x, so reject the case where the
    # "cells" read like sentences and no column holds numbers.
    if looks_like_prose(rows_out):
        return []

    bbox = (
        round(min(r.x0 for row in used_rows for r in row.runs), 2),
        round(min(row.top for row in used_rows), 2),
        round(max(r.x1 for row in used_rows for r in row.runs), 2),
        round(max(row.bottom for row in used_rows), 2),
    )
    return [{"rows": rows_out, "bbox": bbox, "columns": len(keep)}]


def _column_bands(rows_: list[Row], page_width: float) -> list[tuple[float, float]]:
    """Find vertical gutters: bands that almost no run crosses."""
    if not rows_ or page_width <= 0:
        return []
    spans = [(r.x0, r.x1) for row in rows_ for r in row.runs]
    if not spans:
        return []
    spans.sort()
    bands = []
    cursor = spans[0][1]
    for x0, x1 in spans[1:]:
        if x0 - cursor >= max(8.0, 0.03 * page_width):
            bands.append((cursor, x0))
        cursor = max(cursor, x1)
    return bands


def reading_columns(rows_: list[Row], page_width: float) -> list[list[Row]]:
    """Split rows into columns when the page really is multi-column prose."""
    for band in _column_bands(rows_, page_width):
        mid = (band[0] + band[1]) / 2
        left: list[Row] = []
        right: list[Row] = []
        both = 0
        for row in rows_:
            lr = [r for r in row.runs if 0.5 * (r.x0 + r.x1) <= mid]
            rr = [r for r in row.runs if 0.5 * (r.x0 + r.x1) > mid]
            if lr:
                left.append(Row(row.top, row.bottom, row.chars, lr))
            if rr:
                right.append(Row(row.top, row.bottom, row.chars, rr))
            if lr and rr:
                both += 1
        used = len([r for r in rows_ if r.runs])
        # a gutter only counts when it runs through most of the page, not one
        # indented line or a centred heading
        if len(left) >= 2 and len(right) >= 2 and used and both >= 0.5 * used:
            return [left, right]
    return [rows_]


def _row_text(row: Row) -> str:
    size = _median([c.get("size") or 10 for c in row.chars])
    text = ""
    for run in row.runs:
        text = _gap_text(text, run.text, 0.0, size)
    return text


# Bullet glyphs at the start of a line mean a new list item, never a
# continuation of the previous paragraph.
BULLET_START = re.compile(
    r"^\s*(?:[•●○▪◦■□◆◇✓✔☑·]\s*|[-–—*]\s+)(?=\S)"
)
LONE_BULLET = re.compile(r"^\s*[•●○▪◦■□◆◇✓✔☑·]\s*$")
# A line starting with a year is a new CV entry ("2022.03—2024.06 某公司"),
# never a continuation of the bullet above it.
ENTRY_START = re.compile(r"^\s*(?:19|20)\d{2}\s*[.\-/年]")
# "合同编号：…" / "甲方：" / "TEL:" -- a label line holds one field, so joining
# it to the next label produces "合同编号：HT-001甲方：某公司".
LABEL_START = re.compile(r"^\s*[\u4e00-\u9fffA-Za-z][^：:，。；]{0,10}[：:]")


def _paragraphs(rows_: list[Row], gap_factor: float = 1.5) -> list[dict]:
    """Join consecutive rows into paragraphs, keeping their vertical extent.

    Three things end a paragraph early, because they *are* structure:

    * a vertical gap wider than normal leading,
    * a font-size change (a heading is bigger than the body it introduces),
    * a line that starts with a bullet glyph.
    """
    out: list[dict] = []
    buf: list[Run] = []
    top = bottom = None
    prev_bottom = None
    prev_height = 0.0
    prev_size = 0.0
    pending_bullet = ""
    for row in rows_:
        if not row.runs:
            continue
        text = _row_text(row)
        size = _median([c.get("size") or 10 for c in row.chars])
        if LONE_BULLET.match(text):
            pending_bullet = "•"
            continue
        if pending_bullet:
            text = f"• {text}"
            pending_bullet = ""
        if buf and prev_bottom is not None:
            gap = row.top - prev_bottom
            limit = gap_factor * max(prev_height, row.height)
            size_jump = prev_size and abs(size - prev_size) > 0.12 * max(size, prev_size)
            if gap > limit or size_jump or BULLET_START.match(text) or ENTRY_START.match(text) \
                    or LABEL_START.match(text):
                out.append({"text": _join_runs(buf), "top": top, "bottom": bottom,
                            "size": prev_size, "x0": _min_x(buf)})
                buf = []
                top = bottom = None
                prev_size = 0.0
        buf.append(Run(text, min(r.x0 for r in row.runs), max(r.x1 for r in row.runs), row.top, row.bottom))
        top = row.top if top is None else min(top, row.top)
        bottom = row.bottom if bottom is None else max(bottom, row.bottom)
        prev_bottom = row.bottom
        prev_height = row.height
        prev_size = size
    if buf:
        out.append({"text": _join_runs(buf), "top": top, "bottom": bottom,
                    "size": prev_size, "x0": _min_x(buf)})
    return [p for p in out if p["text"].strip()]


def _min_x(runs: list[Run]) -> float:
    return min((r.x0 for r in runs), default=0.0)


def body_blocks(chars, page_width: float) -> list[dict]:
    """Reading-order paragraphs for a page's prose (tables already removed).

    Each paragraph carries ``col`` so callers can keep column order instead of
    re-sorting by vertical position (which would interleave the columns).
    """
    rows_ = rows(chars)
    out: list[dict] = []
    for index, column in enumerate(reading_columns(rows_, page_width)):
        for para in _paragraphs(column):
            para["col"] = index
            out.append(para)
    return out


def _join_runs(runs: list[Run]) -> str:
    text = ""
    for run in runs:
        if not text:
            text = run.text
        elif text.endswith("-") and run.text[:1].islower():
            text = text[:-1] + run.text
        else:
            text = _gap_text(text, run.text, 0.0, 10.0)
    return text


def normalise_running_head(text: str) -> str:
    """Collapse digits so '第 3 页 / 共 9 页' and '第 4 页 / 共 9 页' match."""
    return "".join("#" if ch.isdigit() else ch for ch in text).strip()


def running_heads(pages: list[list[dict]], page_height: float = 0.0) -> set[str]:
    """Keys of paragraphs sitting in the top/bottom band and repeated on most pages.

    ``pages`` is one list of paragraph dicts per page; each dict has text/top/bottom.
    """
    if len(pages) < 3:
        return set()
    from collections import Counter

    counter: Counter = Counter()
    for paras in pages:
        keys = set()
        for p in paras:
            if page_height and 0.06 * page_height < p["top"] < 0.94 * page_height:
                continue
            key = normalise_running_head(p["text"])
            if key:
                keys.add(key)
        for k in keys:
            counter[k] += 1
    limit = max(3, int(0.6 * len(pages)))
    return {k for k, n in counter.items() if n >= limit}
