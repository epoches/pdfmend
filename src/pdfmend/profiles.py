"""Document profiles: what to extract depends on what kind of document it is.

A contract and a resume have nothing in common beyond being PDFs.  A generic
"extract everything" prompt produces a soup of keys; a profile names the fields,
their types, and the words that tend to introduce them in the original text.

Profiles are data (JSON files in ``profiles/``), not code, so adding a template
never touches the extraction engine.  The engine still decides *how* to read the
document; the profile only says *what* matters.
"""

from __future__ import annotations

import json
from pathlib import Path

PROFILE_DIR = Path(__file__).with_name("profiles")
ALIASES = {
    "简历": "resume",
    "resume": "resume",
    "合同": "contract",
    "contract": "contract",
    "研报": "research_report",
    "报告": "research_report",
    "report": "research_report",
    "research": "research_report",
    "generic": "default",
    "通用": "default",
    "default": "default",
}


class ProfileError(ValueError):
    pass


def available() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


def load(name: str) -> dict:
    key = ALIASES.get(str(name).strip().lower(), str(name).strip())
    path = PROFILE_DIR / f"{key}.json"
    if not path.exists():
        raise ProfileError(
            f"未知模板 {name!r}；可用：{', '.join(available())}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("fields"), dict) or not data["fields"]:
        raise ProfileError(f"{path.name} 没有定义 fields")
    data.setdefault("name", key)
    data.setdefault("document_type", key)
    data.setdefault("title", key)
    return data


def from_schema(path: Path) -> dict:
    """Wrap a plain ``{field: description}`` schema file as a default profile."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ProfileError("schema 必须是非空 JSON 对象")
    fields = {}
    for key, value in data.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("type", "string")
        else:
            item = {"type": "string", "description": str(value)}
        fields[str(key)] = item
    return {
        "name": "custom",
        "document_type": "document",
        "title": "自定义字段",
        "description": "用户提供的字段清单",
        "fields": fields,
        "structure": {},
    }


def field_names(profile: dict) -> list[str]:
    return list(profile["fields"].keys())


def schema_text(profile: dict) -> str:
    """Human-readable field list used in prompts (kept small on purpose)."""
    lines = []
    for name, spec in profile["fields"].items():
        kind = spec.get("type", "string")
        hints = spec.get("hints") or []
        note = f"（线索词：{'、'.join(hints[:6])}）" if hints else ""
        lines.append(f"- {name} [{kind}]{note}")
    return "\n".join(lines)


def hints_for(profile: dict, field: str) -> list[str]:
    spec = profile["fields"].get(field) or {}
    return list(spec.get("hints") or []) + [field]
