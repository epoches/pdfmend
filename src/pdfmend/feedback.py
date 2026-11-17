"""Human corrections to structure recognition (P2).

The rule engine is deterministic, which is good for reproducibility and bad
for the long tail: the reviewer still has to fix the occasional paragraph the
rules called a heading.  Every fix is worth recording -- not to train a model
yet, but to see which confusions repeat, and to turn them into regression
fixtures.

A correction is one JSON object per line::

    {"v": 1, "created_at": "...", "document": "x.pdf", "document_type": "contract",
     "page": 3, "block_id": "b17", "bbox": null,
     "original_type": "para", "corrected_type": "clause",
     "original_text": "...", "note": "第二条其实是条款"}

Append-only by design: rewriting history would destroy the very signal we are
collecting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("heading", "para", "bullet_list", "numbered_list", "clause", "quote", "table")
DEFAULT_FILE = Path("corrections.jsonl")


class FeedbackError(ValueError):
    """Raised for a bad target kind, unknown block id, or unreadable structure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_structure(path: str | Path) -> dict:
    """Read the JSON produced by ``pdfmend structure --json``."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("structure"), dict):
        return raw["structure"]
    if isinstance(raw, dict) and ("sections" in raw or "blocks" in raw):
        return raw
    raise FeedbackError(f"{path}: 不是 pdfmend structure 的输出")


def _walk(node: dict):
    yield node
    for key in ("sections", "children"):
        for child in node.get(key) or []:
            yield from _walk(child)


def find_block(structure: dict, block_id: str) -> dict:
    if isinstance(structure.get("blocks"), list):
        for item in structure["blocks"]:
            if item.get("id") == block_id:
                return item
    for node in _walk(structure):
        if node.get("id") == block_id:
            return node
    raise FeedbackError(f"结构里没有 {block_id} 这个块；先看 pdfmend structure --json 的 id")


def _block_text(block: dict) -> str:
    text = block.get("text") or ""
    items = block.get("items") or []
    if items:
        text = (text + " " + " ".join(str(i) for i in items)).strip()
    return text[:400]


def record(
    structure: dict,
    block_id: str,
    corrected_type: str,
    *,
    document: str = "",
    document_type: str = "",
    note: str = "",
    created_at: str | None = None,
) -> dict:
    """Build a correction record from a structure tree and a block id."""
    if corrected_type not in KINDS:
        raise FeedbackError(f"不认识的类型 {corrected_type!r}；可选：{'、'.join(KINDS)}")
    block = find_block(structure, block_id)
    original = block.get("type") or ""
    if original.startswith("heading_"):
        original = "heading"
    if original == corrected_type:
        raise FeedbackError(f"{block_id} 已经是 {corrected_type}，不需要纠正")
    return {
        "v": 1,
        "created_at": created_at or _now(),
        "document": document,
        "document_type": document_type,
        "page": block.get("page"),
        "block_id": block_id,
        "bbox": block.get("bbox"),
        "original_type": original,
        "corrected_type": corrected_type,
        "original_text": _block_text(block),
        "note": note,
    }


def append(record_item: dict, path: str | Path = DEFAULT_FILE) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record_item, ensure_ascii=False) + "\n")
    return target


def load(path: str | Path = DEFAULT_FILE) -> list[dict]:
    target = Path(path)
    if not target.is_file():
        return []
    out: list[dict] = []
    for lineno, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise FeedbackError(f"{target}:{lineno} 不是合法 JSON：{exc}") from exc
    return out


def stats(records: list[dict]) -> dict:
    transitions: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for item in records:
        key = f"{item.get('original_type', '?')} -> {item.get('corrected_type', '?')}"
        transitions[key] = transitions.get(key, 0) + 1
        doc_type = item.get("document_type") or "(未标注)"
        by_type[doc_type] = by_type.get(doc_type, 0) + 1
    top = sorted(transitions.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"total": len(records), "transitions": dict(top), "by_document_type": by_type}
