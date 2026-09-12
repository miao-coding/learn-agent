"""引用元数据解析与正文编号对账 — 只保留真实检索到的文献

原则（用户明确要求）：
- 文献列表只能来自检索结果，禁止补「未命名来源」占位
- 正文中列表外的 [n] 视为模型编造，必须从正文删除
- 报告末尾的「参考文献」章节用真实列表整体重写
"""
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
    Scholar / DDG 格式：
        [1] Title
            URL: https://...
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
            title = m.group(1).strip()[:180]
            break
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


def strip_invalid_citations(report: str, valid_ids: set[int]) -> tuple[str, int]:
    """删除正文（参考文献章节之前）中不在 valid_ids 的 [n] 引用

    Returns:
        (清洗后的报告, 删除的引用次数)
    """
    if not report:
        return report, 0

    m = re.search(r"(?m)^##\s*(参考文献|References|Bibliography)\s*$", report, re.I)
    if m:
        head, tail = report[: m.start()], report[m.start() :]
    else:
        head, tail = report, ""

    removed = 0

    def _repl(match: re.Match) -> str:
        nonlocal removed
        n = int(match.group(1))
        if n in valid_ids:
            return match.group(0)
        removed += 1
        return ""

    head_new = re.sub(r"\s*\[(\d+)(?:-\d+)?\]", _repl, head)
    # 清理连续空白
    head_new = re.sub(r"[ \t]{2,}", " ", head_new)
    head_new = re.sub(r"\n{3,}", "\n\n", head_new)
    return head_new + tail, removed


def format_references_section(references: list[dict[str, Any]]) -> str:
    """用真实检索条目生成标准参考文献章节（Markdown）"""
    lines = ["## 参考文献", ""]
    refs = sorted(references or [], key=lambda r: int(r.get("id", 0)))
    for r in refs:
        rid = r.get("id", "")
        title = r.get("title") or "未知标题"
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
    real_refs = [r for r in (references or []) if r.get("title") and "未命名" not in str(r.get("title"))]
    section = format_references_section(real_refs)
    if not report:
        return section

    m = re.search(r"(?m)^##\s*(参考文献|References|Bibliography)\s*$", report, re.I)
    if m:
        return report[: m.start()].rstrip() + "\n\n" + section
    return report.rstrip() + "\n\n" + section


def reconcile_references(
    report: str, references: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """保证「正文编号 ⊆ 真实 references」，并重写参考文献章节

    策略：
    1. 只保留真实 references（过滤「未命名」占位）
    2. 删除正文中列表外的 [n]（模型编造）
    3. 用真实列表重写「参考文献」章节

    Returns:
        (清洗后的 report, 真实 references 列表, 问题说明)
    """
    refs = [
        r
        for r in (references or [])
        if r.get("id") is not None
        and r.get("title")
        and "未命名" not in str(r.get("title"))
        and str(r.get("source") or "") != "unknown"
    ]
    refs = sorted(refs, key=lambda r: int(r.get("id", 0)))
    valid_ids = {int(r["id"]) for r in refs}
    issues: list[str] = []

    cleaned, removed = strip_invalid_citations(report, valid_ids)
    if removed:
        issues.append(f"删除正文中 {removed} 处列表外/编造引用编号")

    cleaned = replace_references_section(cleaned, refs)
    issues.append(f"参考文献章节已用真实检索列表重写（{len(refs)} 条）")

    # 编号若不连续（1..N）仅提示，不重排以免与正文错位
    if valid_ids and max(valid_ids) != len(refs):
        issues.append(f"引用编号不连续，当前有效编号集合: {sorted(valid_ids)[:20]}")

    return cleaned, refs, issues
