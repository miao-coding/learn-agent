"""文献检索 Skill：工具优先级与每任务预算"""
from backend.skills.base import SkillPolicy, SkillSpec

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
