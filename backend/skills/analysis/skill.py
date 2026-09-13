"""analysis Skill 的代码契约（字段校验）"""
from typing import Any

from backend.skills.base import SkillPolicy, SkillSpec

ANALYSIS_REQUIRED_FIELDS = (
    "field_overview",
    "method_categories",
    "performance_comparison",
    "timeline_analysis",
    "research_groups",
    "challenges_and_gaps",
    "key_findings",
    "data_sources",
)


def validate_analysis_payload(data: dict[str, Any] | None) -> list[str]:
    issues: list[str] = []
    if not data or not isinstance(data, dict):
        return ["analysis_data 为空或非字典"]
    if data.get("error"):
        return [f"analysis_data.error: {data.get('error')}"]
    for f in ANALYSIS_REQUIRED_FIELDS:
        if f not in data or data.get(f) in (None, "", {}, []):
            issues.append(f"缺少分析字段: {f}")
    findings = data.get("key_findings")
    if isinstance(findings, list) and len(findings) < 3:
        issues.append("key_findings 少于 3 条")
    return issues


ANALYSIS = SkillSpec(
    name="analysis",
    description="结构化文献分析：方法分类/性能对比/脉络/空白",
    policy=SkillPolicy(required_analysis_fields=ANALYSIS_REQUIRED_FIELDS),
    validator=validate_analysis_payload,
)
