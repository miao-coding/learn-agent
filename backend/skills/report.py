"""撰稿 Skill：章节结构与引用完整性校验"""
from __future__ import annotations

import re

from backend.skills.base import SkillPolicy, SkillSpec

REPORT_REQUIRED_SECTIONS = (
    "摘要",
    "引言",
    "研究现状",
    "方法",
    "挑战",
    "总结",
    "参考文献",
)


def validate_report_structure(
    report: str,
    *,
    min_chars: int = 800,
    required_sections: tuple[str, ...] = REPORT_REQUIRED_SECTIONS,
    min_citations: int = 3,
) -> list[str]:
    """校验报告结构（不检查语言润色，只查硬结构）"""
    issues: list[str] = []
    text = report or ""
    if len(text.strip()) < min_chars:
        issues.append(f"报告过短: {len(text.strip())} < {min_chars}")
    if not text.lstrip().startswith("#"):
        issues.append("未以 Markdown 标题开头")
    m = re.search(r"(?m)^##\s*(参考文献|References)\s*$", text, re.I)
    body = text[: m.start()] if m else text
    cites = re.findall(r"\[\d+", body)
    if len(set(cites)) < min_citations:
        issues.append(f"正文引用编号过少: {len(set(cites))} < {min_citations}")
    if not m:
        issues.append("缺少参考文献章节")
    head = text[:4000]
    for sec in required_sections:
        if sec == "参考文献":
            continue
        if sec not in head and sec not in text:
            issues.append(f"缺少章节要素: {sec}")
    return issues


REPORT = SkillSpec(
    name="report",
    description="学术综述报告结构与引用完整性",
    policy=SkillPolicy(
        min_report_chars=800,
        required_sections=REPORT_REQUIRED_SECTIONS,
        min_real_references=3,
    ),
    validator=validate_report_structure,
)
