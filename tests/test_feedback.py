"""Human corrections: record a fix, list it, count the recurring confusions."""

from __future__ import annotations

import json

import pytest

from pdfmend import feedback, structure
from pdfmend.model import Block


def _tree() -> dict:
    blocks = [
        Block(kind="heading", text="技术服务合同", level=1, page=1, id="b1"),
        Block(kind="para", text="1.2 乙方向甲方提供以下服务：", page=2, id="b2"),
        Block(kind="para", text="没识别成列表的一行", page=2, id="b3"),
    ]
    return structure.tree(blocks)


def test_record_captures_geometry_and_text(tmp_path):
    item = feedback.record(_tree(), "b3", "bullet_list", document="合同.pdf", document_type="contract")
    assert item["original_type"] == "para"
    assert item["corrected_type"] == "bullet_list"
    assert item["page"] == 2
    assert item["original_text"] == "没识别成列表的一行"
    assert item["v"] == 1


def test_append_is_one_json_per_line(tmp_path):
    path = tmp_path / "nested" / "corrections.jsonl"
    feedback.append(feedback.record(_tree(), "b2", "clause"), path)
    feedback.append(feedback.record(_tree(), "b3", "bullet_list"), path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["corrected_type"] == "clause"
    assert len(feedback.load(path)) == 2


def test_unknown_block_or_kind_is_refused():
    with pytest.raises(feedback.FeedbackError):
        feedback.record(_tree(), "b99", "clause")
    with pytest.raises(feedback.FeedbackError):
        feedback.record(_tree(), "b3", "footnote")
    with pytest.raises(feedback.FeedbackError):
        feedback.record(_tree(), "b3", "para")  # already a paragraph


def test_stats_groups_by_transition_and_document_type():
    data = feedback.stats(
        [
            {"original_type": "para", "corrected_type": "bullet_list", "document_type": "resume"},
            {"original_type": "para", "corrected_type": "bullet_list", "document_type": "resume"},
            {"original_type": "para", "corrected_type": "clause", "document_type": "contract"},
        ]
    )
    assert data["total"] == 3
    assert data["transitions"]["para -> bullet_list"] == 2
    assert data["by_document_type"]["resume"] == 2


def test_cli_add_list_and_stats(tmp_path, capsys):
    from pdfmend.cli import main

    structure_file = tmp_path / "doc.json"
    structure_file.write_text(json.dumps(_tree(), ensure_ascii=False), encoding="utf-8")
    store = tmp_path / "corrections.jsonl"
    assert main(["feedback", "add", "--structure", str(structure_file), "--block", "b3",
                 "--to", "bullet_list", "--note", "其实是列表", "--file", str(store)]) == 0
    assert main(["feedback", "stats", "--file", str(store)]) == 0
    out = capsys.readouterr().out
    assert "para -> bullet_list" in out
    assert main(["feedback", "list", "--file", str(store)]) == 0
    assert "b3" in capsys.readouterr().out
