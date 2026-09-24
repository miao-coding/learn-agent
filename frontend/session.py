"""会话状态：session_state 初始化、阶段点亮口径、任务恢复与终态切换"""
import streamlit as st

from frontend.api_client import fetch_running_tasks, get_report


def init_session_state():
    defaults = {
        "thread_id": None,
        "topic": "",
        "task_status": "idle",  # idle / running / reviewing / completed / error
        "report": "",
        "report_draft": "",
        "references": [],
        "charts": [],
        "quality_metrics": {},
        "task_started_at": 0.0,
        # 运行中任务独立快照：切换历史/刷新时不丢
        "running_task_id": "",
        "running_started_at": 0.0,
        "running_topic": "",
        "running_progress": [],
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
        "writing_chars": 0,
        "revision_count": 0,
        "max_revisions": 3,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
        # 对于 dict 类型也需要确保子键存在
        if key == "phases":
            for pk, pv in defaults["phases"].items():
                if pk not in st.session_state.phases:
                    st.session_state.phases[pk] = pv


_PHASE_ORDER = ["searching", "analyzing", "writing", "reviewing", "completed"]


def _mark_phase_reached(phase: str) -> None:
    """统一阶段点亮口径：到达某阶段时，之前的阶段标完成，当前阶段保持「进行中」"""
    if phase not in _PHASE_ORDER:
        return
    idx = _PHASE_ORDER.index(phase)
    for p in _PHASE_ORDER[:idx]:
        st.session_state.phases[p] = True
    if phase == "completed":
        st.session_state.phases["completed"] = True


def _restore_task(tid: str, topic: str, status: str) -> None:
    """从历史任务恢复会话状态

    - 运行中（initializing/searching/analyzing/writing）：挂回实时 SSE 流；
      断连期间积压在服务端队列的事件会重放，进度日志由服务端缓冲补齐
    - 等待审核（reviewing）：恢复审核区，可提交通过/返工
    - 已完成（completed）：直接展示最终报告
    - 失败（failed）：展示失败信息
    """
    st.session_state.thread_id = tid
    st.session_state.topic = topic
    try:
        st.query_params["tid"] = tid
        st.query_params["topic"] = (topic or "")[:80]
        if float(st.session_state.get("task_started_at") or 0) > 0:
            st.query_params["t0"] = str(int(st.session_state.task_started_at))
    except Exception:
        pass
    st.session_state.error_message = ""
    st.session_state.is_reviewing = status == "reviewing"
    st.session_state.writing_chars = 0

    running_phases = ("initializing", "searching", "analyzing", "writing")

    # 若另有任务在跑：先把其进度快照存起来，避免被本函数清空
    prev_tid = st.session_state.get("running_task_id") or ""
    if prev_tid and prev_tid != tid and st.session_state.get("task_status") == "running":
        st.session_state["running_progress"] = list(st.session_state.get("progress_messages") or [])
        if st.session_state.get("task_started_at"):
            st.session_state["running_started_at"] = float(st.session_state.task_started_at)

    # 切到运行中任务：尽量保留/恢复进度，禁止无故清空
    is_running_status = status in running_phases
    if is_running_status:
        # 运行视图不得展示任何旧任务的报告/审核态（串台根因）
        st.session_state.report = ""
        st.session_state.report_draft = ""
        st.session_state.references = []
        st.session_state.charts = []
        st.session_state.quality_metrics = {}
        st.session_state.is_reviewing = False
    if is_running_status and tid == (st.session_state.get("running_task_id") or tid):
        st.session_state.progress_messages = list(st.session_state.get("running_progress") or st.session_state.get("progress_messages") or [])
    elif not is_running_status:
        st.session_state.progress_messages = []
        st.session_state.report = ""
        st.session_state.report_draft = ""
        st.session_state.references = []
        st.session_state.charts = []
        st.session_state.quality_metrics = {}

    if status == "completed":
        st.session_state.task_status = "completed"
        st.session_state.stream_consumed = True
        st.session_state.task_started_at = 0.0
    elif status == "failed":
        st.session_state.task_status = "error"
        st.session_state.stream_consumed = True
        st.session_state.task_started_at = 0.0
        st.session_state.error_message = "任务已失败（检索或生成未完成）"
    elif status == "reviewing":
        st.session_state.task_status = "reviewing"
        st.session_state.stream_consumed = True
    elif is_running_status:
        st.session_state.task_status = "running"
        st.session_state.stream_consumed = False
        st.session_state.current_phase = status
        st.session_state.running_task_id = tid
        st.session_state.running_topic = topic
        # 优先：本地快照 → 服务器 started_at → 再不用“现在”（避免从 0 开始）
        started = float(st.session_state.get("running_started_at") or 0)
        if not started:
            for r in fetch_running_tasks():
                if r.get("thread_id") == tid:
                    started = float(r.get("started_at") or 0)
                    break
        st.session_state.task_started_at = started or st.session_state.get("task_started_at") or 0.0
        st.session_state.running_started_at = st.session_state.task_started_at
        _mark_phase_reached(status)
    else:
        st.session_state.task_status = "idle"
        st.session_state.stream_consumed = True

    if status not in running_phases:
        for k in st.session_state.phases:
            st.session_state.phases[k] = False

    # 仅非运行中才加载报告；运行中不得把旧 draft/历史报告叠在进度下面
    if status in ("completed", "reviewing", "failed"):
        report_data = get_report(tid)
        if report_data and report_data.get("report"):
            st.session_state.report = report_data["report"]
            if status == "reviewing":
                st.session_state.report_draft = report_data["report"]
                st.session_state.revision_count = int(report_data.get("revision_count") or 0)
                st.session_state.max_revisions = int(report_data.get("max_revisions") or 3)
            st.session_state.references = report_data.get("references", [])
            st.session_state.charts = report_data.get("charts", [])
            st.session_state.quality_metrics = report_data.get("quality_metrics") or {}
    st.rerun()


def _finalize_task_view(thread_id: str, fin: str) -> None:
    """把会话切到任务的终态视图（reviewing/completed/failed）并拉取报告"""
    if fin == "reviewing":
        st.session_state.task_status = "reviewing"
        st.session_state.is_reviewing = True
        _mark_phase_reached("reviewing")
    elif fin == "completed":
        st.session_state.task_status = "completed"
        _mark_phase_reached("completed")
    else:
        st.session_state.task_status = "error"
        if not st.session_state.error_message:
            st.session_state.error_message = "任务已失败（检索或生成未完成）"
    st.session_state.stream_consumed = True
    report_data = get_report(thread_id)
    if report_data and report_data.get("report"):
        st.session_state.report = report_data["report"]
        if fin == "reviewing":
            st.session_state.report_draft = report_data["report"]
            st.session_state.revision_count = int(report_data.get("revision_count") or 0)
            st.session_state.max_revisions = int(report_data.get("max_revisions") or 3)
        st.session_state.references = report_data.get("references") or []
        st.session_state.charts = report_data.get("charts") or []
        st.session_state.quality_metrics = report_data.get("quality_metrics") or {}


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
