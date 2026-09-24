"""主区视图：头部、输入区、进度区、报告区（图表/参考文献）、审核区"""
import time
from pathlib import Path

import streamlit as st

from frontend.api_client import (
    delete_history,
    fetch_available_models,
    get_report,
    submit_research,
    submit_review,
    upload_research_docs,
)
from frontend.markdown_render import render_embedded_markdown
from frontend.theme import (
    _html_escape,
    _render_js_stopwatch,
    _status_icon_css,
    _svg_status_icon,
    _theme_tokens,
)


def render_header():
    """渲染页面头部"""
    t = _theme_tokens()
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem 0;">
        <h1 style="color:{t['fg']}">Multi-Agent 文献综述助手</h1>
        <p style="color: {t['header_sub']}; font-size: 1.1rem;">输入研究方向，自动检索文献并生成带引用的综述报告</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()


def render_input_section():
    """渲染输入区域"""
    # ── 模型选择（后端未配置可用列表时自动隐藏） ──────────────────
    models_info = fetch_available_models()
    selected_model = ""
    if models_info and models_info.get("models"):
        model_options = models_info["models"]
        default_model = models_info.get("default", "")
        default_idx = model_options.index(default_model) if default_model in model_options else 0
        selected_model = st.selectbox(
            "研究模型",
            model_options,
            index=default_idx,
            disabled=st.session_state.task_status == "running",
            label_visibility="collapsed",
        )

    col_input, col_btn = st.columns([4, 1])

    with col_input:
        topic = st.text_input(
            "研究主题",
            placeholder='例如 "大模型检索增强生成（RAG）技术综述"',
            label_visibility="collapsed",
            disabled=st.session_state.task_status == "running",
        )
    with col_btn:
        start_clicked = st.button(
            "开始研究",
            use_container_width=True,
            disabled=st.session_state.task_status == "running",
        )

    # 可选：上传自己读过的相似文献（PDF/TXT/MD）
    with st.expander("上传文件（可选）", expanded=False):
        st.caption("上传后会抽取正文与文末参考文献线索，与联网检索一并分析；不上传也可直接研究。")
        uploaded_docs = st.file_uploader(
            "选择 PDF / TXT / MD（最多 5 个，单个 ≤20MB）",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
            disabled=st.session_state.task_status == "running",
        )
        if uploaded_docs:
            st.caption(f"已选择 {len(uploaded_docs)} 个文件：")
            for u in uploaded_docs:
                st.write(f"- {u.name} ({getattr(u, 'size', 0) or 0} bytes)")

    if start_clicked and topic.strip():
        st.session_state.topic = topic.strip()
        # 重置状态
        st.session_state.thread_id = None
        st.session_state.report = ""
        st.session_state.report_draft = ""
        st.session_state.references = []
        st.session_state.charts = []
        st.session_state.progress_messages = []
        st.session_state.error_message = ""
        st.session_state.is_reviewing = False
        st.session_state.stream_consumed = False
        st.session_state.writing_chars = 0
        st.session_state.revision_count = 0
        for k in st.session_state.phases:
            st.session_state.phases[k] = False

        # 可选上传
        upload_batch_id = ""
        if uploaded_docs:
            with st.spinner("正在解析上传文献..."):
                up = upload_research_docs(uploaded_docs)
            if not up or not up.get("batch_id"):
                err = st.session_state.get("_last_upload_err") or "文献上传失败"
                st.error(err)
                return
            upload_batch_id = up["batch_id"]
            st.success(
                "文献已解析："
                + "；".join(
                    f"{f.get('filename')}（{f.get('text_chars')} 字，参考线索 {f.get('reference_count')}）"
                    for f in up.get("files") or []
                )
            )

        # 提交任务
        result = submit_research(topic.strip(), selected_model, upload_batch_id)
        if result:
            st.session_state.thread_id = result["thread_id"]
            now = time.time()
            st.session_state.task_started_at = now
            st.session_state.running_task_id = result["thread_id"]
            st.session_state.running_started_at = now
            st.session_state.running_topic = topic.strip()
            st.session_state.running_progress = []
            st.session_state.task_status = "running"
            # 种子阶段：后端初始 phase 事件可能先于前端 /progress 落盘（since 会跳过它）
            st.session_state.current_phase = "searching"
            # 写入 URL，刷新后可恢复
            try:
                st.query_params["tid"] = result["thread_id"]
                st.query_params["topic"] = topic.strip()[:80]
            except Exception:
                pass
            st.rerun()
        else:
            err = st.session_state.get("_last_submit_err") or "提交任务失败，请检查后端服务是否正常运行。"
            st.error(err)


