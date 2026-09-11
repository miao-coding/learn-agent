"""RAG 检索工具 - 从向量数据库中检索相关文档片段"""
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def rag_search(query: str, n_results: int = 5) -> str:
    """从向量数据库中检索与研究主题最相关的文档片段。
    用于在已收集的搜索结果中进行精确检索，找到最相关的信息。

    Args:
        query: 检索查询（具体问题或关键词）
        n_results: 返回结果数量，默认5

    Returns:
        最相关的文档片段
    """
    try:
        from backend.utils.document_store import DocumentStore

        store = DocumentStore()
        results = store.search(query=query, n_results=n_results)

        if not results:
            return "向量数据库中暂无相关文档，请先使用搜索工具收集信息"

        output = []
        for i, result in enumerate(results, 1):
            content = result["content"]
            source = result.get("metadata", {}).get("source", "未知")
            output.append(
                f"[{i}] (来源: {source}, 相关度: {1 - (result.get('distance', 0) or 0):.2f})\n"
                f"{content}\n"
            )

        return "\n---\n".join(output)
    except Exception as e:
        logger.error(f"RAG 检索失败: {e}", exc_info=True)
        return f"RAG 检索失败: {str(e)}"


@tool
def rag_store(text: str, source: str = "unknown") -> str:
    """将文本内容存储到向量数据库中，供后续检索使用。

    Args:
        text: 要存储的文本内容
        source: 来源标识（如 URL、工具名称等）

    Returns:
        存储结果确认
    """
    try:
        from backend.utils.document_store import DocumentStore

        store = DocumentStore()
        store.add_documents(
            documents=[text],
            metadatas=[{"source": source}]
        )
        return f"已成功存储文档到向量数据库（来源: {source}）"
    except Exception as e:
        logger.error(f"文档存储失败: {e}", exc_info=True)
        return f"文档存储失败: {str(e)}"
