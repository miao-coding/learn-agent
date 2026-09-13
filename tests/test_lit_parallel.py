"""并行学术检索与预搜合并"""
from unittest.mock import patch

from backend.tools import lit_sources


def test_academic_multi_query_merges():
    with patch.object(
        lit_sources, "_crossref_search_impl", return_value="[1] From Crossref Paper Title Long\n    URL: https://doi.org/10.1/x"
    ), patch.object(
        lit_sources, "_openalex_search_impl", return_value="[1] From OpenAlex Paper Title Long\n    URL: https://doi.org/10.2/y"
    ):
        out = lit_sources.academic_multi_query(["mamba survey", "mamba deep learning"], 3)
    assert "From Crossref" in out
    assert "检索词" in out


def test_academic_fallback_parallel_ok():
    with patch.object(
        lit_sources, "_crossref_search_impl", return_value="[1] Fast Crossref Hit Title Here\n    URL: https://doi.org/10.1/z"
    ) as c, patch.object(
        lit_sources, "_openalex_search_impl", return_value="OpenAlex 搜索失败: timeout"
    ):
        out = lit_sources.academic_fallback_search.invoke({"query": "mamba", "max_results": 4})
    assert c.called
    assert "Fast Crossref" in out
    assert "并行检索" in out or "Crossref" in out
