"""引用覆盖必须用 int 求交"""
from backend.utils.quality import quality_score_report


def test_coverage_int_intersection():
    refs = [
        {"id": 1, "title": "A" * 20, "url": "https://a", "source": "crossref", "date": "2020"},
        {"id": 2, "title": "B" * 20, "url": "https://b", "source": "arxiv", "date": "2021"},
        {"id": 3, "title": "C" * 20, "url": "https://c", "source": "scholar", "date": "2022"},
    ]
    report = (
        "# T\n\n## 摘要\n\n" + ("内容 " * 80)
        + "\n\n方法 [1][2][3] 引用。\n\n## 参考文献\n\n[1] a\n[2] b\n[3] c\n"
    )
    q = quality_score_report(report, refs, min_chars=50)
    assert q["citation_coverage"] == 1.0
    assert not any("列表外" in i for i in q["issues"])


def test_coverage_zero_when_no_body_cites():
    refs = [{"id": 1, "title": "A" * 20, "url": "https://a", "source": "crossref", "date": "2020"}]
    report = "# T\n\n" + ("无引用正文 " * 80) + "\n\n## 参考文献\n\n[1] a\n"
    q = quality_score_report(report, refs, min_chars=50)
    assert q["citation_coverage"] == 0.0
