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

# 工具返回中的失败特征：用于健康告警与结果过滤
_TOOL_FAIL_MARKERS = (
    "搜索失败",
    "配置错误",
    "Unauthorized",
    "invalid api key",
    "工具调用失败",
    "未找到相关搜索结果",
    "未找到相关学术论文",
    "未找到相关",
)


def _is_tool_failure(result: str) -> bool:
    text = str(result or "")
    return any(m in text for m in _TOOL_FAIL_MARKERS)


# ── 搜索员系统提示词 ─────────────────────────────────────────────
SEARCHER_SYSTEM_PROMPT = """你是一个专业的学术文献检索员。你的任务是根据给定的研究方向，进行高效的文献检索，收集相关学术论文和研究资料。

工作要求：
1. 根据研究方向生成 **2-3 个**不同角度的检索查询（综述类 survey/review、核心方法名各一条即可；不要发散过多相似 query）
2. 优先使用 arxiv_search。**同一查询不要重复发送**；ArXiv 有限流，尽量少而精
3. tavily_search 失败时不要反复重试，直接依赖 arxiv_search
4. 整理所有检索结果，确保包含来源信息

输出格式：
- 每条结果包含：标题、来源URL、关键内容摘要
- 按重要性排序
- 明确区分学术论文结果（arxiv/arxiv_pdf）和网络补充资料（web）

检索策略：
- 先宽后深：一个宽泛 survey 查询 + 1-2 个具体方法/技术词查询即可
- 优先收录：高引综述、里程碑工作、SOTA 方法
- arxiv_download 仅在摘要明显不足时使用，整个任务最多 1 篇
- 若工具返回「限流」「429」或「冷却」，停止继续调用 ArXiv，用已有结果总结"""


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

    # ── 工具调用循环（最多 6 轮，降低 ArXiv 压力） ─────────────
    all_search_results: list[dict[str, Any]] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tool_failures: list[str] = []
    seen_arxiv_queries: set[str] = set()
    arxiv_call_budget = 4
    arxiv_downloaded = 0

    for i in range(6):
        logger.debug(f"搜索员第 {i + 1} 轮工具调用")
        await report_progress(config, f"🔎 检索员第 {i + 1} 轮：正在决策检索策略...")
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            tool_failures.append(f"LLM: {e}")
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
                _arg_hint = tool_args.get("query") or tool_args.get("paper_id") or tool_args.get("urls") or ""
                await report_progress(config, f"🛠 调用 {tool_name}：{_arg_hint}")

                # ArXiv 去重 + 预算，避免同一 query 反复 429
                if tool_name == "arxiv_search":
                    qkey = str(tool_args.get("query", "")).strip().lower()
                    if qkey in seen_arxiv_queries:
                        await report_progress(config, f"⏭ 跳过重复 arxiv_search：{_arg_hint}")
                        messages.append(
                            ToolMessage(
                                content="查询与之前相同，已跳过（请换角度或结束检索）",
                                tool_call_id=tool_call["id"],
                            )
                        )
                        continue
                    if arxiv_call_budget <= 0:
                        await report_progress(config, "⏭ 本任务 ArXiv 查询次数已用尽，跳过")
                        messages.append(
                            ToolMessage(
                                content="本任务 ArXiv 查询预算已用尽，请基于已有结果总结",
                                tool_call_id=tool_call["id"],
                            )
                        )
                        continue
                    seen_arxiv_queries.add(qkey)
                    arxiv_call_budget -= 1

                if tool_name == "arxiv_download":
                    if arxiv_downloaded >= 1:
                        messages.append(
                            ToolMessage(
                                content="本任务最多下载 1 篇全文，请使用已有摘要",
                                tool_call_id=tool_call["id"],
                            )
                        )
                        continue
                    arxiv_downloaded += 1

                try:
                    # 同步工具放线程池执行，避免阻塞事件循环
                    result = await asyncio.to_thread(tool_map[tool_name].invoke, tool_args)
                    result_text = str(result)
                    messages.append(
                        ToolMessage(content=result_text, tool_call_id=tool_call["id"])
                    )
                    # 工具健康：失败结果不进入文献池，并向前端告警
                    if _is_tool_failure(result_text):
                        fail_hint = result_text.strip().splitlines()[0][:120] if result_text.strip() else "未知错误"
                        tool_failures.append(f"{tool_name}: {fail_hint}")
                        await report_progress(config, f"⚠️ {tool_name} 失败：{fail_hint}")
                        # ArXiv 429：停止后续 ArXiv 调用
                        if "429" in result_text or "限流" in result_text or "冷却" in result_text:
                            arxiv_call_budget = 0
                        continue
                    # 记录搜索结果
                    if tool_name == "tavily_search":
                        all_search_results.append(
                            {
                                "query": tool_args.get("query", ""),
                                "result": result_text,
                                "source": "web",
                            }
                        )
                    elif tool_name == "arxiv_search":
                        all_search_results.append(
                            {
                                "query": tool_args.get("query", ""),
                                "result": result_text,
                                "source": "arxiv",
                            }
                        )
                    elif tool_name == "arxiv_download":
                        all_search_results.append(
                            {
                                "query": tool_args.get("paper_id", ""),
                                "result": result_text,
                                "source": "arxiv_pdf",
                            }
                        )
                except Exception as e:
                    logger.error(f"工具 {tool_name} 调用失败: {e}")
                    tool_failures.append(f"{tool_name}: {e}")
                    await report_progress(config, f"⚠️ {tool_name} 异常：{e}")
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

    # ── 整理搜索结果（区分来源，过滤失败文本） ─────────────────
    search_results: list[dict[str, Any]] = []
    for item in all_search_results:
        if _is_tool_failure(item.get("result", "")):
            continue
        source = item.get("source", "web")
        search_results.append(
            {
                "query": item["query"],
                "content": item["result"],
                "source": source,
                "timestamp": timestamp,
            }
        )

    # ── 空结果兜底：强制按主题走一轮 ArXiv，避免 Tavily 失效/检索落空导致整条链路失败 ──
    if not search_results:
        fallback_query = topic
        try:
            await report_progress(config, f"🛠 兜底 arxiv_search：{fallback_query}")
            raw = await asyncio.to_thread(arxiv_search.invoke, {"query": fallback_query})
            text = str(raw or "").strip()
            if text and "未找到" not in text and "失败" not in text and not _is_tool_failure(text):
                all_search_results.append(
                    {"query": fallback_query, "result": text, "source": "arxiv"}
                )
                search_results.append(
                    {
                        "query": fallback_query,
                        "content": text,
                        "source": "arxiv",
                        "timestamp": timestamp,
                    }
                )
                logger.info("搜索为空，已用 ArXiv 主题兜底补救")
            else:
                logger.warning(f"ArXiv 兜底仍无结果: {text[:200]}")
                tool_failures.append(f"arxiv_fallback: {text[:120] if text else 'empty'}")
        except Exception as e:
            logger.error(f"ArXiv 兜底失败: {e}")
            tool_failures.append(f"arxiv_fallback: {e}")

    # ── 仍无有效文献 → 进入 failed，不再假装进入分析/审核 ──────
    if not search_results:
        fail_detail = "；".join(tool_failures[-3:]) if tool_failures else "检索策略未返回有效文献"
        err = f"检索失败，未获得有效文献。{fail_detail}"
        logger.error(err)
        await report_progress(config, f"❌ {err}")
        return {
            "search_results": [],
            "current_phase": "failed",
            "references": [],
            "report_draft": f"# {topic}\n\n> 任务失败：{err}",
            "messages": [HumanMessage(content=err)],
        }

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

    # ── 构建引用条目（解析 title/url/date，供前端与对账使用） ──
    from backend.utils.citations import extract_reference_meta

    references: list[dict[str, Any]] = []
    ref_id = 1
    for item in search_results:
        meta = extract_reference_meta(
            item.get("source", "web"),
            str(item.get("content", "")),
            item.get("query", ""),
        )
        references.append({
            "id": ref_id,
            "title": meta["title"],
            "url": meta["url"],
            "source": meta["source"],
            "date": meta["date"],
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
