"""``pdfmend fields``: turn a document into a JSON record with an LLM.

This is opt-in and networked: the extracted text (or a page image) leaves the
machine.  Callers must know that, which is why it lives behind its own command
and needs an API key in the environment.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from . import llm
from .extract import extract
from .model import Document


def load_schema(path: Path) -> dict:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} 不是合法 JSON：{exc.msg}") from exc
    if not isinstance(schema, dict) or not schema:
        raise ValueError("schema 必须是非空 JSON 对象，例如 {\"金额\": \"数字\", \"日期\": \"YYYY-MM-DD\"}")
    return schema


def document_text(doc: Document) -> str:
    parts = [b.text for b in doc.blocks if b.kind in ("para", "heading") and b.text]
    for table in doc.tables:
        parts.append("\n".join(" | ".join(row) for row in table.rows))
    return "\n".join(parts).strip()


def _png(page, dpi: int) -> bytes:
    buffer = io.BytesIO()
    page.to_image(resolution=dpi).original.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def page_images(src: Path, limit: int = 3, dpi: int = 144) -> list[bytes]:
    """Render the first pages to PNG so a vision model can look at them."""
    if src.suffix.lower() != ".pdf":
        return []
    import pdfplumber

    with pdfplumber.open(str(src)) as pdf:
        return [_png(page, dpi) for page in pdf.pages[:limit]]


def build_messages(src: Path, schema: dict, ocr: str = "auto", vision: bool = False) -> list[dict]:
    doc = extract(src, ocr=ocr)
    text = document_text(doc)
    images = page_images(src) if vision else []
    if not text and not images:
        raise ValueError(f"{src.name} 没有可用文本（扫描件请先 --ocr auto 并安装 pdfmend[ocr]）")
    return llm.build_field_messages(text, schema, images=images)


def run(
    src: Path,
    schema_path: Path,
    *,
    out: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    ocr: str = "auto",
    vision: bool = False,
) -> Path:
    """Extract fields and write ``<stem>.fields.json``; returns the path."""
    schema = load_schema(schema_path)
    messages = build_messages(src, schema, ocr=ocr, vision=vision)
    cfg = llm.config_from_env(provider, model)
    content = llm.chat(messages, cfg, json_object=True, max_tokens=1500)
    fields = llm.parse_json(content)
    target = out or src.with_suffix(".fields.json")
    payload = {
        "file": src.name,
        "provider": cfg.provider,
        "model": cfg.model,
        "vision": vision,
        "fields": fields,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
