"""Agent Skill 包

每个技能一个目录：
  <skill_name>/SKILL.md   — 给 LLM 读的技能说明（真正的 skill 文件）
  <skill_name>/skill.py   — 可执行契约（预算、校验函数）

对外导入路径保持稳定：
  from backend.skills import LIT_SEARCH, validate_report_structure, pick_report_template
"""
from __future__ import annotations

from pathlib import Path

from backend.skills.analysis.skill import (
    ANALYSIS,
    ANALYSIS_REQUIRED_FIELDS,
    validate_analysis_payload,
)
from backend.skills.base import SkillPolicy, SkillSpec
from backend.skills.lit_search.skill import LIT_SEARCH
from backend.skills.report.skill import (
    REPORT,
    REPORT_REQUIRED_SECTIONS,
    validate_report_structure,
)
from backend.skills.templates.skill import pick_report_template

SKILLS_DIR = Path(__file__).resolve().parent

SKILL_REGISTRY: dict[str, SkillSpec] = {
    LIT_SEARCH.name: LIT_SEARCH,
    ANALYSIS.name: ANALYSIS,
    REPORT.name: REPORT,
}


def get_skill(name: str) -> SkillSpec:
    return SKILL_REGISTRY[name]


def load_skill_md(name: str) -> str:
    """读取技能的 SKILL.md 全文（含 frontmatter）"""
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_skill_body(name: str) -> str:
    """读取 SKILL.md 正文（去掉 YAML frontmatter），可注入 System Prompt"""
    text = load_skill_md(name)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :].lstrip("\n")
    return text


def list_skill_names() -> list[str]:
    """列出含 SKILL.md 的技能目录名"""
    names = []
    for p in sorted(SKILLS_DIR.iterdir()):
        if p.is_dir() and (p / "SKILL.md").exists():
            names.append(p.name)
    return names


__all__ = [
    "ANALYSIS",
    "ANALYSIS_REQUIRED_FIELDS",
    "LIT_SEARCH",
    "REPORT",
    "REPORT_REQUIRED_SECTIONS",
    "SKILLS_DIR",
    "SKILL_REGISTRY",
    "SkillPolicy",
    "SkillSpec",
    "get_skill",
    "list_skill_names",
    "load_skill_body",
    "load_skill_md",
    "pick_report_template",
    "validate_analysis_payload",
    "validate_report_structure",
]
