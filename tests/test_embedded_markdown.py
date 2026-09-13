"""内嵌 Markdown 报告渲染辅助"""
from frontend.app import _extract_toc


def test_extract_toc_h2():
    report = "# T\n\n## 引言\n\ntext\n\n## 方法\n\nx\n"
    toc = _extract_toc(report)
    assert [t for _, t in toc] == ["引言", "方法"]


def test_render_embedded_markdown_importable():
    from frontend import app as fe

    assert callable(fe.render_embedded_markdown)
    css = fe._report_css()
    assert "report-md" in css
    assert "table" in css
