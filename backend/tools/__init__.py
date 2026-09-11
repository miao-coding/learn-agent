"""工具层 - 提供 Agent 可调用的各类工具

当前包含：
- tavily_search: Tavily 网络搜索工具
- tavily_extract: Tavily 网页内容提取工具
- arxiv_search: ArXiv 学术论文搜索工具
- arxiv_download: ArXiv 论文 PDF 下载与文本提取工具
- generate_trend_chart: 趋势折线图可视化工具
- generate_competition_chart: 竞争格局饼图/柱状图可视化工具
- generate_comparison_chart: 多维度对比柱状图可视化工具
- rag_search: RAG 向量检索工具
- rag_store: RAG 文档存储工具
"""
from backend.tools.search import tavily_search, tavily_extract
from backend.tools.arxiv_tool import arxiv_search, arxiv_download
from backend.tools.visualization import (
    generate_trend_chart,
    generate_competition_chart,
    generate_comparison_chart,
)
from backend.tools.rag import rag_search, rag_store

__all__ = [
    "tavily_search",
    "tavily_extract",
    "arxiv_search",
    "arxiv_download",
    "generate_trend_chart",
    "generate_competition_chart",
    "generate_comparison_chart",
    "rag_search",
    "rag_store",
]
