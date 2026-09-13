"""Agent Skill 包：策略、校验与主题模板

子模块：
- base: SkillPolicy / SkillSpec
- lit_search: 检索工具预算
- analysis: 分析 JSON 校验
- report: 报告结构校验
- templates: pick_report_template

对外保持稳定导入路径：`from backend.skills import LIT_SEARCH, ...`
"""
from backend.skills.analysis import (
    ANALYSIS,
    ANALYSIS_REQUIRED_FIELDS,
    validate_analysis_payload,
)
from backend.skills.base import SkillPolicy, SkillSpec
from backend.skills.lit_search import LIT_SEARCH
from backend.skills.report import (
    REPORT,
    REPORT_REQUIRED_SECTIONS,
    validate_report_structure,
)
from backend.skills.templates import pick_report_template

SKILL_REGISTRY: dict[str, SkillSpec] = {
    LIT_SEARCH.name: LIT_SEARCH,
    ANALYSIS.name: ANALYSIS,
    REPORT.name: REPORT,
}


def get_skill(name: str) -> SkillSpec:
    return SKILL_REGISTRY[name]


__all__ = [
    "ANALYSIS",
    "ANALYSIS_REQUIRED_FIELDS",
    "LIT_SEARCH",
    "REPORT",
    "REPORT_REQUIRED_SECTIONS",
    "SKILL_REGISTRY",
    "SkillPolicy",
    "SkillSpec",
    "get_skill",
    "pick_report_template",
    "validate_analysis_payload",
    "validate_report_structure",
]
