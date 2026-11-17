"""Local conversion log and the "support the author" reminder counter.

Every finished conversion appends one JSON line to ``tmp/conversions.jsonl``
next to the program; the counter in ``tmp/usage.json`` drives the reminder:
unregistered copies see the donation dialog once per five successful
conversions, registered copies never do.

This file is entirely local.  Nothing is uploaded, and deleting ``tmp/``
simply starts the history over.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from pdfmend import licensing, runtime

PROMPT_EVERY = 5


def _read_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def log_conversion(result, extra: dict | None = None) -> dict:
    """Append one line describing a finished conversion; returns the entry."""
    path = runtime.conversions_file()
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "source": str(getattr(result, "source", "")),
        "ok": bool(getattr(result, "ok", False)),
        "score": int(getattr(result, "score", 0) or 0),
        "verdict": str(getattr(result, "verdict", "") or ""),
        "seconds": round(float(getattr(result, "seconds", 0.0) or 0.0), 2),
        "outputs": list(getattr(result, "outputs", {}) or {}),
        "error": getattr(result, "error", None),
    }
    if extra:
        entry.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def usage() -> dict:
    return _read_json(runtime.usage_file(), {"count": 0, "prompted_at": 0.0})


def record_success() -> int:
    """Count one successful conversion; returns the new total."""
    data = usage()
    data["count"] = int(data.get("count") or 0) + 1
    _write_json(runtime.usage_file(), data)
    return data["count"]


def count() -> int:
    return int(usage().get("count") or 0)


def should_prompt(registered: bool | None = None) -> bool:
    """True when the next dialog is due (unregistered, every 5 conversions)."""
    if registered is None:
        registered = licensing.is_registered()
    if registered:
        return False
    total = count()
    if total <= 0 or total % PROMPT_EVERY:
        return False
    return total > int(usage().get("prompted_at") or 0)


def mark_prompted() -> None:
    data = usage()
    data["prompted_at"] = count()
    _write_json(runtime.usage_file(), data)


def history(limit: int = 20) -> list[dict]:
    path = runtime.conversions_file()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-limit:]


def reset() -> None:
    for path in (runtime.usage_file(), runtime.conversions_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def now() -> float:  # small helper for callers that only need a timestamp
    return time.time()
