"""Optional LLM helpers: field extraction (DeepSeek) and page reading (Qwen-VL).

Design rules, because this code is published:

* **No key ever lives in the repo.**  Keys come from the environment only
  (``DEEPSEEK_API_KEY`` / ``DASHSCOPE_API_KEY`` / ``PDFMEND_LLM_API_KEY``).
  ``.env.example`` holds placeholders; ``.env`` is git-ignored.
* **No key ever reaches a log or an exception message.**  Errors are masked.
* **Off by default.**  Nothing here runs unless the user calls ``pdfmend
  fields`` or passes ``--ai``; the converter stays fully local.

Every provider speaks the OpenAI-compatible ``/chat/completions`` protocol, so
there is one code path and no vendor SDK.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_PROVIDERS: dict[str, tuple[str, str, str]] = {
    # name: (base_url, model, key env var)
    "deepseek": ("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "qwen": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3-vl-plus",
        "DASHSCOPE_API_KEY",
    ),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
}


class LLMError(RuntimeError):
    """The provider refused or answered something unusable."""


class MissingKeyError(LLMError):
    """No API key in the environment."""


def _mask(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


@dataclass(frozen=True)
class Config:
    provider: str
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)  # never in repr()
    timeout: float = 90.0

    def describe(self) -> str:
        return f"{self.provider} / {self.model} / key={_mask(self.api_key)}"


def config_from_env(provider: str | None = None, model: str | None = None) -> Config:
    """Resolve provider settings from flags first, then the environment."""
    name = (provider or os.environ.get("PDFMEND_LLM_PROVIDER") or "deepseek").lower()
    if name not in DEFAULT_PROVIDERS:
        raise LLMError(
            f"未知 provider：{name}（可选：{', '.join(sorted(DEFAULT_PROVIDERS))}）"
        )
    base, default_model, key_env = DEFAULT_PROVIDERS[name]
    return Config(
        provider=name,
        base_url=os.environ.get("PDFMEND_LLM_BASE_URL") or base,
        model=model or os.environ.get("PDFMEND_LLM_MODEL") or default_model,
        api_key=os.environ.get("PDFMEND_LLM_API_KEY") or os.environ.get(key_env, ""),
        timeout=float(os.environ.get("PDFMEND_LLM_TIMEOUT") or 90),
    )


def _post(path: str, payload: dict, cfg: Config) -> dict:
    if not cfg.api_key:
        _, _, key_env = DEFAULT_PROVIDERS[cfg.provider]
        raise MissingKeyError(
            f"没有 {cfg.provider} 的 API key。设置环境变量 {key_env}"
            f"（或 PDFMEND_LLM_API_KEY）后重试；key 只从环境读取，不会写进任何文件。"
        )
    request = urllib.request.Request(
        cfg.base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        detail = detail.replace(cfg.api_key, _mask(cfg.api_key))
        raise LLMError(f"{cfg.provider} 返回 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"连不上 {cfg.base_url}：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMError(f"{cfg.provider} 超时（{cfg.timeout:.0f}s）") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMError(f"响应不是 JSON：{body[:200]}") from exc


def chat(
    messages: list[dict],
    cfg: Config | None = None,
    *,
    json_object: bool = False,
    max_tokens: int = 2000,
    temperature: float = 0.2,
) -> str:
    cfg = cfg or config_from_env()
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    body = _post("/chat/completions", payload, cfg)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"响应缺少 choices：{str(body)[:200]}") from exc
    if isinstance(content, list):  # some VL models return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def parse_json(text: str) -> dict:
    """Tolerate ```json fences and chatter around the object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"模型没返回 JSON 对象：{text[:200]}")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败：{exc.msg}（{text[:200]}）") from exc
    if not isinstance(value, dict):
        raise LLMError("模型返回的 JSON 不是对象")
    return value


SYSTEM_PROMPT = (
    "你是严谨的文档字段抽取器。只依据用户给的文本作答，不要推测。"
    "只输出一个 JSON 对象，键来自 schema，找不到的字段填 null。"
)

VISION_PROMPT = (
    "你是严谨的文档字段抽取器。用户会给出页面图片和（可能不完整的）文本，"
    "以图片为准，文本只作补充。只输出一个 JSON 对象，键来自 schema，"
    "找不到的字段填 null；看不清就填 null，不要猜。"
)


def _data_url(image: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def build_field_messages(
    text: str,
    schema: dict,
    images: list[bytes] | None = None,
    max_chars: int = 12000,
) -> list[dict]:
    clipped = text if len(text) <= max_chars else text[:max_chars] + "\n...(已截断)"
    body = (
        "schema：\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n\n文档文本：\n"
        + clipped
    )
    if not images:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": body},
        ]
    parts: list[dict] = [{"type": "text", "text": body}]
    for image in images:
        parts.append({"type": "image_url", "image_url": {"url": _data_url(image)}})
    return [
        {"role": "system", "content": VISION_PROMPT},
        {"role": "user", "content": parts},
    ]


def extract_fields(
    text: str,
    schema: dict,
    cfg: Config | None = None,
    **kwargs,
) -> dict:
    """Ask the model for the schema fields; returns the parsed object."""
    cfg = cfg or config_from_env()
    messages = build_field_messages(text, schema)
    content = chat(messages, cfg, json_object=True, max_tokens=1500, **kwargs)
    return parse_json(content)


def understand_image(
    image_bytes: bytes,
    question: str,
    cfg: Config | None = None,
    mime: str = "image/png",
) -> str:
    """One-shot question about a page image (Qwen-VL or any vision model)."""
    cfg = cfg or config_from_env()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": _data_url(image_bytes, mime)}},
            ],
        }
    ]
    return chat(messages, cfg, max_tokens=1200)
