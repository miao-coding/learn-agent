"""StateGraph 构建器 — 定义多智能体协作的完整图拓扑

拓扑结构:
    START → init → searcher → analyst → writer → reviewer ─┬→ END（审核通过 / 超过重试上限）
                                                              └→ writer（审核不通过，自修正闭环）
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.analyst import analyst_agent
from backend.agents.searcher import searcher_agent
from backend.agents.supervisor import should_continue_or_end
from backend.agents.writer import writer_agent
from backend.graph.state import AgentState

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  初始化节点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def init_node(state: AgentState) -> dict[str, Any]:
    """初始化节点 - 设置初始状态

    从用户输入提取研究主题，初始化各字段，
    将 current_phase 设为 "searching" 以启动流程。

    Args:
        state: 全局 AgentState，topic 字段由用户输入提供

    Returns:
        初始化后的状态更新字典
    """
    topic = state.get("topic", "未命名研究主题")
    logger.info(f"初始化研究任务: {topic}")

    return {
        "topic": topic,
        "model_name": state.get("model_name", ""),
        "current_phase": "searching",
        "search_results": [],
        "analysis_data": {},
        "report_draft": "",
        "review_feedback": None,
        "final_report": "",
        "revision_count": 0,
        "max_revisions": 3,
        "references": [],
        "charts": [],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审核节点（人工审核 / HITL）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def reviewer_node(state: AgentState) -> dict[str, Any]:
    """审核节点 - 同步草稿到 final_report，进入等待人工审核状态

    审核采用 update_state 模式（替代 langgraph interrupt——后者依赖
    contextvar 传播，在 Python 3.10 的 async 图执行中无法工作，会抛
    RuntimeError: Called get_config outside of a runnable context）：

    1. 本节点把 report_draft 同步到 final_report，current_phase 置为
       "reviewing"，随后条件边判定 END，图正常结束（前端展示草稿等待审核）
    2. 用户提交审核后，API 层通过 graph.aupdate_state(as_node="reviewer")
       注入审核结果，并从断点继续执行：
       - 通过：current_phase="completed" → 条件边 END
       - 返工：current_phase="writing" + review_feedback → 条件边回 writer

    Args:
        state: 全局 AgentState，包含 report_draft 供审核

    Returns:
        状态更新字典，由 should_continue_or_end 条件边决定下一步
    """
    report_draft = state.get("report_draft", "")
    phase = state.get("current_phase", "")
    # 失败终态：不进入人工审核
    if phase == "failed":
        logger.info("任务处于 failed，跳过人工审核")
        return {
            "final_report": report_draft,
            "current_phase": "failed",
        }

    logger.info("草稿已生成，进入等待人工审核状态")

    return {
        "final_report": report_draft,
        "current_phase": "reviewing",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  图构建函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_graph(checkpointer=None):
    """构建并编译多智能体协作图。

    图的拓扑结构:
        START → init → searcher → analyst → writer → reviewer ─┬→ END
                                                                 └→ writer

    Args:
        checkpointer: AsyncSqliteSaver 实例，用于状态持久化。
            通过 ``async with get_checkpointer() as cp`` 获取。
            传 None 则不启用持久化。

    Returns:
        编译后的 LangGraph 图对象，可通过 ``await graph.ainvoke(...)`` 调用。
    """
    # 1. 创建 StateGraph
    builder = StateGraph(AgentState)

    # 2. 添加节点
    builder.add_node("init", init_node)
    builder.add_node("searcher", searcher_agent)
    builder.add_node("analyst", analyst_agent)
    builder.add_node("writer", writer_agent)
    builder.add_node("reviewer", reviewer_node)

    # 3. 设置边 — 线性流水线部分
    builder.add_edge(START, "init")          # START → 初始化
    builder.add_edge("init", "searcher")     # 初始化 → 搜索员
    builder.add_edge("searcher", "analyst")  # 搜索员 → 分析师
    builder.add_edge("analyst", "writer")    # 分析师 → 撰稿人
    builder.add_edge("writer", "reviewer")   # 撰稿人 → 审核员

    # 4. reviewer 之后的条件边
    #    should_continue_or_end 返回 "completed" → END
    #    should_continue_or_end 返回 "revise"   → writer（返工）
    builder.add_conditional_edges(
        "reviewer",
        should_continue_or_end,
        {
            "completed": END,
            "revise": "writer",
        },
    )

    # 5. 编译图（附加 checkpointer 实现状态持久化）
    graph = builder.compile(checkpointer=checkpointer)
    logger.info("研究图构建并编译完成")

    return graph
