"""Merging per-chunk extractions: normalisation, evidence, conflicts, re-search."""

from __future__ import annotations

from pathlib import Path

from pdfmend import merge, profiles
from pdfmend.model import Block, Document

CONTRACT = profiles.load("contract")


def _result(chunk_id: str, page: int, fields: dict) -> dict:
    return {"chunk_id": chunk_id, "page_start": page, "page_end": page, "fields": fields}


def test_normalize_dates_and_numbers():
    assert merge.normalize("date", "2026年1月5日") == "2026-01-05"
    assert merge.normalize("date", "2026/01/05") == "2026-01-05"
    assert merge.normalize("number", "¥8,000") == 8000.0
    assert merge.normalize("number", "16.5%") == 0.165
    assert merge.normalize("string", "  北京  某某  ") == "北京 某某"


def test_evidence_must_contain_the_value():
    assert merge.evidence_supports("date", "2026-01-05", "发布日期：2026-01-05")
    assert not merge.evidence_supports("date", "2026-01-05", "发布日期：2026-01-06")
    assert merge.evidence_supports("number", "4,530.50", "合计 4530.50 元")
    assert not merge.evidence_supports("number", 100, "金额为 200 元")


def test_same_value_merges_pages_and_evidence():
    merged = merge.merge_fields(
        [
            _result("c1", 1, {"合同编号": {"value": "HT-2026-001", "evidence": "合同编号：HT-2026-001", "confidence": 0.9}}),
            _result("c2", 3, {"合同编号": {"value": "ht-2026-001".upper(), "evidence": "编号 HT-2026-001", "confidence": 0.8}}),
        ],
        CONTRACT,
    )
    assert merged["合同编号"]["status"] == "ok"
    assert merged["合同编号"]["source_pages"] == [1, 3]
    assert merged["合同编号"]["conflicts"] == []


def test_conflict_is_kept_and_supported_evidence_wins():
    merged = merge.merge_fields(
        [
            _result("c1", 1, {"合同金额": {"value": 100000, "evidence": "合同金额：100000 元", "confidence": 0.6}}),
            _result("c2", 2, {"合同金额": {"value": 90000, "evidence": "总计九万元", "confidence": 0.95}}),
        ],
        CONTRACT,
    )
    item = merged["合同金额"]
    assert item["status"] == "conflict"
    assert item["value"] == 100000  # evidence backs it, confidence alone does not
    assert item["conflicts"] and item["conflicts"][0]["value"] == 90000


def test_missing_fields_and_page_search():
    doc = Document(path=Path("r.pdf"), kind="pdf", pages=62)
    doc.blocks = [
        Block(kind="para", text="某某证券研究所出品", page=60),
        Block(kind="para", text="无关内容", page=5),
    ]
    merged = merge.merge_fields([_result("c1", 1, {"报告标题": {"value": "某报告", "evidence": "某报告", "confidence": 0.9}})], profiles.load("research_report"))
    missing = merge.missing(merged, profiles.load("research_report"))
    assert "研究机构" in missing
    pages = merge.search_pages(doc, ["研究机构"], profiles.load("research_report"))
    assert 60 in pages


def test_payload_reports_stats_and_missing():
    merged = merge.merge_fields(
        [_result("c1", 1, {"合同编号": {"value": "HT-1", "evidence": "编号：HT-1", "confidence": 0.9}})],
        CONTRACT,
    )
    data = merge.payload(merged, CONTRACT, {"chunks": 1})
    assert data["fields"]["合同编号"] == "HT-1"
    assert data["fields"]["合同金额"] is None
    assert data["stats"]["found"] == 1
    assert "合同金额" in data["stats"]["missing"]
    assert data["evidence"]["合同编号"]["source_pages"] == [1]
