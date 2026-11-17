"""User preferences and API-key storage.

Preferences live in ``QSettings`` when Qt is available (the desktop app), and
in a small JSON file otherwise (CLI, tests).  API keys never go to either of
those places: they go to the OS credential store via ``keyring`` and are read
from the environment as a fallback, so a settings file can be copied around or
pasted into an issue without leaking a key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP = "PDFMend"
ORG = "pdfmend"
CONFIG_DIR = Path(os.environ.get("PDFMEND_CONFIG_DIR") or Path.home() / ".pdfmend")
CONFIG_FILE = CONFIG_DIR / "settings.json"

PROVIDERS = ("deepseek", "qwen", "openai")
ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

DEFAULTS: dict[str, Any] = {
    "output_dir": "",
    "formats": ["md", "xlsx", "json", "html"],
    "ocr": "auto",
    "provider": "deepseek",
    "model": "",
    "base_url": "",
    "theme": "system",
    "last_open_dir": "",
    "check_updates": True,
    "webhook": "",
}


class _JsonStore:
    """Tiny persistent key/value store used when Qt is not importable."""

    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self._load()
        data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _QtStore:
    """QSettings backend (registry on Windows, ini file elsewhere)."""

    def __init__(self) -> None:
        from PySide6.QtCore import QSettings  # imported lazily: CLI must not need Qt

        self._q = QSettings(ORG, APP)

    def get(self, key: str, default: Any = None) -> Any:
        value = self._q.value(key, default)
        return value

    def set(self, key: str, value: Any) -> None:
        self._q.setValue(key, value)
        self._q.sync()


class _MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


def default_store():
    """QSettings in the desktop app, JSON for scripts, memory for tests."""
    try:
        return _QtStore()
    except Exception:  # no PySide6, no display, or a broken Qt install
        return _JsonStore()


def memory_store() -> _MemoryStore:
    return _MemoryStore()


class Settings:
    """Typed access to the preference store with sane defaults."""

    def __init__(self, store=None) -> None:
        self._store = store or default_store()

    # -- generic ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        value = self._store.get(key, None)
        if value is None or value == "":
            return DEFAULTS.get(key, default)
        if isinstance(value, str) and key == "formats":
            return [f for f in value.split(",") if f]
        if isinstance(value, str) and key in ("check_updates",):
            return value.lower() in ("1", "true", "yes")
        return value

    def set(self, key: str, value: Any) -> None:
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        self._store.set(key, value)

    # -- typed helpers ---------------------------------------------------
    @property
    def output_dir(self) -> Path | None:
        raw = self.get("output_dir", "")
        return Path(raw) if raw else None

    @output_dir.setter
    def output_dir(self, value) -> None:
        self.set("output_dir", str(value or ""))

    @property
    def formats(self) -> list[str]:
        value = self.get("formats", list(DEFAULTS["formats"]))
        if isinstance(value, str):
            value = [v for v in value.split(",") if v]
        return [f for f in value if f in ("md", "xlsx", "json", "html")]

    @formats.setter
    def formats(self, value) -> None:
        self.set("formats", list(value))

    @property
    def ocr(self) -> str:
        value = str(self.get("ocr", "auto"))
        return value if value in ("auto", "always", "never") else "auto"

    @ocr.setter
    def ocr(self, value: str) -> None:
        self.set("ocr", value)

    @property
    def provider(self) -> str:
        value = str(self.get("provider", "deepseek"))
        return value if value in PROVIDERS else "deepseek"

    @provider.setter
    def provider(self, value: str) -> None:
        self.set("provider", value)

    @property
    def model(self) -> str:
        return str(self.get("model", "") or "")

    @model.setter
    def model(self, value: str) -> None:
        self.set("model", value)

    @property
    def base_url(self) -> str:
        return str(self.get("base_url", "") or "")

    @base_url.setter
    def base_url(self, value: str) -> None:
        self.set("base_url", value)

    @property
    def theme(self) -> str:
        value = str(self.get("theme", "system"))
        return value if value in ("system", "light", "dark") else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        self.set("theme", value)

    @property
    def recent_files(self) -> list[str]:
        raw = self._store.get("recent_files", []) or []
        if isinstance(raw, str):
            raw = [part for part in raw.split("|") if part]
        return [str(item) for item in raw]

    def add_recent(self, path, limit: int = 10) -> None:
        items = [p for p in self.recent_files if p != str(path)]
        items.insert(0, str(path))
        self._store.set("recent_files", items[:limit])

    def as_dict(self) -> dict[str, Any]:
        return {key: self.get(key) for key in DEFAULTS}


# ---------------------------------------------------------------- API keys
def _keyring():
    try:
        import keyring  # noqa: PLC0415 - optional dependency

        backend = keyring.get_keyring()
        name = type(backend).__name__.lower()
        if "fail" in name or "null" in name:
            return None
        return keyring
    except Exception:
        return None


def set_api_key(provider: str, key: str | None) -> bool:
    """Store a key in the OS credential store. Returns False if unavailable."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        if key:
            kr.set_password(f"{APP}:{provider}", "api_key", key)
        else:
            try:
                kr.delete_password(f"{APP}:{provider}", "api_key")
            except Exception:
                pass
        return True
    except Exception:
        return False


def api_key(provider: str) -> str:
    """Key for ``provider``: credential store first, environment second."""
    kr = _keyring()
    if kr is not None:
        try:
            stored = kr.get_password(f"{APP}:{provider}", "api_key")
            if stored:
                return stored
        except Exception:
            pass
    env = ENV_KEYS.get(provider)
    return os.environ.get(env, "") if env else ""


def masked(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:5]}...{key[-4:]}"
