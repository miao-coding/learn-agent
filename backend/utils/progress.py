"""Agent 进度事件总线 — 让 Agent 节点内部能向前端 SSE 推送细粒度进度

- report_progress() → 推到该任务的 SSE 队列
- 同时写入内存 ring buffer，前端断开/刷新后可 GET /progress 补齐历史
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

logger = logging.getLogger(__name__)

# thread_id → asyncio.Queue（与 routes.active_tasks 指向同一队列）
_queues: dict[str, asyncio.Queue] = {}

# thread_id → 最近进度消息（ring buffer，供断线重连时拉取）
_buffers: dict[str, deque] = {}
_BUFFER_MAX = 80


def register(thread_id: str, queue: asyncio.Queue) -> None:
    """注册任务的进度队列（任务启动时由 API 层调用）"""
    _queues[thread_id] = queue
    _buffers.setdefault(thread_id, deque(maxlen=_BUFFER_MAX))


def unregister(thread_id: str) -> None:
    """注销 SSE 队列（任务结束时调用，幂等）

    进度缓冲保留一段时间，便于前端在任务刚结束时仍能拉到日志。
    """
    _queues.pop(thread_id, None)


def get_progress_messages(thread_id: str, limit: int = 50) -> list[str]:
    """读取该任务的进度历史（用于刷新/重连后补齐日志）"""
    buf = _buffers.get(thread_id)
    if not buf:
        return []
    return list(buf)[-max(1, min(limit, _BUFFER_MAX)) :]


def clear_progress(thread_id: str) -> None:
    """删除任务时清掉缓冲"""
    _buffers.pop(thread_id, None)
    _queues.pop(thread_id, None)


async def report_progress(config: dict | None, message: str) -> None:
    """Agent 节点内推送进度消息到前端（失败静默，不影响主流程）"""
    try:
        if not config:
            return
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if not thread_id:
            return
        # 始终记入缓冲（即使 SSE 队列尚未注册）
        buf = _buffers.setdefault(thread_id, deque(maxlen=_BUFFER_MAX))
        buf.append(str(message))
        queue = _queues.get(thread_id)
        if queue is not None:
            await queue.put({"event": "progress", "data": {"message": message}})
    except Exception:
        logger.debug("report_progress 失败（忽略）", exc_info=True)
