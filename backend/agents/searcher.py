"""搜索员 Agent - 负责学术文献检索与研究资料收集

搜索员通过 LLM + 工具调用的方式，自主决定检索策略，
以 arxiv_search、arxiv_download 检索和下载学术论文为主，
辅以 tavily_search、tavily_extract 收集网络补充资料（研究团队、开源项目、基准数据集）。

注意：所有同步工具（ArXiv/PDF 下载/RAG 入库）必须通过 asyncio.to_thread
在线程池中执行，否则会阻塞 asyncio 事件循环，导致整个后端服务假死
（任务运行期间 health/SSE/页面请求全部无响应）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.tools.search import tavily_search, tavily_extract
from backend.tools.arxiv_tool import arxiv_search, arxiv_download
from backend.utils.progress import report_progress

logger = logging.getLogger(__name__)

# ── 搜索员系统提示词 ─────────────────────────────────────────────
SEARCHER_SYSTEM_PROMPT = """你是一个专业的学术文献检索员。你的任务是根据给定的研究方向，进行全面的文献检索，收集相关学术论文和研究资料。

工作要求：
1. 根据研究方向生成 3-5 个不同角度的检索查询（如综述类关键词 survey/review、核心方法名、技术路线、经典工作与最新进展等）
2. 优先使用 arxiv_search 检索学术论文。**摘要信息通常已足够综述分析**——仅当某篇论文确属里程碑工作且摘要明显不足时才用 arxiv_download 下载全文，整个任务最多下载 1-2 篇（PDF 下载耗时很长，频繁下载会严重拖慢任务）
3. 使用 tavily_search 辅助检索：知名研究团队/实验室、顶会论文信息、开源项目与基准数据集（benchmark）
4. 从搜索结果中选择最有价值的页面，使用 tavily_extract 获取详细内容
5. 整理所有检索结果，确保包含来源信息

输出格式：
- 每条结果包含：标题、来源URL、关键内容摘要
- 按重要性排序
- 标注数据来源URL
- 明确区分学术论文结果（arxiv/arxiv_pdf）和网络补充资料（web）
- 最终总结中需分别列出学术来源和网络来源

