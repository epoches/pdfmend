"""``pdfmend fields`` plumbing: schema loading, dry run, file output."""

from __future__ import annotations

import json

import pytest

from pdfmend import cli, fields, llm


@pytest.fixture
def schema_file(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"amount": "数字", "date": "YYYY-MM-DD"}, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_schema_rejects_arrays(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        fields.load_schema(bad)


def test_document_text_keeps_tables(sample_docx):
    from pdfmend.extract import extract

    text = fields.document_text(extract(sample_docx))
    assert "季度报告" in text
    assert "华东" in text and "1200" in text


def test_dry_run_needs_no_key(sample_docx, schema_file, capsys, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PDFMEND_LLM_API_KEY", raising=False)
    code = cli.main(["fields", str(sample_docx), "--schema", str(schema_file), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "schema" in out
    assert "华东" in out  # the document text is in the prompt
    assert "dry-run" in out


def test_missing_key_fails_without_writing(sample_docx, schema_file, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PDFMEND_LLM_API_KEY", raising=False)
    code = cli.main(["fields", str(sample_docx), "--schema", str(schema_file)])
    assert code == 2
    assert not sample_docx.with_suffix(".fields.json").exists()


def test_fields_writes_json_without_the_key(sample_docx, schema_file, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
    monkeypatch.setattr(llm, "chat", lambda messages, cfg=None, **kwargs: '{"amount": 1200, "date": "2026-01-05"}')

    target = fields.run(sample_docx, schema_file, provider="deepseek")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["fields"] == {"amount": 1200, "date": "2026-01-05"}
    assert payload["provider"] == "deepseek"
    assert "sk-test-key-123" not in target.read_text(encoding="utf-8")


def test_cli_ocr_flag_is_accepted(sample_docx):
    assert cli.main(["check", str(sample_docx), "--ocr", "never"]) in (0, 2)


def test_vision_attaches_page_images_without_dumping_them(sample_pdf, schema_file, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
    seen = {}

    def fake_chat(messages, cfg=None, **kwargs):
        seen["content"] = messages[-1]["content"]
        return '{"title": "x"}'

    monkeypatch.setattr(llm, "chat", fake_chat)
    fields.run(sample_pdf, schema_file, provider="deepseek", vision=True)
    parts = seen["content"]
    assert isinstance(parts, list) and parts[0]["type"] == "text"
    images = [p for p in parts if p["type"] == "image_url"]
    assert images and images[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_page_images_on_non_pdf_is_empty(sample_docx):
    assert fields.page_images(sample_docx) == []


def test_vision_dry_run_redacts_base64(sample_pdf, schema_file, capsys, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PDFMEND_LLM_API_KEY", raising=False)
    code = cli.main([
        "fields", str(sample_pdf), "--schema", str(schema_file), "--vision", "--dry-run",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "<page image" in out
    assert len(out) < 8000  # no megabyte of base64 in the console
