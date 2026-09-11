"""分析师 Agent - 从文献资料中提取研究信息和分析洞察

分析师接收检索员收集的文献资料，使用 LLM 进行深度分析，
提取研究方法分类、性能对比、发展脉络、研究空白等结构化信息。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.tools.visualization import (
    generate_trend_chart,
    generate_competition_chart,
    generate_comparison_chart,
)
from backend.tools.rag import rag_search

logger = logging.getLogger(__name__)

# ── 分析师系统提示词 ─────────────────────────────────────────────
ANALYST_SYSTEM_PROMPT = """你是一个资深的学术研究分析师。你的任务是根据检索员收集的文献资料，进行深度分析并提取结构化的研究信息。

分析维度：
1. **领域概况**：研究方向定义、发展阶段、里程碑工作
2. **方法分类**：主流方法/技术路线分类，各类原理与代表工作
3. **性能对比**：各方法在公开基准/数据集上的关键指标对比（如准确率、效率、成本）
4. **发展脉络**：时间线上的重要进展与演进逻辑
5. **研究团队**：代表性研究团队/机构及其贡献
6. **挑战与空白**：现有工作的局限性、尚未解决的问题、未来研究方向

引用标注要求：
- 分析结果中每个数据点、每条论断必须关联引用编号 [1] [2] 等
- 引用编号与检索员提供的引用编号对应
- 确保内容可溯源，不得编造文献

输出要求：
- 所有内容必须标注引用来源编号
- 对于相互矛盾的结果，列出不同文献的观点
- 使用 JSON 格式输出分析结果
- comparison_table 字段：方法/技术路线对比表格（Markdown 表格格式）
- key_findings 字段：核心发现列表，每条带引用标注

请以 JSON 格式输出，包含以下字段：
{
    "field_overview": {"definition": "", "development_stage": "", "milestones": [{"year": "", "work": "", "contribution": ""}], "key_drivers": []},
    "method_categories": {"categories": [{"name": "", "principle": "", "representative_works": [], "pros": "", "cons": ""}], "main_streams": ""},
    "performance_comparison": {"benchmarks": [], "comparison_table": "Markdown 格式的方法性能对比表格", "state_of_the_art": ""},
    "timeline_analysis": {"early_works": [], "recent_trends": "", "evolution_logic": ""},
    "research_groups": {"groups": [{"name": "", "institution": "", "contributions": ""}], "collaboration_landscape": ""},
    "challenges_and_gaps": {"challenges": [], "open_problems": [], "future_directions": []},
    "key_findings": ["发现1 [1]", "发现2 [3]"],
    "data_sources": []
}

注意：只输出 JSON，不要输出其他内容。如果某个字段没有相关内容，填写“暂无数据”。

