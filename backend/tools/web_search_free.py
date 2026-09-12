"""免 API Key 的补充检索工具

- duckduckgo_search: 网页搜索（无需 Key）
- wikipedia_search: 百科条目（无需 Key）
- semantic_scholar_search: 学术论文元数据（无需 Key）
- openalex_search: 开放学术图谱（无需 Key）
- searxng_search: 本地自建 SearXNG（若已部署）

设计目标：Tavily 失效时仍能收集网页/学术补充资料。
所有 HTTP 调用带超时；失败返回错误字符串（不抛异常打断 Agent）。
"""
from __future__ import annotations

import logging
import os

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 本地 SearXNG（docker 部署在 8888；可用环境变量覆盖）
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/")

_UA = {"User-Agent": "learn-agent/1.0 (research-bot)"}


def _fmt_hits(items: list[dict], max_n: int = 5) -> str:
    lines = []
    for i, it in enumerate(items[:max_n], 1):
        title = (it.get("title") or "").strip()[:160]
        url = (it.get("url") or it.get("href") or "").strip()
        snippet = (it.get("content") or it.get("snippet") or "").strip()[:280]
        lines.append(f"[{i}] {title}\n    URL: {url}\n    摘要: {snippet}\n")
    return "\n".join(lines) if lines else "未找到相关搜索结果"


