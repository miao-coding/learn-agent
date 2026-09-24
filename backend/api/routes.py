"""API 路由 — 研究任务提交、SSE 流式进度、人工审核、报告获取、健康检查"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

from backend.api.schemas import (
    AdminConfigRequest,
    AdminConfigResponse,
    AdminModelsResponse,
    AdminStatusResponse,
    AdminTestRequest,
    AdminTestResponse,
    AvailableModelsResponse,
    DeleteResponse,
    DependenciesResponse,
    HealthResponse,
    HistoryItem,
    ReportResponse,
    ResearchRequest,
    ResearchResponse,
    ReviewRequest,
    ReviewResponse,
    RunningTaskItem,
    UploadDocsResponse,
)
from backend.config import settings, update_env_file
from backend.tools.search import reload_tavily_client
from backend.utils import progress as progress_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["research"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  活跃任务管理：内存中执行的任务 thread_id 集合
#  （事件经 progress_bus 发布：有界日志 + 每连接独立订阅队列）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
active_tasks: set[str] = set()
# 任务开始时间与主题，供「进行中任务」显示
task_started_at: dict[str, float] = {}
task_meta: dict[str, dict] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  节点名称 → 阶段映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NODE_PHASE_MAP: dict[str, str] = {
    "init": "initializing",
    "searcher": "searching",
    "analyst": "analyzing",
    "writer": "writing",
    "reviewer": "reviewing",
}


def _get_graph(request: Request):
    """从 app.state 获取编译好的 LangGraph 图"""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")
    return graph


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/research — 提交研究任务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.post("/research", response_model=ResearchResponse)
async def start_research(request: Request, body: ResearchRequest):
    """提交研究任务，启动后台图执行，返回 thread_id"""
    thread_id = str(uuid.uuid4())
    active_tasks.add(thread_id)
    task_started_at[thread_id] = time.time()
    task_meta[thread_id] = {"topic": body.topic[:80], "model": body.model_name or ""}

    graph = _get_graph(request)

    # 校验模型白名单（未配置 AVAILABLE_MODELS 时不开放自选）
    if body.model_name:
        allowed = settings.get_available_models()
        if body.model_name not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"模型不可用: {body.model_name}，可用模型: {allowed or '未配置（功能未开放）'}",
            )

    # 可选：用户上传文献
    uploaded_docs: list[dict] = []
    if body.upload_batch_id:
        from backend.utils.upload_docs import load_upload_batch, uploads_to_search_seed

        batch = load_upload_batch(body.upload_batch_id)
        if not batch:
            raise HTTPException(status_code=400, detail="upload_batch_id 无效或已过期")
        seeds = uploads_to_search_seed(body.upload_batch_id)
        uploaded_docs = [
            {
                "filename": batch.get("filename", ""),
                "text": str(batch.get("text") or "")[:50000],
                "reference_titles": batch.get("reference_titles") or [],
                "seeds": seeds,
            }
        ]
        logger.info(
            f"研究任务附加上传文献: {batch.get('filename')} "
            f"({batch.get('text_chars')} 字, 参考线索 {len(batch.get('reference_titles') or [])})"
        )

    # 启动后台协程执行图
    asyncio.create_task(
        _run_graph(
            graph,
            thread_id,
            body.topic,
            model_name=body.model_name or "",
            uploaded_docs=uploaded_docs,
        ),
        name=f"research-{thread_id}",
    )
    logger.info(f"研究任务已启动: thread_id={thread_id}, topic={body.topic}")

    return ResearchResponse(thread_id=thread_id, topic=body.topic)


@router.post("/uploads/research-docs", response_model=UploadDocsResponse)
async def upload_research_docs(files: list[UploadFile] = File(...)):
    """上传用户已有研究文献（PDF/TXT/MD，可选）

    返回 batch_id；提交研究时带 upload_batch_id 即可并入检索。
    """
    from backend.utils.upload_docs import MAX_FILES, ingest_uploaded_file

    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"最多上传 {MAX_FILES} 个文件")

    metas = []
    batch_id = ""
    for f in files:
        data = await f.read()
        try:
            meta = ingest_uploaded_file(f.filename or "doc.pdf", data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("上传文献处理失败")
            raise HTTPException(status_code=500, detail=f"处理失败: {e}")
        if meta:
            batch_id = meta.get("batch_id") or batch_id
            metas.append(
                {
                    "filename": meta.get("filename"),
                    "text_chars": meta.get("text_chars"),
                    "reference_count": len(meta.get("reference_titles") or []),
                    "title_guess": meta.get("title_guess"),
                }
            )

    if not metas:
        raise HTTPException(status_code=400, detail="未能从文件中抽取文本")
    return UploadDocsResponse(batch_id=batch_id, files=metas)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  后台图执行核心
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def _run_graph(
    graph: Any,
    thread_id: str,
    topic: str,
    model_name: str = "",
    uploaded_docs: list[dict] | None = None,
) -> None:
    """后台执行 LangGraph 图，事件经 progress_bus 发布（日志 + SSE 扇出）"""
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "topic": topic,
        "model_name": model_name,
        "messages": [],
        "uploaded_docs": uploaded_docs or [],
    }
    # 立即点亮检索阶段（节点 update 要等节点完成才推送，先发一个初始 phase）
    progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": "searching"}})

    try:
        async for event in graph.astream(
            initial_state,
            config=config,
            stream_mode=["updates", "messages"],
        ):
            # astream 在 stream_mode=list 时返回 tuple: (mode, data)
            if not isinstance(event, tuple) or len(event) != 2:
                continue

            mode, data = event

            if mode == "updates":
                # data 是 dict: {node_name: state_update}
                await _handle_update_event(data, thread_id)

            elif mode == "messages":
                # data 是 tuple: (message_chunk, metadata)
                _handle_message_event(data, thread_id)

        # 图执行完毕：区分「等待人工审核」与「真正完成」
        await _finalize_stream(graph, config, thread_id)

    except Exception as e:
        logger.exception(f"图执行异常: thread_id={thread_id}")
        progress_bus.publish(thread_id, {"event": "error", "data": {"message": str(e)}})
        progress_bus.publish(thread_id, {"event": "done", "data": ""})
    finally:
        # 延迟清理，让 SSE 客户端有时间读取；事件日志保留一段时间供重连补齐
        await asyncio.sleep(2)
        active_tasks.discard(thread_id)
        task_started_at.pop(thread_id, None)
        task_meta.pop(thread_id, None)


async def _finalize_stream(graph: Any, config: dict, thread_id: str) -> None:
    """图流结束后的收尾：区分「等待人工审核 / 失败 / 真正完成」

    update_state 审核模式下，reviewer 之后图会正常 END；此时通过
    aget_state 检查最终阶段：
    - reviewing：不推送 completed，仅结束 SSE
    - failed：推送 phase=failed（禁止伪装成 completed）
    - 其他：completed
    """
    snap = await graph.aget_state(config)
    final_phase = (snap.values or {}).get("current_phase", "") if snap else ""
    if final_phase == "reviewing":
        # interrupt 审核事件已在 _handle_update_event 中推送
        progress_bus.publish(thread_id, {"event": "done", "data": ""})
    elif final_phase == "failed":
        progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": "failed"}})
        progress_bus.publish(thread_id, {"event": "done", "data": ""})
    else:
        progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": "completed"}})
        progress_bus.publish(thread_id, {"event": "done", "data": ""})


async def _handle_update_event(
    data: dict[str, Any],
    thread_id: str,
) -> None:
    """处理 stream_mode='updates' 的事件"""
    for node_name, state_update in data.items():
        if not isinstance(state_update, dict):
            continue

        # 阶段事件：优先用节点写入的 current_phase（含 failed），避免线性边把失败点亮成 reviewing/completed
        node_phase = NODE_PHASE_MAP.get(node_name)
        emitted_phase = state_update.get("current_phase") or ""
        if emitted_phase == "failed":
            progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": "failed"}})
            progress_bus.publish(thread_id, {
                "event": "error",
                "data": {
                    "message": state_update.get("report_draft", "")
                    or "任务失败（检索或生成未完成）",
                },
            })
        elif emitted_phase and emitted_phase not in ("", "init"):
            progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": emitted_phase}})
        elif node_phase:
            progress_bus.publish(thread_id, {"event": "phase", "data": {"phase": node_phase}})

        # 审核等待：reviewer 完成后图正常 END，推送审核请求
        # （update_state 审核模式，前端协议沿用 interrupt 事件）
        if node_name == "reviewer" and state_update.get("current_phase") == "reviewing":
            progress_bus.publish(thread_id, {
                "event": "interrupt",
                "data": {
                    "thread_id": thread_id,
                    "report_draft": state_update.get("final_report", ""),
                    "message": "请审核综述草稿，输入修改意见或输入 '通过' 通过审核。",
                    "revision_count": state_update.get("revision_count", 0),
                    "max_revisions": state_update.get("max_revisions", 3),
                },
            })

        # 发送进度信息（中间输出）
        current_phase = state_update.get("current_phase", "")
        if current_phase and current_phase != "failed":
            progress_msg = _build_progress_message(node_name, current_phase, state_update)
            if progress_msg:
                progress_bus.publish(thread_id, {"event": "progress", "data": {"message": progress_msg}})

        # 检查是否完成（最终报告）
        final_report = state_update.get("final_report", "")
        if final_report and current_phase == "completed":
            progress_bus.publish(thread_id, {
                "event": "complete",
                "data": {
                    "report": final_report,
                    "references": state_update.get("references") or [],
                    "charts": state_update.get("charts") or [],
                    "quality_metrics": state_update.get("quality_metrics") or {},
                },
            })


def _handle_message_event(
    data: tuple,
    thread_id: str,
) -> None:
    """处理 stream_mode='messages' 的事件 — LLM token 流（仅实时扇出，不进日志）"""
    if not isinstance(data, tuple) or len(data) < 1:
        return

    chunk = data[0]
    # LangChain message chunk 有 content 属性
    content = ""
    if hasattr(chunk, "content"):
        content = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
    elif isinstance(chunk, dict):
        content = chunk.get("content", "")

    if content:
        progress_bus.publish(thread_id, {"event": "token", "data": {"content": content}})


def _build_progress_message(
    node_name: str,
    current_phase: str,
    state_update: dict[str, Any],
) -> str:
    """根据节点和阶段构建进度消息"""
    messages = {
        "init": "正在初始化研究任务...",
        "searcher": "搜索员正在搜索相关资料...",
        "analyst": "分析师正在分析数据...",
        "writer": "撰稿人正在撰写报告...",
        "reviewer": "等待人工审核...",
    }
    return messages.get(node_name, "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/research/{thread_id}/stream — SSE 流式推送
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/research/{thread_id}/progress")
async def get_task_progress(thread_id: str, limit: int = 50):
    """任务进度历史（内存事件日志），供刷新/重连后补齐日志

    返回 upto_seq：客户端应带 ?since=upto_seq 连 /stream，只重放其后事件。
    """
    from backend.utils.progress import get_progress_snapshot

    messages, upto_seq = get_progress_snapshot(thread_id, limit=limit)
    return {
        "thread_id": thread_id,
        "messages": messages,
        "started_at": float(task_started_at.get(thread_id) or 0),
        "upto_seq": upto_seq,
    }


@router.get("/research/{thread_id}/stream")
async def stream_research(thread_id: str, since: int = 0):
    """SSE 流式推送研究进度（多订阅者 + 断线重放）

    - 每个连接独立订阅队列：多标签页互不抢事件
    - 先重放事件日志中 since 之后的事件，再持续推送新事件
    - 任务已结束（不在内存执行）时：日志里有 done 终止事件才服务，
      重放完毕即关闭；否则 404（前端走 resume/回查降级）
    """
    is_active = thread_id in active_tasks
    if not is_active and not progress_bus.has_terminal_event(thread_id):
        raise HTTPException(status_code=404, detail="Task not found or already completed")

    queue, replay = progress_bus.subscribe(thread_id, since=since)

    def _fmt(event: dict) -> str:
        event_data = event.get("data", "")
        if isinstance(event_data, dict):
            data_str = json.dumps(event_data, ensure_ascii=False)
        else:
            data_str = str(event_data)
        return f"event: {event.get('event', '')}\ndata: {data_str}\n\n"

    async def event_generator():
        try:
            for event in replay:
                yield _fmt(event)
                if event.get("event") == "done":
                    return
            if not is_active:
                # 任务已结束且重放中无 done（since 已越过终止事件）：直接关闭
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=2)
                except asyncio.TimeoutError:
                    # 心跳：2s 一次，驱动前端计时近似每秒刷新，并防代理断连
                    yield ": heartbeat\n\n"
                    continue

                if event.get("event") == "done":
                    break

                yield _fmt(event)
        except asyncio.CancelledError:
            logger.info(f"SSE 连接已断开: thread_id={thread_id}")
        finally:
            progress_bus.unsubscribe(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/research/{thread_id}/review — 提交人工审核
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.post("/research/{thread_id}/review", response_model=ReviewResponse)
async def submit_review(request: Request, thread_id: str, body: ReviewRequest):
    """提交人工审核结果（update_state 审核模式）

    - action=approve（或旧文本"通过"）：注入 current_phase="completed"，条件边判定图结束
    - action=revise：注入 review_feedback / current_phase="writing"，writer 以
      上一版草稿为底稿分节修订，SSE 实时推送修改进度
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snap = await graph.aget_state(config)
    except Exception as e:
        logger.exception(f"读取任务状态失败: thread_id={thread_id}")
        raise HTTPException(status_code=500, detail=str(e))

    if snap is None or not snap.values:
        raise HTTPException(status_code=404, detail="Task not found")

    values = snap.values
    phase = values.get("current_phase")
    if phase == "failed":
        raise HTTPException(status_code=400, detail="任务已失败，无法审核；请删除后重新提交研究")
    if phase not in ("reviewing", "writing"):
        raise HTTPException(status_code=400, detail="当前状态不可审核（任务未就绪或已完成）")

    feedback = body.feedback.strip()
    action = (body.action or "").strip().lower()
    if not action:
        # 兼容旧客户端：未显式传 action 时按文本判断（新前端一律显式传 action）
        action = (
            "approve"
            if feedback.lower() in ["通过", "approve", "approved", "ok", "good", ""]
            else "revise"
        )

    if action == "approve":
        await graph.aupdate_state(
            config,
            {"current_phase": "completed", "review_feedback": None},
            as_node="reviewer",
        )
        return ReviewResponse(thread_id=thread_id, status="approved", message="报告已审核通过")

    if not feedback:
        raise HTTPException(status_code=400, detail="返工需要填写修改意见")

    revision_count = values.get("revision_count", 0)
    max_revisions = values.get("max_revisions", 3)
    if revision_count >= max_revisions:
        return ReviewResponse(
            thread_id=thread_id,
            status="approved",
            message=f"已达最大返工次数（{max_revisions}），请直接使用当前版本",
        )

    await graph.aupdate_state(
        config,
        {
            "review_feedback": feedback,
            "current_phase": "writing",
            "revision_count": revision_count + 1,
        },
        as_node="reviewer",
    )

    # 后台从断点继续执行（不阻塞 HTTP 响应）
    active_tasks.add(thread_id)
    task_started_at.setdefault(thread_id, time.time())
    asyncio.create_task(
        _resume_and_stream(graph, thread_id, config),
        name=f"review-{thread_id}",
    )

    return ReviewResponse(thread_id=thread_id, status="revising", message="报告正在修改中，请查看实时进度")


