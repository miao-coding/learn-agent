"""定义多智能体协作系统的全局状态"""
from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """全局 Agent 状态

    流程: START -> searcher -> analyst -> writer -> reviewer -> END / 返工
    """

    # ── 消息列表（LangGraph 累加器模式） ──────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── 研究主题（用户输入） ──────────────────────────────────────
    topic: str

    # ── 用户自选模型名（空串表示使用服务端默认模型） ──
    model_name: str

    # ── 当前阶段标识 ─────────────────────────────────────────────
    # init / searching / analyzing / writing / reviewing / completed / failed
    current_phase: str

    # ── 搜索员的输出：结构化搜索结果（含来源 URL） ────────────────
    search_results: list[dict[str, Any]]

    # ── 分析师的输出：提取的关键数据 ──────────────────────────────
    analysis_data: dict[str, Any]

    # ── 撰稿人的输出：报告草稿（Markdown 格式） ───────────────────
    report_draft: str

    # ── 人工审核反馈（通过时为 None，不通过时为修改意见） ──────────
    review_feedback: str | None

    # ── 最终报告 ─────────────────────────────────────────────────
    final_report: str

    # ── 重试计数器（自修正闭环，最多 3 次） ──────────────────────
    revision_count: int

    # ── 最大重试次数 ─────────────────────────────────────────────
    max_revisions: int

    # ── 文献引用列表 ─────────────────────────────────────────────
    references: list[dict[str, Any]]

    # ── 生成的图表路径列表 ───────────────────────────────────────
    charts: list[str]

    # ── 质量评分（Supervisor 门禁 / 日志，可选） ─────────────────
    quality_metrics: dict[str, Any]

    # ── 用户上传文献种子（可选） ────────────────────────────────
    uploaded_docs: list[dict[str, Any]]
