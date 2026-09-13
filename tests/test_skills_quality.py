"""Skill 校验与质量门禁"""
from backend.skills import (
    get_skill,
    pick_report_template,
    validate_analysis_payload,
    validate_report_structure,
)
from backend.utils.quality import (
    quality_score_report,
    quality_score_search,
    should_fail_search,
    should_retry_report,
)


def test_skill_registry():
    assert get_skill("lit_search").policy.min_real_references == 6
    assert get_skill("report").policy.min_report_chars == 800


def test_validate_analysis_missing_fields():
    issues = validate_analysis_payload({"field_overview": {}})
    assert any("method_categories" in i for i in issues)
    assert validate_analysis_payload({"error": "boom"})


def test_validate_report_structure():
    bad = validate_report_structure("short")
    assert bad
    good = (
        "# 标题\n\n## 摘要\n\n足够长度的内容" * 40
        + "\n\n## 引言\n\n## 研究现状与方法\n\n## 方法对比\n"
        + "\n## 挑战\n\n## 总结与展望\n\n"
        + "内容 [1] [2] [3]\n\n## 参考文献\n\n[1] a\n[2] b\n[3] c\n"
    )
    issues = validate_report_structure(good, min_chars=200)
    assert issues == []


def test_quality_search_gate():
    refs = [
        {"id": i, "title": f"t{i}", "url": "u", "source": "crossref", "date": "2020"}
        for i in range(1, 9)
    ]
    results = [{"content": "x", "source": "scholar", "query": "q"}] * 3
    q = quality_score_search(results, refs)
    assert q["score"] > 0.5
    assert not should_fail_search(q)
    q2 = quality_score_search([], refs[:1])
    assert should_fail_search(q2)


def test_quality_report_retry():
    refs = [{"id": 1, "title": "a" * 20, "url": "https://x", "source": "arxiv", "date": "2024"}]
    q = quality_score_report("# only title", refs)
    assert should_retry_report(q)


def test_pick_report_template():
    tid, focus = pick_report_template("MAMBA遥感变化检测")
    assert tid in ("change_detection", "ssm_mamba", "remote_sensing")
    assert focus
    tid2, _ = pick_report_template("完全无关的主题xyz")
    assert tid2 == "general"
