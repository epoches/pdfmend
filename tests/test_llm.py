"""Tests for the optional LLM layer.  No network, no real keys."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from pdfmend import llm

FAKE_KEY = "sk-test-key-123"


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_parse_json_accepts_fences_and_chatter():
    assert llm.parse_json('```json\n{"amount": "1,200.00"}\n```') == {"amount": "1,200.00"}
    assert llm.parse_json('好的：{"date": "2026-01-05"} 以上') == {"date": "2026-01-05"}


def test_parse_json_rejects_non_json():
    with pytest.raises(llm.LLMError):
        llm.parse_json("抱歉，我无法完成")


def test_missing_key_names_the_env_var(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PDFMEND_LLM_API_KEY", raising=False)
    cfg = llm.config_from_env("deepseek")
    with pytest.raises(llm.MissingKeyError) as excinfo:
        llm.chat([{"role": "user", "content": "hi"}], cfg)
    assert "DEEPSEEK_API_KEY" in str(excinfo.value)


def test_key_is_masked_in_repr_and_describe():
    cfg = llm.Config(provider="deepseek", base_url="https://x", model="m", api_key=FAKE_KEY)
    assert FAKE_KEY not in repr(cfg)
    assert FAKE_KEY not in cfg.describe()
    assert cfg.describe().startswith("deepseek / m / key=sk-t")


def test_env_overrides_provider_settings(monkeypatch):
    monkeypatch.setenv("PDFMEND_LLM_PROVIDER", "qwen")
    monkeypatch.setenv("PDFMEND_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("PDFMEND_LLM_MODEL", "qwen3-vl-plus")
    monkeypatch.setenv("PDFMEND_LLM_API_KEY", "sk-test-env")
    cfg = llm.config_from_env()
    assert cfg.provider == "qwen"
    assert cfg.base_url == "https://proxy.example/v1"
    assert cfg.model == "qwen3-vl-plus"
    assert cfg.api_key == "sk-test-env"


def test_chat_sends_bearer_header_and_json_mode(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        return _Response({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = llm.Config(provider="deepseek", base_url="https://example.test/v1", model="deepseek-chat", api_key=FAKE_KEY)
    out = llm.chat([{"role": "user", "content": "hi"}], cfg, json_object=True)

    assert out == '{"ok": true}'
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == f"Bearer {FAKE_KEY}"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["model"] == "deepseek-chat"


def test_http_error_never_leaks_the_key(monkeypatch):
    def boom(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(f'{{"error":"bad key {FAKE_KEY}"}}'.encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", boom)
    cfg = llm.Config(provider="deepseek", base_url="https://x", model="m", api_key=FAKE_KEY)
    with pytest.raises(llm.LLMError) as excinfo:
        llm.chat([{"role": "user", "content": "hi"}], cfg)
    message = str(excinfo.value)
    assert "401" in message
    assert FAKE_KEY not in message


def test_field_messages_truncate_long_text():
    messages = llm.build_field_messages("x" * 20000, {"amount": "number"}, max_chars=1000)
    assert messages[0]["role"] == "system"
    assert "已截断" in messages[1]["content"]
    assert len(messages[1]["content"]) < 2000


def test_extract_fields_parses_model_output(monkeypatch):
    def fake_chat(messages, cfg=None, **kwargs):
        return '```json\n{"amount": 1200.0, "date": "2026-01-05"}\n```'

    monkeypatch.setattr(llm, "chat", fake_chat)
    cfg = llm.Config(provider="deepseek", base_url="https://x", model="m", api_key=FAKE_KEY)
    assert llm.extract_fields("text", {"amount": "number"}, cfg) == {
        "amount": 1200.0,
        "date": "2026-01-05",
    }
