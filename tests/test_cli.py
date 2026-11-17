from __future__ import annotations

import json
from pathlib import Path

from pdfmend.cli import main


def test_convert_writes_files(sample_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = main(["convert", str(sample_pdf), "-o", str(out), "-f", "md,json,html"])
    assert code == 0
    assert (out / "sample.md").exists()
    assert (out / "sample.report.json").exists()
    assert (out / "sample.report.html").exists()
    data = json.loads((out / "sample.report.json").read_text(encoding="utf-8"))
    assert 0 <= data["score"] <= 100


def test_bare_path_defaults_to_convert(sample_docx: Path, tmp_path: Path) -> None:
    code = main([str(sample_docx), "-o", str(tmp_path / "o"), "-f", "md"])
    assert code == 0
    assert (tmp_path / "o" / "sample.md").exists()


def test_strict_mode_returns_2(sample_pdf: Path, tmp_path: Path) -> None:
    code = main([
        "convert", str(sample_pdf), "-o", str(tmp_path / "s"), "-f", "json", "-q",
        "--strict", "101",
    ])
    assert code == 2


def test_bad_format_is_rejected(sample_pdf: Path, tmp_path: Path) -> None:
    assert main(["convert", str(sample_pdf), "-f", "pdf"]) == 1


def test_check_mode(sample_pdf: Path) -> None:
    assert main(["check", str(sample_pdf)]) in (0, 2)


def test_directory_input_picks_supported_files(sample_docx: Path, sample_xlsx: Path, tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.docx").write_bytes(sample_docx.read_bytes())
    (src / "b.xlsx").write_bytes(sample_xlsx.read_bytes())
    (src / "c.txt").write_text("skip me", encoding="utf-8")
    code = main(["convert", str(src), "-o", str(tmp_path / "out"), "-f", "json", "-q"])
    assert code == 0
    names = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert names == ["a.report.json", "b.report.json"]
