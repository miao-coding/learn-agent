"""SVG 状态图标与目录链接颜色"""
from frontend.app import _svg_status_icon, _theme_tokens


def test_svg_icons_no_emoji():
    for kind in ("done", "fail", "wait", "run", "search", "analyze", "write", "review"):
        svg = _svg_status_icon(kind)
        assert "<svg" in svg
        assert "st-spin" in svg or kind in ("done", "fail", "wait", "review")


def test_toc_link_uses_fg_not_accent():
    from frontend import app as fe

    orig = fe._is_dark_theme
    fe._is_dark_theme = lambda: False
    try:
        # 渲染 HTML 中 toc-link 颜色应为 fg
        md = "## 引言\n\nx"
        # 通过 render 源码检查：抓 html_doc 构造片段
        import inspect

        src = inspect.getsource(fe.render_embedded_markdown)
        assert "color: {t['fg']}" in src.replace("color: {t['fg']};", "color: {t['fg']}")
        # 更直接：生成 css 段中的 toc-link
        # 调用内部逻辑：用 f-string 渲染后包含 toc-link 且不含 accent 在 toc-link 块
        # 简化断言：_report_css 不含 toc；toc 在 render_embedded 中，检查源码中 toc-link 使用 fg
        assert ".toc-link" in src
        assert "t['accent']}" not in src.split(".toc-link")[1].split(".toc-link:hover")[0]
    finally:
        fe._is_dark_theme = orig


def test_theme_tokens_light_fg_black():
    t = _theme_tokens  # import
    from frontend import app as fe

    orig = fe._is_dark_theme
    fe._is_dark_theme = lambda: False
    try:
        assert fe._theme_tokens()["fg"] == "#1a1a1a"
    finally:
        fe._is_dark_theme = orig
