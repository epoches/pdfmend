"""``pdfmend fields``: turn a document into a JSON record with an LLM.

Two things matter here beyond "call a model":

* **Long documents are chunked**, page by page, and every chunk is asked for the
  page number and a quoted line as evidence.  Merging happens locally, so a
  field on page 60 is found even though no single request could hold the file.
* **The network is opt-in.**  Text (or a page image) leaves the machine, so this
  lives behind its own command and needs a key in the environment.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from . import chunk as chunking
from . import llm, merge, profiles, quality
from .extract import extract
from .model import Document

MISSING = merge.MISSING


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
    """Single-shot prompt (kept for ``--dry-run`` and custom schemas)."""
    doc = extract(src, ocr=ocr)
    text = document_text(doc)
    images = page_images(src) if vision else []
    if not text and not images:
        raise ValueError(f"{src.name} 没有可用文本（扫描件请先 --ocr auto 并安装 pdfmend[ocr]）")
    return llm.build_field_messages(text, schema, images=images)


def profile_for(schema_path: Path | None, name: str | None) -> dict:
    if name:
        return profiles.load(name)
    if schema_path:
        return profiles.from_schema(schema_path)
    raise ValueError(
        f"请给 --profile（{', '.join(profiles.available())}）或 --schema"
    )


def make_chunks(doc: Document, enabled: bool = True) -> list[chunking.Chunk]:
    if enabled:
        return chunking.chunk_document(doc)
    segments = chunking.page_segments(doc)
    pages = sorted(segments) or [1]
    text = "\n\n".join(line for page in pages for line in segments.get(page, []))
    return [
        chunking.Chunk(
            id="chunk_001",
            page_start=pages[0],
            page_end=pages[-1],
            text=text,
            sections=[],
            context=None,
        )
    ]


def _extract_chunks(
    chunks: list[chunking.Chunk],
    profile: dict,
    cfg: llm.Config,
    *,
    src: Path,
    vision: bool,
    focus: list[str] | None = None,
    pages: list[int] | None = None,
) -> tuple[list[dict], list[str]]:
    schema_text = profiles.schema_text(profile)
    results: list[dict] = []
    errors: list[str] = []
    if pages is not None:
        chunks = [c for c in chunks if c.page_start in pages or c.page_end in pages] or chunks[:1]
    images = page_images(src) if vision else []
    for index, item in enumerate(chunks):
        attached = images if index == 0 else None
        last: Exception | None = None
        for attempt in range(2):
            try:
                data = llm.extract_chunk(
                    item.text,
                    schema_text,
                    profile.get("title") or profile["name"],
                    item.page_start,
                    item.page_end,
                    cfg,
                    context=item.context,
                    focus=focus,
                    images=attached,
                )
                inner = data.get("fields")
                fields = inner if isinstance(inner, dict) else data
                results.append(
                    {
                        "chunk_id": item.id,
                        "page_start": item.page_start,
                        "page_end": item.page_end,
                        "fields": fields,
                    }
                )
                last = None
                break
            except (llm.LLMError, ValueError) as exc:
                last = exc
        if last is not None:
            errors.append(f"{item.id}: {last}")
    return results, errors


def run(
    src: Path,
    schema_path: Path | None = None,
    *,
    profile: str | None = None,
    out: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    ocr: str = "auto",
    vision: bool = False,
    chunk: bool = True,
    second_pass: bool = True,
) -> Path:
    """Extract fields and write ``<stem>.fields.json``; returns the path."""
    prof = profile_for(schema_path, profile)
    doc = extract(src, ocr=ocr)
    if not doc.blocks and not doc.tables:
        raise ValueError(f"{src.name} 没有可用内容（扫描件请先 --ocr auto 并安装 pdfmend[ocr]）")
    chunks = make_chunks(doc, enabled=chunk)
    cfg = llm.config_from_env(provider, model)

    results, errors = _extract_chunks(chunks, prof, cfg, src=src, vision=vision)
    if not results:
        raise llm.LLMError(f"所有分块都失败了：{errors[0] if errors else '未知原因'}")
    merged = merge.merge_fields(results, prof)

    passes = 1
    missing = merge.missing(merged, prof)
    if second_pass and missing:
        found_pages = merge.search_pages(doc, missing, prof)
        if found_pages:
            segments = chunking.page_segments(doc)
            focused = chunking.Chunk(
                id="chunk_missing",
                page_start=min(found_pages),
                page_end=max(found_pages),
                text="\n\n".join(
                    line for page in sorted(found_pages) for line in segments.get(page, [])
                ),
                sections=[],
                context=None,
            )
            extra, more_errors = _extract_chunks(
                [focused], prof, cfg, src=src, vision=False, focus=missing
            )
            errors.extend(more_errors)
            results.extend(extra)
            merged = merge.merge_fields(results, prof)
            passes = 2

    evidenced = sum(
        1 for item in merged.values() if isinstance(item, dict) and item.get("evidence")
    )
    doc.meta["extraction"] = {
        "total": len(prof["fields"]),
        "found": len(merged),
        "evidenced": evidenced,
        "conflicts": sum(1 for item in merged.values() if item.get("status") == "conflict"),
    }
    report = quality.score_document(doc)
    info = {
        "chunked": chunk,
        "passes": passes,
        "pages": doc.pages if isinstance(doc.pages, int) else len(doc.pages),
        "chunks": len(chunks),
        "errors": errors,
    }
    payload = merge.payload(merged, prof, info)
    payload.update(info)
    payload.update(
        {
            "file": src.name,
            "provider": cfg.provider,
            "model": cfg.model,
            "vision": vision,
        }
    )
    payload["quality"] = {"score": report.score, "verdict": report.verdict}
    target = out or src.with_suffix(".fields.json")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def dry_run_messages(
    src: Path,
    schema_path: Path | None = None,
    *,
    profile: str | None = None,
    ocr: str = "auto",
    vision: bool = False,
) -> list[dict]:
    """Exactly what would be sent, without reading a key or calling out."""
    if profile:
        prof = profiles.load(profile)
        doc = extract(src, ocr=ocr)
        chunks = make_chunks(doc)[:1]
        item = chunks[0]
        return llm.build_chunk_messages(
            item.text,
            profiles.schema_text(prof),
            prof.get("title") or prof["name"],
            item.page_start,
            item.page_end,
            context=item.context,
            images=page_images(src) if vision else None,
        )
    if schema_path is None:
        raise ValueError("dry-run 需要 --profile 或 --schema")
    return build_messages(src, load_schema(schema_path), ocr=ocr, vision=vision)
