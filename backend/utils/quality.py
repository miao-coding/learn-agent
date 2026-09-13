"""报告/检索质量评分 — 供 Supervisor 门禁与日志

分数越高越好；返回各维度子分与 issues，便于前端/审核展示。
"""
from __future__ import annotations

import re
from typing import Any

from backend.skills import validate_report_structure


def quality_score_search(search_results: list[dict] | None, references: list[dict] | None) -> dict[str, Any]:
    """检索阶段质量：真实文献数、来源多样性"""
    refs = references or []
    results = search_results or []
    sources = {str(r.get("source") or "") for r in refs}
    n = len(refs)
    score = min(1.0, n / 8.0)  # 8 条以上满分
    diversity = min(1.0, len(sources) / 3.0)
    issues = []
    if n < 6:
        issues.append(f"真实文献偏少: {n} < 6")
    if len(sources) < 2:
        issues.append("来源过于单一")
    total = round(0.7 * score + 0.3 * diversity, 3)
    return {
        "stage": "search",
        "score": total,
        "references_count": n,
        "sources": sorted(sources),
        "result_blocks": len(results),
        "issues": issues,
    }


def quality_score_report(
    report: str,
    references: list[dict] | None,
    *,
    min_chars: int = 800,
) -> dict[str, Any]:
    """报告阶段质量：结构、引用覆盖、长度"""
    refs = references or []
    struct_issues = validate_report_structure(report, min_chars=min_chars)
    text = report or ""
    m = re.search(r"(?m)^##\s*(参考文献|References)\s*$", text, re.I)
    body = text[: m.start()] if m else text
    cited = set(re.findall(r"\[(\d+)", body))
    ref_ids = {int(r.get("id", 0)) for r in refs if r.get("id") is not None}
    coverage = (len(cited & ref_ids) / len(ref_ids)) if ref_ids else 0.0
    length_score = min(1.0, len(text.strip()) / 2500.0)
    struct_score = 1.0 if not struct_issues else max(0.0, 1.0 - 0.15 * len(struct_issues))
    score = round(0.4 * struct_score + 0.35 * coverage + 0.25 * length_score, 3)
    issues = list(struct_issues)
    if ref_ids and len(cited & ref_ids) < 3:
        issues.append("与真实文献对应的正文引用少于 3 处")
    if cited - ref_ids:
        issues.append(f"正文仍含列表外编号: {sorted(cited - ref_ids)[:8]}")
    return {
        "stage": "report",
        "score": score,
        "structure_score": struct_score,
        "citation_coverage": round(coverage, 3),
        "length_score": round(length_score, 3),
        "references_count": len(ref_ids),
        "cited_count": len(cited),
        "issues": issues,
    }


def should_fail_search(quality: dict[str, Any], *, min_score: float = 0.25) -> bool:
    return float(quality.get("score") or 0) < min_score


def should_retry_report(quality: dict[str, Any], *, min_score: float = 0.45) -> bool:
    return float(quality.get("score") or 0) < min_score
