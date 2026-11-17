"""Structure recognition: turn paragraphs into headings, lists, and clauses.

Text extraction answers "what does the page say"; that is not the same as "how
is the document organised".  A resume whose bullets were flattened into one
paragraph still scores 100 on a text-only check, yet is useless to a human.

Everything here works on the geometry the parser already recovered (font size,
x offset, line order) plus a small set of typographic rules.  No model is
involved: rules are cheap, deterministic, testable, and run offline.  The LLM
is only asked about fields, never about layout.

Block kinds produced:

    heading (level 1-3) | para | bullet_list | numbered_list | clause | quote
"""

from __future__ import annotations

import re

from .model import Block

BULLET_CHARS = "•●○▪◦■□◆◇✓✔☑·∙"
BULLET_RE = re.compile(rf"^\s*(?:[{BULLET_CHARS}]\s*|[-–—*]\s+)(\S.*)$")
NUMBERED_RE = re.compile(r"^\s*(?:\(?(\d{1,3})[.)、）](?![.\d])|（(\d{1,3})）)\s*(.+)$")
CN_ORDINAL_RE = re.compile(r"^\s*([一二三四五六七八九十百]+)[、.．]\s*(.+)$")
CLAUSE_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})+)[.、]?\s*(.+)$")
CHAPTER_RE = re.compile(r"^\s*第[一二三四五六七八九十百零\d]+[编章]\s*")
SECTION_RE = re.compile(r"^\s*第[一二三四五六七八九十百零\d]+节\s*")
ARTICLE_RE = re.compile(r"^\s*第[一二三四五六七八九十百零\d]+条")
QUOTE_RE = re.compile(r"^\s*(?:>|“|「)")
SENTENCE_END = re.compile(r"[。！？；：.!?;:]\s*$")
NUMERIC_LINE = re.compile(r"^[\d\s.,:：/%-]+$")# A clause or chapter marker used to cut a paragraph that swallowed several of them.
SECTION_MARK_RE = re.compile(
    r"(?:第[一二三四五六七八九十百零\d]+[条章节编])"
    r"|(?<![\d.])(?:\d{1,2}\.\d{1,2}(?:\.\d{1,2})*)(?=[\u4e00-\u9fff（(])"
    r"|(?<![\d.])(?:\d{1,3}[.、])(?=[\u4e00-\u9fff])"
)

# Sub-items inside a clause: "（1）系统架构设计" / "① 数据库设计".
SUBITEM_RE = re.compile(r"^\s*(?:[（(]\s*[0-9]{1,2}\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)$")
SUBITEM_MARK_RE = re.compile(r"(?:[（(]\s*[0-9]{1,2}\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩])")