注意：检索要全面、多角度，覆盖研究方向的各个维度。
检索策略：
- 先用宽泛查询摸清领域全貌，再用具体方法名/技术词深挖
- 优先收录：高引综述、里程碑工作、SOTA 方法、基准数据集论文
- 覆盖不同年份的代表工作，体现领域发展脉络
- arxiv_download 谨慎使用：摘要优先，最多下载 1-2 篇核心论文全文，避免在下载上浪费时间"""


async def searcher_agent(state: dict, config: RunnableConfig) -> dict[str, Any]:
    """检索员节点 - 执行文献检索，收集研究资料

    流程：
    1. 从 state 获取研究主题 topic
    2. 初始化 LLM 并绑定检索工具
    3. 通过工具调用循环，让 LLM 自主决定检索策略
    4. 整理检索结果，更新 state

    Args:
        state: AgentState 字典，包含 topic 字段
        config: LangGraph 注入的运行配置（含 thread_id），
            用于通过 report_progress 向前端推送工具级实时进度。
            注意：必须是无默认值的标准双参签名，否则 LangGraph 不会注入 config。

    Returns:
        包含 search_results、current_phase、messages 的状态更新字典
    """
    topic = state["topic"]
    logger.info(f"搜索员开始工作，主题: {topic}")

    # ── 初始化 LLM 和工具 ──────────────────────────────────────
    llm_cfg = settings.resolve_llm_config(state.get("model_name"))
    llm = ChatOpenAI(
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        temperature=0.1,
    )
    tools = [tavily_search, tavily_extract, arxiv_search, arxiv_download]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    # ── 构建初始消息 ───────────────────────────────────────────
    messages: list = [
        SystemMessage(content=SEARCHER_SYSTEM_PROMPT),
        HumanMessage(content=f"请围绕以下研究方向进行全面文献检索：{topic}"),
    ]

    # ── 工具调用循环（最多 10 轮） ─────────────────────────────
    all_search_results: list[dict[str, Any]] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i in range(10):
        logger.debug(f"搜索员第 {i + 1} 轮工具调用")
        await report_progress(config, f"🔎 检索员第 {i + 1} 轮：正在决策检索策略...")
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            break

        messages.append(response)

        # 没有工具调用 → LLM 认为搜索已完成
        if not response.tool_calls:
            logger.info("搜索员完成搜索（无更多工具调用）")
            break

        # 逐个执行工具调用
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            logger.info(f"调用工具: {tool_name}, 参数: {tool_args}")

            if tool_name in tool_map:
                # 工具级实时进度：让用户看到每一步在做什么
                _arg_hint = tool_args.get("query") or tool_args.get("paper_id") or tool_args.get("urls") or ""
                await report_progress(config, f"🛠 调用 {tool_name}：{_arg_hint}")
                try:
                    # 同步工具放线程池执行，避免阻塞事件循环
                    result = await asyncio.to_thread(tool_map[tool_name].invoke, tool_args)
                    messages.append(
                        ToolMessage(content=str(result), tool_call_id=tool_call["id"])
                    )
                    # 记录搜索结果
                    if tool_name == "tavily_search":
                        all_search_results.append(
                            {
                                "query": tool_args.get("query", ""),
                                "result": result,
                                "source": "web",
                            }
                        )
                    elif tool_name == "arxiv_search":
                        all_search_results.append(
                            {
                                "query": tool_args.get("query", ""),
                                "result": result,
                                "source": "arxiv",
                            }
                        )
                    elif tool_name == "arxiv_download":
                        all_search_results.append(
                            {
                                "query": tool_args.get("paper_id", ""),
                                "result": result,
                                "source": "arxiv_pdf",
                            }
                        )
                except Exception as e:
                    logger.error(f"工具 {tool_name} 调用失败: {e}")
                    messages.append(
                        ToolMessage(
                            content=f"工具调用失败: {e}",
                            tool_call_id=tool_call["id"],
                        )
                    )
            else:
                logger.warning(f"未知工具: {tool_name}")
                messages.append(
                    ToolMessage(
                        content=f"未知工具: {tool_name}",
                        tool_call_id=tool_call["id"],
                    )
                )

    # ── 整理搜索结果（区分来源） ───────────────────────────────
    search_results: list[dict[str, Any]] = []
    for item in all_search_results:
        source = item.get("source", "web")
        search_results.append(
            {
                "query": item["query"],
                "content": item["result"],
                "source": source,
                "timestamp": timestamp,
            }
        )

    logger.info(f"搜索员完成工作，共 {len(search_results)} 条搜索结果")

    # ── 批量存储搜索结果到向量数据库（供分析师/撰稿人 RAG 检索） ───
    try:
        from backend.tools.rag import rag_store
        for item in search_results:
            content = str(item.get("content", ""))
            source = item.get("source", "unknown")
            query = item.get("query", "")
            if content:
                await asyncio.to_thread(
                    rag_store.invoke, {"text": content, "source": f"{source}:{query}"}
                )
        logger.info(f"已将 {len(search_results)} 条搜索结果存储到向量数据库")
    except Exception as e:
        logger.warning(f"向量数据库存储失败（不影响主流程）: {e}")

    # ── 构建引用条目 ───────────────────────────────────────────
    references: list[dict[str, Any]] = []
    ref_id = 1
    for item in all_search_results:
        references.append({
            "id": ref_id,
            "title": item.get("query", "未知来源"),
            "url": "",  # 如果有 URL 则填入
            "source": item.get("source", "tavily"),
            "date": "",
        })
        ref_id += 1

    # ── 让 LLM 做最终总结 ──────────────────────────────────────
    messages.append(HumanMessage(content="请总结你搜索到的所有信息，按类别整理输出。请明确区分网络来源（web）和学术来源（arxiv/arxiv_pdf），分别列出。"))
    try:
        final_response = await llm.ainvoke(messages)
    except Exception as e:
        logger.error(f"LLM 总结调用失败: {e}")
        final_response = HumanMessage(content="搜索总结生成失败")

    return {
        "search_results": search_results,
        "current_phase": "analyzing",
        "references": references,
        "messages": [final_response],
    }
