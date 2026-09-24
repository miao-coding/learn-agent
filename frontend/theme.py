"""主题与视觉基础：颜色 token、报告 CSS、SVG 状态图标、秒表、转义

深浅主题随 Streamlit Settings → Appearance 切换；SVG 图标用 SMIL 内联动画，
不依赖外部 CSS。
"""
import streamlit as st
import streamlit.components.v1 as components


def _is_dark_theme() -> bool:
    """跟随 Streamlit 主题（Settings → Appearance）"""
    try:
        base = st.get_option("theme.base")
        if base:
            return str(base).lower() == "dark"
    except Exception:
        pass
    try:
        bg = str(st.get_option("theme.backgroundColor") or "")
        # 粗略判断：背景偏深则按暗色处理
        if bg.startswith("#"):
            h = bg.lstrip("#")[:6]
            if len(h) == 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return (r * 299 + g * 587 + b * 114) / 1000 < 100
    except Exception:
        pass
    return False


def _theme_tokens() -> dict[str, str]:
    """返回当前主题下的 UI 颜色 token，避免深色模式字色/底色撞车"""
    if _is_dark_theme():
        return {
            "bg": "#0e1117",
            "fg": "#e8eaed",
            "muted": "#9aa0a6",
            "border": "#3c4043",
            "accent": "#8ab4f8",
            "h3": "#c4c7c5",
            "th_bg": "#1f2428",
            "tr_bg": "#161a1d",
            "code_bg": "#1f2428",
            "code_fg": "#e8eaed",
            "pre_bg": "#000000",
            "pre_fg": "#d7dadd",
            "quote_bg": "#1a1f24",
            "quote_fg": "#bdc1c6",
            "ok_bg": "#143d24",
            "bad_bg": "#4a1c1c",
            "info_bg": "#1a2744",
            "card_fg": "#c4c7c5",
            "header_sub": "#9aa0a6",
        }
    return {
        "bg": "#ffffff",
        "fg": "#1a1a1a",
        "muted": "#5f6368",
        "border": "#e2e8f0",
        "accent": "#2b6cb0",
        "h3": "#2d3748",
        "th_bg": "#edf2f7",
        "tr_bg": "#fafafa",
        "code_bg": "#f1f5f9",
        "code_fg": "#1a1a1a",
        "pre_bg": "#0f172a",
        "pre_fg": "#e2e8f0",
        "quote_bg": "#f7fafc",
        "quote_fg": "#4a5568",
        "ok_bg": "#e6f4ea",
        "bad_bg": "#fce8e6",
        "info_bg": "#e8f0fe",
        "card_fg": "#555555",
        "header_sub": "#666666",
    }


