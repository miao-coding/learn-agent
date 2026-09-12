"""ArXiv 学术论文检索工具 - 为 Agent 提供学术搜索和论文下载能力

本模块封装了 ArXiv API，提供两个 LangChain 工具：
- arxiv_search: 搜索学术论文，返回标题、作者、摘要等信息
- arxiv_download: 下载论文 PDF 并提取全文文本

export.arxiv.org 限流较严（HTTP 429）。内置：
- 全局最小请求间隔
- 429 指数退避 + 冷却窗口
- 短时查询缓存（同任务重复 query 不再打接口）
"""
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_arxiv_client = None

# 论文 PDF 下载目录（项目 output 目录）
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# ── 限流与缓存 ─────────────────────────────────────────────────
_MIN_REQUEST_INTERVAL_SEC = 3.5
_last_request_ts = 0.0
_rate_lock = threading.Lock()

_SEARCH_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_SEARCH_CACHE_TTL_SEC = 15 * 60
_SEARCH_CACHE_MAX = 64

# 429 后进程级冷却，避免同一任务继续打爆 ArXiv
_arxiv_cool_until = 0.0


def _throttle() -> None:
    """保证两次 ArXiv 请求之间至少间隔 _MIN_REQUEST_INTERVAL_SEC"""
    global _last_request_ts
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_REQUEST_INTERVAL_SEC - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _cache_key(query: str, max_results: int) -> str:
    return f"{query.strip().lower()}|{max_results}"


def _cache_get(key: str) -> str | None:
    item = _SEARCH_CACHE.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > _SEARCH_CACHE_TTL_SEC:
        _SEARCH_CACHE.pop(key, None)
        return None
    _SEARCH_CACHE.move_to_end(key)
    return val


def _cache_put(key: str, val: str) -> None:
    _SEARCH_CACHE[key] = (time.time(), val)
    _SEARCH_CACHE.move_to_end(key)
    while len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX:
        _SEARCH_CACHE.popitem(last=False)


def get_arxiv_client():
    """获取 ArXiv 客户端（单例缓存）"""
    global _arxiv_client
    if _arxiv_client is None:
        import arxiv
        _arxiv_client = arxiv.Client(page_size=10, delay_seconds=3.0, num_retries=4)
    return _arxiv_client


def _parse_papers(results) -> str:
    output = []
    for i, paper in enumerate(results, 1):
        authors = ", ".join([a.name for a in paper.authors[:5]])
        if len(paper.authors) > 5:
            authors += " et al."
        paper_id = paper.entry_id.split("/")[-1]
        categories = (
            paper.categories[:3]
            if isinstance(paper.categories, (list, tuple))
            else str(paper.categories).split(",")[:3]
        )
        output.append(
            f"[{i}] {paper.title}\n"
            f"    作者: {authors}\n"
            f"    日期: {paper.published.strftime('%Y-%m-%d')}\n"
            f"    arXiv ID: {paper_id}\n"
            f"    分类: {', '.join(categories)}\n"
            f"    摘要: {paper.summary[:500]}...\n"
        )
    return "\n".join(output)


@tool
def arxiv_search(query: str, max_results: int = 4) -> str:
    """搜索 ArXiv 学术论文。输入研究主题或关键词，返回论文标题、作者、摘要等。
    适用于查找学术研究、技术论文、最新科研成果。

    Args:
        query: 研究主题或关键词（如 "energy storage lithium battery"）
        max_results: 最大返回论文数量，默认4篇

    Returns:
        包含论文标题、作者、摘要、arXiv ID 的格式化结果
    """
    global _arxiv_cool_until

    q = (query or "").strip()
    if not q:
        return "错误：查询为空"

    if time.time() < _arxiv_cool_until:
        remain = int(_arxiv_cool_until - time.time())
        return f"ArXiv 搜索失败: 触发限流冷却，请 {remain}s 后再试（可跳过 ArXiv）"

    max_results = max(1, min(int(max_results or 4), 8))
    key = _cache_key(q, max_results)
    cached = _cache_get(key)
    if cached:
        return cached + "\n（缓存命中，未重复请求 ArXiv）"

    try:
        import arxiv

        client = get_arxiv_client()
        search = arxiv.Search(
            query=q,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        last_err = None
        results = None
        for attempt in range(4):
            _throttle()
            try:
                results = list(client.results(search))
                last_err = None
                break
            except Exception as e:
                last_err = e
                msg = str(e)
                if "429" in msg or "rate" in msg.lower() or "Too Many" in msg:
                    backoff = 5 * (2 ** attempt)  # 5, 10, 20, 40
                    logger.warning(
                        f"ArXiv 429，{backoff}s 后重试（attempt {attempt + 1}/4）"
                    )
                    time.sleep(backoff)
                    continue
                raise

        if last_err is not None:
            if "429" in str(last_err):
                _arxiv_cool_until = time.time() + 90
            return f"ArXiv 搜索失败: {last_err}"

        if not results:
            return "未找到相关学术论文"

        text = _parse_papers(results)
        _cache_put(key, text)
        return text
    except Exception as e:
        logger.error(f"ArXiv 搜索失败: {e}", exc_info=True)
        if "429" in str(e):
            _arxiv_cool_until = time.time() + 90
        return f"ArXiv 搜索失败: {str(e)}"


@tool
def arxiv_download(paper_id: str) -> str:
    """根据 ArXiv ID 下载论文 PDF 并提取全文文本。

    Args:
        paper_id: ArXiv 论文 ID（如 "2301.12345" 或完整 URL）

    Returns:
        论文全文文本内容（截取前 3000 字符）
    """
    global _arxiv_cool_until

    if time.time() < _arxiv_cool_until:
        remain = int(_arxiv_cool_until - time.time())
        return f"论文下载失败: ArXiv 限流冷却中，请 {remain}s 后再试"

    try:
        import arxiv
        import fitz  # pymupdf

        client = get_arxiv_client()
        search = arxiv.Search(id_list=[paper_id])

        results = None
        last_err = None
        for attempt in range(3):
            _throttle()
            try:
                results = list(client.results(search))
                last_err = None
                break
            except Exception as e:
                last_err = e
                if "429" in str(e):
                    backoff = 5 * (2 ** attempt)
                    logger.warning(f"ArXiv download 429，{backoff}s 后重试")
                    time.sleep(backoff)
                    continue
                raise
        if last_err is not None:
            if "429" in str(last_err):
                _arxiv_cool_until = time.time() + 90
            return f"论文下载失败: {last_err}"

        if not results:
            return f"未找到论文: {paper_id}"

        paper = results[0]

        # 解析 PDF 下载地址：兼容 arxiv 2.x（pdf_url）与 4.x（source_url）
        pdf_url = getattr(paper, "pdf_url", None) or getattr(paper, "source_url", None)
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{paper_id}"

        output_dir = OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = paper_id.replace("/", "_").replace(".", "_")
        pdf_path = output_dir / f"{safe_id}.pdf"

        resp = requests.get(pdf_url, timeout=60, headers={"User-Agent": "learn-agent/1.0"})
        resp.raise_for_status()
        pdf_path.write_bytes(resp.content)

        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()

        if pdf_path.exists():
            os.remove(str(pdf_path))

        text = text[:3000]
        authors = ", ".join([a.name for a in paper.authors[:5]])
        return f"论文: {paper.title}\n作者: {authors}\n\n全文内容:\n{text}"
    except Exception as e:
        logger.error(f"论文下载失败: {e}", exc_info=True)
        return f"论文下载失败: {str(e)}"
