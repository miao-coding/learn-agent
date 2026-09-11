"""P0：失败短路、工具失败识别、撰稿输出校验"""
from backend.agents.searcher import _is_tool_failure
from backend.agents.writer import _strip_llm_preamble, _validate_report


class TestToolFailureMarkers:
    def test_tavily_unauthorized(self):
        assert _is_tool_failure("搜索失败: Unauthorized: missing or invalid API key.")

    def test_config_error(self):
        assert _is_tool_failure("配置错误: TAVILY_API_KEY 未配置")

    def test_empty_search(self):
        assert _is_tool_failure("未找到相关搜索结果")

    def test_arxiv_empty_paper_marker(self):
        assert _is_tool_failure("未找到相关学术论文")

    def test_normal_result_not_failure(self):
        assert not _is_tool_failure("[1] Mamba paper\n    URL: https://arxiv.org/abs/x\n    摘要: ...")

    def test_arxiv_hits_not_failure(self):
        assert not _is_tool_failure("Title: ChangeMamba\nAuthors: ...\nAbstract: ...")


class TestValidateReport:
    def test_empty(self):
        assert _validate_report("") == ["报告为空"]

    def test_clean_report_passes(self):
        text = "# 标题\n\n## 摘要\n\n内容 [1]\n\n## 参考文献\n\n[1] foo\n"
        assert _validate_report(text) == []

    def test_duplicate_h1(self):
        text = "# A\n\n正文\n\n# A\n\n正文2\n"
        issues = _validate_report(text)
        assert any("一级标题重复" in i for i in issues)

    def test_duplicate_references(self):
        text = "# T\n\n## 摘要\n\nx\n\n## 参考文献\n\n[1] a\n\n## 参考文献\n\n[1] a\n"
        issues = _validate_report(text)
        assert any("参考文献" in i for i in issues)

    def test_process_marker(self):
        text = "# T\n\n所有关键文献已核实完毕。\n"
        issues = _validate_report(text)
        assert any("过程说明" in i for i in issues)

    def test_replacement_char(self):
        text = "# T\n\n## 摘要\n\n破�坏\n"
        assert any("乱码" in i for i in _validate_report(text))


class TestStripPreamble:
    def test_strips_meta_prefix(self):
        raw = "所有关键文献已核实完毕。以下是完整的文献综述报告：\n\n---\n\n# 正式标题\n\n正文"
        out = _strip_llm_preamble(raw)
        assert out.startswith("# 正式标题")

    def test_keeps_first_h1_only(self):
        raw = "# 第一篇\n\n正文A\n\n# 第二篇\n\n正文B"
        out = _strip_llm_preamble(raw)
        assert out.count("# ") == 1 or out.startswith("# 第一篇")
        assert "第二篇" not in out

    def test_clean_text_unchanged(self):
        raw = "# 标题\n\n内容"
        assert _strip_llm_preamble(raw).startswith("# 标题")


class TestFailedPhaseShortCircuit:
    def test_analyst_passthrough_when_failed(self):
        import asyncio
        from backend.agents.analyst import analyst_agent

        result = asyncio.run(
            analyst_agent(
                {
                    "topic": "t",
                    "search_results": [],
                    "current_phase": "failed",
                    "report_draft": "# t\n\n> fail",
                }
            )
        )
        assert result["current_phase"] == "failed"

    def test_writer_error_is_failed_not_reviewing(self):
        import asyncio
        from backend.agents.writer import writer_agent

        result = asyncio.run(
            writer_agent(
                {
                    "topic": "t",
                    "analysis_data": {"error": "搜索结果为空，无法进行分析"},
                    "current_phase": "analyzing",
                    "references": [],
                }
            )
        )
        assert result["current_phase"] == "failed"
        assert "任务失败" in result["report_draft"]
