"""免 Key 检索工具单元测试（mock 网络，不真实外呼）"""
from unittest.mock import MagicMock, patch

from backend.tools.web_search_free import (
    duckduckgo_search,
    openalex_search,
    searxng_search,
    semantic_scholar_search,
    wikipedia_search,
)


def test_ddg_empty_query():
    assert "错误" in duckduckgo_search.invoke({"query": "  "})


def test_searxng_connection_error():
    with patch("backend.tools.web_search_free.requests.get", side_effect=ConnectionError("refused")):
        out = searxng_search.invoke({"query": "mamba"})
    assert "无法连接" in out or "失败" in out


def test_semantic_scholar_parses_json():
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "data": [
            {
                "title": "ChangeMamba",
                "year": 2024,
                "citationCount": 12,
                "url": "https://example.com/p",
                "abstract": "A paper",
                "externalIds": {"ArXiv": "2403.001"},
                "authors": [{"name": "A"}, {"name": "B"}],
            }
        ]
    }
    with patch("backend.tools.web_search_free.requests.get", return_value=mock):
        out = semantic_scholar_search.invoke({"query": "mamba change detection", "max_results": 2})
    assert "ChangeMamba" in out
    assert "2403.001" in out


def test_openalex_parses_works():
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {
        "results": [
            {
                "title": "Remote Sensing Survey",
                "publication_year": 2023,
                "cited_by_count": 99,
                "doi": "https://doi.org/10.1/xyz",
                "primary_location": {
                    "landing_page_url": "https://example.org/x",
                    "source": {"display_name": "ISPRS"},
                },
                "open_access": {},
                "authorships": [{"author": {"display_name": "Zhang"}}],
                "abstract_inverted_index": {"Hello": [0], "world": [1]},
            }
        ]
    }
    with patch("backend.tools.web_search_free.requests.get", return_value=mock):
        out = openalex_search.invoke({"query": "remote sensing"})
    assert "Remote Sensing Survey" in out
    assert "ISPRS" in out


def test_wikipedia_import_error_is_soft():
    with patch.dict("sys.modules", {"wikipedia": None}):
        # force import failure path
        out = wikipedia_search.invoke({"query": "Transformer"})
    assert "失败" in out or "未找到" in out or "摘要" in out
