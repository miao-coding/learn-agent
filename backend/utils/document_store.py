"""文档存储与检索 - 基于 ChromaDB 的向量存储"""
import logging
import hashlib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ChromaDB 持久化目录
CHROMA_DIR = Path(__file__).parent.parent.parent / "output" / "chroma_db"


class DocumentStore:
    """文档向量存储与检索"""

    def __init__(self, collection_name: str = "research_docs"):
        import chromadb
        from chromadb.config import Settings

        CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add_documents(self, documents: list[str], metadatas: list[dict] = None, ids: list[str] = None):
        """添加文档到向量存储"""
        if not documents:
            return

        # 自动生成 ID
        if ids is None:
            ids = [hashlib.md5(doc[:100].encode()).hexdigest() for doc in documents]

        # 自动分块（如果文档太长）
        chunked_docs = []
        chunked_meta = []
        chunked_ids = []

        for i, doc in enumerate(documents):
            chunks = self._chunk_text(doc, chunk_size=500, overlap=50)
            for j, chunk in enumerate(chunks):
                chunked_docs.append(chunk)
                meta = metadatas[i] if metadatas else {}
                meta["chunk_index"] = j
                chunked_meta.append(meta)
                chunked_ids.append(f"{ids[i]}_chunk{j}")

        self.collection.add(
            documents=chunked_docs,
            metadatas=chunked_meta,
            ids=chunked_ids
        )
        logger.info(f"添加 {len(chunked_docs)} 个文档块到向量存储")

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """相似度检索"""
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )

        docs = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                docs.append({
                    "content": doc,
                    "metadata": meta,
                    "distance": results["distances"][0][i] if results["distances"] else None
                })
        return docs

    def clear(self):
        """清空集合"""
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"}
        )

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """文本分块"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - overlap
        return chunks
