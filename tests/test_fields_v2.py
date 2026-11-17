"""End-to-end field extraction with profiles and evidence (no network)."""

from __future__ import annotations

import json

import pytest

from pdfmend import cli, fields, llm


@pytest.fixture
def contract_pdf(tmp_path):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in ("Technical Service Contract", "Contract No: HT-2026-001"):
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    pdf.add_page()
    pdf.cell(0, 8, "Amount: 100000 CNY")
    out = tmp_path / "contract.pdf"
    pdf.output(str(out))
    return out


def _reply(text: str) -> str:
    fields = {}
    if "HT-2026-001" in text:
        fields["合同编号"] = {
            "value": "HT-2026-001",
            "evidence": "Contract No: HT-2026-001",
            "source_page": 1,
            "confidence": 0.95,
        }
    if "100000" in text:
        fields["合同金额"] = {
            "value": 100000,
            "evidence": "Amount: 100000 CNY",
            "source_page": 2,
            "confidence": 0.9,
        }
    return json.dumps({"fields": fields}, ensure_ascii=False)


def _messages_text(messages) -> str:
    content = messages[-1]["content"]
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if part.get("type") == "text")
    return content


def test_profile_run_merges_fields_with_evidence(contract_pdf, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
    monkeypatch.setattr(llm, "chat", lambda messages, cfg=None, **kw: _reply(_messages_text(messages)))

    target = fields.run(contract_pdf, profile="contract", provider="deepseek")
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["profile"] == "contract"
    assert payload["fields"]["合同编号"] == "HT-2026-001"
    assert payload["fields"]["合同金额"] == 100000
    assert payload["evidence"]["合同编号"]["source_pages"] == [1]
    assert payload["evidence"]["合同金额"]["source_pages"] == [2]
    assert payload["stats"]["found"] == 2
    assert payload["stats"]["passes"] >= 1
    assert payload["quality"]["score"] >= 0
    assert "sk-test-key-123" not in target.read_text(encoding="utf-8")


def test_no_chunk_sends_one_request(contract_pdf, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
    calls = []

    def fake_chat(messages, cfg=None, **kw):
        calls.append(_messages_text(messages))
        return _reply(calls[-1])

    monkeypatch.setattr(llm, "chat", fake_chat)
    fields.run(contract_pdf, profile="contract", provider="deepseek", chunk=False)
    assert len(calls) == 1


def test_custom_schema_still_works(contract_pdf, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key-123")
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps({"合同编号": "编号"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm, "chat", lambda messages, cfg=None, **kw: _reply(_messages_text(messages)))
    payload = json.loads(fields.run(contract_pdf, schema, provider="deepseek").read_text(encoding="utf-8"))
    assert payload["fields"]["合同编号"] == "HT-2026-001"
    assert payload["profile"] == "custom"


def test_profile_dry_run_needs_no_key(contract_pdf, capsys, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PDFMEND_LLM_API_KEY", raising=False)
    code = cli.main(["fields", str(contract_pdf), "--profile", "contract", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "合同编号" in out
    assert "dry-run" in out


def test_unknown_profile_is_reported(contract_pdf):
    with pytest.raises(ValueError):
        fields.profile_for(None, "nope")


def test_structure_command_prints_counts(sample_docx, capsys):
    code = cli.main(["structure", str(sample_docx)])
    out = capsys.readouterr().out
    assert code == 0
    assert "heading" in out
    assert "季度报告" in out
