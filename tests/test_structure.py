"""Structure recognition and the six-dimension quality score."""

from __future__ import annotations

from pdfmend import structure
from pdfmend.model import Block, Document
from pdfmend.quality import score_document


def test_bullet_variants_are_recognised():
    assert structure.bullet_item("• 负责后端开发") == "负责后端开发"
    assert structure.bullet_item("•负责后端开发") == "负责后端开发"  # no space
    assert structure.bullet_item("- 负责数据库") == "负责数据库"
    assert structure.bullet_item("并没有 • 在中间") is None
    assert structure.bullet_item("•") is None  # decoration only


def test_numbered_and_chinese_ordinals():
    assert structure.numbered_item("1. 项目背景") == ("1.", "项目背景")
    assert structure.numbered_item("（2）数据库设计") == ("2.", "数据库设计")
    assert structure.numbered_item("三、人员安排") == ("三、", "人员安排")


def test_clause_numbers():
    assert structure.clause("1.2 乙方向甲方提供软件开发服务。") == (
        "1.2",
        "乙方向甲方提供软件开发服务。",
    )
    assert structure.clause("第一条 服务内容") is None  # that is a heading


def test_heading_level_uses_size_then_markers():
    assert structure.heading_level("工作经历", size=18, body_size=10) == 1
    assert structure.heading_level("工作经历", size=12, body_size=10) == 2
    assert structure.heading_level("第一条 服务内容", size=10, body_size=10) == 2
    assert structure.heading_level("一、总则", size=10, body_size=10) == 2
    assert structure.heading_level("负责后端系统设计与开发", size=10, body_size=10) == 0
    # label/data lines are not headings even when the font is slightly bigger
    assert structure.heading_level("年龄：23岁电话：15305682345", size=12, body_size=10) == 0
    assert structure.heading_level("邮箱：a@b.com", size=12, body_size=10) == 0


def test_inline_bullets_are_split_into_a_list():
    head, items = structure.split_inline_bullets("技能 • Python • PHP • MySQL")
    assert head == "技能"
    assert items == ["Python", "PHP", "MySQL"]


def test_classify_groups_consecutive_bullets():
    paras = [
        {"text": "工作经历", "size": 12, "top": 10, "x0": 40},
        {"text": "• 负责后端开发", "size": 10, "top": 30, "x0": 50},
        {"text": "• 优化数据库", "size": 10, "top": 45, "x0": 50},
        {"text": "1.1 乙方提供软件开发服务。", "size": 10, "top": 70, "x0": 40},
    ]
    blocks = structure.classify(paras, body_size=10, page=1)
    kinds = [b.kind for b in blocks]
    assert kinds == ["heading", "bullet_list", "clause"]
    assert blocks[1].items == ["负责后端开发", "优化数据库"]
    assert blocks[2].number == "1.1"


def test_tree_nests_blocks_under_headings():
    blocks = [
        Block(kind="heading", text="工作经历", level=1),
        Block(kind="para", text="某科技公司"),
        Block(kind="heading", text="项目经历", level=1),
    ]
    tree = structure.tree(blocks)
    assert [s["title"] for s in tree["sections"]] == ["工作经历", "项目经历"]
    assert tree["sections"][0]["children"][0]["text"] == "某科技公司"


def test_counts_reports_lists_and_items():
    blocks = [
        Block(kind="heading", text="x"),
        Block(kind="bullet_list", items=["a", "b"]),
        Block(kind="para", text="y"),
    ]
    counts = structure.counts(blocks)
    assert counts["heading"] == 1
    assert counts["bullet_list"] == 1
    assert counts["bullet_items"] == 2


def test_quality_has_six_dimensions(sample_docx):
    from pdfmend.extract import extract

    report = score_document(extract(sample_docx))
    dims = report.dimensions
    assert {"text", "table", "structure", "ocr"}.issubset(dims)
    assert dims["structure"]["weight"] == 20
    assert sum(v["weight"] for k, v in dims.items() if k != "total") == 100
    assert 0 <= report.score <= 100


def test_long_paragraph_loses_structure_points():
    doc = Document(path=None, kind="pdf", pages=1)
    doc.blocks = [Block(kind="para", text="很长的正文" * 200)]
    doc.text_chars = len(doc.blocks[0].text)
    report = score_document(doc)
    assert report.dimensions["structure"]["score"] < 1.0


def test_inline_subitems_become_clause_items():
    blocks = structure.classify(
        [{"text": "1.2 乙方向甲方提供以下服务：（1）系统架构设计（2）数据库设计"}],
        body_size=10,
        page=1,
    )
    assert len(blocks) == 1
    clause = blocks[0]
    assert clause.kind == "clause"
    assert clause.text == "乙方向甲方提供以下服务："
    assert clause.items == ["（1）系统架构设计", "（2）数据库设计"]


def test_standalone_subitem_lines_attach_to_the_previous_clause():
    paras = [
        {"text": "1.2 乙方负责以下服务：", "size": 10, "top": 10, "x0": 40},
        {"text": "（1）系统架构设计", "size": 10, "top": 25, "x0": 55},
        {"text": "（2）数据库设计", "size": 10, "top": 40, "x0": 55},
        {"text": "1.3 甲方应在验收后付款。", "size": 10, "top": 60, "x0": 40},
    ]
    blocks = structure.classify(paras, body_size=10, page=1)
    assert [b.kind for b in blocks] == ["clause", "clause"]
    assert blocks[0].items == ["（1）系统架构设计", "（2）数据库设计"]
    assert blocks[1].items == []


def test_subitems_without_a_parent_stay_a_list():
    blocks = structure.classify(
        [{"text": "（1）准备材料", "size": 10}, {"text": "（2）提交申请", "size": 10}],
        body_size=10,
        page=1,
    )
    assert [b.kind for b in blocks] == ["numbered_list"]


def test_single_parenthesis_reference_is_not_a_list():
    head, items = structure.split_subitems("1.4 详见附件（1）的说明。")
    assert items == []
    assert head == "1.4 详见附件（1）的说明。"


def test_markdown_renders_clause_subitems_as_nested_list():
    from pathlib import Path

    from pdfmend.model import Report
    from pdfmend.render import to_markdown

    doc = Document(path=Path("contract.pdf"), kind="pdf", pages=1)
    doc.blocks = [
        Block(kind="clause", number="1.2", text="乙方负责：", items=["（1）系统架构设计", "（2）数据库设计"]),
    ]
    report = Report(document=doc, score=90, verdict="可直接使用", reasons=[], tables=[])
    md = to_markdown(report)
    assert "- 1.2 乙方负责：" in md
    assert "  - （1）系统架构设计" in md
