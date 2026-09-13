"""Agent Skill 规格：把策略从「散文 prompt」收成可测的代码契约

Skill 不是 UI 插件，而是给检索/分析/撰稿用的：
- 工具优先级与预算
- 产出字段/章节要求
- 校验入口
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class SkillPolicy:
    """执行策略（代码可读，不依赖 LLM 自觉）"""

    tool_priority: tuple[str, ...] = ()
    # 每任务最大调用次数（按工具名）
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


# ── 文献检索技能 ─────────────────────────────────────────────────
LIT_SEARCH = SkillSpec(
    name="lit_search",
    description="多源学术检索：Crossref/OpenAlex/EuropePMC/CORE 优先，ArXiv 限量补充",
    policy=SkillPolicy(
        tool_priority=(
            "academic_fallback_search",
            "crossref_search",
            "openalex_search",
            "europepmc_search",
            "core_search",
            "arxiv_search",
            "arxiv_download",
        ),
        tool_budgets={
            "academic_fallback_search": 2,
            "crossref_search": 2,
            "openalex_search": 2,
            "europepmc_search": 1,
            "core_search": 1,
            "arxiv_search": 4,
            "arxiv_download": 1,
            "tavily_search": 1,
            "duckduckgo_search": 2,
            "wikipedia_search": 1,
            "searxng_search": 1,
        },
        min_real_references=6,
    ),
)


# ── 分析技能 ─────────────────────────────────────────────────────
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
    """校验分析师 JSON 是否具备综述所需结构（缺失项列表）"""
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


# ── 撰稿技能 ─────────────────────────────────────────────────────
# 标题匹配用子串，兼容中英文
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
    import re

    issues: list[str] = []
    text = report or ""
    if len(text.strip()) < min_chars:
        issues.append(f"报告过短: {len(text.strip())} < {min_chars}")
    if not text.lstrip().startswith("#"):
        issues.append("未以 Markdown 标题开头")
    # 参考文献前的正文引用
    m = re.search(r"(?m)^##\s*(参考文献|References)\s*$", text, re.I)
    body = text[: m.start()] if m else text
    cites = re.findall(r"\[\d+", body)
    if len(set(cites)) < min_citations:
        issues.append(f"正文引用编号过少: {len(set(cites))} < {min_citations}")
    if not m:
        issues.append("缺少参考文献章节")
    # 必含章节：摘要/引言等可用子串
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


# ── 按主题粗选报告模板（指导撰稿侧重点，非硬切章节目录）──────────
_REPORT_TEMPLATES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("survey", "review", "综述", "overview"),
        "survey",
        "全景综述：强调方法分类谱系、发展脉络、代表性工作对比表、研究空白",
    ),
    (
        ("change detection", "变化检测", "变化", "change"),
        "change_detection",
        "变化检测专题：任务定义（BCD/SCD/损害评估）、数据集与指标、方法家族对比、误差来源",
    ),
    (
        ("mamba", "ssm", "state space"),
        "ssm_mamba",
        "SSM/Mamba 专题：与 CNN/Transformer 复杂度对比、扫描顺序/双向建模、在遥感中的适配",
    ),
    (
        ("ch4", "methane", "甲烷", "no2", "pollution", "污染", "大气"),
        "atmospheric",
        "大气/温室气体专题：观测平台与传感器、反演/补全任务、物理约束与数据驱动融合、验证数据",
    ),
    (
        ("remote sensing", "遥感", "satellite", "卫星"),
        "remote_sensing",
        "遥感专题：影像模态、分辨率/重访、标注与基准、跨域泛化",
    ),
    (
        ("rag", "retrieval", "检索增强"),
        "rag",
        "RAG 专题：检索器-重排-生成链路、评估指标、幻觉与引用治理",
    ),
)


def pick_report_template(topic: str) -> tuple[str, str]:
    """根据主题关键词返回 (template_id, 写作侧重点说明)

    未命中则返回通用综述模板。
    """
    t = (topic or "").lower()
    for keys, tid, focus in _REPORT_TEMPLATES:
        if any(k in t for k in keys):
            return tid, focus
    return "general", "通用文献综述：背景—方法分类—对比—挑战—展望，引用必须来自真实文献"


SKILL_REGISTRY: dict[str, SkillSpec] = {
    LIT_SEARCH.name: LIT_SEARCH,
    ANALYSIS.name: ANALYSIS,
    REPORT.name: REPORT,
}


def get_skill(name: str) -> SkillSpec:
    return SKILL_REGISTRY[name]
