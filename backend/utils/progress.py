"""Agent 进度事件总线 — 让 Agent 节点内部能向前端 SSE 推送细粒度进度

解决"检索阶段长时间静默、用户不知道系统是否在运行"的体验问题：
Agent 节点（如检索员的工具调用循环）通过 report_progress() 推送
工具级进度消息，经全局队列注册表路由到对应任务的 SSE 流。
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# thread_id → asyncio.Queue（与 routes.active_tasks 指向同一队列）
_queues: dict[str, asyncio.Queue] = {}


def register(thread_id: str, queue: asyncio.Queue) -> None:
    """注册任务的进度队列（任务启动时由 API 层调用）"""
    _queues[thread_id] = queue


def unregister(thread_id: str) -> None:
    """注销任务的进度队列（任务结束时调用，幂等）"""
    _queues.pop(thread_id, None)


async def report_progress(config: dict | None, message: str) -> None:
    """Agent 节点内推送进度消息到前端（失败静默，不影响主流程）

    Args:
        config: LangGraph 节点收到的 config，从中提取 thread_id；
            None 或未注册的任务直接忽略（便于测试与独立调用）
        message: 人类可读的进度描述
    """
    try:
        if not config:
            return
        thread_id = (config.get("configurable") or {}).get("thread_id")
        queue = _queues.get(thread_id)
        if queue is not None:
            await queue.put({"event": "progress", "data": {"message": message}})
    except Exception:
        logger.debug("report_progress 失败（忽略）", exc_info=True)
