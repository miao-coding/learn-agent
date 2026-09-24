"""侧边栏：系统说明、依赖状态、进行中/历史任务、在线配置（管理员口令保护）"""
import streamlit as st

from frontend.api_client import (
    API_BASE_URL,
    admin_list_models,
    admin_test_model,
    check_health,
    delete_history,
    fetch_dependencies,
    fetch_history,
    fetch_running_tasks,
    get_admin_status,
    update_admin_config,
)
from frontend.session import _restore_task
from frontend.theme import (
    _html_escape,
    _render_js_stopwatch,
    _status_icon_css,
    _svg_status_icon,
    _theme_tokens,
)


def _render_admin_settings(admin_status: dict) -> None:
    """系统设置：适配侧边栏窄宽度的纵向状态 + 单列表单"""
    llm_ok = bool(admin_status.get("openai_key_set"))
    tavily_ok = bool(admin_status.get("tavily_key_set"))
    model_name = (admin_status.get("model_name") or "-").strip()
    base_url = (admin_status.get("openai_base_url") or "").strip()
    t = _theme_tokens()

    # 侧边栏约 280–320px：避免三列卡片挤压，改用单列状态条
    def _row(ok: bool | None, label: str, value: str, *, warn: bool = False) -> str:
        if ok is True:
            icon = _svg_status_icon("done", size=16)
            color = t["fg"]
        elif ok is False:
            icon = _svg_status_icon("fail", size=16)
            color = t["fg"]
        else:
            icon = _svg_status_icon("wait", size=16)
            color = t["card_fg"]
        bg = t["th_bg"]
        if ok is True:
            bg = t["ok_bg"]
        elif ok is False:
            bg = t["bad_bg"]
        return (
            f"<div style='display:flex;align-items:center;gap:8px;padding:6px 8px;"
            f"margin:0 0 6px 0;border-radius:8px;border:1px solid {t['border']};"
            f"background:{bg};min-height:36px;box-sizing:border-box'>"
            f"{icon}"
            f"<div style='min-width:0;flex:1'>"
            f"<div style='font-size:0.8rem;color:{t['card_fg']};line-height:1.2'>{label}</div>"
            f"<div style='font-size:0.82rem;color:{color};font-weight:600;"
            f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis' title=\"{_html_escape(value)}\">"
            f"{_html_escape(value)}</div>"
            f"</div></div>"
        )

    st.markdown("##### 当前状态")
    st.markdown(
        _row(llm_ok, "LLM Key", "已配置" if llm_ok else "未配置")
        + _row(tavily_ok, "Tavily", "已配置" if tavily_ok else "未配置或占位")
        + _row(None, "默认模型", model_name[:28] if model_name else "-"),
        unsafe_allow_html=True,
    )
    if base_url:
        st.caption(f"接口：`{base_url[:42]}`" + ("…" if len(base_url) > 42 else ""))

    st.markdown("##### 修改配置")
    st.caption("留空表示不修改；保存后即时生效。")

    with st.form("admin_config_form", clear_on_submit=False):
        admin_pwd = st.text_input(
            "管理员口令",
            type="password",
            placeholder="ADMIN_PASSWORD",
            help="所有操作均需校验口令",
        )

        st.markdown("**模型接口**")
        new_base_url = st.text_input(
            "BASE_URL",
            placeholder="https://open.bigmodel.cn/api/coding/paas/v4",
            help="OpenAI 兼容接口地址",
        )
        new_model = st.text_input(
            "默认模型",
            placeholder="glm-5.3-flash",
            help="接口内的模型名",
        )
        new_openai_key = st.text_input(
            "API Key",
            type="password",
            placeholder="sk-... / 智谱 Key",
        )

        st.markdown("**检索服务**")
        new_tavily_key = st.text_input(
            "Tavily Key",
            type="password",
            placeholder="tvly-...",
            help="无效时系统自动仅走学术源",
        )

        st.markdown("**操作**")
        # 侧边栏按钮：两行布局，避免三列文字被截断
        b1, b2 = st.columns(2)
        with b1:
            fetch_clicked = st.form_submit_button("获取模型", use_container_width=True)
        with b2:
            test_clicked = st.form_submit_button("测试连接", use_container_width=True)
        save_clicked = st.form_submit_button("保存配置", use_container_width=True, type="primary")

    if fetch_clicked:
        if not admin_pwd:
            st.error("请输入管理员口令")
        else:
            with st.spinner("正在获取模型列表..."):
                result = admin_list_models({
                    "password": admin_pwd,
                    "openai_api_key": new_openai_key or None,
                    "openai_base_url": new_base_url or None,
                })
            if result is None:
                st.error("获取失败：后端异常")
            elif result.get("error"):
                st.error(f"获取失败：{result['error']}")
            else:
                models = result.get("models", [])
                st.session_state.remote_models = models
                st.success(f"获取到 {len(models)} 个模型")
                st.rerun()

    if test_clicked:
        if not admin_pwd:
            st.error("请输入管理员口令")
        else:
            with st.spinner("正在测试连接（真实发送一次最小调用）..."):
                result = admin_test_model({
                    "password": admin_pwd,
                    "openai_api_key": new_openai_key or None,
                    "openai_base_url": new_base_url or None,
                    "openai_model": new_model or None,
                })
            if result is None:
                st.error("测试失败：后端异常")
            elif result.get("ok"):
                st.success(f"{result.get('message', '连接成功')}")
            else:
                st.error(f"连接失败：{result.get('message', '未知错误')}")

    if save_clicked:
        if not admin_pwd:
            st.error("请输入管理员口令")
        elif not (new_openai_key or new_base_url or new_model or new_tavily_key):
            st.warning("请至少填写一项要修改的配置")
        else:
            result = update_admin_config({
                "password": admin_pwd,
                "openai_api_key": new_openai_key or None,
                "openai_base_url": new_base_url or None,
                "openai_model": new_model or None,
                "tavily_api_key": new_tavily_key or None,
            })
            if result is None:
                st.error("保存失败：口令错误或后端异常")
            else:
                st.success(f"{result.get('message', '配置已保存并即时生效')}")

    remote_models = st.session_state.get("remote_models") or []
    if remote_models:
        with st.expander(f"接口可用模型（{len(remote_models)} 个）", expanded=False):
            for m in remote_models[:50]:
                st.code(m, language=None)
            if len(remote_models) > 50:
                st.caption(f"仅显示前 50 个，共 {len(remote_models)} 个")