def clean(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def bullet_item(text: str) -> str | None:
    """Return the item text when the line is a bullet, else None."""
    m = BULLET_RE.match(text or "")
    if not m:
        return None
    item = m.group(1).strip()
    # "-" alone or a symbol with nothing after it is decoration, not an item
    return item or None


def numbered_item(text: str) -> tuple[str, str] | None:
    """Return (marker, item) for an ordered-list line."""
    m = NUMBERED_RE.match(text or "")
    if not m:
        m2 = CN_ORDINAL_RE.match(text or "")
        if not m2:
            return None
        return m2.group(1) + "、", m2.group(2).strip()
    marker = m.group(1) or m.group(2)
    item = m.group(3).strip()
    if len(item) < 2:
        return None
    return marker + ".", item


def clause(text: str) -> tuple[str, str] | None:
    """Return (number, body) for a numbered clause such as ``1.2 乙方…``.

    Guard rails matter here: financial PDFs are full of decimals ("38.97 元"),
    and a loose rule turns price labels into hundreds of fake clauses.
    """
    m = CLAUSE_RE.match(text or "")
    if not m:
        return None
    number, body = m.group(1), m.group(2).strip()
    parts = [int(p) for p in number.split(".") if p]
    if not parts or parts[0] < 1 or parts[0] > 20:
        return None
    if any(p > 30 for p in parts[1:]):
        return None
    if len(body) < 4:
        return None
    if not re.match(r"[\u4e00-\u9fff]", body):
        return None
    if re.match(r"[元万亿%％倍个成]", body):
        return None
    return number, body


def heading_level(text: str, size: float = 0.0, body_size: float = 0.0) -> int:
    """0 means "not a heading"; otherwise 1-3.

    Font size is the strongest signal, but many PDFs export everything at one
    size.  Numbered chapter/section markers are then the next best evidence.
    """
    t = clean(text)
    if not t or len(t) > 60:
        return 0
    # "年龄：23岁 电话：138…" is a label line, not a section title; a heading
    # that carries a number and a colon is almost always data.
    if ("：" in t or ":" in t) and re.search(r"[\d@]", t):
        return 0
    if size and body_size and body_size > 0:
        ratio = size / body_size
        if ratio >= 1.6:
            return 1
        if ratio >= 1.15:
            return 2
        if ratio >= 1.04 and len(t) <= 30:
            return 3
    if CHAPTER_RE.match(t):
        return 1
    if SECTION_RE.match(t) or ARTICLE_RE.match(t):
        return 2
    if CN_ORDINAL_RE.match(t) and len(t) <= 40:
        return 2
    # A short line with no sentence punctuation, followed by nothing numeric,
    # is how "工作经历" or "专业技能" renders when the exporter flattens styles.
    if len(t) <= 8 and not SENTENCE_END.search(t) and not NUMERIC_LINE.match(t):
        if not re.search(r"[，,、\d]", t) and not bullet_item(t) and not numbered_item(t):
            return 3 if re.search(r"[\u4e00-\u9fffA-Za-z]", t) else 0
    return 0


def _at_boundary(t: str, pos: int) -> bool:
    if pos == 0:
        return True
    prev = t[pos - 1]
    if prev in "。！？；:：\n":
        return True
    return prev in " \t" and pos >= 2 and t[pos - 2] in "。！？；:："


def split_inline_sections(text: str) -> list[str]:
    """Split a paragraph that swallowed several clauses into separate pieces.

    PDFs do not have paragraphs; they have lines at coordinates.  When the
    leading is tight, the layout pass merges "1.1 … 1.2 … 第二条 …" into one
    paragraph even though visually each is its own clause.  Their markers are
    still in the text, so cut on them before classifying -- but only where a
    marker actually starts a clause, otherwise "3.5%的增速" becomes a clause.
    """
    t = clean(text)
    if not t:
        return []
    marks = [m for m in SECTION_MARK_RE.finditer(t) if _at_boundary(t, m.start())]
    if len(marks) < 2:
        return [t]
    pieces: list[str] = []
    head = t[: marks[0].start()].strip()
    if head:
        pieces.append(head)
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        piece = t[mark.start():end].strip()
        if len(piece) >= 3:
            pieces.append(piece)
    return pieces


def subitem_line(text: str) -> str | None:
    """Return the normalised text when a whole line is a sub-item, else None."""
    if not SUBITEM_RE.match(text or ""):
        return None
    item = clean(text)
    return item or None


def split_subitems(text: str) -> tuple[str, list[str]]:
    """Cut a clause body into its lead-in and the ``（1）（2）`` items inside it.

    Contract clauses usually look like

        1.2 乙方向甲方提供以下服务：（1）系统架构设计（2）数据库设计

    One paragraph, three logical pieces.  Keeping the enumeration as plain
    text inside ``text`` loses the nesting; splitting on the markers restores
    it.  A single parentheses pair ("（详见附件）") is a reference, not a list,
    so at least two markers are required unless the marker follows a colon.
    """
    t = clean(text)
    if not t:
        return "", []
    marks = list(SUBITEM_MARK_RE.finditer(t))
    if not marks:
        return t, []
    colon_before = t[: marks[0].start()].rstrip().endswith(("：", ":", "；", ";"))
    if len(marks) < 2 and not colon_before:
        return t, []

    head = t[: marks[0].start()].strip()
    items: list[str] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        piece = t[mark.start():end].strip()
        # "（1）" with nothing usable after it is a stray marker, not an item
        body = SUBITEM_MARK_RE.sub("", piece, count=1).strip()
        if len(body) >= 2:
            items.append(piece)
    if len(items) < 2 and not colon_before:
        return t, []
    return head, items


def split_inline_bullets(text: str) -> tuple[str, list[str]]:
    """Split a line that holds several bullets ("… •a •b") into items.

    Resume exporters happily put a whole section's bullets on one visual line;
    the glyphs are still there, so use them as delimiters instead of returning
    one long paragraph that no longer reads as a list.
    """
    hits = list(re.finditer(rf"[{BULLET_CHARS}]", text or ""))
    if len(hits) < 2:
        return text, []
    head = text[: hits[0].start()].strip()
    items: list[str] = []
    for i, hit in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        item = text[hit.end():end].strip()
        if item:
            items.append(item)
    return head, items


def classify(
    paras: list[dict],
    body_size: float = 0.0,
    page: int | None = None,
    source: str = "pdf",
) -> list[Block]:
    """Turn reading-order paragraphs into structured blocks.

    ``paras`` items need ``text`` and (optionally) ``size``/``top``/``x0``.
    """
    blocks: list[Block] = []
    bullets: list[str] = []
    numbered: list[tuple[str, str]] = []
    list_meta: dict = {}

    expanded: list[dict] = []
    for para in paras:
        for piece in split_inline_sections(para.get("text", "")):
            head, inline = split_inline_bullets(piece)
            if inline:
                if head:
                    expanded.append({**para, "text": head})
                for item in inline:
                    expanded.append({**para, "text": f"• {item}"})
            else:
                expanded.append({**para, "text": clean(piece)})
    paras = expanded

    def flush() -> None:
        nonlocal bullets, numbered
        if bullets:
            blocks.append(
                Block(
                    kind="bullet_list",
                    items=list(bullets),
                    page=page,
                    source=source,
                    top=float(list_meta.get("top") or 0.0),
                    x0=float(list_meta.get("x0") or 0.0),
                    size=float(list_meta.get("size") or 0.0),
                )
            )
            bullets = []
        if numbered:
            blocks.append(
                Block(
                    kind="numbered_list",
                    items=[f"{marker} {item}" for marker, item in numbered],
                    page=page,
                    source=source,
                    top=float(list_meta.get("top") or 0.0),
                    x0=float(list_meta.get("x0") or 0.0),
                    size=float(list_meta.get("size") or 0.0),
                )
            )
            numbered = []

    for para in paras:
        text = clean(para.get("text", ""))
        if not text:
            continue
        size = float(para.get("size") or 0.0)
        top = float(para.get("top") or 0.0)
        x0 = float(para.get("x0") or 0.0)

        # A "（1）…" line right after a clause/paragraph belongs to it: keep the
        # nesting instead of turning it into a sibling ordered list.
        sub = subitem_line(text)
        if sub and blocks and blocks[-1].kind in ("clause", "para") and blocks[-1].page == page:
            blocks[-1].items.append(sub)
            continue

        item = bullet_item(text)
        if item:
            if numbered:
                flush()
            if not bullets:
                list_meta = {"top": top, "x0": x0, "size": size}
            bullets.append(item)
            continue
        pair = numbered_item(text)
        # "一、业务详情" is a section heading, not the first item of a list.
        if pair and CN_ORDINAL_RE.match(text) and len(text) <= 40 and not SENTENCE_END.search(text):
            pair = None
        number, clause_body = clause(text) or ("", "")
        if number:
            # "1.2 乙方…" must be a clause, not a list item numbered "1."
            pair = None
        if pair and not number:
            if bullets:
                flush()
            if not numbered:
                list_meta = {"top": top, "x0": x0, "size": size}
            numbered.append(pair)
            continue
        flush()

        if number:
            lead, subs = split_subitems(clause_body)
            blocks.append(
                Block(
                    kind="clause",
                    text=lead,
                    number=number,
                    items=subs,
                    page=page,
                    top=top,
                    x0=x0,
                    size=size,
                    source=source,
                )
            )
            continue

        lead, subs = split_subitems(text)
        level = heading_level(lead, size, body_size) if not subs else 0
        if level:
            blocks.append(
                Block(kind="heading", text=lead, level=level, page=page, top=top, x0=x0,
                      size=size, source=source)
            )
        else:
            blocks.append(
                Block(kind="para", text=lead, items=subs, page=page, top=top, x0=x0,
                      size=size, source=source)
            )
    flush()
    for i, block in enumerate(blocks, 1):
        block.id = block.id or f"b{i}"
    return blocks


def tree(blocks: list[Block]) -> dict:
    """Nest headings and their content into the JSON shape used by ``to_json``."""
    root: dict = {"type": "document", "title": "", "sections": []}
    stack: list[tuple[int, dict]] = []
    for block in blocks:
        if block.kind == "heading":
            node = {
                "type": f"heading_{max(1, min(3, block.level or 1))}",
                "title": block.text,
                "page": block.page,
                "children": [],
            }
            level = block.level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else root
            parent["sections" if parent is root else "children"].append(node)
            stack.append((level, node))
            continue
        parent = stack[-1][1] if stack else None
        if parent is None:
            root["sections"].append(_leaf(block))
        else:
            parent["children"].append(_leaf(block))
    if not root["sections"]:
        root["sections"] = [_leaf(b) for b in blocks if b.kind not in ("page",)]
    return root


def _leaf(block: Block) -> dict:
    out: dict = {"id": block.id, "type": block.kind, "page": block.page}
    if block.kind in ("bullet_list", "numbered_list"):
        out["items"] = block.items
        return out
    if block.kind == "clause":
        out.update({"number": block.number, "text": block.text})
    else:
        out["text"] = block.text
    if block.kind == "heading":
        out["level"] = block.level
    if block.items:
        out["items"] = block.items
    if block.bbox:
        out["bbox"] = list(block.bbox)
    return out


def counts(blocks: list[Block]) -> dict:
    """Small summary used by the quality scorer and the report."""
    out = {"heading": 0, "para": 0, "bullet_list": 0, "bullet_items": 0,
           "numbered_list": 0, "clause": 0, "quote": 0}
    for block in blocks:
        if block.kind in out:
            out[block.kind] += 1
        if block.kind == "bullet_list":
            out["bullet_items"] += len(block.items)
    return out
