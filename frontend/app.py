"""Multi-Agent 学术文献综述系统 - Streamlit 前端入口

模块拆分（frontend/ 包）：
- theme            主题 token / 报告 CSS / SVG 图标 / 秒表
- markdown_render  内嵌 Markdown 报告渲染（锚点 + 目录）
- api_client       后端 HTTP 调用 + SSE 流消费
- session          session_state 初始化 / 阶段口径 / 任务恢复 / 终态切换
- stream           SSE 分片消费（process_stream）
- sidebar          侧边栏（说明 / 依赖 / 进行中 / 历史 / 系统设置）
- views            主区视图（输入 / 进度 / 报告 / 审核）
"""
import streamlit as st

# ============ 页面配置（必须是第一个 st 命令） ============
st.set_page_config(
    page_title="Multi-Agent 文献综述助手",
    page_icon=None,
    layout="wide",
)

# streamlit run frontend/app.py 只把脚本目录放进 sys.path，
# 包内相互 import（from frontend.xxx）需要项目根在路径上
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frontend.api_client import fetch_history, fetch_running_tasks
from frontend.session import _reset_state, _restore_task, init_session_state
from frontend.sidebar import render_sidebar
from frontend.stream import process_stream
from frontend.views import (
    render_header,
    render_input_section,
    render_progress_section,
    render_report_section,
    render_review_section,
)

init_session_state()


# ============ 主流程 ============
def main():
    # 浏览器刷新后：从 URL 恢复最近查看/运行中的任务
    try:
        qp = st.query_params
        qtid = qp.get("tid") or ""
        qtopic = qp.get("topic") or ""
        qt0 = qp.get("t0") or ""
    except Exception:
        qtid, qtopic, qt0 = "", "", ""
    if qtid and not st.session_state.get("thread_id"):
        if qt0:
            try:
                st.session_state.running_started_at = float(qt0)
            except Exception:
                pass
        running = fetch_running_tasks()
        rstat = "searching"
        for r in running:
            if r.get("thread_id") == qtid:
                # 用 checkpoint 里的真实阶段（/running 返回），而非一律当作 searching
                rstat = r.get("phase") or "searching"
                if not st.session_state.get("running_started_at"):
                    st.session_state.running_started_at = float(r.get("started_at") or 0)
                break
        else:
            # 非运行中：从 history 推断
            for h in fetch_history(50):
                if h.get("thread_id") == qtid:
                    rstat = h.get("status") or "completed"
                    break
        _restore_task(qtid, qtopic or "已恢复任务", rstat)

    render_header()
    render_sidebar()
    render_input_section()

    thread_id = st.session_state.get("thread_id")

    if thread_id and st.session_state.task_status == "running" and not st.session_state.stream_consumed:
        # 分片消费 SSE：先渲染完整页面（报告/审核区按当前空状态渲染，Streamlit
        # 在每轮运行结束时清理未刷新的旧元素，不残留上一视图内容），再消费
        # 一小段事件后 rerun 进入下一轮 — 页面在任务运行期间全程可交互
        st.divider()
        render_progress_section()
        render_report_section()
        render_review_section()
        process_stream(thread_id)
        st.rerun()

    if thread_id:
        st.divider()
        # 任务进行中/失败时展示进度；完成后或进入审核后隐藏，避免报告上方还挂着进度条
        if st.session_state.task_status in ("running", "error"):
            render_progress_section()
        render_report_section()
        render_review_section()

        # 任务完成后提供重新开始的按钮
        if st.session_state.task_status == "completed":
            st.divider()
            if st.button("开始新的研究", use_container_width=True):
                _reset_state()
                st.rerun()


main()
