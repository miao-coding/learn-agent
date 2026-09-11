"""P1 引用解析/对账 + P2 历史时间解析"""
from backend.utils.checkpoint_time import format_checkpoint_time, uuid6_to_datetime
from backend.utils.citations import (
    extract_reference_meta,
    parse_body_citations,
    reconcile_references,
)


class TestExtractReferenceMeta:
    def test_arxiv_block(self):
        content = (
            "[3] ChangeMamba\n"
            "    作者: A, B\n"
            "    日期: 2024-03-01\n"
            "    arXiv ID: 2403.00123\n"
            "    摘要: ...\n"
        )
        meta = extract_reference_meta("arxiv", content, "q")
        assert meta["title"] == "ChangeMamba"
        assert meta["url"] == "https://arxiv.org/abs/2403.00123"
        assert meta["date"] == "2024-03-01"

    def test_tavily_block(self):
        content = "[1] Some Paper\n    URL: https://example.com/a\n    摘要: x"
        meta = extract_reference_meta("web", content, "q")
        assert meta["title"] == "Some Paper"
        assert meta["url"] == "https://example.com/a"


class TestReconcile:
    def test_parse_citations(self):
        assert parse_body_citations("方法 [1][3] 与 [10-2] 以及 [23]") == [1, 3, 10, 23]

    def test_missing_id_gets_placeholder(self):
        report = "# T\n\n内容 [2]\n"
        refs = [{"id": 1, "title": "only one", "url": "", "source": "arxiv", "date": ""}]
        new_refs, issues = reconcile_references(report, refs)
        assert any(r["id"] == 2 for r in new_refs)
        assert any("[2]" in i for i in issues)

    def test_no_missing_when_aligned(self):
        report = "# T\n\n内容 [1]\n"
        refs = [{"id": 1, "title": "a", "url": "u", "source": "arxiv", "date": ""}]
        new_refs, issues = reconcile_references(report, refs)
        assert len(new_refs) == 1
        assert not any("不在文献列表" in i for i in issues)


class TestCheckpointTime:
    def test_uuid6_sample(self):
        # 服务器样例 checkpoint_id
        dt = uuid6_to_datetime("1f1adea4-1f2a-6c84-bfff-4789bed2ce0d")
        assert dt is not None
        assert dt.year >= 2024

    def test_format_fallback(self):
        assert format_checkpoint_time("not-a-uuid").startswith("not-a-uuid"[:8])
