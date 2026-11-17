"""Chunk a document for field extraction.

A 67-page report does not fit in one prompt.  Truncating at 12k characters loses
whatever sits after the cut -- typically the exact field the user asked for
("研究机构" lives in the footer of the last page).  So the document is split
into page-aligned chunks, each extracted separately, and the results merged.

Design notes:

* chunks are built from *pages* first, so every chunk knows its page range and
  every value can point back at a page;
* a chunk never exceeds ``max_chars``: an oversized page is split on segment
  boundaries, and a single oversized segment on line boundaries;
* consecutive chunks overlap by a few hundred characters, so a clause cut in
  half is still readable by the next chunk;
* the overlap is carried separately (``context``) and never counted as the
  chunk's own content, otherwise the same page would be attributed twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .model import Block, Document

DEFAULT_TARGET = 6500
DEFAULT_OVERLAP = 600
DEFAULT_MAX = 8000


@dataclass
class Chunk:
    id: str
    page_start: int
    page_end: int
    text: str
    sections: list[str] = field(default_factory=list)
    context: str = ""
    part: int = 1

    @property
    def char_count(self) -> int:
        return len(self.text)

    def prompt_text(self, with_context: bool = True) -> str:
        if with_context and self.context:
            return f"[上文，仅供参考，不要重复抽取]\n{self.context}\n[本段开始]\n{self.text}"
        return self.text

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "part": self.part,
            "chars": self.char_count,
            "sections": self.sections,
        }


def _block_text(block: Block) -> str:
    if block.kind == "heading":
        return "#" * max(1, min(3, block.level or 1)) + " " + block.text
    if block.kind in ("bullet_list", "numbered_list"):
        return "\n".join(f"- {item}" for item in block.items)
    if block.kind == "clause":
        return (f"{block.number}. " if block.number else "") + block.text
    if block.kind == "table" and block.table:
        t = block.table
        rows = [" | ".join(c for c in row) for row in t.rows]
        head = f"[表 {t.id}，第 {t.page or '?'} 页，{t.shape}]"
        return head + "\n" + "\n".join(rows)
    return block.text


def page_segments(doc: Document) -> dict[int, list[str]]:
    """Group block texts by page, in reading order."""
    pages: dict[int, list[str]] = {}
    current = 1
    for block in doc.blocks:
        if block.kind == "page":
            current = block.page or current
            pages.setdefault(current, [])
            continue
        page = block.page or current
        text = _block_text(block)
        if text.strip():
            pages.setdefault(page, []).append(text)
    if not pages:
        pages[1] = [doc.path.name]
    return dict(sorted(pages.items()))


def _split_long_text(text: str, limit: int) -> list[str]:
    """Split on line boundaries, then hard-wrap, so no chunk exceeds ``limit``."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines():
        while len(line) > limit:
            if buf:
                parts.append("\n".join(buf))
                buf, size = [], 0
            parts.append(line[:limit])
            line = line[limit:]
        if size + len(line) + 1 > limit and buf:
            parts.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        parts.append("\n".join(buf))
    return parts


def _headings(segments: list[str]) -> list[str]:
    out = []
    for segment in segments:
        first = segment.splitlines()[0] if segment else ""
        if first.startswith("#"):
            out.append(first.lstrip("# ").strip())
    return out


def chunk_document(
    doc: Document,
    target: int = DEFAULT_TARGET,
    overlap: int = DEFAULT_OVERLAP,
    max_chars: int = DEFAULT_MAX,
) -> list[Chunk]:
    """Page-aligned chunks with a little context overlap between them."""
    pages = page_segments(doc)
    chunks: list[Chunk] = []
    buf_pages: list[int] = []
    buf_segments: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf_pages, buf_segments, buf_len
        if not buf_segments:
            return
        text = "\n".join(buf_segments)
        chunks.append(
            Chunk(
                id=f"chunk_{len(chunks) + 1:03d}",
                page_start=buf_pages[0],
                page_end=buf_pages[-1],
                text=text,
                sections=_headings(buf_segments),
            )
        )
        buf_pages, buf_segments, buf_len = [], [], 0

    for page_no, segments in pages.items():
        page_len = sum(len(s) + 1 for s in segments)
        if page_len > max_chars:
            # One page, more than a whole chunk: keep its parts on their own.
            flush()
            for part_no, piece in enumerate(_split_long_text("\n".join(segments), max_chars), 1):
                chunks.append(
                    Chunk(
                        id=f"chunk_{len(chunks) + 1:03d}",
                        page_start=page_no,
                        page_end=page_no,
                        text=piece,
                        sections=_headings(piece.splitlines()),
                        part=part_no,
                    )
                )
            continue
        if buf_segments and buf_len + page_len > target:
            flush()
        buf_pages.append(page_no)
        buf_segments.extend(segments)
        buf_len += page_len
    flush()

    for i, chunk in enumerate(chunks):
        if i == 0 or not overlap:
            continue
        previous = chunks[i - 1]
        tail = previous.text[-overlap:]
        cut = tail.find("\n")
        if 0 <= cut < len(tail) - 1:
            tail = tail[cut + 1:]
        chunk.context = tail.strip()
    return chunks


def coverage(chunks: list[Chunk], doc: Document) -> dict:
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.page_start, chunk.page_end + 1))
    missing = [p for p in range(1, doc.pages + 1) if p not in covered]
    return {
        "pages": doc.pages,
        "covered": len(covered),
        "missing": missing,
        "chunks": len(chunks),
    }
