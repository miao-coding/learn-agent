"""撰稿人 Agent - 将分析数据整合成结构化 Markdown 文献综述

撰稿人接收分析师的结构化数据，结合研究方向，
使用 LLM 撰写结构完整、引用规范的学术文献综述报告（Markdown 格式）。
支持根据审核反馈进行针对性修改。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.tools.rag import rag_search

logger = logging.getLogger(__name__)

# ── 撰稿人系统提示词 ─────────────────────────────────────────────
WRITER_SYSTEM_PROMPT = """你是一个专业的学术综述撰稿人。你的任务是根据分析师提供的数据，撰写一份结构完整、引用规范的文献综述报告（Markdown 格式）。

报告结构要求：

1. **摘要（Abstract）** — 200-300字，概括综述范围、主要方法脉络与核心结论
2. **引言（Introduction）** — 研究背景与意义、综述的范围界定、文献来源说明
3. **研究现状与分类（Taxonomy）** — 按方法/技术路线分类梳理现有工作，阐述各类原理与代表工作
4. **方法对比与分析（Comparison）** — 使用 Markdown 表格对比各方法的性能指标、优缺点，结合图表深入分析
5. **挑战与研究空白（Challenges & Gaps）** — 现有工作的局限性、尚未解决的问题
6. **总结与展望（Conclusion）** — 领域发展趋势、值得关注的未来方向
7. **参考文献（References）** — 所有引用来源的完整列表

引用格式要求：
- 正文中所有论断、数据、观点必须使用 [数字] 标注引用来源
- 引用编号与分析师提供的引用编号对应
- 报告末尾的参考文献列表按编号排列，包含文献标题和URL
- 严格依据提供的引用来源撰写，不得编造不存在的文献
- 示例：Transformer 架构自提出以来已成为该领域的主流方法 [1]。

写作要求：
- 学术综述风格，客观、严谨、以文献为依据
- 明确区分领域内的“共识”与“争议”，对矛盾结果并列呈现不同文献的观点
- 使用 Markdown 格式
- 报告长度 2500-5000 字
- 合理使用表格与图表（分析师生成的图表路径）展示对比数据
- 如果有修改意见，请针对性修改并确保质量提升

