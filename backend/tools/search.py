"""Tavily 搜索工具 - 为 Agent 提供联网搜索和内容提取能力

本模块封装了 Tavily 搜索 API，提供两个 LangChain 工具：
- tavily_search: 网络搜索，返回结构化结果
- tavily_extract: 从指定 URL 提取网页内容
"""
import logging
from typing import Any

from langchain_core.tools import tool
from tavily import TavilyClient

from backend.config import settings

logger = logging.getLogger(__name__)

_tavily_client = None


def get_tavily_client() -> TavilyClient:
    """创建并返回 Tavily 客户端实例（模块级缓存，避免重复创建）

    Returns:
        TavilyClient: 配置好 API Key 的 Tavily 客户端

    Raises:
        ValueError: 当 TAVILY_API_KEY 未配置时抛出
    """
    global _tavily_client
    if _tavily_client is None:
        if not settings.tavily_api_key:
            raise ValueError(
                "TAVILY_API_KEY 未配置，请在 .env 文件中设置 TAVILY_API_KEY 环境变量"
            )
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client


def reload_tavily_client() -> None:
    """重置 Tavily 客户端缓存（API Key 在线更新后调用，下次使用时以新 Key 重建）"""
    global _tavily_client
    _tavily_client = None


@tool
def tavily_search(query: str) -> str:
    """使用 Tavily 进行网络搜索。输入搜索查询字符串，返回包含标题、URL、摘要的结构化搜索结果。

    Args:
        query: 搜索查询字符串，例如 "2024年中国新能源汽车市场趋势"

    Returns:
        包含标题、URL、摘要内容的搜索结果（格式化字符串）。
        如果搜索失败，返回错误信息字符串。
    """
    try:
        client = get_tavily_client()
        response = client.search(
            query=query,
            max_results=5,
            search_depth="advanced",
            include_answer=True,
        )

        # 格式化结果
        results: list[str] = []

        # 添加 AI 摘要（如果存在）
        if response.get("answer"):
            results.append(f"AI 摘要: {response['answer']}\n")

        # 添加每条搜索结果
        for i, item in enumerate(response.get("results", []), 1):
            title = item.get("title", "N/A")
            url = item.get("url", "N/A")
            content = item.get("content", "N/A")
            results.append(
                f"[{i}] {title}\n"
                f"    URL: {url}\n"
                f"    摘要: {content}\n"
            )

        return "\n".join(results) if results else "未找到相关搜索结果"

    except ValueError as e:
        # 配置错误，直接返回提示
        logger.error(f"Tavily 配置错误: {e}")
        return f"配置错误: {str(e)}"
    except Exception as e:
        logger.error(f"Tavily 搜索失败: {e}", exc_info=True)
        return f"搜索失败: {str(e)}"


@tool
def tavily_extract(urls: list[str]) -> str:
    """从指定 URL 列表提取网页文本内容。适用于需要深入阅读某个网页全文的场景。

    Args:
        urls: 要提取内容的 URL 列表，例如 ["https://example.com/article"]

    Returns:
        提取的网页文本内容（格式化字符串，每个 URL 的内容用分隔线隔开）。
        内容截取前 2000 字符。如果提取失败，返回错误信息字符串。
    """
    try:
        client = get_tavily_client()
        response = client.extract(urls=urls)

        results: list[str] = []
        for item in response.get("results", []):
            url = item.get("url", "N/A")
            # 优先使用 raw_content，回退到 content
            raw_content = item.get("raw_content") or item.get("content", "N/A")
            # 截取前 2000 字符，避免内容过长
            truncated = raw_content[:2000] if raw_content else "N/A"
            results.append(
                f"URL: {url}\n"
                f"内容: {truncated}\n"
                f"---"
            )

        return "\n".join(results) if results else "未能提取到任何内容"

    except ValueError as e:
        logger.error(f"Tavily 配置错误: {e}")
        return f"配置错误: {str(e)}"
    except Exception as e:
        logger.error(f"Tavily 内容提取失败: {e}", exc_info=True)
        return f"内容提取失败: {str(e)}"
