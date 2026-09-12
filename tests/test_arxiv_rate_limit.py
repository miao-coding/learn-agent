"""ArXiv 限流与缓存行为"""
import time

from backend.tools import arxiv_tool


def test_cache_roundtrip():
    arxiv_tool._SEARCH_CACHE.clear()
    key = arxiv_tool._cache_key("mamba remote sensing", 4)
    arxiv_tool._cache_put(key, "cached-body")
    assert arxiv_tool._cache_get(key) == "cached-body"


def test_throttle_enforces_interval():
    arxiv_tool._last_request_ts = time.monotonic()
    t0 = time.monotonic()
    arxiv_tool._throttle()
    elapsed = time.monotonic() - t0
    # 应至少等待接近最小间隔（允许一点调度误差）
    assert elapsed >= 2.5


def test_cool_until_blocks_search():
    arxiv_tool._arxiv_cool_until = time.time() + 60
    out = arxiv_tool.arxiv_search.invoke({"query": "anything", "max_results": 2})
    assert "限流冷却" in out or "冷却" in out
    arxiv_tool._arxiv_cool_until = 0
