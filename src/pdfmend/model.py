"""Core data model: documents, blocks, tables, and the quality report."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pdfmend import __version__


@dataclass
class Table:
    id: str
    rows: list[list[str]]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    origin: str = "unknown"  # lines | text | docx | xlsx | pptx
    flags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    header_rows: int = 1

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def shape(self) -> str:
        return f"{self.n_rows}x{self.n_cols}"


@dataclass
class Block:
    kind: str  # heading | para | table | page
    text: str = ""
    level: int = 0
    table: Table | None = None
    page: int | None = None


@dataclass
class Document:
    path: Path
    kind: str
    pages: int = 1
    blocks: list[Block] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    text_chars: int = 0
    cjk_chars: int = 0
    damaged_chars: int = 0
    scanned_pages: list[int] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class Report:
    document: Document
    score: int
    verdict: str
    reasons: list[str]
    tables: list[Table]

    def to_dict(self) -> dict:
        d = self.document
        return {
            "tool": "pdfmend",
            "version": __version__,
            "file": d.path.name,
            "kind": d.kind,
            "pages": d.pages,
            "text_chars": d.text_chars,
            "cjk_chars": d.cjk_chars,
            "damaged_chars": d.damaged_chars,
            "scanned_pages": d.scanned_pages,
            "score": self.score,
            "verdict": self.verdict,
            "reasons": self.reasons,
            "tables": [
                {
                    "id": t.id,
                    "page": t.page,
                    "shape": t.shape,
                    "rows": t.n_rows,
                    "cols": t.n_cols,
                    "origin": t.origin,
                    "confidence": round(t.confidence, 3),
                    "flags": t.flags,
                }
                for t in self.tables
            ],
            "meta": d.meta,
        }