def _report_css(t: dict[str, str] | None = None) -> str:
    """内嵌 Markdown 报告样式（随主题切换，深色模式可读）"""
    t = t or _theme_tokens()
    return f"""
<style>
html, body {{
  background: {t['bg']};
  color: {t['fg']};
  margin: 0;
  padding: 0;
}}
.report-md {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 15px;
  line-height: 1.75;
  color: {t['fg']};
  background: {t['bg']};
  max-width: 920px;
  margin: 0 auto;
  padding: 8px 4px 32px;
}}
.report-md h1 {{
  font-size: 1.65rem;
  font-weight: 700;
  border-bottom: 2px solid {t['border']};
  padding-bottom: 0.4rem;
  margin: 1.2rem 0 1rem;
  color: {t['fg']};
}}
.report-md h2 {{
  font-size: 1.3rem;
  font-weight: 650;
  margin: 1.6rem 0 0.7rem;
  padding-left: 0.55rem;
  border-left: 4px solid {t['accent']};
  color: {t['fg']};
}}
.report-md h3 {{
  font-size: 1.1rem;
  font-weight: 600;
  margin: 1.2rem 0 0.5rem;
  color: {t['h3']};
}}
.report-md h4, .report-md h5 {{
  font-size: 1rem;
  font-weight: 600;
  margin: 1rem 0 0.4rem;
  color: {t['fg']};
}}
.report-md p {{ margin: 0.55rem 0; color: {t['fg']}; }}
.report-md ul, .report-md ol {{ padding-left: 1.4rem; margin: 0.5rem 0; }}
.report-md li {{ margin: 0.25rem 0; color: {t['fg']}; }}
.report-md blockquote {{
  margin: 0.8rem 0;
  padding: 0.6rem 1rem;
  border-left: 4px solid {t['border']};
  background: {t['quote_bg']};
  color: {t['quote_fg']};
  border-radius: 0 6px 6px 0;
}}
.report-md table {{
  border-collapse: collapse;
  width: 100%;
  margin: 1rem 0;
  font-size: 0.92rem;
  display: block;
  overflow-x: auto;
  color: {t['fg']};
}}
.report-md th, .report-md td {{
  border: 1px solid {t['border']};
  padding: 0.5rem 0.75rem;
  text-align: left;
  vertical-align: top;
  color: {t['fg']};
}}
.report-md th {{
  background: {t['bg']};
  font-weight: 600;
  white-space: nowrap;
}}
.report-md tr:nth-child(even) td {{ background: {t['tr_bg']}; }}
.report-md code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.88em;
  background: {t['code_bg']};
  color: {t['code_fg']};
  padding: 0.12em 0.35em;
  border-radius: 4px;
}}
.report-md pre {{
  background: {t['pre_bg']};
  color: {t['pre_fg']};
  padding: 0.9rem 1rem;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.8rem 0;
}}
.report-md pre code {{ background: transparent; color: inherit; padding: 0; }}
.report-md a {{ color: {t['accent']}; text-decoration: none; }}
.report-md a:hover {{ text-decoration: underline; }}
.report-md hr {{
  border: none;
  border-top: 1px solid {t['border']};
  margin: 1.5rem 0;
}}
.report-md img {{ max-width: 100%; border-radius: 6px; }}
.report-md em:empty {{ display: none; }}
</style>
"""


def _fmt_elapsed(sec: int) -> str:
    sec = max(0, int(sec or 0))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _render_js_stopwatch(started_at: float, dom_id: str = "sw") -> None:
    """前端 JS 秒表：每秒自增，不依赖 SSE 心跳；切换历史再回来也会按绝对时间续走"""
    if not started_at or float(started_at) <= 0:
        return
    safe = "".join(c if c.isalnum() else "_" for c in dom_id)[:40] or "sw"
    t = _theme_tokens()
    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
         background:transparent; color:{t['fg']}; }}
  .sw {{ font-variant-numeric: tabular-nums; font-weight:600; font-size:0.95rem; }}
  .lbl {{ opacity:0.7; font-size:0.8rem; font-weight:400; }}
