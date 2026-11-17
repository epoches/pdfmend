"""Chunking: page ranges, overlap, and the max-size guarantee."""

from __future__ import annotations

from pathlib import Path

from pdfmend import chunk
from pdfmend.model import Block, Document


def _doc(pages: int = 5, chars_per_page: int = 300) -> Document:
    doc = Document(path=Path("x.pdf"), kind="pdf", pages=pages)
    for page in range(1, pages + 1):
        doc.blocks.append(Block(kind="para", text=f"第{page}页。" + "内容" * chars_per_page, page=page))
    return doc


def test_page_segments_prefix_headings():
    doc = Document(path=Path("x.pdf"), kind="pdf", pages=1)
    doc.blocks = [Block(kind="heading", text="工作经历", level=2, page=1), Block(kind="para", text="某公司", page=1)]
    segments = chunk.page_segments(doc)
    assert segments[1][0] == "## 工作经历"


def test_chunks_are_page_aligned_and_cover_every_page():
    doc = _doc(pages=5, chars_per_page=300)
    chunks = chunk.chunk_document(doc, target=1200, overlap=100)
    assert len(chunks) >= 2
    assert all(c.page_start <= c.page_end for c in chunks)
    report = chunk.coverage(chunks, doc)
    assert report["missing"] == []
    assert report["covered"] == 5


def test_later_chunks_carry_overlap_as_context():
    doc = _doc(pages=5, chars_per_page=300)
    chunks = chunk.chunk_document(doc, target=1200, overlap=100)
    assert chunks[0].context == ""
    assert chunks[1].context
    assert "仅供参考" in chunks[1].prompt_text()
    assert chunks[1].char_count <= chunk.DEFAULT_MAX


def test_oversized_page_is_split_and_keeps_its_page_number():
    doc = Document(path=Path("x.pdf"), kind="pdf", pages=1)
    doc.blocks = [Block(kind="para", text="字" * 20000, page=1)]
    chunks = chunk.chunk_document(doc, target=1000, max_chars=4000)
    assert len(chunks) >= 5
    assert {c.page_start for c in chunks} == {1}
    assert all(c.part >= 1 and c.char_count <= 4000 for c in chunks)
    assert [c.id for c in chunks] == [f"chunk_{i:03d}" for i in range(1, len(chunks) + 1)]


def test_empty_document_still_yields_one_chunk():
    doc = Document(path=Path("empty.pdf"), kind="pdf", pages=1)
    chunks = chunk.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].page_start == 1
