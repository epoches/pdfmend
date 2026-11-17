"""Merge per-chunk field extractions into one answer, with evidence.

Each chunk sees a slice of the document, so the same field can come back several
times: the report title from page 1, the research institute from the footer of
page 40.  Merging is not "take the last non-null":

* identical values are merged, keeping every page and quote that supports them;
* different values become a *conflict*, never silently resolved by confidence;
* before preferring the higher-confidence candidate, the evidence is checked --
  a value whose quote does not actually contain it is downgraded;
* fields that never appear are handed back for a focused second pass.

Nothing here calls a model, so merging is deterministic and testable.
"""

from __future__ import annotations

import json
import re

DATE_RE = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
NUM_CLEAN = re.compile(r"[¥￥$€£\s,，]")
MISSING = (None, "", [], {})


def normalize(kind: str, value):
    """Canonical form used to decide whether two values are the same value."""
    if kind == "date":
        m = DATE_RE.search(str(value))
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        return str(value).strip()
    if kind == "number":
        text = NUM_CLEAN.sub("", str(value))
        percent = text.endswith("%")
        text = text.rstrip("%")
        try:
            number = float(text)
        except ValueError:
            return str(value).strip()
        return round(number / 100, 6) if percent else round(number, 6)
    if isinstance(value, (list, tuple)):
        return sorted(json.dumps(_canonical(v), ensure_ascii=False, sort_keys=True) for v in value)
    if isinstance(value, dict):
        return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True)
    return " ".join(str(value).split())


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def evidence_supports(kind: str, value, evidence: str) -> bool:
    """Does the quoted original really contain this value?"""
    if not evidence:
        return False
    quote = " ".join(str(evidence).split())
    if kind in ("date", "number"):
        target = str(normalize(kind, value))
        if kind == "date":
            return target.replace("-", "") in quote.replace("-", "").replace("/", "").replace(" ", "")
        number = normalize("number", value)
        for token in re.findall(r"[-+]?\d[\d,，]*(?:\.\d+)?", quote):
            try:
                if np_close(float(token.replace(",", "").replace("，", "")), float(number)):
                    return True
            except (TypeError, ValueError):
                continue
        return False
    needle = str(value).strip()
    return bool(needle) and needle in quote


def np_close(a: float, b: float, rel: float = 0.005) -> bool:
    return abs(a - b) <= max(0.01, rel * max(abs(a), abs(b)))


def _candidate(source: dict, key: str, spec: dict, item) -> dict:
    kind = spec.get("type", "string")
    if isinstance(item, dict):
        value = item.get("value")
        evidence = item.get("evidence") or ""
        page = item.get("source_page") or item.get("page") or source["page_start"]
        confidence = item.get("confidence")
    else:
        value, evidence, page, confidence = item, "", source["page_start"], None
    try:
        confidence = float(confidence) if confidence is not None else 0.6
    except (TypeError, ValueError):
        confidence = 0.6
    return {
        "value": value,
        "kind": kind,
        "normalized": normalize(kind, value),
        "confidence": confidence,
        "evidence": evidence,
        "page": page,
        "chunk_id": source["chunk_id"],
        "supported": evidence_supports(kind, value, evidence) if evidence else False,
    }


