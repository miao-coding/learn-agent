"""引用元数据解析与正文编号对账 — 只保留真实检索到的文献

原则（用户明确要求）：
- 文献列表只能来自检索结果，禁止补「未命名来源」占位
- 禁止用检索 query 冒充论文标题
- 正文中列表外的 [n] 视为模型编造，必须从正文删除
- 参考文献章节用真实列表重编号后整体重写
"""
from __future__ import annotations

import re
from typing import Any


def _is_plausible_title(title: str, query: str = "") -> bool:
    t = (title or "").strip()
    if len(t) < 8:
        return False
    low = t.lower()
    bad = ("未命名", "未知来源", "未知标题", "搜索失败", "未找到", "error", "failed")
    if any(b in low for b in bad):
        return False
    q = (query or "").strip().lower()
    # 与 query 完全相同 → 不是论文标题
    if q and t.lower() == q:
        return False
    return True


def _clean_reference_title(title: str) -> str:
    """清洗文献标题：去 HTML、Crossref review 前缀、过长摘要式文本"""
    import re as _re

    t = _re.sub(r"<[^>]+>", " ", str(title or ""))
    t = _re.sub(r"\s+", " ", t).strip()
    # Crossref 评审条目不是论文本身
    if _re.match(r"(?i)^review\s+for\s+", t):
        return ""
    # 明显是摘要/句子而非标题
    if len(t) > 180 and ("." in t[20:80] or t.count(",") > 6):
        return ""
    if t.lower().startswith(("abstract", "摘要")):
        return ""
    return t[:200]


