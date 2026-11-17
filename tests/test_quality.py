from __future__ import annotations

from pathlib import Path

from pdfmend.model import Block, Document, Table
from pdfmend.quality import score_document, score_table


def make(rows, **kw) -> Table:
    return Table(id="t1", rows=rows, **kw)


def test_clean_table_scores_high() -> None:
    t = make([
        ["月份", "收入", "成本"],
        ["1月", "1200", "800"],
        ["2月", "1350", "910"],
        ["3月", "1980", "1120"],
    ])
    score_table(t)
    assert t.confidence >= 0.8
    assert t.flags == []


def test_single_column_table_is_flagged_and_capped() -> None:
    t = make([["项目"], ["A"], ["B"], ["C"]])
    score_table(t)
    assert "collapsed_single_column" in t.flags
    assert t.confidence <= 0.30


def test_ragged_rows_are_detected() -> None:
    t = make([
        ["a", "b", "c"],
        ["1", "2", "3"],
        ["4", "5"],
        ["6", "7", "8"],
    ])
    score_table(t)
    assert "ragged_rows" in t.flags
    # normalization still happens so renderers get a rectangle
    assert all(len(r) == 3 for r in t.rows)


def test_numeric_column_with_a_footer_is_mixed() -> None:
    t = make([
        ["项目", "金额"],
        ["A", "100"],
        ["B", "200"],
        ["C", "300"],
        ["合计", "约 600 元"],
    ])
    score_table(t)
    assert "mixed_types" in t.flags


def test_repeated_neighbour_cells_suggest_merged_cells() -> None:
    t = make([
        ["h1", "h2", "h3"],
        ["相同", "相同", "x"],
        ["相同", "相同", "y"],
        ["相同", "相同", "z"],
    ])
    score_table(t)
    assert "merged_cells_suspected" in t.flags


def test_empty_cells_flag() -> None:
    t = make([
        ["a", "b", "c"],
        ["", "", "1"],
        ["", "", "2"],
    ])
    score_table(t)
    assert "empty_cells" in t.flags


def test_text_only_first_row_is_data_not_header_continuation() -> None:
    t = make([
        ["任务", "负责人", "状态"],
        ["接口联调", "李四", "完成"],
        ["压测", "王五", "延期"],
    ])
    score_table(t)
    assert t.header_rows == 1
    assert "接口联调" in t.rows[1]


def test_two_level_header_is_detected() -> None:
    t = make([
        ["科目", "本期发生额", "", "变动"],
        ["", "借方", "贷方", "比例"],
        ["营业收入", "1,284,300.00", "0.00", "16.5%"],
        ["营业成本", "612,800.00", "0.00", "4.2%"],
    ])
    score_table(t)
    assert t.header_rows == 2
    assert "mixed_types" not in t.flags


def test_damaged_chars_lower_the_score() -> None:
    good = Document(path=Path("a.pdf"), kind="pdf", text_chars=100, damaged_chars=0)
    good.blocks = [Block(kind="para", text="x" * 100)]
    bad = Document(path=Path("b.pdf"), kind="pdf", text_chars=60, damaged_chars=40)
    bad.blocks = [Block(kind="para", text="x" * 60)]
    assert score_document(good).score > score_document(bad).score


def test_verdict_thresholds() -> None:
    doc = Document(path=Path("a.xlsx"), kind="xlsx")
    doc.tables = [Table(id="t1", rows=[
        ["月份", "收入"],
        ["1月", "100"],
        ["2月", "200"],
    ])]
    r = score_document(doc)
    assert r.verdict == "可直接使用"
    assert r.score >= 85


def test_report_dict_is_json_ready() -> None:
    import json

    doc = Document(path=Path("a.xlsx"), kind="xlsx")
    doc.tables = [Table(id="t1", rows=[["a", "b"], ["1", "2"]])]
    d = score_document(doc).to_dict()
    json.dumps(d)  # must not raise
    assert d["tool"] == "pdfmend"
    assert d["tables"][0]["shape"] == "2x2"