def merge_fields(results: list[dict], profile: dict) -> dict:
    """``results`` = [{"chunk_id","page_start","page_end","fields":{...}}]."""
    specs = profile["fields"]
    merged: dict[str, dict] = {}
    for source in results:
        fields = source.get("fields") or {}
        if not isinstance(fields, dict):
            continue
        for key, item in fields.items():
            if key not in specs:
                continue
            cand = _candidate(source, key, specs[key], item)
            if cand["value"] in MISSING:
                continue
            old = merged.get(key)
            if old is None:
                merged[key] = {
                    "value": cand["value"],
                    "normalized": cand["normalized"],
                    "confidence": cand["confidence"],
                    "evidence": cand["evidence"],
                    "source_pages": [cand["page"]] if cand["page"] else [],
                    "supporting": [cand],
                    "conflicts": [],
                }
                continue
            if cand["normalized"] == old["normalized"]:
                old["confidence"] = max(old["confidence"], cand["confidence"])
                if cand["page"] and cand["page"] not in old["source_pages"]:
                    old["source_pages"].append(cand["page"])
                if cand["evidence"] and cand["evidence"] not in old["evidence"]:
                    old["evidence"] = (old["evidence"] + " / " + cand["evidence"]).strip(" /")
                old["supporting"].append(cand)
                continue
            # Different value. A supported quote beats a confident guess, but a
            # conflict is recorded either way -- the user decides.
            if _better(cand, old) :
                old["conflicts"].append(_conflict_of(old))
                old["value"] = cand["value"]
                old["normalized"] = cand["normalized"]
                old["confidence"] = cand["confidence"]
                old["evidence"] = cand["evidence"]
                old["source_pages"] = [cand["page"]] if cand["page"] else []
            else:
                old["conflicts"].append(_conflict_of(cand))

    out = {}
    for key, item in merged.items():
        out[key] = {
            "value": item["value"],
            "status": "conflict" if item["conflicts"] else "ok",
            "confidence": round(item["confidence"], 3),
            "evidence": item["evidence"],
            "source_pages": sorted(p for p in item["source_pages"] if p),
            "conflicts": item["conflicts"],
        }
    return out


def _better(cand: dict, old: dict) -> bool:
    if cand["supported"] != bool(old["supporting"] and old["supporting"][0]["supported"]):
        return cand["supported"]
    return cand["confidence"] > old["confidence"] + 0.05


def _conflict_of(cand: dict) -> dict:
    return {
        "value": cand["value"],
        "confidence": round(cand["confidence"], 3),
        "evidence": cand["evidence"],
        "page": cand["page"],
        "chunk_id": cand["chunk_id"],
    }


def missing(merged: dict, profile: dict) -> list[str]:
    return [name for name in profile["fields"] if name not in merged]


def search_pages(doc, fields: list[str], profile: dict, limit: int = 3) -> dict[int, list[str]]:
    """Pages worth re-reading for the missing fields, with the lines that hint at them."""
    hints: dict[str, list[str]] = {}
    for name in fields:
        spec = profile["fields"].get(name) or {}
        words = [w for w in (spec.get("hints") or []) if len(w) >= 2]
        hints[name] = words + ([name] if len(name) >= 2 else [])

    pages: dict[int, list[str]] = {}
    for block in doc.blocks:
        if block.kind in ("page", "table") or not block.text:
            continue
        page = block.page or 1
        text = block.text
        for name, words in hints.items():
            for word in words:
                if word in text:
                    pages.setdefault(page, [])
                    snippet = text[:200]
                    if snippet not in pages[page]:
                        pages[page].append(snippet)
                    break
    # pages with more hints first, then earlier pages
    ranked = sorted(pages.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return dict(ranked[:limit])


def payload(merged: dict, profile: dict, meta: dict) -> dict:
    """Final JSON written to disk: values first, evidence alongside."""
    fields = {}
    evidence = {}
    for name, spec in profile["fields"].items():
        item = merged.get(name)
        if item is None:
            fields[name] = None
            evidence[name] = {"status": "missing", "reason": "原文中没有找到该字段"}
            continue
        fields[name] = item["value"]
        evidence[name] = {
            "status": item["status"],
            "confidence": item["confidence"],
            "source_pages": item["source_pages"],
            "evidence": item["evidence"],
            "conflicts": item["conflicts"],
        }
    return {
        "profile": profile["name"],
        "document_type": profile.get("document_type"),
        "fields": fields,
        "evidence": evidence,
        "stats": {
            "fields": len(profile["fields"]),
            "found": sum(1 for v in fields.values() if v not in MISSING),
            "conflicts": sum(1 for e in evidence.values() if e.get("status") == "conflict"),
            "missing": [n for n, v in fields.items() if v in MISSING],
            **meta,
        },
    }
