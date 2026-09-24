"""内嵌 Markdown 报告渲染：标题锚点、目录导航、iframe 阅读区"""
import markdown as md_lib
import streamlit as st
import streamlit.components.v1 as components

from frontend.theme import _html_escape, _report_css, _theme_tokens


def _slugify_heading(title: str, used: dict[str, int] | None = None) -> str:
    """生成稳定的标题锚点 id（支持中文）"""
    import re

    text = (title or "").strip()
    # 去掉 Markdown 强调/代码标记
    text = re.sub(r"[`*_]+", "", text)
    # 保留中英文数字与空格/连字符
    text = re.sub(r"[^\w\s\-一-鿿]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip()).strip("-").lower()
    if not text:
        text = "section"
    if used is not None:
        n = used.get(text, 0)
        used[text] = n + 1
        if n:
            text = f"{text}-{n}"
    return text


def _inject_heading_ids(body_html: str) -> str:
    """给 h1-h3 注入 id，供 iframe 内目录锚点跳转"""
    import re

    used: dict[str, int] = {}

    def _repl(m: re.Match) -> str:
        tag = m.group(1).lower()
        attrs = m.group(2) or ""
        inner = m.group(3)
        if re.search(r"\bid\s*=", attrs):
            return m.group(0)
        # 取纯文本做 slug
        plain = re.sub(r"<[^>]+>", "", inner)
        hid = _slugify_heading(plain, used)
        return f"<{tag} id=\"{hid}\"{attrs}>{inner}</{tag}>"

    return re.sub(
        r"<(h[1-3])([^>]*)>(.*?)</\1>",
        _repl,
        body_html,
        flags=re.I | re.S,
    )


def _build_toc_html(md_text: str) -> tuple[str, list[tuple[str, str]]]:
    """从 Markdown 提取目录，并生成 iframe 内可点击的 TOC HTML"""
    import re

    entries: list[tuple[str, str]] = []
    used: dict[str, int] = {}
    for line in str(md_text or "").splitlines():
        m = re.match(r"^(#{2,3})\s+(.+)$", line.strip())
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        title = re.sub(r"[`*_]+", "", title).strip()
        hid = _slugify_heading(title, used)
        entries.append((hid, title, level))

    if not entries:
        return "", []

    items = []
    for hid, title, level in entries:
        pad = "padding-left:12px;" if level == 3 else ""
        items.append(
            f"<a class='toc-link' href='#{hid}' data-target='{hid}' style='{pad}'>"
            f"{_html_escape(title)}</a>"
        )
    toc = (
        "<nav class='toc-box'><div class='toc-title'>目录导航</div>"
        + "".join(items)
        + "</nav>"
    )
    # 兼容旧接口：返回 (anchor, title) 二元组列表
    flat = [(hid, title) for hid, title, _lvl in entries]
    return toc, flat


def render_embedded_markdown(md_text: str, *, min_height: int = 520, max_height: int = 1400) -> None:
    """把 Markdown 内嵌渲染为带样式的 HTML 阅读区（含 iframe 内目录跳转）"""
    if not md_text or not str(md_text).strip():
        st.info("暂无内容")
        return

    body_html = md_lib.markdown(
        str(md_text),
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
            "nl2br",
            "smarty",
        ],
        output_format="html5",
    )
    body_html = _inject_heading_ids(body_html)
    toc_html, _entries = _build_toc_html(md_text)

    # 粗略按字符估算高度，限制在 [min, max]
    est = 480 + len(str(md_text)) // 18
    height = max(min_height, min(max_height, est))
    t = _theme_tokens()

    # 目录与正文在同一个 iframe 内，#锚点 / JS 滚动才能生效
    # （Streamlit 侧的 st.markdown 链接无法滚到 iframe 内部）
    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{_report_css()}
<style>
.toc-box {{
  position: sticky;
  top: 0;
  z-index: 5;
  background: {t['bg']};
  border: 1px solid {t['border']};
  border-radius: 8px;
  padding: 10px 12px;
  margin: 0 0 1rem 0;
  max-height: 180px;
  overflow-y: auto;
}}
.toc-title {{
  font-weight: 600;
  margin-bottom: 6px;
  color: {t['fg']};
  font-size: 0.92rem;
}}
.toc-link {{
  display: block;
  color: {t['fg']};
  text-decoration: none;
  font-size: 0.88rem;
  line-height: 1.55;
  padding: 2px 0;
}}
.toc-link:hover {{
  text-decoration: underline;
  color: {t['fg']};
}}
.report-md h1, .report-md h2, .report-md h3 {{ scroll-margin-top: 200px; }}
</style>
<script>
function jumpTo(id) {{
  var el = document.getElementById(id);
  if (el) {{
    el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    return false;
  }}
  return false;
}}
document.addEventListener('click', function (e) {{
  var a = e.target.closest('a.toc-link');
  if (!a) return;
  e.preventDefault();
  jumpTo(a.getAttribute('data-target'));
}});
</script>
</head>
<body>
{toc_html}
<article class="report-md">
{body_html}
</article>
</body></html>"""
    components.html(html_doc, height=height, scrolling=True)


def _extract_toc(report: str) -> list[tuple[str, str]]:
    """从 Markdown 报告中提取二级标题作为目录"""
    import re
    entries = []
    for line in report.splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            anchor = title.lower().replace(" ", "-")
            entries.append((anchor, title))
    return entries
