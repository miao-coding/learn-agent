"""引用元数据解析与正文编号对账（P1）"""
from __future__ import annotations

import re
from typing import Any


def extract_reference_meta(
    source: str, content: str, query: str = ""
) -> dict[str, str]:
    """从检索工具返回文本中尽量抽出 title / url / date

    arXiv 格式：
        [1] Title
            作者: ...
            日期: 2024-03-01
            arXiv ID: 2301.12345
    Tavily 格式：
        [1] Title
            URL: https://...
            摘要: ...
    """
    text = str(content or "")
    title = ""
    url = ""
    date = ""

    # 标题：第一行去掉 [n] 前缀
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[\d+\]\s*(.+)$", line)
        if m:
            title = m.group(1).strip()[:180]
            break
        # arXiv 单条可能以 Title: 开头
        if line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()[:180]
            break

    m = re.search(r"arXiv ID:\s*([0-9]{4}\.[0-9]{4,5}(v\d+)?)", text)
    if m:
        url = f"https://arxiv.org/abs/{m.group(1)}"
    else:
        m = re.search(r"https?://arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", text)
        if m:
            url = f"https://arxiv.org/abs/{m.group(1)}"
        else:
            m = re.search(r"URL:\s*(https?://\S+)", text)
            if m:
                url = m.group(1).rstrip("),.;")

    m = re.search(r"日期:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    if m:
        date = m.group(1)
    else:
        m = re.search(r"date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.I)
        if m:
            date = m.group(1)

    if not title:
        title = (query or "未知来源")[:180]

    return {"title": title, "url": url, "date": date, "source": source or "web"}


def parse_body_citations(report: str) -> list[int]:
    """提取正文中的引用编号（支持 [1] 与 [10-2] 的主编号）"""
    ids: set[int] = set()
    for m in re.finditer(r"\[(\d+)(?:-\d+)?\]", report or ""):
        n = int(m.group(1))
        if 1 <= n <= 999:
            ids.add(n)
    return sorted(ids)


def reconcile_references(
    report: str, references: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """正文编号与 references 列表对账

    - 缺失编号：补占位条目（title=未命名来源）
    - 返回 (新列表, 问题说明列表)
    """
    refs = list(references or [])
    by_id = {int(r.get("id", 0)): r for r in refs if r.get("id") is not None}
    issues: list[str] = []
    body_ids = parse_body_citations(report)

    for n in body_ids:
        if n not in by_id:
            refs.append(
                {
                    "id": n,
                    "title": "未命名来源（正文引用但检索列表缺失）",
                    "url": "",
                    "source": "unknown",
                    "date": "",
                }
            )
            by_id[n] = refs[-1]
            issues.append(f"正文引用 [{n}] 不在文献列表，已补占位")

    # 按 id 排序并重新连续编号仅当乱序严重时不重排（保持与正文一致）
    refs_sorted = sorted(refs, key=lambda r: int(r.get("id", 0)))
    body_set = set(body_ids)
    orphans = [int(r.get("id", 0)) for r in refs_sorted if int(r.get("id", 0)) not in body_set]
    if orphans:
        issues.append(f"文献列表中未在正文出现的编号: {orphans[:12]}")

    return refs_sorted, issues