@router.post("/research/{thread_id}/resume", response_model=ReviewResponse)
async def resume_interrupted_task(request: Request, thread_id: str):
    """复活中断的任务（服务重启导致 SSE 队列丢失的僵尸状态）

    checkpoint 中存有断点：重新挂进度队列并 astream(None) 从断点续跑。
    仅对“运行中但无活跃队列”的任务生效；已完成/审核中的任务不受影响。
    前端在 SSE 404 时自动调用，对用户透明。
    """
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        snap = await graph.aget_state(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if snap is None or not snap.values:
        raise HTTPException(status_code=404, detail="Task not found")

    status = str(snap.values.get("current_phase", ""))
    if thread_id in active_tasks:
        return ReviewResponse(thread_id=thread_id, status=status or "running", message="任务已在运行中")
    if status not in ("initializing", "searching", "analyzing", "writing"):
        return ReviewResponse(thread_id=thread_id, status=status, message="任务不在可恢复的运行状态")

    active_tasks.add(thread_id)
    task_started_at.setdefault(thread_id, time.time())
    asyncio.create_task(
        _resume_and_stream(graph, thread_id, config),
        name=f"resume-{thread_id}",
    )
    logger.info(f"复活中断任务: thread_id={thread_id}, phase={status}")
    return ReviewResponse(thread_id=thread_id, status="resumed", message="任务已从断点恢复执行")


async def _resume_and_stream(
    graph: Any,
    thread_id: str,
    config: dict,
) -> None:
    """后台从断点继续执行图并经 progress_bus 发布事件

    update_state 审核模式下使用 astream(None) 从上次结束的位置继续，
    复用与 _run_graph 相同的事件解析和发布逻辑。
    """
    try:
        async for event in graph.astream(None, config=config, stream_mode=["updates", "messages"]):
            # astream 在 stream_mode=list 时返回 tuple: (mode, data)
            if not isinstance(event, tuple) or len(event) != 2:
                continue

            mode, data = event

            if mode == "updates":
                await _handle_update_event(data, thread_id)

            elif mode == "messages":
                _handle_message_event(data, thread_id)

        # 图执行完毕：返工后再次进入等待审核或完成
        await _finalize_stream(graph, config, thread_id)

    except Exception as e:
        logger.exception(f"图恢复执行异常: thread_id={thread_id}")
        progress_bus.publish(thread_id, {"event": "error", "data": {"message": str(e)}})
        progress_bus.publish(thread_id, {"event": "done", "data": ""})
    finally:
        # 延迟清理，让 SSE 客户端有时间读取；事件日志保留一段时间供重连补齐
        await asyncio.sleep(2)
        active_tasks.discard(thread_id)
        task_started_at.pop(thread_id, None)
        task_meta.pop(thread_id, None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/research/{thread_id}/report — 获取最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/research/{thread_id}/report", response_model=ReportResponse)
async def get_report(request: Request, thread_id: str):
    """从 checkpointer 获取最终状态并返回报告"""
    graph = _get_graph(request)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = await graph.aget_state(config)

        if state is None or not state.values:
            raise HTTPException(status_code=404, detail="Task not found")

        values = state.values
        final_report = values.get("final_report", "") or values.get("report_draft", "")
        topic = values.get("topic", "")
        current_phase = values.get("current_phase", "")

        if not final_report and current_phase != "failed":
            raise HTTPException(status_code=404, detail="Report not ready yet")

        if not final_report and current_phase == "failed":
            final_report = f"# {topic}\n\n> 任务失败"

        return ReportResponse(
            thread_id=thread_id,
            topic=topic,
            report=final_report,
            status=current_phase,
            references=values.get("references", []),
            charts=values.get("charts", []),
            quality_metrics=values.get("quality_metrics") or {},
            revision_count=int(values.get("revision_count") or 0),
            max_revisions=int(values.get("max_revisions") or 3),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取报告失败: thread_id={thread_id}")
        raise HTTPException(status_code=500, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/models — 可用模型列表（供前端模型选择框）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/models", response_model=AvailableModelsResponse)
async def list_available_models():
    """返回服务端可用模型白名单及默认模型"""
    return AvailableModelsResponse(
        models=settings.get_available_models(),
        default=settings.openai_model,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  管理接口 — 口令保护的在线配置（Key 热更新 + 持久化到 .env）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/admin/status", response_model=AdminStatusResponse)
async def admin_status():
    """查询配置状态（不返回任何密钥明文）"""
    return AdminStatusResponse(
        admin_enabled=bool(settings.admin_password),
        openai_key_set=bool(settings.openai_api_key),
        tavily_key_set=bool(settings.tavily_api_key),
        openai_base_url=settings.openai_base_url,
        model_name=settings.openai_model,
    )


@router.post("/admin/config", response_model=AdminConfigResponse)
async def update_admin_config(body: AdminConfigRequest):
    """更新 API 配置（口令保护，进程内即时生效并持久化到 .env）

    - 未设置 ADMIN_PASSWORD 时功能禁用（403）
    - 口令错误返回 401，使用 compare_digest 防时序攻击
    - 更新同步到三处：settings 属性（新任务即时生效）、
      os.environ（模型专属配置回退链）、.env 文件（重启后仍生效）
    """
    if not settings.admin_password:
        raise HTTPException(
            status_code=403,
            detail="在线配置功能未启用（服务器未设置 ADMIN_PASSWORD）",
        )
    if not secrets.compare_digest(body.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="管理员口令错误")

    env_updates: dict[str, str] = {}
    if body.openai_api_key:
        settings.openai_api_key = body.openai_api_key
        os.environ["OPENAI_API_KEY"] = body.openai_api_key
        env_updates["OPENAI_API_KEY"] = body.openai_api_key
    if body.openai_base_url:
        settings.openai_base_url = body.openai_base_url
        os.environ["OPENAI_BASE_URL"] = body.openai_base_url
        env_updates["OPENAI_BASE_URL"] = body.openai_base_url
    if body.openai_model:
        settings.openai_model = body.openai_model
        os.environ["OPENAI_MODEL"] = body.openai_model
        env_updates["OPENAI_MODEL"] = body.openai_model
    if body.tavily_api_key:
        settings.tavily_api_key = body.tavily_api_key
        os.environ["TAVILY_API_KEY"] = body.tavily_api_key
        reload_tavily_client()  # 重建 Tavily 客户端使新 Key 生效
        env_updates["TAVILY_API_KEY"] = body.tavily_api_key

    updated: list[str] = []
    if env_updates:
        update_env_file(env_updates)
        updated = list(env_updates.keys())

    logger.info(f"管理员已更新配置项: {updated}")
    return AdminConfigResponse(
        message=(f"已更新 {len(updated)} 项配置并即时生效" if updated else "没有需要更新的配置项"),
        updated=updated,
    )


def _require_admin(password: str) -> None:
    """管理员口令校验：未启用 403，口令错误 401（compare_digest 防时序攻击）"""
    if not settings.admin_password:
        raise HTTPException(
            status_code=403,
            detail="在线配置功能未启用（服务器未设置 ADMIN_PASSWORD）",
        )
    if not secrets.compare_digest(password, settings.admin_password):
        raise HTTPException(status_code=401, detail="管理员口令错误")


def _resolve_admin_llm_params(body: AdminTestRequest) -> tuple[str, str]:
    """解析测试用 LLM 参数：请求携带值优先，否则回退当前已保存配置"""
    api_key = body.openai_api_key or settings.openai_api_key
    base_url = body.openai_base_url or settings.openai_base_url or None
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY 未配置（请填写或先保存配置）")
    return api_key, base_url


@router.post("/admin/list-models", response_model=AdminModelsResponse)
async def admin_list_models(body: AdminTestRequest):
    """获取 OpenAI 兼容接口的可用模型列表（口令保护）

    调用接口的标准 GET /models 端点，帮助管理员确认该接口
    实际支持哪些模型名，避免因模型名不存在导致任务失败。
    """
    _require_admin(body.password)
    api_key, base_url = _resolve_admin_llm_params(body)
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=15)
        resp = await client.models.list()
        models = sorted(m.id for m in resp.data)
        return AdminModelsResponse(models=models)
    except Exception as e:
        return AdminModelsResponse(error=str(e))


@router.post("/admin/test-model", response_model=AdminTestResponse)
async def admin_test_model(body: AdminTestRequest):
    """测试模型连通性（口令保护）

    用给定配置真实发送一次最小 chat 调用（max_tokens=8），
    验证 Key / Base URL / 模型名三者组合是否可用。
    """
    _require_admin(body.password)
    api_key, base_url = _resolve_admin_llm_params(body)
    model = body.openai_model or settings.openai_model
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=20)
        t0 = time.monotonic()
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        return AdminTestResponse(
            ok=True,
            message=f"模型 {model} 连接成功，耗时 {latency_ms}ms",
            latency_ms=latency_ms,
        )
    except Exception as e:
        return AdminTestResponse(ok=False, message=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/research/history — 历史任务列表（持久化于 checkpoints.db）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def _load_history_threads(limit: int) -> list[tuple[str, str]]:
    """从 checkpoints.db 读取最近任务（thread_id, 最新 checkpoint_id）

    langgraph-checkpoint 4.x 的表结构为 checkpoints 单表（无独立 threads 表）；
    checkpoint_id 为 UUIDv6（时间有序），MAX+ORDER BY 即按最近活动排序。
    """
    import aiosqlite

    from backend.graph.checkpointer import DB_PATH

    rows: list[tuple[str, str]] = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints "
            "GROUP BY thread_id ORDER BY MAX(checkpoint_id) DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return rows


@router.get("/research/history")
async def list_history(request: Request, limit: int = 20):
    """列出最近的历史任务（checkpointer 持久化的全部任务，刷新/退出不丢失）

    从 checkpoints.db 读取线程列表，返回 topic / 状态 / 更新时间，
    前端点击可恢复查看报告或继续审核。
    """
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")

    try:
        rows = await _load_history_threads(limit)
    except Exception as e:
        logger.exception("读取历史任务列表失败")
        raise HTTPException(status_code=500, detail=str(e))

    # 逐个取任务状态（topic / current_phase）
    items: list[HistoryItem] = []
    from backend.utils.checkpoint_time import format_checkpoint_time

    for tid, ts in rows:
        try:
            snap = await graph.aget_state({"configurable": {"thread_id": tid}})
            values = (snap.values or {}) if snap else {}
            if not values:
                continue
            items.append(HistoryItem(
                thread_id=tid,
                topic=str(values.get("topic", ""))[:60],
                status=str(values.get("current_phase", "")),
                updated_at=format_checkpoint_time(str(ts)),
                elapsed_sec=int(time.time() - task_started_at[tid]) if tid in task_started_at else 0,
            ))
        except Exception:
            continue

    return items


@router.get("/research/running", response_model=list[RunningTaskItem])
async def list_running_tasks(request: Request):
    """当前仍在内存中执行的任务（侧边栏「进行中」）

    phase 从 checkpoint 读取（节点边界粒度），前端恢复视图时据此点亮
    正确阶段，而不是一律当作 searching。
    """
    graph = getattr(request.app.state, "graph", None)
    running: list[RunningTaskItem] = []
    now = time.time()
    for tid in list(active_tasks):
        started = task_started_at.get(tid)
        meta = task_meta.get(tid) or {}
        phase = ""
        if graph is not None:
            try:
                snap = await graph.aget_state({"configurable": {"thread_id": tid}})
                phase = str(((snap.values or {}) if snap else {}).get("current_phase") or "")
            except Exception:
                phase = ""
        running.append(
            RunningTaskItem(
                thread_id=tid,
                topic=str(meta.get("topic") or "")[:60],
                status="running",
                phase=phase,
                elapsed_sec=int(now - started) if started else 0,
                started_at=float(started or 0.0),
            )
        )
    return running


async def _delete_thread_from_checkpoints(thread_id: str) -> int:
    """从 checkpoints.db 删除指定 thread 的全部持久化记录，返回删除行数"""
    import aiosqlite

    from backend.graph.checkpointer import DB_PATH

    deleted = 0
    async with aiosqlite.connect(DB_PATH) as db:
        # 动态发现带 thread_id 列的表，兼容不同 langgraph-checkpoint 版本
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = [r[0] for r in await cur.fetchall()]

        for table in tables:
            try:
                async with db.execute(f"PRAGMA table_info({table})") as cur:
                    cols = [r[1] for r in await cur.fetchall()]
            except Exception:
                continue
            if "thread_id" not in cols:
                continue
            try:
                async with db.execute(
                    f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,)
                ) as cur:
                    deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            except Exception as e:
                logger.warning(f"删除表 {table} 中 thread {thread_id} 失败: {e}")

        await db.commit()
    return deleted


@router.delete("/research/{thread_id}", response_model=DeleteResponse)
async def delete_research(thread_id: str, request: Request):
    """手动删除研究报告 / 历史任务（含 checkpoints 持久化数据）

    用于前端历史列表的删除按钮；正在运行的任务会先从活跃队列摘除。
    """
    if not thread_id or len(thread_id) > 128:
        raise HTTPException(status_code=400, detail="无效的 thread_id")

    # 从活跃任务摘除（运行中任务删除后不再推送）
    active_tasks.discard(thread_id)
    try:
        progress_bus.clear_progress(thread_id)
    except Exception:
        pass

    try:
        deleted = await _delete_thread_from_checkpoints(thread_id)
    except Exception as e:
        logger.exception(f"删除任务 {thread_id} 失败")
        raise HTTPException(status_code=500, detail=str(e))

    if deleted <= 0:
        # 可能本来就没有记录，仍返回成功，避免前端二次确认困扰
        return DeleteResponse(
            thread_id=thread_id,
            deleted=True,
            message="任务不存在或已删除",
        )

    logger.info(f"已删除研究任务 {thread_id}，清理 {deleted} 行持久化数据")
    return DeleteResponse(
        thread_id=thread_id,
        deleted=True,
        message=f"已删除（清理 {deleted} 条记录）",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/health — 健康检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse()


@router.get("/dependencies", response_model=DependenciesResponse)
async def get_dependencies():
    """外部依赖状态（前端侧边栏依赖面板；不含密钥明文）"""
    tavily_raw = (settings.tavily_api_key or "").strip()
    placeholder = (
        not tavily_raw
        or tavily_raw.startswith("your-")
        or tavily_raw == "your-tavily-api-key-here"
    )

    # 探测本地 SearXNG（用 / 首页探活；完整 /search 会等上游引擎，太慢）
    searx_url = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/")
    searx_ok = False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(searx_url + "/")
            searx_ok = r.status_code == 200 and ("searx" in r.text.lower() or "SearXNG" in r.text)
    except Exception:
        searx_ok = False

    return DependenciesResponse(
        backend_ok=True,
        llm_key_set=bool((settings.openai_api_key or "").strip()),
        llm_base_url=settings.openai_base_url or "",
        llm_model=settings.openai_model or "",
        tavily_key_set=bool(tavily_raw) and not placeholder,
        tavily_key_placeholder=placeholder,
        arxiv_enabled=True,
        duckduckgo_enabled=True,
        wikipedia_enabled=True,
        semantic_scholar_enabled=True,
        openalex_enabled=True,
        crossref_enabled=True,
        europepmc_enabled=True,
        core_enabled=True,
        searxng_url=searx_url,
        searxng_reachable=searx_ok,
    )
