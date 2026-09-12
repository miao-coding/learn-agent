"""Multi-Agent 学术文献综述系统 - Streamlit 前端"""
import glob
import json
import time

import requests
import streamlit as st
from pathlib import Path

# ============ 页面配置 ============
st.set_page_config(
    page_title="Multi-Agent 文献综述助手",
    page_icon="🏭",
    layout="wide",
)

# ============ 常量 ============
API_BASE_URL = "http://localhost:8000"

# ============ Session State 初始化 ============
def init_session_state():
    defaults = {
        "thread_id": None,
        "topic": "",
        "task_status": "idle",  # idle / running / reviewing / completed / error
        "report": "",
        "report_draft": "",
        "references": [],
        "charts": [],
        "phases": {
            "searching": False,
            "analyzing": False,
            "writing": False,
            "reviewing": False,
            "completed": False,
            "failed": False,
        },
        "current_phase": "",
        "progress_messages": [],
        "is_reviewing": False,
        "error_message": "",
        "stream_consumed": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
        # 对于 dict 类型也需要确保子键存在
        if key == "phases":
            for pk, pv in defaults["phases"].items():
                if pk not in st.session_state.phases:
                    st.session_state.phases[pk] = pv


init_session_state()


# ============ API 调用函数 ============
def check_health() -> bool:
    """检查后端连接"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def fetch_available_models() -> dict | None:
    """获取后端可用模型列表（未配置白名单时返回 None，前端隐藏选择框）"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/models", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def get_admin_status() -> dict | None:
    """获取后端配置状态（在线配置是否启用、Key 是否已配置，不含密钥明文）"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/admin/status", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def update_admin_config(payload: dict) -> dict | None:
    """提交管理员配置（口令保护，成功后即时生效并持久化到服务器 .env）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/config", json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def admin_list_models(payload: dict) -> dict | None:
    """获取 OpenAI 兼容接口的可用模型列表（口令保护）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/list-models", json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def admin_test_model(payload: dict) -> dict | None:
    """测试模型连通性（真实发送一次最小调用，口令保护）"""
    try:
        resp = requests.post(f"{API_BASE_URL}/api/admin/test-model", json=payload, timeout=40)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def fetch_history(limit: int = 15) -> list:
    """获取历史任务列表（服务端 checkpoints.db 持久化，刷新/退出不丢失）"""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/research/history", params={"limit": limit}, timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


def delete_history(thread_id: str) -> bool:
    """删除指定历史研究报告（服务端清 checkpoints 持久化数据）"""
    try:
        resp = requests.delete(
            f"{API_BASE_URL}/api/research/{thread_id}", timeout=15
        )
        return resp.status_code == 200 and resp.json().get("deleted", False)
    except Exception:
        return False


def fetch_dependencies() -> dict | None:
    """获取后端外部依赖健康状态"""
    try:
        resp = requests.get(f"{API_BASE_URL}/api/dependencies", timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _restore_task(tid: str, topic: str, status: str) -> None:
    """从历史任务恢复会话状态

    - 运行中（initializing/searching/analyzing/writing）：挂回实时 SSE 流，
      继续接收后续进度事件（已错过的事件不重播，按当前状态近似点亮）
    - 等待审核（reviewing）：恢复审核区，可提交通过/返工
    - 已完成（completed）：直接展示最终报告
    """
    st.session_state.thread_id = tid
    st.session_state.topic = topic
    st.session_state.report = ""
    st.session_state.report_draft = ""
    st.session_state.references = []
    st.session_state.charts = []
    st.session_state.progress_messages = []
    st.session_state.error_message = ""
    st.session_state.is_reviewing = status == "reviewing"

    running_phases = ("initializing", "searching", "analyzing", "writing")
    phase_order = ["searching", "analyzing", "writing"]

    if status == "completed":
        st.session_state.task_status = "completed"
        st.session_state.stream_consumed = True
    elif status == "failed":
        st.session_state.task_status = "error"
        st.session_state.stream_consumed = True
        st.session_state.error_message = "任务已失败（检索或生成未完成）"
    elif status == "reviewing":
        st.session_state.task_status = "reviewing"
        st.session_state.stream_consumed = True
    elif status in running_phases:
        # 运行中：重新挂回实时流，继续接收后续进度
        st.session_state.task_status = "running"
        st.session_state.stream_consumed = False
        st.session_state.current_phase = status
        if status in phase_order:
            for p in phase_order[: phase_order.index(status)]:
                st.session_state.phases[p] = True
    else:
        st.session_state.task_status = "idle"
        st.session_state.stream_consumed = True

    if status not in running_phases:
        for k in st.session_state.phases:
            st.session_state.phases[k] = False

    # 拉取报告（reviewing / completed 都已写入 final_report）
    report_data = get_report(tid)
    if report_data and report_data.get("report"):
        st.session_state.report = report_data["report"]
        if status == "reviewing":
            st.session_state.report_draft = report_data["report"]
        st.session_state.references = report_data.get("references", [])
        st.session_state.charts = report_data.get("charts", [])
    st.rerun()


def submit_research(topic: str, model_name: str = "") -> dict | None:
    """提交研究任务"""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/research",
            json={"topic": topic, "model_name": model_name},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def submit_review(thread_id: str, feedback: str) -> dict | None:
    """提交审核；4xx 时返回带 message 的错误字典以便前端展示 detail"""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/research/{thread_id}/review",
            json={"feedback": feedback},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = (resp.text or "")[:160]
        return {"status": "error", "message": detail or f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_report(thread_id: str) -> dict | None:
    """获取最终报告"""
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/research/{thread_id}/report",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def consume_sse_sync(thread_id: str, max_retries: int = 3, retry_delay: float = 1.0):
    """同步消费 SSE 流式事件

    Args:
        thread_id: 任务线程 ID
        max_retries: 连接失败时的最大重试次数（用于返工场景下后端队列尚未就绪的情况）
        retry_delay: 每次重试之间的等待秒数
    """
    url = f"{API_BASE_URL}/api/research/{thread_id}/stream"

    for attempt in range(max_retries + 1):
        try:
            with requests.get(url, stream=True, timeout=None) as response:
                if response.status_code == 404:
                    # 队列不存在（常见于服务重启后队列丢失）→
                    # 先尝试从 checkpoint 断点复活任务，再重连
                    if attempt == 0:
                        try:
                            requests.post(
                                f"{API_BASE_URL}/api/research/{thread_id}/resume", timeout=30
                            )
                            time.sleep(2)
                        except Exception:
                            pass
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    yield "error", {"message": "任务未找到，可能已完成或过期"}
                    return

                event_type = None
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        event_type = None
                        continue
                    # SSE 心跳注释 → 转为心跳事件（驱动前端刷新运行计时）
                    if line.startswith(":"):
                        yield "heartbeat", {}
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            data = {"raw": line[6:]}
                        yield event_type, data
                    elif line.startswith("data:"):
                        # 兼容无空格的情况
                        try:
                            data = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            data = {"raw": line[5:].strip()}
                        yield event_type, data
            # 正常结束（连接关闭），不再重试
            return

        except requests.exceptions.ConnectionError:
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            yield "error", {"message": "无法连接到后端服务，请确认后端已启动"}
            return
        except Exception as e:
            yield "error", {"message": f"SSE 流异常中断: {str(e)}"}
            return


# ============ 核心流程：消费 SSE 并更新状态 ============
def process_stream(thread_id: str):
    """消费 SSE 流，将事件写入 session_state 并触发 rerun"""
    st.session_state.task_status = "running"
    st.session_state.stream_consumed = False

    # 使用占位符实时更新（阶段区与日志区分离，避免 heartbeat 整块重绘导致页面跳动）
    phases_placeholder = st.empty()
    log_placeholder = st.empty()
    meta_placeholder = st.empty()

    token_buffer = []  # 用于收集 token 事件的内容
    t0 = time.time()  # 任务开始时间（用于运行计时显示）
    last_render = 0.0

    def _paint(force: bool = False, writing_chars: int | None = None):
        nonlocal last_render
        now = time.time()
        # 心跳/token 高频事件节流：至少间隔 1.5s，避免页面被 empty() 反复顶到底部
        if not force and (now - last_render) < 1.5:
            return
        last_render = now
        elapsed = int(now - t0)
        with phases_placeholder.container():
            _render_phase_steps()
        with log_placeholder.container():
            _render_progress_log()
        with meta_placeholder.container():
            if writing_chars is not None:
                st.caption(f"✍️ 正在撰写综述… 已生成 {writing_chars} 字 · 已运行 {elapsed // 60}:{elapsed % 60:02d}")
            else:
                st.caption(f"⏱ 已运行 {elapsed // 60}:{elapsed % 60:02d} · 连接正常，系统处理中")

    for event_type, data in consume_sse_sync(thread_id):
        if event_type == "heartbeat":
            _paint()
            continue

        if event_type == "phase":
            phase = data.get("phase", "")
            st.session_state.current_phase = phase
            if phase in st.session_state.phases:
                st.session_state.phases[phase] = True
            if phase == "failed":
                st.session_state.task_status = "error"
                if not st.session_state.error_message:
                    st.session_state.error_message = "任务已失败（检索或生成未完成）"
            _paint(force=True)

        elif event_type == "progress":
            msg = data.get("message", "")
            st.session_state.progress_messages.append(msg)
            # 只保留最近 50 条，防止 session 无限膨胀
            if len(st.session_state.progress_messages) > 50:
                st.session_state.progress_messages = st.session_state.progress_messages[-50:]
            _paint(force=True)

        elif event_type == "token":
            content = data.get("content", "")
            token_buffer.append(content)
            if len(token_buffer) % 20 == 0:
                total_chars = sum(len(c) for c in token_buffer)
                _paint(writing_chars=total_chars)

        elif event_type == "complete":
            report = data.get("report", "")
            if token_buffer:
                report = "".join(token_buffer) if not report else report
            st.session_state.report = report
            refs = data.get("references", [])
            charts = data.get("charts", [])
            if refs:
                st.session_state.references = refs
            if charts:
                st.session_state.charts = charts
            st.session_state.task_status = "completed"
            st.session_state.phases["completed"] = True
            st.session_state.stream_consumed = True
            _paint(force=True)
            break

        elif event_type == "interrupt":
            draft = data.get("report_draft", "")
            st.session_state.report_draft = draft
            if token_buffer and not draft:
                st.session_state.report_draft = "".join(token_buffer)
            st.session_state.is_reviewing = True
            st.session_state.task_status = "reviewing"
            st.session_state.phases["reviewing"] = True
            st.session_state.stream_consumed = True
            _paint(force=True)
            break

        elif event_type == "error":
            err_msg = data.get("message", "未知错误")
            st.session_state.error_message = err_msg
            st.session_state.task_status = "error"
            st.session_state.stream_consumed = True
            _paint(force=True)
            break


def _render_phase_steps():
    """渲染阶段步骤条（固定五步，不随消息增长）"""
    phases_info = [
        ("searching", "🔍 文献检索", "ArXiv 论文 + 网络补充资料"),
        ("analyzing", "📊 文献分析", "方法分类、性能对比、研究空白"),
        ("writing", "✍️ 撰写综述", "生成带引用的综述报告"),
        ("reviewing", "👀 等待审核", "人工审核反馈"),
        ("completed", "✅ 完成", "报告已生成"),
    ]
    for phase_key, label, desc in phases_info:
        done = st.session_state.phases.get(phase_key, False)
        is_current = st.session_state.current_phase == phase_key and not done
        if done:
            st.markdown(f"&nbsp;&nbsp;✅ ~~{label}~~ · {desc}")
        elif is_current:
            st.markdown(f"&nbsp;&nbsp;🔄 **{label}** · {desc}")
        else:
            st.markdown(f"&nbsp;&nbsp;⚪ {label} · {desc}")


def _render_progress_log(max_lines: int = 24):
    """固定高度日志框：只显示最近若干条，整页高度不随消息变长"""
    messages = st.session_state.progress_messages[-max_lines:]
    if not messages:
        return
    # 单块 HTML 滚动容器，避免 Streamlit 逐条 markdown 撑开页面
    lines = "".join(
        f"<div style='margin:0 0 4px 0;line-height:1.45'>→ {_html_escape(m)}</div>"
        for m in messages
    )
    st.markdown(
        f"""
        <div style="max-height:220px;overflow-y:auto;border:1px solid rgba(128,128,128,.35);
                    border-radius:8px;padding:10px 12px;font-size:0.88rem;background:rgba(128,128,128,.06)">
          <div style="font-weight:600;margin-bottom:6px">📝 详细进度（最近 {len(messages)} 条）</div>
          {lines}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============ UI 组件 ============
def render_header():
    """渲染页面头部"""
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0;">
        <h1>📚 Multi-Agent 文献综述助手</h1>
        <p style="color: #666; font-size: 1.1rem;">输入研究方向，自动检索文献并生成带引用的综述报告</p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()


def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.markdown("## 📋 系统说明")
        st.markdown("""
        本系统基于 Multi-Agent 架构，自动完成文献综述：
        - 🔍 **检索** — ArXiv 学术论文检索为主 + 网络补充资料
        - 📊 **分析** — 方法分类、性能对比、研究空白提取 + 可视化
        - ✍️ **撰稿** — 生成结构化文献综述报告
        - 📚 **引用** — 自动文献引用管理
        - ✅ **审核** — 支持人工审核反馈
        """)
        st.divider()
        st.markdown("## 🛠 技术栈")
        st.markdown("""
        - **后端**: FastAPI + LangGraph
        - **前端**: Streamlit
        - **LLM**: OpenAI GPT-4o
        - **搜索**: Tavily API
        """)
        st.divider()

        # 连接状态
        st.markdown("## 🔗 连接状态")
        if check_health():
            st.success("✅ 后端服务已连接")
        else:
            st.error("❌ 后端服务未启动")
            st.caption(f"请确认后端运行在 `{API_BASE_URL}`")

        # 依赖健康面板（P2）
        deps = fetch_dependencies()
        if deps is not None:
            with st.expander("🧩 依赖状态", expanded=False):
                st.caption(
                    f"LLM：{'✅' if deps.get('llm_key_set') else '❌ 未配置 Key'}"
                    f"　模型：`{deps.get('llm_model') or '-'}`"
                )
                if deps.get("tavily_key_set"):
                    st.caption("Tavily：✅ 已配置")
                elif deps.get("tavily_key_placeholder"):
                    st.warning("Tavily：❌ Key 仍是占位符（网络检索不可用，仅 ArXiv）")
                else:
                    st.warning("Tavily：❌ 未配置 Key")
                if deps.get("llm_base_url"):
                    st.caption(f"接口：`{deps.get('llm_base_url')}`")
                st.caption("ArXiv：✅ 默认可用（国内 PDF 可能超时）")

        # 历史任务（服务器持久化，刷新/退出不丢失）
        st.divider()
        st.markdown("## 🕘 历史任务")
        history = fetch_history()
        if history:
            status_icons = {
                "reviewing": "👀", "completed": "✅", "searching": "🔍",
                "analyzing": "📊", "writing": "✍️", "failed": "❌",
            }
            for item in history[:10]:
                h_topic = (item.get("topic") or "未命名")[:24]
                h_status = item.get("status", "")
                tid = item.get("thread_id", "")
                icon = status_icons.get(h_status, "•")
                h_time = item.get("updated_at") or ""
                label = f"{icon} {h_topic}"
                if h_time:
                    label = f"{label}  ·  {h_time}"
                col_open, col_del = st.columns([5, 1])
                with col_open:
                    if st.button(
                        label,
                        key=f"hist-{tid}",
                        use_container_width=True,
                    ):
                        _restore_task(tid, item.get("topic", ""), h_status)
                with col_del:
                    if st.button(
                        "🗑",
                        key=f"hist-del-{tid}",
                        help=f"删除「{h_topic}」",
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
        with st.expander("⚙️ 系统设置"):
            if not admin_status.get("admin_enabled"):
                st.caption("在线配置未启用：需在服务器 .env 中设置 ADMIN_PASSWORD 后重启服务")
            else:
                st.caption(
                    f"OpenAI Key: {'✅ 已配置' if admin_status.get('openai_key_set') else '❌ 未配置'}　"
                    f"Tavily Key: {'✅ 已配置' if admin_status.get('tavily_key_set') else '❌ 未配置'}"
                )
                with st.form("admin_config_form"):
                    admin_pwd = st.text_input("管理员口令", type="password")
                    new_openai_key = st.text_input("OPENAI_API_KEY（留空不修改）", type="password")
                    new_base_url = st.text_input("OPENAI_BASE_URL（留空不修改）")
                    new_model = st.text_input("默认模型名（留空不修改）")
                    new_tavily_key = st.text_input("TAVILY_API_KEY（留空不修改）", type="password")
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        fetch_clicked = st.form_submit_button("📋 获取模型", use_container_width=True)
                    with col_b:
                        test_clicked = st.form_submit_button("🔌 测试连接", use_container_width=True)
                    with col_c:
                        save_clicked = st.form_submit_button("💾 保存配置", use_container_width=True)
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
                            st.success(f"✅ 获取到 {len(models)} 个模型，见下方列表")
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
                            st.success(f"✅ {result.get('message', '连接成功')}")
                        else:
                            st.error(f"❌ 连接失败：{result.get('message', '未知错误')}")
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
                            st.success(f"✅ {result.get('message', '配置已保存并即时生效')}")
                # 展示接口可用模型列表（点击「获取模型」后出现）
                remote_models = st.session_state.get("remote_models") or []
                if remote_models:
                    with st.expander(f"📋 接口可用模型（{len(remote_models)} 个，点击代码块右侧复制）"):
                        for m in remote_models[:50]:
                            st.code(m, language=None)
                        if len(remote_models) > 50:
                            st.caption(f"仅显示前 50 个，共 {len(remote_models)} 个")


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
            "🚀 开始研究",
            use_container_width=True,
            disabled=st.session_state.task_status == "running",
        )

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
        for k in st.session_state.phases:
            st.session_state.phases[k] = False

        # 提交任务
        result = submit_research(topic.strip(), selected_model)
        if result:
            st.session_state.thread_id = result["thread_id"]
            # 关键：标记运行中，下一轮 rerun 才会进入 process_stream 消费 SSE 进度流
            # （遗漏此行会导致前端永远不消费进度事件，界面停留在初始状态）
            st.session_state.task_status = "running"
            st.rerun()
        else:
            st.error("提交任务失败，请检查后端服务是否正常运行。")


def render_progress_section():
    """渲染进度区域"""
    st.markdown("### 📊 任务进度")

    if st.session_state.error_message:
        st.error(f"⚠️ {st.session_state.error_message}")
        return

    phases_info = [
        ("searching", "🔍 文献检索", "ArXiv 论文 + 网络补充资料"),
        ("analyzing", "📊 文献分析", "方法分类、性能对比、研究空白"),
        ("writing", "✍️ 撰写综述", "生成带引用的综述报告"),
        ("reviewing", "👀 等待审核", "人工审核反馈"),
        ("completed", "✅ 完成", "报告已生成"),
    ]

    for phase_key, label, desc in phases_info:
        done = st.session_state.phases.get(phase_key, False)
        is_current = (st.session_state.current_phase == phase_key
                      and not done)

        if done:
            st.markdown(f"&nbsp;&nbsp;✅ ~~{label}~~ · {desc}")
        elif is_current:
            st.markdown(f"&nbsp;&nbsp;🔄 **{label}** · {desc}")
        else:
            st.markdown(f"&nbsp;&nbsp;⚪ {label} · {desc}")

    # 显示进度消息（固定高度滚动容器，页面不被撑长）
    _render_progress_log()


def _render_progress_ui():
    """在流式处理过程中渲染进度 UI（兼容旧调用）"""
    st.markdown("### 📊 任务进度")
    _render_phase_steps()
    _render_progress_log()


def render_report_section():
    """渲染报告区域（含报告、图表、参考文献三个 Tab）"""
    report = st.session_state.report
    draft = st.session_state.report_draft

    if not report and not draft:
        return

    st.divider()
    st.markdown("### 📝 综述报告")

    # 当前报告也可手动删除（与历史列表共用同一接口）
    tid_now = st.session_state.get("thread_id") or ""
    if tid_now and st.session_state.task_status in ("completed", "reviewing"):
        col_title, col_del = st.columns([6, 1])
        with col_del:
            if st.button("🗑 删除报告", key="del-current-report"):
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
            ["📄 综述报告", "📊 数据图表", "📚 参考文献"]
        )

        with tab_report:
            # 目录导航（基于报告中的二级标题生成）
            toc_entries = _extract_toc(report)
            if toc_entries:
                with st.expander("📑 目录导航", expanded=False):
                    for anchor, title in toc_entries:
                        st.markdown(f"- [{title}](#{anchor})")
                    st.divider()

            st.markdown(report, unsafe_allow_html=True)

            # 下载按钮
            st.divider()
            st.download_button(
                label="📥 下载报告 (.md)",
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
        st.info("📋 以下是报告草稿，请审核后决定是否通过：")
        st.markdown(draft, unsafe_allow_html=True)


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
            source = ref.get("source", "")
            date = ref.get("date", "")
            meta = " · ".join(filter(None, [source, date]))
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


def render_review_section():
    """渲染审核区域"""
    if not st.session_state.is_reviewing:
        return

    st.divider()
    st.markdown("### ✅ 人工审核")

    col_feedback, col_actions = st.columns([3, 1])

    with col_feedback:
        feedback = st.text_input(
            "审核意见",
            placeholder='输入 "通过" 或修改意见，如 "请补充XX数据"',
            label_visibility="collapsed",
        )

    with col_actions:
        approve_clicked = st.button(
            "✅ 通过",
            use_container_width=True,
            disabled=not feedback.strip(),
        )
        revise_clicked = st.button(
            "🔄 返工",
            use_container_width=True,
            disabled=not feedback.strip(),
        )

    if approve_clicked and feedback.strip():
        _do_review(feedback.strip())
    elif revise_clicked and feedback.strip():
        _do_review(feedback.strip())


def _do_review(feedback: str):
    """执行审核提交"""
    thread_id = st.session_state.thread_id
    if not thread_id:
        return

    with st.spinner("正在提交审核意见..."):
        result = submit_review(thread_id, feedback)

    if result is None:
        st.error("审核提交失败，请重试。")
        return

    status = result.get("status", "")
    message = result.get("message", "")

    if status == "error":
        st.error(f"审核提交失败：{message}")
        return

    if status == "approved":
        st.success(f"✅ 审核通过！{message}")
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
        st.info(f"🔄 已提交修改意见，正在返工... {message}")
        st.session_state.is_reviewing = False
        st.session_state.task_status = "running"
        st.session_state.report_draft = ""
        st.session_state.phases["reviewing"] = False
        st.session_state.phases["completed"] = False
        st.session_state.progress_messages = []
        st.session_state.current_phase = ""
        st.session_state.stream_consumed = False
        # 等待后台 SSE 队列就绪，避免前端重连时后端尚未创建队列
        time.sleep(1)
        st.rerun()
    else:
        st.warning(f"未知状态: {status} - {message}")


# ============ 主流程 ============
def main():
    render_header()
    render_sidebar()
    render_input_section()

    thread_id = st.session_state.get("thread_id")

    if thread_id and st.session_state.task_status == "running" and not st.session_state.stream_consumed:
        # 正在运行且流尚未消费完 → 消费 SSE
        st.divider()
        process_stream(thread_id)
        # 流消费完毕后 rerun 以刷新 UI
        st.rerun()

    if thread_id:
        st.divider()
        render_progress_section()
        render_report_section()
        render_review_section()

        # 任务完成后提供重新开始的按钮
        if st.session_state.task_status == "completed":
            st.divider()
            if st.button("🔄 开始新的研究", use_container_width=True):
                _reset_state()
                st.rerun()


def _reset_state():
    """重置所有状态"""
    st.session_state.thread_id = None
    st.session_state.topic = ""
    st.session_state.task_status = "idle"
    st.session_state.report = ""
    st.session_state.report_draft = ""
    st.session_state.references = []
    st.session_state.charts = []
    st.session_state.progress_messages = []
    st.session_state.current_phase = ""
    st.session_state.is_reviewing = False
    st.session_state.error_message = ""
    st.session_state.stream_consumed = False
    for k in st.session_state.phases:
        st.session_state.phases[k] = False


main()
