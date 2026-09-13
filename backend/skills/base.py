"""Skill 基础类型：策略与规格（代码契约，不靠 LLM 自觉）"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class SkillPolicy:
    """执行策略"""

    tool_priority: tuple[str, ...] = ()
    tool_budgets: dict[str, int] = field(default_factory=dict)
    min_real_references: int = 6
    min_report_chars: int = 800
    required_sections: tuple[str, ...] = ()
    required_analysis_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    policy: SkillPolicy
    validator: Callable[..., list[str]] | None = None