def extract_reference_meta(
    source: str, content: str, query: str = ""
) -> dict[str, str]:
    """从单条检索结果块中抽出 title / url / date

    arXiv：
        [1] Title
            作者: ...
            日期: 2024-03-01
            arXiv ID: 2301.12345
    Crossref/Scholar/DDG：
        [1] Title
            URL: https://...
            DOI: 10.xxxx/yyy
    """
    text = str(content or "")
    title = ""
    url = ""
    date = ""

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[\d+\]\s*(.+)$", line)
        if m:
            title = m.group(1).strip()[:200]
            break
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()[:200]
            break

    # URL / arXiv / DOI
    m = re.search(r"arXiv ID:\s*([0-9]{4}\.[0-9]{4,5}(v\d+)?)", text)
    if m:
        url = f"https://arxiv.org/abs/{m.group(1)}"
    else:
        m = re.search(r"https?://arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", text)
        if m:
            url = f"https://arxiv.org/abs/{m.group(1)}"
        else:
            m = re.search(r"DOI:\s*(10\.\d{4,9}/\S+)", text, re.I)
            if m:
                doi = m.group(1).rstrip(".,;)")
                url = f"https://doi.org/{doi}"
            else:
                m = re.search(r"https?://doi\.org/(10\.\d{4,9}/\S+)", text, re.I)
                if m:
                    url = f"https://doi.org/{m.group(1).rstrip('.,;)')}"
                else:
                    m = re.search(r"URL:\s*(https?://\S+)", text)
                    if m:
                        url = m.group(1).rstrip("),.;")

    m = re.search(r"日期:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    if m:
        date = m.group(1)
    else:
        m = re.search(r"年份:\s*([0-9]{4})", text)
        if m:
            date = m.group(1)
        else:
            m = re.search(r"date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.I)
            if m:
                date = m.group(1)

    # 不再用 query 冒充标题；无标题则留空，由调用方决定是否丢弃
    cleaned_title = _clean_reference_title(title) if title else ""
    if cleaned_title and not _is_plausible_title(cleaned_title, query):
        cleaned_title = ""
    return {
        "title": cleaned_title,
        "url": url,
        "date": date,
        "source": source or "web",
    }


def split_search_result_entries(content: str) -> list[str]:
    """把一次检索返回的多篇论文块切成列表

    形如：
        [1] TitleA\n...\n[2] TitleB\n...
    """
    text = str(content or "")
    if not text.strip():
        return []
    # 去掉尾部「（来源: xxx）」
    text = re.sub(r"（来源:\s*[^）]+）\s*$", "", text.strip())
    parts = re.split(r"(?m)^(?=\[\d+\]\s+)", text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) == 1 and not parts[0].startswith("["):
        return [parts[0]]
    return parts


def build_references_from_search_results(
    search_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将检索员结果转成带真实 title/url 的 references（连续 1..N）

    - 每条 search_result 的 content 可能含多篇论文
    - 丢弃无标题且无 URL 的块
    """
    refs: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    rid = 1
    for item in search_results or []:
        source = str(item.get("source") or "web")
        # 上传文件只作分析上下文，不进入「可引用文献」列表
        if source in ("uploaded", "uploaded_refs"):
            continue
        query = str(item.get("query") or "")
        content = str(item.get("content") or item.get("result") or "")
        if not content.strip():
            continue
        if any(x in content for x in ("搜索失败", "配置错误", "Unauthorized", "限流冷却")):
            continue
        for block in split_search_result_entries(content):
            meta = extract_reference_meta(source, block, query)
            title = meta.get("title") or ""
            url = meta.get("url") or ""
            # 至少要有可信标题，或有 URL/DOI/arXiv
            if not title and not url:
                continue
            if not title and url:
                title = url.rstrip("/").split("/")[-1][:80] or "文献"
            title = _clean_reference_title(title)
            if not title and not url:
                continue
            if not title and url:
                title = url.rstrip("/").split("/")[-1][:80] or "文献"
            key = (url or title).lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            refs.append(
                {
                    "id": rid,
                    "title": title[:200],
                    "url": url,
                    "source": source,
                    "date": meta.get("date") or "",
                }
            )
            rid += 1
    return refs


def parse_body_citations(report: str, stop_at_references: bool = True) -> list[int]:
    """提取正文中的引用编号（可选在「参考文献」章节前停止）"""
    text = report or ""
    if stop_at_references:
        m = re.search(r"(?m)^##\s*(参考文献|References|Bibliography)\s*$", text, re.I)
        if m:
            text = text[: m.start()]
    ids: set[int] = set()
    for m in re.finditer(r"\[(\d+)(?:-\d+)?\]", text):
        n = int(m.group(1))
        if 1 <= n <= 999:
            ids.add(n)
    return sorted(ids)


def _split_refs_section(report: str) -> tuple[str, str]:
    m = re.search(r"(?m)^##\s*(参考文献|References|Bibliography)\s*$", report or "", re.I)
    if not m:
        return report or "", ""
    return report[: m.start()], report[m.start() :]


def strip_invalid_citations(report: str, valid_ids: set[int]) -> tuple[str, int]:
    """删除正文（参考文献章节之前）中不在 valid_ids 的 [n] 引用"""
    if not report:
        return report, 0
    head, tail = _split_refs_section(report)
    removed = 0

    def _repl(match: re.Match) -> str:
        nonlocal removed
        n = int(match.group(1))
        if n in valid_ids:
            return match.group(0)
        removed += 1
        return ""

    head_new = re.sub(r"\[(\d+)(?:-\d+)?\]", _repl, head)
    head_new = re.sub(r"[ \t]{2,}", " ", head_new)
    head_new = re.sub(r"\n{3,}", "\n\n", head_new)
    return head_new + tail, removed


def remap_body_citations(report: str, id_map: dict[int, int]) -> str:
    """按 old→new 映射重写正文引用编号（参考文献章节前）"""
    if not report or not id_map:
        return report
    head, tail = _split_refs_section(report)

    def _repl(match: re.Match) -> str:
        n = int(match.group(1))
        new = id_map.get(n)
        if new is None:
            return ""
        sub = match.group(2) or ""
        return f"[{new}{sub}]"

    head_new = re.sub(r"\[(\d+)(-\d+)?\]", _repl, head)
    head_new = re.sub(r"[ \t]{2,}", " ", head_new)
    head_new = re.sub(r"\n{3,}", "\n\n", head_new)
    return head_new + tail


def filter_real_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留可视为真实检索产物的条目（排除上传材料）"""
    out = []
    for r in references or []:
        if not r or r.get("id") is None:
            continue
        title = str(r.get("title") or "")
        url = str(r.get("url") or "")
        source = str(r.get("source") or "")
        if source in ("unknown", "", "uploaded", "uploaded_refs"):
            continue
        if "未命名" in title or "未知来源" in title:
            continue
        title = _clean_reference_title(title)
        if not _is_plausible_title(title) and not url:
            continue
        item = dict(r)
        item["title"] = title or item.get("title") or "文献"
        out.append(item)
    return out


def format_references_section(references: list[dict[str, Any]]) -> str:
    """用真实检索条目生成标准参考文献章节（Markdown）"""
    lines = ["## 参考文献", ""]
    refs = sorted(references or [], key=lambda r: int(r.get("id", 0)))
    for r in refs:
        rid = r.get("id", "")
        title = r.get("title") or "文献"
        url = r.get("url") or ""
        source = r.get("source") or ""
        date = r.get("date") or ""
        meta_bits = [b for b in (source, date) if b]
        meta = f" ({' · '.join(meta_bits)})" if meta_bits else ""
        if url:
            lines.append(f"[{rid}] [{title}]({url}){meta}")
        else:
            lines.append(f"[{rid}] {title}{meta}")
    lines.append("")
    return "\n".join(lines)


def replace_references_section(report: str, references: list[dict[str, Any]]) -> str:
    """把报告中的参考文献章节整体替换为真实列表；没有则追加"""
    section = format_references_section(references)
    if not report:
        return section
    head, _ = _split_refs_section(report)
    return head.rstrip() + "\n\n" + section


def reconcile_references(
    report: str, references: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """强制「正文引用 ⊆ 真实 references」

    1. 过滤非法/占位条目  
    2. 重编号 1..N 并映射正文  
    3. 删除映射后仍无效的 [n]  
    4. 重写参考文献章节  

    Returns:
        (清洗后的 report, 真实 references 列表, 问题说明)
    """
    raw = filter_real_references(references)
    issues: list[str] = []

    # 仅保留在正文中出现过的编号（按原 id），避免列表塞入从未引用的可疑条目
    body_ids = set(parse_body_citations(report))
    used = [r for r in raw if int(r["id"]) in body_ids] if body_ids else list(raw)
    if body_ids and len(used) < len(raw):
        issues.append(f"丢弃 {len(raw) - len(used)} 条正文未引用的列表项")

    # 重编号 1..N
    id_map: dict[int, int] = {}
    renumbered: list[dict[str, Any]] = []
    for i, r in enumerate(used, 1):
        old = int(r["id"])
        id_map[old] = i
        item = dict(r)
        item["id"] = i
        renumbered.append(item)

    cleaned = remap_body_citations(report or "", id_map)
    valid_ids = set(range(1, len(renumbered) + 1))
    cleaned, removed = strip_invalid_citations(cleaned, valid_ids)
    if removed:
        issues.append(f"删除正文中 {removed} 处无法映射到真实文献的引用编号")

    cleaned = replace_references_section(cleaned, renumbered)
    issues.append(f"参考文献已重编号并重写（{len(renumbered)} 条真实文献）")

    return cleaned, renumbered, issues
