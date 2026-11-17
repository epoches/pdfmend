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
