"""Supervisor Agent - 任务分发与结果聚合

Supervisor 是整个流程的编排中心，负责：
- 根据当前 state 的 current_phase 决定下一步路由
- 汇总各 Worker 的输出，传递给下一环节

实现方式：基于固定线性流程，通过 current_phase 字段追踪状态，
而非使用 LLM 做动态路由决策。这样更可靠、更高效。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def supervisor_router(state: dict[str, Any]) -> str:
    """Supervisor 路由函数 - 根据当前阶段决定下一步

    根据 state 中的 current_phase 字段，返回下一个要执行的节点名称。
    该函数可用作 LangGraph 的条件边路由函数。

    注意：当前系统使用固定线性流程，此路由函数暂未在图中直接使用，
    保留作为未来动态路由扩展的预留接口。

    Args:
        state: 全局 AgentState

    Returns:
        下一个节点名称（searcher / analyst / writer / reviewer / __end__）
    """
    phase = state.get("current_phase", "init")

    if phase == "init" or phase == "searching":
        return "searcher"
    elif phase == "analyzing":
        return "analyst"
    elif phase == "writing":
        return "writer"
    elif phase == "reviewing":
        return "reviewer"
    elif phase == "completed":
        return "__end__"
    elif phase == "failed":
        return "__end__"
    else:
        logger.warning(f"未知阶段: {phase}，默认进入搜索")
        return "searcher"


def should_continue_or_end(state: dict[str, Any]) -> str:
    """Reviewer 之后的路由：等待人工审核 → END，收到返工指示 → writer

    状态约定（配合 update_state 审核模式，替代 langgraph interrupt——
    后者在 Python 3.10 的 async 图执行中 contextvar 无法传播）：
    1. current_phase == "writing" 且未超返工上限 → "revise"（回 writer 修改）
    2. 其他（"reviewing" 等待审核 / "completed" 已通过 / 超过上限）→ "completed"（END）

    Args:
        state: 全局 AgentState

    Returns:
        "completed" 表示结束，"revise" 表示返工回 writer
    """
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 3)

    if state.get("current_phase") == "failed":
        return "completed"

    if state.get("current_phase") == "writing":
        if revision_count >= max_revisions:
            logger.warning(f"已达到最大修改次数 ({max_revisions})，强制结束")
            return "completed"
        logger.info(f"审核不通过，需要返工（第 {revision_count} 次修改）")
        return "revise"

    return "completed"