@tool
def duckduckgo_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo 网页搜索（无需 API Key）。用于补充研究团队、开源项目、技术博客等网络资料。

    Args:
        query: 搜索关键词
        max_results: 返回条数，默认 5
    """
    q = (query or "").strip()
    if not q:
        return "错误：查询为空"
    try:
        from ddgs import DDGS

        max_results = max(1, min(int(max_results or 5), 8))
        hits: list[dict] = []
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=max_results):
                hits.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", r.get("link", "")),
                        "content": r.get("body", r.get("snippet", "")),
                    }
                )
        return _fmt_hits(hits, max_results)
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}")
        return f"DuckDuckGo 搜索失败: {e}"


@tool
def wikipedia_search(query: str, max_results: int = 3) -> str:
    """Wikipedia 条目检索（无需 API Key）。适合补背景定义、里程碑与术语解释。

    Args:
        query: 主题关键词（优先英文）
        max_results: 条目数，默认 3
    """
    q = (query or "").strip()
    if not q:
        return "错误：查询为空"
    try:
        import wikipedia

        wikipedia.set_lang("en")
        max_results = max(1, min(int(max_results or 3), 5))
        titles = wikipedia.search(q, results=max_results)
        if not titles:
            # 中文回退
            try:
                wikipedia.set_lang("zh")
                titles = wikipedia.search(q, results=max_results)
            except Exception:
                titles = []
        if not titles:
            return "未找到相关搜索结果"

        parts = []
        for i, title in enumerate(titles, 1):
            try:
                page = wikipedia.page(title, auto_suggest=False)
                summary = (page.summary or "")[:500]
                parts.append(
                    f"[{i}] {page.title}\n    URL: {page.url}\n    摘要: {summary}\n"
                )
            except Exception as e:
                parts.append(f"[{i}] {title}\n    摘要: （详情获取失败: {e}）\n")
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"Wikipedia 搜索失败: {e}")
        return f"Wikipedia 搜索失败: {e}"


@tool
def semantic_scholar_search(query: str, max_results: int = 5) -> str:
    """Semantic Scholar 学术搜索（无需 API Key）。返回标题、年份、引用数、摘要与链接。

    Args:
        query: 研究主题英文关键词
        max_results: 返回论文数，默认 5
    """
    q = (query or "").strip()
    if not q:
        return "错误：查询为空"
    try:
        max_results = max(1, min(int(max_results or 5), 10))
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        resp = requests.get(
            url,
            params={
                "query": q,
                "limit": max_results,
                "fields": "title,year,citationCount,abstract,url,externalIds,authors",
            },
            headers=_UA,
            timeout=15,
        )
        if resp.status_code == 429:
            return "Semantic Scholar 搜索失败: HTTP 429 限流，请稍后重试"
        resp.raise_for_status()
        data = resp.json() or {}
        papers = data.get("data") or []
        if not papers:
            return "未找到相关学术论文"

        parts = []
        for i, p in enumerate(papers, 1):
            title = (p.get("title") or "").strip()
            year = p.get("year") or ""
            cites = p.get("citationCount")
            url_p = p.get("url") or ""
            ext = p.get("externalIds") or {}
            doi = ext.get("DOI") or ""
            arx = ext.get("ArXiv") or ""
            authors = ", ".join(
                [a.get("name", "") for a in (p.get("authors") or [])[:4]]
            )
            abstract = (p.get("abstract") or "")[:400]
            meta = f"年份: {year} | 引用: {cites}"
            if arx:
                meta += f" | arXiv: {arx}"
            if doi:
                meta += f" | DOI: {doi}"
            parts.append(
                f"[{i}] {title}\n    作者: {authors}\n    {meta}\n"
                f"    URL: {url_p}\n    摘要: {abstract}\n"
            )
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"Semantic Scholar 搜索失败: {e}")
        return f"Semantic Scholar 搜索失败: {e}"


@tool
def openalex_search(query: str, max_results: int = 5) -> str:
    """OpenAlex 开放学术检索（无需 API Key）。返回标题、年份、被引、来源期刊与链接。

    Args:
        query: 研究主题关键词
        max_results: 返回条数，默认 5
    """
    q = (query or "").strip()
    if not q:
        return "错误：查询为空"
    try:
        max_results = max(1, min(int(max_results or 5), 10))
        resp = requests.get(
            "https://api.openalex.org/works",
            params={"search": q, "per-page": max_results},
            headers=_UA,
            timeout=15,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            return "未找到相关搜索结果"

        parts = []
        for i, w in enumerate(results, 1):
            title = (w.get("title") or w.get("display_name") or "").strip()
            year = w.get("publication_year") or ""
            cited = w.get("cited_by_count")
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            loc = w.get("primary_location") or {}
            src = ((loc.get("source") or {}).get("display_name")) or ""
            oa = (w.get("open_access") or {}).get("oa_url") or ""
            url_w = oa or (loc.get("landing_page_url") or "") or (w.get("doi") or "")
            authors = []
            for a in (w.get("authorships") or [])[:4]:
                name = (a.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)
            abstract = ""
            inv = w.get("abstract_inverted_index") or {}
            if inv:
                # 还原倒排摘要（取前若干词）
                pairs = []
                for word, positions in inv.items():
                    for pos in positions:
                        pairs.append((pos, word))
                pairs.sort()
                abstract = " ".join(w for _, w in pairs)[:400]
            parts.append(
                f"[{i}] {title}\n    作者: {', '.join(authors)}\n"
                f"    年份: {year} | 被引: {cited} | 来源: {src}\n"
                f"    URL: {url_w}"
                + (f" | DOI: {doi}" if doi else "")
                + f"\n    摘要: {abstract}\n"
            )
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"OpenAlex 搜索失败: {e}")
        return f"OpenAlex 搜索失败: {e}"


@tool
def searxng_search(query: str, max_results: int = 5) -> str:
    """本地自建 SearXNG 元搜索（无需外部 Key）。若服务未启动会返回错误提示。

    Args:
        query: 搜索关键词
        max_results: 返回条数，默认 5
    """
    q = (query or "").strip()
    if not q:
        return "错误：查询为空"
    try:
        max_results = max(1, min(int(max_results or 5), 10))
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": q, "format": "json"},
            headers=_UA,
            timeout=12,
        )
        if resp.status_code != 200:
            return f"SearXNG 搜索失败: HTTP {resp.status_code}（本地服务可能未启动）"
        data = resp.json() or {}
        results = data.get("results") or []
        hits = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in results
        ]
        if not hits:
            return "未找到相关搜索结果"
        return _fmt_hits(hits, max_results)
    except requests.exceptions.ConnectionError:
        return (
            f"SearXNG 搜索失败: 无法连接 {SEARXNG_URL}。"
            "请确认本地容器已启动（docker compose up -d searxng）"
        )
    except Exception as e:
        logger.warning(f"SearXNG 搜索失败: {e}")
        return f"SearXNG 搜索失败: {e}"
