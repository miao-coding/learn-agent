"""学术源工具：格式化与 fallback 行为（mock 网络）"""
from unittest.mock import MagicMock, patch

from backend.tools import lit_sources


def test_crossref_parses_items():
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "message": {
            "items": [
                {
                    "title": ["A Review of Deep-Learning Change Detection"],
                    "DOI": "10.3390/rs15082092",
                    "URL": "https://doi.org/10.3390/rs15082092",
                    "author": [{"given": "A", "family": "B"}],
                    "published-print": {"date-parts": [[2023, 4, 1]]},
                    "is-referenced-by-count": 12,
                    "abstract": "<jats:p>Deep learning CD review</jats:p>",
                }
            ]
        }
    }
    with patch("backend.tools.lit_sources.requests.get", return_value=mock):
        out = lit_sources.crossref_search.invoke({"query": "change detection", "max_results": 3})
    assert "A Review of Deep-Learning Change Detection" in out
    assert "10.3390/rs15082092" in out
    assert "crossref" in out


def test_academic_fallback_uses_first_success():
    with patch.object(
        lit_sources, "_crossref_search_impl", return_value="[1] From Crossref\n    URL: https://x"
    ) as c:
        out = lit_sources.academic_fallback_search.invoke({"query": "mamba"})
    assert c.called
    assert "From Crossref" in out
    assert "Crossref" in out


def test_academic_fallback_skips_failures():
    with patch.object(
        lit_sources, "_crossref_search_impl", return_value="Crossref 搜索失败: timeout"
    ), patch.object(
        lit_sources, "_openalex_search_impl", return_value="[1] From OA\n    URL: https://y"
    ) as oa:
        out = lit_sources.academic_fallback_search.invoke({"query": "mamba"})
    assert oa.called
    assert "From OA" in out
