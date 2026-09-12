"""引用真实性：只保留真实文献，删除编造编号，重写参考文献章节"""
from backend.utils.citations import (
    format_references_section,
    parse_body_citations,
    reconcile_references,
    replace_references_section,
    strip_invalid_citations,
)


def test_strip_out_of_range_citations():
    report = "# T\n\n甲方法 [1] 与虚构 [5] 以及 [2]\n\n## 参考文献\n\n[99] fake\n"
    cleaned, removed = strip_invalid_citations(report, {1, 2})
    assert removed == 1
    assert "[5]" not in cleaned.split("## 参考文献")[0]
    assert "[1]" in cleaned and "[2]" in cleaned


def test_reconcile_no_placeholder_and_rewrites_refs():
    report = (
        "# 综述\n\n方法 A [1] 方法 B [7] 方法 C [2]\n\n"
        "## 参考文献\n\n[1] 真\n[7] 编造论文\n"
    )
    refs = [
        {"id": 1, "title": "Real Paper A", "url": "https://a.example", "source": "arxiv", "date": "2024-01-01"},
        {"id": 2, "title": "Real Paper B", "url": "https://b.example", "source": "scholar", "date": "2023"},
        {"id": 3, "title": "未命名来源（正文引用但检索列表缺失）", "url": "", "source": "unknown", "date": ""},
    ]
    cleaned, real_refs, issues = reconcile_references(report, refs)

    # 无占位
    assert all("未命名" not in str(r.get("title")) for r in real_refs)
    assert all(r.get("source") != "unknown" for r in real_refs)
    # 正文删除 [7]
    body = cleaned.split("## 参考文献")[0]
    assert "[7]" not in body
    assert "[1]" in body and "[2]" in body
    # 参考文献章节只有真实条目
    assert "编造论文" not in cleaned
    assert "Real Paper A" in cleaned
    assert any("删除" in i or "重写" in i for i in issues)


def test_format_references_section():
    refs = [{"id": 1, "title": "T", "url": "https://x", "source": "arxiv", "date": "2020"}]
    sec = format_references_section(refs)
    assert sec.startswith("## 参考文献")
    assert "https://x" in sec


def test_replace_appends_when_missing_section():
    report = "# Only\n\nText [1]\n"
    refs = [{"id": 1, "title": "OnlyRef", "url": "", "source": "wiki", "date": ""}]
    out = replace_references_section(report, refs)
    assert "## 参考文献" in out
    assert "OnlyRef" in out


def test_parse_body_stops_before_references():
    report = "# T\n\n[1] [2]\n\n## 参考文献\n\n[9]\n"
    assert parse_body_citations(report) == [1, 2]