def _phase_step_rows() -> None:
    """阶段步骤：SVG 动态图标 + 文案"""
    phases_info = [
        ("searching", "文献检索", "ArXiv / Crossref / OpenAlex 等学术源", "search"),
        ("analyzing", "文献分析", "方法分类、性能对比、研究空白", "analyze"),
        ("writing", "撰写综述", "生成带引用的综述报告", "write"),
        ("reviewing", "等待审核", "人工审核反馈", "review"),
        ("completed", "完成", "报告已生成", "done"),
    ]
    st.markdown(_status_icon_css(), unsafe_allow_html=True)
    for phase_key, label, desc, icon_kind in phases_info:
        done = st.session_state.phases.get(phase_key, False)
        is_current = st.session_state.current_phase == phase_key and not done
        if st.session_state.task_status == "error" and phase_key == "completed" and not done:
            # 失败时不点亮完成，而是在当前阶段显示失败感（由 error_message 负责）
            pass
        if done:
            icon = _svg_status_icon("done")
            title = f"<span style='text-decoration:line-through;opacity:.85'>{label}</span>"
        elif is_current:
            icon = _svg_status_icon(icon_kind)
            title = f"<strong>{label}</strong>"
        else:
            icon = _svg_status_icon("wait")
            title = f"<span style='opacity:.75'>{label}</span>"
        st.markdown(
            f"<div class='st-row' style='margin:4px 0'>{icon}<div>"
            f"{title} <span style='opacity:.65;font-size:0.9em'>· {desc}</span></div></div>",
            unsafe_allow_html=True,
        )


