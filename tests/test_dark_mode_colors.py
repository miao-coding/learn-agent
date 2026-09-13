"""深色模式颜色 token 与报告 CSS"""


def test_dark_tokens_are_light_on_dark():
    from frontend import app as fe

    orig = fe._is_dark_theme
    fe._is_dark_theme = lambda: True
    try:
        t = fe._theme_tokens()
        assert t["fg"].lower() == "#e8eaed"
        assert t["bg"].lower() == "#0e1117"
        css = fe._report_css()
        assert t["fg"] in css
        assert t["bg"] in css
        assert "color: #1a1a1a" not in css
    finally:
        fe._is_dark_theme = orig


def test_light_tokens_keep_dark_text():
    from frontend import app as fe

    orig = fe._is_dark_theme
    fe._is_dark_theme = lambda: False
    try:
        t = fe._theme_tokens()
        assert t["fg"] == "#1a1a1a"
        css = fe._report_css()
        assert "#1a1a1a" in css
    finally:
        fe._is_dark_theme = orig
