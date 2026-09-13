"""标题清洗、上传不入引用、错配启发"""
from backend.utils.citations import (
    _clean_reference_title,
    build_references_from_search_results,
)
from backend.utils.quality import quality_score_report


def test_clean_review_for_prefix():
    assert _clean_reference_title("Review for \"SPMNet: A Siamese Pyramid Mamba\"") == ""
    assert "ChangeMamba" in _clean_reference_title("ChangeMamba: Remote Sensing Change Detection")


def test_uploaded_not_in_references():
    results = [
        {"source": "uploaded", "query": "upload:x", "content": "Some uploaded paper body " * 20},
        {"source": "uploaded_refs", "query": "upload:references", "content": "[1] ChangeMamba: Visual State Space Model for Remote Sensing Change Detection\n"},
        {"source": "crossref", "query": "q", "content": "[1] A Real Crossref Paper Title About Mamba\n    URL: https://doi.org/10.1/x\n"},
    ]
    refs = build_references_from_search_results(results)
    assert all(r["source"] not in ("uploaded", "uploaded_refs") for r in refs)
    assert any("Crossref" in r["title"] or "Mamba" in r["title"] for r in refs)


def test_mismatch_heuristic_flags():
    refs = [
        {"id": 1, "title": "Quantum Chromodynamics Lattice Gauge Theory", "url": "https://a", "source": "crossref", "date": "2020"},
        {"id": 2, "title": "Mamba Remote Sensing Change Detection", "url": "https://b", "source": "arxiv", "date": "2024"},
    ]
    report = (
        "# T\n\n## 摘要\n\n"
        + ("Mamba remote sensing change detection methods " * 40)
        + "\n\n我们讨论 [1] 与 [2]。\n\n## 参考文献\n\n[1] qcd\n[2] mamba\n"
    )
    q = quality_score_report(report, refs, min_chars=50)
    # [1] 标题词在正文未出现 → 应标记
    assert any("不匹配" in i for i in q["issues"])
    assert q["citation_coverage"] == 1.0
