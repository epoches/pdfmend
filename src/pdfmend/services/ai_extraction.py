"""AI field extraction service: key handling + a UI-friendly result object.

The engine (``fields.run``) reads its configuration from ``PDFMEND_LLM_*``
environment variables by design -- that is how the CLI keeps keys out of files.
The desktop app stores keys in the OS credential store instead, so this module
bridges the two: it takes the key from ``config.settings``, exports it for the
duration of one call, and always restores the environment afterwards.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pdfmend import fields, llm
from pdfmend.config import settings as config

ENV_PROVIDER = "PDFMEND_LLM_PROVIDER"
ENV_MODEL = "PDFMEND_LLM_MODEL"
ENV_BASE_URL = "PDFMEND_LLM_BASE_URL"
ENV_KEY = "PDFMEND_LLM_API_KEY"


@dataclass
class ExtractionResult:
    source: Path
    path: Path | None = None
    payload: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.payload)

    @property
    def stats(self) -> dict:
        return self.payload.get("stats", {}) if isinstance(self.payload, dict) else {}

    @property
    def fields(self) -> dict:
        return self.payload.get("fields", {}) if isinstance(self.payload, dict) else {}

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "ok": self.ok,
            "error": self.error,
            "seconds": round(self.seconds, 2),
            "output": str(self.path) if self.path else "",
            "stats": self.stats,
        }


@contextmanager
def _exported(provider: str, model: str, base_url: str, key: str):
    before = {name: os.environ.get(name) for name in (ENV_PROVIDER, ENV_MODEL, ENV_BASE_URL, ENV_KEY)}
    try:
        os.environ[ENV_PROVIDER] = provider
        if model:
            os.environ[ENV_MODEL] = model
        if base_url:
            os.environ[ENV_BASE_URL] = base_url
        if key:
            os.environ[ENV_KEY] = key
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def resolved(provider: str | None = None, model: str | None = None) -> tuple[str, str, str, str]:
    """(provider, model, base_url, key) after user settings, then defaults."""
    store = config.Settings()
    name = provider or store.provider
    default_url, default_model, _env = llm.DEFAULT_PROVIDERS.get(
        name, llm.DEFAULT_PROVIDERS["deepseek"]
    )
    chosen_model = model or (store.model if name == store.provider else "") or default_model
    base_url = (store.base_url if name == store.provider else "") or default_url
    key = config.api_key(name)
    if not key:
        key = os.environ.get(config.ENV_KEYS.get(name, ""), "")
    return name, chosen_model, base_url, key


def has_key(provider: str | None = None) -> bool:
    return bool(resolved(provider)[3])


def extract_fields(
    source,
    *,
    profile: str | None = None,
    schema=None,
    provider: str | None = None,
    model: str | None = None,
    ocr: str = "auto",
    vision: bool = False,
    out=None,
) -> ExtractionResult:
    """Run the chunked extraction pipeline and return its JSON payload."""
    src = Path(source)
    result = ExtractionResult(source=src)
    started = time.perf_counter()
    try:
        name, chosen_model, base_url, key = resolved(provider, model)
        if not key:
            env = config.ENV_KEYS.get(name, "API Key")
            raise llm.MissingKeyError(f"没有配置 {name} 的 API Key。请在设置里填写，或设置环境变量 {env}。")
        with _exported(name, chosen_model, base_url, key):
            path = fields.run(
                src,
                Path(schema) if schema else None,
                profile=profile,
                out=Path(out) if out else None,
                ocr=ocr,
                vision=vision,
            )
        result.path = Path(path)
        result.payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.seconds = time.perf_counter() - started
    return result