def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.markdown("## 系统说明")
        st.markdown("""
        本系统基于 Multi-Agent 架构，自动完成文献综述：
        - **检索** — ArXiv 学术论文检索为主 + 网络补充资料
        - **分析** — 方法分类、性能对比、研究空白提取 + 可视化
        - **撰稿** — 生成结构化文献综述报告
        - **引用** — 自动文献引用管理
        - **审核** — 支持人工审核反馈
        """)
        st.divider()
        st.markdown("## 技术栈")
        st.markdown("""
        - **后端**: FastAPI + LangGraph
        - **前端**: Streamlit
        - **检索**: ArXiv 学术 + Tavily 网络
        - **模型**: OpenAI 兼容接口（服务端可配置）
        """)
        st.divider()

        # 连接状态
        st.markdown("## 连接状态")
        if check_health():
            st.success("后端服务已连接")
        else:
            st.error("后端服务未启动")
            st.caption(f"请确认后端运行在 `{API_BASE_URL}`")

        # 依赖健康面板（P2）
        deps = fetch_dependencies()
        if deps is not None:
            with st.expander("依赖状态", expanded=False):
                st.caption(
                    f"LLM：{'OK' if deps.get('llm_key_set') else '未配置 Key'}"
                    f"　模型：`{deps.get('llm_model') or '-'}`"
                )
                if deps.get("tavily_key_set"):
                    st.caption("Tavily：已配置")
                elif deps.get("tavily_key_placeholder"):
                    st.warning("Tavily：Key 仍是占位符（网络检索不可用，仅 ArXiv）")
                else:
                    st.warning("Tavily：未配置 Key")
                if deps.get("llm_base_url"):
                    st.caption(f"接口：`{deps.get('llm_base_url')}`")
                st.caption("ArXiv：默认可用（国内 PDF 可能超时）")
                # 免 Key 学术主源（服务器实测优先）
                acad = []
                if deps.get("crossref_enabled"):
                    acad.append("Crossref")
                if deps.get("openalex_enabled"):
                    acad.append("OpenAlex")
                if deps.get("europepmc_enabled"):
                    acad.append("EuropePMC")
                if deps.get("core_enabled"):
                    acad.append("CORE")
                if acad:
                    st.caption("学术主源：" + "、".join(acad))
                free_parts = []
                if deps.get("duckduckgo_enabled"):
                    free_parts.append("DuckDuckGo")
                if deps.get("wikipedia_enabled"):
                    free_parts.append("Wikipedia")
                if deps.get("semantic_scholar_enabled"):
                    free_parts.append("Semantic Scholar")
                if free_parts:
                    st.caption("其它免 Key 源：" + "、".join(free_parts) + "（部分环境可能不可达）")
                if deps.get("searxng_reachable"):
                    st.caption(f"自建 SearXNG：`{deps.get('searxng_url')}`")
                else:
                    st.caption("自建 SearXNG：未启动（可选）")

        # 进行中任务（内存中仍在跑的）
        st.divider()
        st.markdown("## 进行中")
        running = fetch_running_tasks()
        if running:
            st.markdown(_status_icon_css(), unsafe_allow_html=True)
            for r in running:
                rid = r.get("thread_id") or ""
                rtopic = (r.get("topic") or "未命名研究")[:28]
                started = float(r.get("started_at") or 0)
                col_run, col_open_run = st.columns([3, 1])
                with col_run:
                    st.markdown(
                        f"<div class='st-row' style='font-size:0.85rem'>"
                        f"{_svg_status_icon('run', size=14)}<span>{rtopic}</span></div>",
                        unsafe_allow_html=True,
                    )
                    if started > 0:
                        _render_js_stopwatch(started, dom_id=f"sw-{rid[:8]}")
                with col_open_run:
                    if st.button("查看", key=f"run-open-{rid}", use_container_width=True):
                        _restore_task(rid, r.get("topic") or "未命名研究", r.get("phase") or "searching")
        else:
            st.caption("暂无进行中的任务")

        # 历史任务（排除进行中，避免与上面重复）
        st.divider()
        st.markdown("## 历史任务")
        running_ids = {r.get("thread_id") for r in running}
        history = [h for h in fetch_history() if h.get("thread_id") not in running_ids]
        if history:
            st.markdown(_status_icon_css(), unsafe_allow_html=True)
            status_kind = {
                "reviewing": "review",
                "completed": "done",
                "searching": "search",
                "analyzing": "analyze",
                "writing": "write",
                "failed": "fail",
            }
            for item in history[:10]:
                h_topic = (item.get("topic") or "未命名")[:24]
                h_status = item.get("status", "")
                tid = item.get("thread_id", "")
                kind = status_kind.get(h_status, "wait")
                h_time = item.get("updated_at") or ""
                time_suf = f"  ·  {h_time}" if h_time else ""
                col_open, col_del = st.columns([5, 1])
                with col_open:
                    # 用 HTML 图标 + 文字；按钮仍用纯文本避免 emoji
                    if st.button(
                        f"{h_topic}{time_suf}",
                        key=f"hist-{tid}",
                        use_container_width=True,
                    ):
                        _restore_task(tid, item.get("topic", ""), h_status)
                    st.markdown(
                        f"<div class='st-row' style='margin:-2px 0 6px 0;font-size:0.78rem;opacity:.85'>"
                        f"{_svg_status_icon(kind, size=14)}<span>{h_status or '-'}</span></div>",
                        unsafe_allow_html=True,
                    )
                with col_del:
                    if st.button(
                        "删除",
                        key=f"hist-del-{tid}",
                        help=f"删除「{h_topic}」",
                        icon=":material/delete:",
                    ):
                        if delete_history(tid):
                            # 若删除的是当前查看的任务，一并清空界面
                            if st.session_state.get("thread_id") == tid:
                                st.session_state.thread_id = None
                                st.session_state.report = ""
                                st.session_state.report_draft = ""
                                st.session_state.references = []
                                st.session_state.charts = []
                                st.session_state.progress_messages = []
                                st.session_state.is_reviewing = False
                                st.session_state.task_status = "idle"
                            st.success(f"已删除：{h_topic}")
                            st.rerun()
                        else:
                            st.error("删除失败，请重试")
        else:
            st.caption("暂无历史任务")

        # 在线配置（管理员口令保护）
        st.divider()
        admin_status = get_admin_status()
        if admin_status is None:
            return
        with st.expander("系统设置", expanded=False):
            if not admin_status.get("admin_enabled"):
                st.info("在线配置未启用：需在服务器 `.env` 中设置 `ADMIN_PASSWORD` 后重启服务。")
            else:
                _render_admin_settings(admin_status)