RAG 检索能力：你可以使用 rag_search 工具从向量数据库中检索相关文档片段。
当你需要核实某个论断的文献依据、补充引用细节时，主动调用 rag_search 获取最相关的信息。"""


async def writer_agent(state: dict) -> dict[str, Any]:
    """撰稿人节点 - 基于分析数据撰写/修改报告

    流程：
    1. 从 state 获取 analysis_data、topic、review_feedback
    2. 构建 prompt（包含分析数据和可能的修改意见）
    3. 调用 LLM 生成/修改报告
    4. 更新 report_draft 和 current_phase

    Args:
        state: AgentState 字典，包含 analysis_data、topic，可选 review_feedback

    Returns:
        包含 report_draft、current_phase、messages 的状态更新字典
    """
    topic = state["topic"]
    analysis_data = state.get("analysis_data", {})
    review_feedback = state.get("review_feedback")
    references = state.get("references", [])
    logger.info(f"撰稿人开始工作，主题: {topic}")

    if review_feedback:
        logger.info(f"撰稿人收到修改意见: {review_feedback}")

    # ── 检查分析数据是否可用 ───────────────────────────────────
    if not analysis_data or analysis_data.get("error"):
        error_msg = analysis_data.get("error", "分析数据为空") if analysis_data else "分析数据为空"
        logger.warning(f"分析数据不可用: {error_msg}")
        return {
            "report_draft": f"# {topic}\n\n> 报告生成失败：{error_msg}",
            "current_phase": "reviewing",
            "messages": [HumanMessage(content=f"分析数据不可用: {error_msg}")],
        }

    # ── 将分析数据格式化为文本 ─────────────────────────────────
    analysis_text = _format_analysis_data(analysis_data)

    # ── 格式化引用列表 ─────────────────────────────────────────
    references_text = _format_references(references)

    # ── 初始化 LLM 并绑定工具 ─────────────────────────────────
    llm_cfg = settings.resolve_llm_config(state.get("model_name"))
    llm = ChatOpenAI(
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        temperature=0.3,  # 撰稿需要一定创造性
    )

    tools = [rag_search]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {"rag_search": rag_search}

    # ── 构建消息 ───────────────────────────────────────────────
    messages: list = [SystemMessage(content=WRITER_SYSTEM_PROMPT)]

    if review_feedback:
        # 有修改意见 → 基于已有报告进行修改
        existing_report = state.get("report_draft", "")
        messages.append(
            HumanMessage(
                content=(
                    f"研究主题：{topic}\n\n"
                    f"以下是之前的报告草稿：\n\n{existing_report}\n\n"
                    f"---\n\n"
                    f"审核修改意见：\n{review_feedback}\n\n"
                    f"请根据以上修改意见对报告进行修改，确保质量提升。"
                    f"直接输出修改后的完整报告（Markdown 格式）。"
                )
            )
        )
    else:
        # 首次撰写
        messages.append(
            HumanMessage(
                content=(
                    f"研究主题：{topic}\n\n"
                    f"以下是分析师提供的分析数据，请据此撰写完整的文献综述报告：\n\n"
                    f"{analysis_text}\n\n"
                    f"---\n\n"
                    f"引用来源列表（请在报告中使用 [数字] 格式引用这些来源）：\n\n"
                    f"{references_text}"
                )
            )
        )

    # ── 工具调用循环（最多 3 轮）─────────────────────────────
    try:
        for round_idx in range(3):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                logger.info(f"撰稿人第 {round_idx + 1} 轮无工具调用，结束循环")
                break

            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_id = tc["id"]
                logger.info(f"撰稿人调用工具: {tool_name}, 参数: {tool_args}")

                tool_func = tool_map.get(tool_name)
                if tool_func:
                    try:
                        # 同步工具（RAG 检索）放线程池，避免阻塞事件循环
                        result = await asyncio.to_thread(tool_func.invoke, tool_args)
                    except Exception as tool_err:
                        result = f"工具调用失败: {tool_err}"
                        logger.error(f"工具 {tool_name} 执行失败: {tool_err}")
                else:
                    result = f"未知工具: {tool_name}"
                    logger.warning(f"未知工具: {tool_name}")

                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

        # 如果最后一轮有工具调用，再调用一次 LLM 获取最终报告
        if response.tool_calls:
            response = await llm_with_tools.ainvoke(messages)

        report_draft = response.content.strip()
        msg = response if not review_feedback else HumanMessage(content="报告已修改完成")
        logger.info(f"撰稿人生成报告，长度: {len(report_draft)} 字符")
    except Exception as e:
        logger.error(f"撰稿人 LLM 调用失败: {e}")
        report_draft = f"# {topic}\n\n> 报告生成失败：LLM 调用错误 - {e}"
        msg = HumanMessage(content=f"撰稿人调用失败: {e}")

    return {
        "report_draft": report_draft,
        "current_phase": "reviewing",
        "messages": [msg],
    }


def _format_analysis_data(analysis_data: dict[str, Any]) -> str:
    """将分析数据字典格式化为可读文本

    支持两种情况：
    - 结构化 JSON 数据（正常流程）
    - raw_analysis 原始文本（JSON 解析失败时的回退）

    Args:
        analysis_data: 分析师输出的数据字典

    Returns:
        格式化后的文本字符串
    """
    # 如果是原始文本回退模式
    if "raw_analysis" in analysis_data:
        return f"分析师原始输出（未解析为结构化数据）：\n\n{analysis_data['raw_analysis']}"

    # 结构化数据 → 按维度格式化
    parts: list[str] = []

    section_labels = {
        "field_overview": "领域概况",
        "method_categories": "方法分类",
        "performance_comparison": "性能对比",
        "timeline_analysis": "发展脉络",
        "research_groups": "研究团队",
        "challenges_and_gaps": "挑战与研究空白",
        "key_findings": "核心发现",
        "data_sources": "数据来源",
    }

    for key, label in section_labels.items():
        value = analysis_data.get(key)
        if value is not None:
            if isinstance(value, dict):
                formatted = json.dumps(value, ensure_ascii=False, indent=2)
            elif isinstance(value, list):
                formatted = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                formatted = str(value)
            parts.append(f"## {label}\n{formatted}")

    return "\n\n---\n\n".join(parts) if parts else "暂无结构化分析数据"


def _format_references(references: list[dict[str, Any]]) -> str:
    """将引用列表格式化为可读文本

    Args:
        references: 引用条目列表，每个条目包含 id、title、url、source、date

    Returns:
        格式化后的引用文本字符串
    """
    if not references:
        return "暂无引用来源"

    parts: list[str] = []
    for ref in references:
        ref_id = ref.get("id", "?")
        title = ref.get("title", "未知来源")
        url = ref.get("url", "")
        source = ref.get("source", "")
        date = ref.get("date", "")
        line = f"[{ref_id}] {title}"
        if source:
            line += f" ({source})"
        if date:
            line += f", {date}"
        if url:
            line += f" - {url}"
        parts.append(line)

    return "\n".join(parts)
