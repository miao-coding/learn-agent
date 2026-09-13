"""目录锚点：slug、标题 id 注入、iframe 内 TOC"""
from frontend.app import (
    _build_toc_html,
    _extract_toc,
    _inject_heading_ids,
    _slugify_heading,
)


def test_slugify_chinese_and_english():
    assert _slugify_heading("研究现状与方法分类") == "研究现状与方法分类"
    assert _slugify_heading("Method Comparison") == "method-comparison"
    used = {}
    a = _slugify_heading("摘要", used)
    b = _slugify_heading("摘要", used)
    assert a == "摘要"
    assert b == "摘要-1"


def test_inject_heading_ids():
    html = "<h2>引言</h2><p>x</p><h2>方法</h2><h3>细节</h3>"
    out = _inject_heading_ids(html)
    assert 'id="引言"' in out
    assert 'id="方法"' in out
    assert 'id="细节"' in out
    # 不重复注入
    out2 = _inject_heading_ids(out)
    assert out2 == out


def test_build_toc_html_contains_links():
    md = "# T\n\n## 引言\n\nx\n\n### 背景\n\ny\n\n## 方法\n"
    toc, entries = _build_toc_html(md)
    assert "toc-box" in toc
    assert "data-target" in toc and "引言" in toc and "背景" in toc
    assert any(t == "引言" for _a, t in entries)
    assert len(entries) == 3  # 引言 / 背景 / 方法


def test_extract_toc_still_works():
    report = "# T\n\n## 引言\n\n## 方法\n"
    toc = _extract_toc(report)
    assert [t for _a, t in toc] == ["引言", "方法"]
