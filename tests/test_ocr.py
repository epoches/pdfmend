"""OCR parsing tests: no paddle install, no images needed."""

from __future__ import annotations

from pdfmend import ocr

QUAD = [[10, 20], [60, 20], [60, 34], [10, 34]]
QUAD2 = [[10, 40], [70, 40], [70, 54], [10, 54]]


def test_parse_paddleocr_2x_nested():
    raw = [[[QUAD, ("合计", 0.99)], [QUAD2, ("4,530.50", 0.95)]]]
    lines = ocr.parse_result(raw)
    assert [line.text for line in lines] == ["合计", "4,530.50"]
    assert lines[0].conf == 0.99
    assert lines[0].top == 20 and lines[0].height == 14
    assert lines[1].left == 10


def test_parse_paddleocr_2x_flat():
    raw = [[QUAD, ("月份", 0.9)]]
    assert [line.text for line in ocr.parse_result(raw)] == ["月份"]


def test_parse_paddleocr_3x_dict():
    raw = [
        {
            "rec_texts": ["Month", "Income"],
            "rec_scores": [0.9, 0.8],
            "rec_boxes": [[0, 0, 40, 12], [0, 12, 40, 24]],
        }
    ]
    lines = ocr.parse_result(raw)
    assert [line.text for line in lines] == ["Month", "Income"]
    assert lines[1].top == 12


def test_parse_skips_blank_and_empty():
    assert ocr.parse_result(None) == []
    assert ocr.parse_result([]) == []
    assert ocr.parse_result([[QUAD, ("  ", 0.9)]]) == []


def test_paragraphs_join_cjk_without_spaces():
    lines = [
        ocr.Line("银行流水", 0.9, top=0, left=0, height=10),
        ocr.Line("对账单", 0.9, top=11, left=0, height=10),
        ocr.Line("备注：无", 0.9, top=80, left=0, height=10),
    ]
    paras = ocr.to_paragraphs(lines)
    assert [para["text"] for para in paras] == ["银行流水对账单", "备注：无"]
    assert paras[0]["top"] == 0


def test_paragraphs_join_latin_with_space_and_dehyphenate():
    lines = [
        ocr.Line("The quick brown", 0.9, top=0, left=0, height=10),
        ocr.Line("fox jumps", 0.9, top=11, left=0, height=10),
        ocr.Line("well-", 0.9, top=22, left=0, height=10),
        ocr.Line("known", 0.9, top=33, left=0, height=10),
    ]
    text = ocr.to_paragraphs(lines)[0]["text"]
    assert text == "The quick brown fox jumps wellknown"