def _render_progress_log(max_lines: int = 24):
    """固定高度日志框：只显示最近若干条，整页高度不随消息变长"""
    messages = st.session_state.progress_messages[-max_lines:]
    if not messages:
        return
    t = _theme_tokens()
    # 单块 HTML 滚动容器，避免 Streamlit 逐条 markdown 撑开页面
    lines = "".join(
        f"<div style='margin:0 0 4px 0;line-height:1.45;color:{t['fg']}'>→ {_html_escape(m)}</div>"
        for m in messages
    )
    st.markdown(
        f"""
        <div style="max-height:220px;overflow-y:auto;border:1px solid {t['border']};
                    border-radius:8px;padding:10px 12px;font-size:0.88rem;
                    background:{t['th_bg']};color:{t['fg']}">
          <div style="font-weight:600;margin-bottom:6px;color:{t['fg']}">详细进度（最近 {len(messages)} 条）</div>
          {lines}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_section():
    """渲染进度区域"""
    st.markdown("### 任务进度")
    # 秒表：每秒自增；历史切换后用绝对 started_at 续走
    started = float(st.session_state.get("task_started_at") or 0)
    if st.session_state.task_status == "running" and started > 0:
        _render_js_stopwatch(started, dom_id="sw-main")

    if st.session_state.error_message:
        st.error(f"{st.session_state.error_message}")
        return

    _phase_step_rows()

    # 显示进度消息（固定高度滚动容器，页面不被撑长）
    _render_progress_log()

    if st.session_state.task_status == "running":
        wc = int(st.session_state.get("writing_chars") or 0)
        if st.session_state.current_phase == "writing" and wc > 0:
            st.caption(f"正在撰写综述… 已生成 {wc} 字")
        else:
            st.caption("连接正常，系统处理中")


def _render_progress_ui():
    """在流式处理过程中渲染进度 UI（兼容旧调用）"""
    st.markdown("### 任务进度")
    _phase_step_rows()
    _render_progress_log()


def _render_quality_metrics(qm: dict) -> None:
    """紧凑展示检索/分析/报告质量分（无数据则不占位）"""
    if not qm:
        return
    t = _theme_tokens()
    parts = []
    s = qm.get("search") or {}
    r = qm.get("report") or {}
    a = qm.get("analysis") or {}
    if s:
        sc = s.get("score")
        n = s.get("references_count", "-")
        parts.append(("检索", f"{sc:.0%}" if isinstance(sc, (int, float)) else "-", f"文献 {n}"))
    if a:
        ok = "通过" if a.get("ok") else "有缺项"
        parts.append(("分析", ok, f"图表 {a.get('charts', 0)}"))
    if r:
        sc = r.get("score")
        cov = r.get("citation_coverage")
        nref = r.get("references_count")
        cov_txt = f"引用覆盖 {cov:.0%}" if isinstance(cov, (int, float)) else ""
        if isinstance(cov, (int, float)) and cov < 0.2 and nref:
            cov_txt += f"（{nref} 条文献中正文几乎未引用）"
        parts.append((
            "报告",
            f"{sc:.0%}" if isinstance(sc, (int, float)) else "-",
            cov_txt,
        ))
    if not parts:
        return
    cells = []
    for name, val, sub in parts:
        cells.append(
            f"<div style='flex:1;min-width:0;padding:6px 8px;border-radius:8px;"
            f"background:{t['th_bg']};border:1px solid {t['border']}'>"
            f"<div style='font-size:0.72rem;color:{t['card_fg']}'>{name}</div>"
            f"<div style='font-size:0.95rem;font-weight:600;color:{t['fg']}'>{val}</div>"
            f"<div style='font-size:0.7rem;color:{t['card_fg']};white-space:nowrap;"
            f"overflow:hidden;text-overflow:ellipsis'>{sub}</div></div>"
        )
    st.markdown(
        f"<div style='display:flex;gap:8px;margin:0 0 10px 0'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )


def _render_charts_tab():
    """渲染图表 Tab — 仅显示当前任务 charts 列表中的文件，避免串到其它任务"""
    chart_paths = list(st.session_state.get("charts") or [])
    # 兼容历史 checkpoint：若列表为空则不回退到全局目录扫描（那是串台根因）
    visible = []
    for p in chart_paths:
        if not p:
            continue
        path = Path(p)
        # 相对路径按项目根解析；绝对路径直接用
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists():
            visible.append(path)
        else:
            st.caption(f"图表文件缺失：{p}")

    if visible:
        for path in visible:
            st.image(str(path), use_container_width=True)
            st.caption(f"图表: {path.stem}")
            st.divider()
    else:
        st.info("本次研究未生成图表数据")


def _render_references_tab():
    """渲染参考文献 Tab"""
    references = st.session_state.get("references", [])

    # 优先使用 state 中的结构化数据
    if references:
        for ref in references:
            ref_id = ref.get("id", "")
            title = ref.get("title", "未知")
            url = ref.get("url", "")
            journal = ref.get("journal", "")
            source = ref.get("source", "")
            date = ref.get("date", "")
            meta = " · ".join(filter(None, [journal, source, date]))
            if url:
                st.markdown(f"**[{ref_id}]** [{title}]({url}) — {meta}")
            else:
                st.markdown(f"**[{ref_id}]** {title} — {meta}")
    else:
        # 尝试从报告 Markdown 中解析参考文献章节
        parsed = _parse_references_from_report(st.session_state.report)
        if parsed:
            for entry in parsed:
                st.markdown(entry)
        else:
            st.info("暂无参考文献")


def _parse_references_from_report(report: str) -> list[str]:
    """尝试从报告 Markdown 中解析参考文献章节"""
    import re
    if not report:
        return []
    # 查找"参考文献"或"References"章节
    pattern = r"(?:##\s*(?:参考文献|References|Bibliography)\s*\n)(.*?)(?:\n##|\Z)"
    match = re.search(pattern, report, re.DOTALL | re.IGNORECASE)
    if not match:
        return []
    section = match.group(1).strip()
    entries = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", line):
            entries.append(line.lstrip("-* ").strip())
    return entries


def render_report_section():
    """渲染报告区域（含报告、图表、参考文献三个 Tab）"""
    report = st.session_state.report
    draft = st.session_state.report_draft

    # 运行中不展示旧报告，避免与进度区叠在一起
    if st.session_state.task_status == "running":
        return
    if not report and not draft:
        return

    st.divider()
    st.markdown("### 综述报告")
    _render_quality_metrics(st.session_state.get("quality_metrics") or {})

    # 当前报告也可手动删除（与历史列表共用同一接口）
    tid_now = st.session_state.get("thread_id") or ""
    if tid_now and st.session_state.task_status in ("completed", "reviewing"):
        col_title, col_del = st.columns([6, 1])
        with col_del:
            if st.button(
                "删除报告",
                key="del-current-report",
                icon=":material/delete_sweep:",
            ):
                if delete_history(tid_now):
                    st.session_state.thread_id = None
                    st.session_state.report = ""
                    st.session_state.report_draft = ""
                    st.session_state.references = []
                    st.session_state.charts = []
                    st.session_state.progress_messages = []
                    st.session_state.is_reviewing = False
                    st.session_state.task_status = "idle"
                    st.success("报告已删除")
                    st.rerun()
                else:
                    st.error("删除失败")

    if report:
        # 最终报告 — 使用 Tabs 组织内容
        tab_report, tab_charts, tab_refs = st.tabs(
            ["综述报告", "数据图表", "参考文献"]
        )

        with tab_report:
            # 目录在 iframe 内渲染（粘性 TOC + 平滑滚动到标题 id）
            # Streamlit 侧 #锚点 无法滚到 components.html 内部，故不在此单独放 TOC
            render_embedded_markdown(report)

            # 下载按钮
            st.divider()
            st.download_button(
                label="下载报告 (.md)",
                data=report,
                file_name=f"research_{st.session_state.topic}.md",
                mime="text/markdown",
                use_container_width=True,
            )

        with tab_charts:
            _render_charts_tab()

        with tab_refs:
            _render_references_tab()

    elif draft:
        # 审核中的草稿
        st.info("以下是报告草稿，请审核后决定是否通过：")
        render_embedded_markdown(draft)


def render_review_section():
    """渲染审核区域"""
    if not st.session_state.is_reviewing:
        return

    st.divider()
    st.markdown("### 人工审核")

    rc = int(st.session_state.get("revision_count") or 0)
    mx = int(st.session_state.get("max_revisions") or 3)
    if rc:
        st.caption(f"当前为第 {rc} 次返工后的版本（最多可返工 {mx} 次）")

    col_feedback, col_actions = st.columns([3, 1])

    with col_feedback:
        feedback = st.text_input(
            "审核意见",
            placeholder='返工需填写修改意见，如 "请补充XX数据"；点"通过"可直接通过',
            label_visibility="collapsed",
        )

    with col_actions:
        # 按钮显式携带意图（action），不再靠输入文本猜：
        # "通过"无需输入；"返工"必须有修改意见
        approve_clicked = st.button(
            "通过", use_container_width=True, type="primary"
        )
        revise_clicked = st.button(
            "返工",
            use_container_width=True,
            disabled=not feedback.strip(),
            help="按修改意见修订报告（需先填写意见）",
        )

    if approve_clicked:
        _do_review(feedback.strip(), "approve")
    elif revise_clicked and feedback.strip():
        _do_review(feedback.strip(), "revise")


def _do_review(feedback: str, action: str = ""):
    """执行审核提交（action: approve 直接通过 / revise 按意见返工）"""
    thread_id = st.session_state.thread_id
    if not thread_id:
        return

    with st.spinner("正在提交审核意见..."):
        result = submit_review(thread_id, feedback, action)

    if result is None:
        st.error("审核提交失败，请重试。")
        return

    status = result.get("status", "")
    message = result.get("message", "")

    if status == "error":
        st.error(f"审核提交失败：{message}")
        return

    if status == "approved":
        st.success(f"审核通过！{message}")
        st.session_state.is_reviewing = False
        st.session_state.task_status = "completed"
        # 获取最终报告（含 references / charts）
        report_data = get_report(thread_id)
        if report_data and report_data.get("report"):
            st.session_state.report = report_data["report"]
            st.session_state.references = report_data.get("references", [])
            st.session_state.charts = report_data.get("charts", [])
        st.rerun()
    elif status == "revising":
        st.info(f"已提交修改意见，正在返工... {message}")
        st.session_state.is_reviewing = False
        st.session_state.task_status = "running"
        st.session_state.report_draft = ""
        st.session_state.phases["reviewing"] = False
        st.session_state.phases["completed"] = False
        st.session_state.progress_messages = []
        st.session_state.current_phase = ""
        st.session_state.stream_consumed = False
        st.session_state.writing_chars = 0
        # 等待后台 SSE 队列就绪，避免前端重连时后端尚未创建队列
        time.sleep(1)
        st.rerun()
    else:
        st.warning(f"未知状态: {status} - {message}")
