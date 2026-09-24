"""SSE 分片消费：每轮消费一小段事件写入 session_state，由 main 循环调用并 rerun"""
import time

import streamlit as st

from frontend.api_client import _probe_task_status, consume_sse_sync, fetch_task_progress
from frontend.session import _finalize_task_view, _mark_phase_reached


def process_stream(thread_id: str, slice_seconds: float = 2.5) -> None:
    """分片消费 SSE 事件写入 session_state（由 main 循环调用并 rerun）

    非阻塞设计：每轮先拉服务端进度历史（日志权威来源）拿 upto_seq 作重放
    锚点，只听其后事件；时间片到即断开，让脚本跑完整个渲染周期再 rerun —
    页面在任务运行期间保持可交互，且 Streamlit 按轮清理未刷新的旧元素，
    不会残留上一视图的报告/审核区。
    """
    st.session_state.task_status = "running"
    st.session_state.stream_consumed = False

    hist = None
    try:
        hist = fetch_task_progress(thread_id)
    except Exception:
        pass
    since = 0
    if hist:
        server_msgs = hist.get("messages") or []
        if server_msgs:
            st.session_state.progress_messages = list(server_msgs)[-50:]
            if st.session_state.get("running_task_id") == thread_id:
                st.session_state["running_progress"] = list(st.session_state.progress_messages)
        st0 = float(hist.get("started_at") or 0)
        if st0 > 0:
            st.session_state.task_started_at = st0
            st.session_state.running_started_at = st0
        since = int(hist.get("upto_seq") or 0)

    if not st.session_state.get("task_started_at"):
        st.session_state.task_started_at = time.time()

    deadline = time.time() + slice_seconds
    ended_normally = True
    for event_type, data in consume_sse_sync(thread_id, since=since):
        if time.time() >= deadline:
            # 时间片到：断开连接，让本轮脚本跑完渲染并由 main 触发下一轮
            ended_normally = False
            break

        if event_type == "heartbeat":
            # 仅保活；时间由 JS 秒表每秒自增
            continue

        if event_type == "phase":
            phase = data.get("phase", "")
            st.session_state.current_phase = phase
            _mark_phase_reached(phase)
            if phase == "failed":
                st.session_state.task_status = "error"
                if not st.session_state.error_message:
                    st.session_state.error_message = "任务已失败（检索或生成未完成）"

        elif event_type == "progress":
            msg = data.get("message", "")
            st.session_state.progress_messages.append(msg)
            if st.session_state.get("running_task_id") == thread_id:
                st.session_state["running_progress"] = list(st.session_state.progress_messages)
            # 只保留最近 50 条，防止 session 无限膨胀
            if len(st.session_state.progress_messages) > 50:
                st.session_state.progress_messages = st.session_state.progress_messages[-50:]
                if st.session_state.get("running_task_id") == thread_id:
                    st.session_state["running_progress"] = list(st.session_state.progress_messages)

        elif event_type == "token":
            content = data.get("content", "")
            st.session_state.writing_chars = int(st.session_state.get("writing_chars") or 0) + len(content)

        elif event_type == "complete":
            report = data.get("report", "")
            st.session_state.report = report
            refs = data.get("references", [])
            charts = data.get("charts", [])
            if refs:
                st.session_state.references = refs
            if charts:
                st.session_state.charts = charts
            qm = data.get("quality_metrics") or {}
            if qm:
                st.session_state.quality_metrics = qm
            st.session_state.task_status = "completed"
            _mark_phase_reached("completed")
            st.session_state.stream_consumed = True
            return

        elif event_type == "interrupt":
            st.session_state.report_draft = data.get("report_draft", "")
            st.session_state.is_reviewing = True
            st.session_state.task_status = "reviewing"
            _mark_phase_reached("reviewing")
            st.session_state.revision_count = int(data.get("revision_count") or 0)
            st.session_state.max_revisions = int(data.get("max_revisions") or 3)
            st.session_state.stream_consumed = True
            return

        elif event_type == "task_finished":
            # SSE 队列已消失但任务其实已结束（切换/刷新与任务完成撞车的竞态）：
            # 回查到真实终态后直接转入对应视图，而不是误报「任务未找到」
            _finalize_task_view(thread_id, data.get("status", ""))
            return

        elif event_type == "error":
            err_msg = data.get("message", "未知错误")
            st.session_state.error_message = err_msg
            st.session_state.task_status = "error"
            st.session_state.stream_consumed = True
            return

    # 流被服务端正常关闭但未收到终态事件（如任务恰好结束且 since 已越过
    # 终止事件）：回查真实状态并转入终态视图，防止停留在 running 反复重连
    if ended_normally and not st.session_state.stream_consumed:
        real_status = _probe_task_status(thread_id)
        if real_status in ("reviewing", "completed", "failed"):
            _finalize_task_view(thread_id, real_status)