RAG 检索能力：你可以使用 rag_search 工具从向量数据库中精确检索相关文档片段。
当你需要核实某个论断的文献依据、查证性能数据或补充分析细节时，主动调用 rag_search 获取最相关的信息。"""


async def analyst_agent(state: dict) -> dict[str, Any]:
    """分析师节点 - 对搜索结果进行深度分析，提取关键数据

    流程：
    1. 从 state 获取 search_results 和 topic
    2. 将搜索结果拼接为分析输入
    3. 调用 LLM 进行结构化分析
    4. 解析 JSON 输出，更新 analysis_data

    Args:
        state: AgentState 字典，包含 search_results、topic 字段

    Returns:
        包含 analysis_data、current_phase、messages 的状态更新字典
    """
    topic = state["topic"]
    search_results = state.get("search_results", [])
    logger.info(f"分析师开始工作，主题: {topic}，搜索结果数: {len(search_results)}")

    # 上游已失败：短路透传，不继续分析
    if state.get("current_phase") == "failed":
        return {
            "analysis_data": state.get("analysis_data") or {"error": "上游检索失败"},
            "current_phase": "failed",
            "report_draft": state.get("report_draft", ""),
            "messages": [HumanMessage(content="上游已失败，跳过分析")],
        }

    # ── 构建分析输入：将所有搜索结果拼接 ───────────────────────
    if not search_results:
        logger.warning("搜索结果为空，分析师无法进行分析")
        # 上游已 failed 时保持 failed；否则将本节点标为 failed（不再进入审核）
        phase = state.get("current_phase") or "failed"
        if phase not in ("failed",):
            phase = "failed"
        return {
            "analysis_data": {"error": "搜索结果为空，无法进行分析"},
            "current_phase": phase,
            "report_draft": state.get("report_draft")
            or f"# {topic}\n\n> 任务失败：搜索结果为空，无法进行分析",
            "messages": [HumanMessage(content="搜索结果为空，无法进行分析")],
        }

    search_context_parts: list[str] = []
    for i, item in enumerate(search_results, 1):
        query = item.get("query", "未知查询")
        content = item.get("content", "无内容")
        search_context_parts.append(f"### 搜索 {i}: {query}\n{content}")

    search_context = "\n\n---\n\n".join(search_context_parts)

    # ── 初始化 LLM 并绑定可视化工具 ───────────────────────────────
    llm_cfg = settings.resolve_llm_config(state.get("model_name"))
    llm = ChatOpenAI(
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        temperature=0.1,
    )

    visualization_tools = [
        generate_trend_chart,
        generate_competition_chart,
        generate_comparison_chart,
        rag_search,
    ]
    llm_with_tools = llm.bind_tools(visualization_tools)

    # ── 构建消息并调用 LLM ─────────────────────────────────────
    messages = [
        SystemMessage(content=ANALYST_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"研究主题：{topic}\n\n"
                f"以下是搜索员收集的搜索结果，请进行深度分析并提取关键数据：\n\n"
                f"{search_context}"
            )
        ),
    ]

    # ── 工具调用循环（最多 5 轮）─────────────────────────────────
    charts: list[str] = []
    max_tool_rounds = 5

    try:
        for round_idx in range(max_tool_rounds):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            # 如果 LLM 没有调用工具，直接跳出循环
            if not response.tool_calls:
                logger.info(f"分析师第 {round_idx + 1} 轮无工具调用，结束循环")
                break

            # 执行所有工具调用
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_id = tc["id"]
                logger.info(f"分析师调用工具: {tool_name}, 参数: {tool_args}")

                # 查找并执行对应工具
                tool_map = {
                    "generate_trend_chart": generate_trend_chart,
                    "generate_competition_chart": generate_competition_chart,
                    "generate_comparison_chart": generate_comparison_chart,
                    "rag_search": rag_search,
                }
                tool_func = tool_map.get(tool_name)
                if tool_func:
                    try:
                        # 同步工具（matplotlib 绘图/RAG 检索）放线程池，避免阻塞事件循环
                        result = await asyncio.to_thread(tool_func.invoke, tool_args)
                        logger.info(f"工具 {tool_name} 返回: {result}")
                        # 收集图表路径
                        if isinstance(result, str) and "图表已生成:" in result:
                            chart_path = result.split("图表已生成:")[-1].strip()
                            charts.append(chart_path)
                    except Exception as tool_err:
                        result = f"工具调用失败: {tool_err}"
                        logger.error(f"工具 {tool_name} 执行失败: {tool_err}")
                else:
                    result = f"未知工具: {tool_name}"
                    logger.warning(f"未知工具: {tool_name}")

                # 将工具结果作为 ToolMessage 加入消息列表
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(content=result, tool_call_id=tool_id))

            logger.info(f"分析师第 {round_idx + 1} 轮工具调用完成，已生成 {len(charts)} 张图表")

        # 最终响应（可能包含工具调用结果的总结）
        if response.tool_calls:
            # 如果最后一轮仍有工具调用，再调用一次 LLM 获取最终分析文本
            final_response = await llm_with_tools.ainvoke(messages)
            response_text = final_response.content.strip()
            response = final_response
        else:
            response_text = response.content.strip()

        logger.info(f"分析师 LLM 响应长度: {len(response_text)} 字符")
    except Exception as e:
        logger.error(f"分析师 LLM 调用失败: {e}")
        return {
            "analysis_data": {"error": f"LLM 调用失败: {e}"},
            "current_phase": "failed",
            "report_draft": f"# {topic}\n\n> 任务失败：分析阶段 LLM 调用失败 - {e}",
            "messages": [HumanMessage(content=f"分析失败: {e}")],
        }

    # ── 解析 JSON 输出 ─────────────────────────────────────────
    analysis_data = _parse_analysis_json(response_text)

    logger.info(f"分析师完成分析，共生成 {len(charts)} 张图表")

    return {
        "analysis_data": analysis_data,
        "current_phase": "writing",
        "messages": [response],
        "charts": charts,
    }


def _parse_analysis_json(text: str) -> dict[str, Any]:
    """从 LLM 响应中解析 JSON 分析数据

    支持从 Markdown 代码块中提取 JSON。

    Args:
        text: LLM 响应文本

    Returns:
        解析后的分析数据字典
    """
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试从 Markdown 代码块中提取 JSON
    try:
        # 查找 ```json ... ``` 或 ``` ... ``` 代码块
        import re

        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            return json.loads(json_str)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"从代码块提取 JSON 失败: {e}")

    # 尝试找到第一个 { 和最后一个 } 之间的内容
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON 解析全部尝试失败: {e}")

    # 最终回退：将原始文本作为 raw_analysis 返回
    logger.warning("无法解析 JSON，返回原始文本")
    return {
        "raw_analysis": text,
        "parse_status": "failed",
        "message": "LLM 输出无法解析为 JSON，已保存原始文本",
    }
