"""用户上传文献的接收与抽取（可选输入）

- PDF → 全文文本（pymupdf）
- 从文末启发式抽出参考文献标题
- 供检索员作为「种子文献」并入 search_results，并可用标题再搜一轮
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "uploads"
MAX_FILES = 5
MAX_FILE_MB = 20
ALLOWED_SUFFIX = {".pdf", ".txt", ".md"}


def _batch_dir(batch_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (batch_id or "")) or "misc"
    p = UPLOAD_DIR / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def extract_pdf_text(path: Path, max_pages: int = 80) -> str:
    """提取 PDF 文本；失败返回空串"""
    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))
        parts: list[str] = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            parts.append(page.get_text() or "")
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"PDF 文本提取失败 {path.name}: {e}")
        return ""


def extract_plain_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"读取文本失败 {path.name}: {e}")
        return ""


def _is_citation_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 20 or len(s) > 400:
        return False
    # [12] Title / 12. Title / Author (2020). Title
    if re.match(r"^\[?\d{1,3}\]?[.)]?\s+\S", s):
        return True
    if re.match(r"^[A-Z][A-Za-z\-]+\s+et\s+al\.", s):
        return True
    if re.search(r"\(\d{4}[a-z]?\)", s) and len(s) > 40:
        return True
    return False


def extract_reference_titles(text: str, limit: int = 25) -> list[str]:
    """从全文启发式抽取参考文献标题（供二次检索用）"""
    if not text:
        return []
    # 定位 References / 参考文献 附近
    m = re.search(
        r"(?is)(\n\s*(references|bibliography|参考文献)\s*\n)(.*)$",
        text,
    )
    body = m.group(3) if m else text[-8000:]
    titles: list[str] = []
    for line in body.splitlines():
        if not _is_citation_line(line):
            continue
        # 去掉编号前缀
        t = re.sub(r"^\[?\d{1,3}\]?[.)]?\s+", "", line.strip())
        t = t[:200].strip()
        if len(t) < 15:
            continue
        titles.append(t)
        if len(titles) >= limit:
            break
    return titles


def ingest_uploaded_file(filename: str, data: bytes) -> dict[str, Any] | None:
    """落盘并抽取内容；返回文档元数据"""
    if not data:
        return None
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"文件过大: {filename}（上限 {MAX_FILE_MB}MB）")
    suffix = Path(filename or "doc").suffix.lower() or ".pdf"
    if suffix not in ALLOWED_SUFFIX:
        raise ValueError(f"不支持的文件类型: {suffix}（仅 PDF/TXT/MD）")

    batch_id = str(uuid.uuid4())
    out_dir = _batch_dir(batch_id)
    safe_name = re.sub(r"[^\w.\-]+", "_", Path(filename).name)[:120] or f"doc{suffix}"
    path = out_dir / safe_name
    path.write_bytes(data)

    if suffix == ".pdf":
        text = extract_pdf_text(path)
    else:
        text = extract_plain_text(path)

    ref_titles = extract_reference_titles(text)
    meta = {
        "batch_id": batch_id,
        "filename": safe_name,
        "path": str(path),
        "suffix": suffix,
        "text_chars": len(text),
        "reference_titles": ref_titles,
        "title_guess": _guess_title(text, safe_name),
    }
    # 缓存抽取文本，供运行时读取（避免再解 PDF）
    (out_dir / "extracted.json").write_text(
        __import__("json").dumps(
            {"text": text[:200000], "reference_titles": ref_titles, "filename": safe_name},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info(
        f"已接收上传文献 {safe_name}: {len(text)} 字, 参考线索 {len(ref_titles)} 条, batch={batch_id}"
    )
    return meta


def _guess_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines()[:30]:
        s = line.strip()
        if 12 <= len(s) <= 160 and not s.lower().startswith(("abstract", "摘要", "http")):
            return s
    return Path(fallback).stem


def load_upload_batch(batch_id: str) -> dict[str, Any] | None:
    """读取 batch 的抽取结果；不存在返回 None（不创建目录）"""
    if not batch_id:
        return None
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in batch_id) or ""
    if not safe:
        return None
    out_dir = UPLOAD_DIR / safe
    meta_path = out_dir / "extracted.json"
    if not meta_path.exists():
        return None
    try:
        import json

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["batch_id"] = batch_id
        data["dir"] = str(out_dir)
        return data
    except Exception as e:
        logger.warning(f"读取 upload batch 失败 {batch_id}: {e}")
        return None


def uploads_to_search_seed(batch_id: str) -> list[dict[str, Any]]:
    """把上传文献转成 search_results 种子（source=uploaded）"""
    data = load_upload_batch(batch_id)
    if not data:
        return []
    text = str(data.get("text") or "")
    if len(text) < 80:
        return []
    # 正文截断，避免塞爆上下文
    excerpt = text[:12000]
    seeds = [
        {
            "query": f"upload:{data.get('filename') or 'doc'}",
            "content": excerpt,
            "source": "uploaded",
            "timestamp": "",
        }
    ]
    # 参考文献标题单独成块，便于后续二次检索
    titles = data.get("reference_titles") or []
    if titles:
        block = "\n".join(f"[{i+1}] {t}" for i, t in enumerate(titles[:20]))
        seeds.append(
            {
                "query": "upload:references",
                "content": block,
                "source": "uploaded_refs",
                "timestamp": "",
            }
        )
    return seeds