</style></head>
<body>
<div><span class="lbl">已运行</span> <span class="sw" id="{safe}">0:00</span></div>
<script>
(function () {{
  var start = {float(started_at)};
  var el = document.getElementById('{safe}');
  function fmt(sec) {{
    sec = Math.max(0, Math.floor(sec));
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var mm = (m < 10 && h > 0 ? '0' : '') + m;
    var ss = (s < 10 ? '0' : '') + s;
    return h > 0 ? (h + ':' + mm + ':' + ss) : (m + ':' + ss);
  }}
  function tick() {{
    if (el) el.textContent = fmt(Date.now() / 1000 - start);
  }}
  tick();
  setInterval(tick, 1000);
}})();
</script>
</body></html>
"""
    components.html(html, height=28, scrolling=False)


def _svg_status_icon(kind: str, *, size: int = 18) -> str:
    """SVG 状态图标（SMIL 内联动画，不依赖外部 CSS）

    done/fail：弹入缩放；run/search/analyze/write：进度环旋转；
    review：呼吸缩放；wait：静态空心。
    """
    s = size
    common = (
        f'width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" '
        f'style="vertical-align:-3px;flex-shrink:0" aria-hidden="true"'
    )
    # 绕圆心旋转（SMIL，Streamlit HTML 更可靠）
    spin = (
        '<animateTransform attributeName="transform" type="rotate" '
        'from="0 12 12" to="360 12 12" dur="0.9s" repeatCount="indefinite"/>'
    )
    # 弹入
    pop = (
        '<animateTransform attributeName="transform" type="scale" '
        'values="0.7;1.05;1" keyTimes="0;0.6;1" dur="0.45s" fill="freeze" '
        'additive="sum"/>'
    )
    # 呼吸
    pulse = (
        '<animate attributeName="opacity" values="0.55;1;0.55" dur="1.4s" '
        'repeatCount="indefinite"/>'
    )

    if kind == "done":
        return (
            f"<svg {common}>"
            f'<circle cx="12" cy="12" r="10" fill="#22c55e">'
            f'<animate attributeName="r" values="8;10.5;10" dur="0.4s" fill="freeze"/>'
            f"</circle>"
            f'<path d="M7.5 12.5l3 3 6-7" stroke="#fff" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round">'
            f'<animate attributeName="stroke-dasharray" values="0 20;20 0" dur="0.45s" fill="freeze"/>'
            f"</path>"
            f"</svg>"
        )
    if kind == "fail":
        return (
            f"<svg {common}>"
            f'<circle cx="12" cy="12" r="10" fill="#ef4444">{pulse}</circle>'
            f'<path d="M8 8l8 8M16 8l-8 8" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>'
            f"</svg>"
        )
    if kind == "wait":
        return (
            f"<svg {common}>"
            f'<circle cx="12" cy="12" r="9" stroke="#94a3b8" stroke-width="2"/>'
            f"</svg>"
        )
    if kind in ("run", "search", "analyze", "write"):
        inner = {
            "search": (
                '<circle cx="10.5" cy="10.5" r="3.2" stroke="#3b82f6" stroke-width="1.8"/>'
                '<path d="M13 13l4 4" stroke="#3b82f6" stroke-width="1.8" stroke-linecap="round"/>'
            ),
            "analyze": (
                '<path d="M8 15V10M12 15V7M16 15v-3" stroke="#3b82f6" stroke-width="2" stroke-linecap="round">'
                '<animate attributeName="opacity" values="0.4;1;0.4" dur="1s" repeatCount="indefinite"/>'
                "</path>"
            ),
            "write": (
                '<path d="M8 16l2.5-.5L18 8l-2-2-7.5 7.5L8 16z" stroke="#3b82f6" '
                'stroke-width="1.6" stroke-linejoin="round"/>'
            ),
            "run": '<circle cx="12" cy="12" r="3.5" fill="#3b82f6"/>',
        }.get(kind, '<circle cx="12" cy="12" r="3" fill="#3b82f6"/>')
        return (
            f"<svg {common}>"
            f'<g>{spin}'
            f'<circle cx="12" cy="12" r="9" stroke="#3b82f6" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-dasharray="36 24" opacity="0.95"/>'
            f"</g>"
            f"{inner}"
            f"</svg>"
        )
    if kind == "review":
        return (
            f"<svg {common}>"
            f'<circle cx="12" cy="12" r="9" stroke="#f59e0b" stroke-width="2">{pulse}</circle>'
            f'<circle cx="12" cy="12" r="3.2" fill="#f59e0b">{pulse}</circle>'
            f"</svg>"
        )
    return (
        f"<svg {common}>"
        f'<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" opacity="0.45"/>'
        f"</svg>"
    )


def _status_icon_css() -> str:
    # 仅布局；动画已内置到 SVG SMIL
    return """
<style>
.st-row { display:flex; align-items:center; gap:8px; }
</style>
"""


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
