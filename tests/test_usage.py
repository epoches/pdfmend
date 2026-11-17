"""Conversion history and the once-per-five reminder for unregistered copies."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pdfmend import licensing, runtime, usage


@dataclass
class FakeResult:
    source: Path = Path("demo.pdf")
    ok: bool = True
    score: int = 97
    verdict: str = "可直接使用"
    seconds: float = 1.25
    outputs: dict = field(default_factory=lambda: {"md": Path("demo.md")})
    error: str | None = None


def test_log_writes_one_json_line_per_conversion(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    usage.log_conversion(FakeResult())
    usage.log_conversion(FakeResult(source=Path("b.pdf"), score=0, ok=False, error="boom"))

    path = runtime.conversions_file()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2
    assert lines[0]["source"].endswith("demo.pdf")
    assert lines[0]["score"] == 97
    assert lines[0]["outputs"] == ["md"]
    assert lines[1]["ok"] is False and lines[1]["error"] == "boom"
    assert len(usage.history()) == 2


def test_reminder_fires_every_five_and_only_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    monkeypatch.setenv("PDFMEND_MACHINE_ID", "A1B2C3D4E5F6")

    for _ in range(4):
        usage.record_success()
    assert not usage.should_prompt()

    usage.record_success()
    assert usage.count() == 5
    assert usage.should_prompt()

    usage.mark_prompted()
    assert not usage.should_prompt(), "the same milestone must not nag twice"

    for _ in range(5):
        usage.record_success()
    assert usage.count() == 10
    assert usage.should_prompt()


def test_registered_users_never_see_the_reminder(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    monkeypatch.setenv("PDFMEND_MACHINE_ID", "A1B2C3D4E5F6")
    code = licensing.make_code("alice", "2026-11-17", "A1B2C3D4E5F6")
    assert licensing.register("alice", code, allow_server=False)[0]

    for _ in range(10):
        usage.record_success()
    assert not usage.should_prompt()
    assert not usage.should_prompt(registered=True)


def test_reset_clears_counter_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFMEND_TMP", str(tmp_path / "state"))
    usage.record_success()
    usage.log_conversion(FakeResult())
    usage.reset()
    assert usage.count() == 0
    assert usage.history() == []
