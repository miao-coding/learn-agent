"""ArXiv 学术论文检索工具 - 为 Agent 提供学术搜索和论文下载能力

本模块封装了 ArXiv API，提供两个 LangChain 工具：
- arxiv_search: 搜索学术论文，返回标题、作者、摘要等信息
- arxiv_download: 下载论文 PDF 并提取全文文本
"""
import time
import logging
import os
import requests
from pathlib import Path
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_arxiv_client = None

# 论文 PDF 下载目录（项目 output 目录）
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


def get_arxiv_client():
    """获取 ArXiv 客户端（单例缓存）"""
    global _arxiv_client
    if _arxiv_client is None:
        import arxiv
        _arxiv_client = arxiv.Client(page_size=10, delay_seconds=3, num_retries=2)
    return _arxiv_client


@tool
def arxiv_search(query: str, max_results: int = 5) -> str:
    """搜索 ArXiv 学术论文。输入研究主题或关键词，返回论文标题、作者、摘要等。
    适用于查找学术研究、技术论文、最新科研成果。

    Args:
        query: 研究主题或关键词（如 "energy storage lithium battery"）
        max_results: 最大返回论文数量，默认5篇

    Returns:
        包含论文标题、作者、摘要、arXiv ID 的格式化结果
    """
    try:
        import arxiv
        client = get_arxiv_client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = list(client.results(search))

        if not results:
            return "未找到相关学术论文"

        output = []
        for i, paper in enumerate(results, 1):
            authors = ", ".join([a.name for a in paper.authors[:5]])
            if len(paper.authors) > 5:
                authors += " et al."
            paper_id = paper.entry_id.split("/")[-1]
            # arxiv 库的 categories 是 list（如 ["cs.AI", "cs.CL"]）
            categories = paper.categories[:3] if isinstance(paper.categories, (list, tuple)) else str(paper.categories).split(",")[:3]
            output.append(
                f"[{i}] {paper.title}\n"
                f"    作者: {authors}\n"
                f"    日期: {paper.published.strftime('%Y-%m-%d')}\n"
                f"    arXiv ID: {paper_id}\n"
                f"    分类: {', '.join(categories)}\n"
                f"    摘要: {paper.summary[:500]}...\n"
            )
        return "\n".join(output)
    except Exception as e:
        logger.error(f"ArXiv 搜索失败: {e}", exc_info=True)
        return f"ArXiv 搜索失败: {str(e)}"


@tool
def arxiv_download(paper_id: str) -> str:
    """根据 ArXiv ID 下载论文 PDF 并提取全文文本。

    Args:
        paper_id: ArXiv 论文 ID（如 "2301.12345" 或完整 URL）

    Returns:
        论文全文文本内容（截取前 3000 字符）
    """
    try:
        import arxiv
        import fitz  # pymupdf

        client = get_arxiv_client()
        search = arxiv.Search(id_list=[paper_id])
        results = list(client.results(search))

        if not results:
            return f"未找到论文: {paper_id}"

        paper = results[0]

        # 解析 PDF 下载地址：兼容 arxiv 2.x（pdf_url）与 4.x（source_url，
        # 4.x 已移除 download_pdf 方法，需自行下载）
        pdf_url = getattr(paper, "pdf_url", None) or getattr(paper, "source_url", None)
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{paper_id}"

        # 下载到项目 output 目录
        output_dir = OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = paper_id.replace("/", "_").replace(".", "_")
        pdf_path = output_dir / f"{safe_id}.pdf"

        resp = requests.get(pdf_url, timeout=60, headers={"User-Agent": "learn-agent/1.0"})
        resp.raise_for_status()
        pdf_path.write_bytes(resp.content)

        # 提取文本
        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()

        # 清理临时文件
        if pdf_path.exists():
            os.remove(str(pdf_path))

        # 截取前 3000 字符
        text = text[:3000]
        authors = ", ".join([a.name for a in paper.authors[:5]])
        return f"论文: {paper.title}\n作者: {authors}\n\n全文内容:\n{text}"
    except Exception as e:
        logger.error(f"论文下载失败: {e}", exc_info=True)
        return f"论文下载失败: {str(e)}"
