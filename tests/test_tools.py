"""工具层单元测试"""
import pytest
from unittest.mock import patch, MagicMock


class TestTavilySearch:
    """Tavily 搜索工具测试"""

    @patch("backend.tools.search.get_tavily_client")
    def test_search_success(self, mock_get_client):
        """测试搜索成功返回"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "测试摘要",
            "results": [
                {"title": "测试标题", "url": "https://example.com", "content": "测试内容"}
            ]
        }
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_search
        result = tavily_search.invoke({"query": "测试查询"})

        assert "测试标题" in result
        assert "https://example.com" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_search_api_error(self, mock_get_client):
        """测试 API 错误处理"""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_search
        result = tavily_search.invoke({"query": "测试"})

        assert "搜索失败" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_search_no_results(self, mock_get_client):
        """测试无结果"""
        mock_client = MagicMock()
        mock_client.search.return_value = {"answer": None, "results": []}
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_search
        result = tavily_search.invoke({"query": "不存在的内容"})

        assert "未找到" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_search_with_answer(self, mock_get_client):
        """测试带 AI 摘要的搜索"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "AI 生成的摘要",
            "results": []
        }
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_search
        result = tavily_search.invoke({"query": "测试"})

        assert "AI 摘要" in result
        assert "AI 生成的摘要" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_search_multiple_results(self, mock_get_client):
        """测试多条搜索结果"""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": None,
            "results": [
                {"title": "结果1", "url": "https://a.com", "content": "内容A"},
                {"title": "结果2", "url": "https://b.com", "content": "内容B"},
                {"title": "结果3", "url": "https://c.com", "content": "内容C"},
            ]
        }
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_search
        result = tavily_search.invoke({"query": "多项搜索"})

        assert "结果1" in result
        assert "结果2" in result
        assert "结果3" in result


class TestTavilyExtract:
    """Tavily 内容提取工具测试"""

    @patch("backend.tools.search.get_tavily_client")
    def test_extract_success(self, mock_get_client):
        """测试内容提取成功"""
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [
                {"url": "https://example.com", "raw_content": "提取的网页内容"}
            ]
        }
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_extract
        result = tavily_extract.invoke({"urls": ["https://example.com"]})

        assert "提取的网页内容" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_extract_no_results(self, mock_get_client):
        """测试提取无结果"""
        mock_client = MagicMock()
        mock_client.extract.return_value = {"results": []}
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_extract
        result = tavily_extract.invoke({"urls": ["https://empty.com"]})

        assert "未能提取" in result

    @patch("backend.tools.search.get_tavily_client")
    def test_extract_error(self, mock_get_client):
        """测试提取失败"""
        mock_client = MagicMock()
        mock_client.extract.side_effect = Exception("Extract Error")
        mock_get_client.return_value = mock_client

        from backend.tools.search import tavily_extract
        result = tavily_extract.invoke({"urls": ["https://error.com"]})

        assert "内容提取失败" in result


class TestArxivTools:
    """ArXiv 工具测试"""

    @patch("backend.tools.arxiv_tool.get_arxiv_client")
    def test_arxiv_search_success(self, mock_get_client):
        """测试 ArXiv 搜索成功"""
        mock_paper = MagicMock()
        mock_paper.title = "Test Paper"
        # MagicMock(name=...) 设置的是 mock 内部名称，需要用属性方式设置
        author_mock = MagicMock()
        author_mock.name = "Author A"
        mock_paper.authors = [author_mock]
        mock_paper.published.strftime.return_value = "2025-01-01"
        mock_paper.entry_id = "http://arxiv.org/abs/2301.12345"
        # arxiv 库的 categories 是 list 类型（修复过把它当 str 的 bug）
        mock_paper.categories = ["cs.AI", "cs.LG"]
        mock_paper.summary = "This is a test abstract for the paper."

        mock_client = MagicMock()
        mock_client.results.return_value = [mock_paper]
        mock_get_client.return_value = mock_client

        # Mock arxiv 模块（局部导入，需要 create=True）
        mock_arxiv = MagicMock()
        mock_arxiv.Search.return_value = MagicMock()
        mock_arxiv.SortCriterion.Relevance = "relevance"

        with patch.dict("sys.modules", {"arxiv": mock_arxiv}):
            from backend.tools.arxiv_tool import arxiv_search
            result = arxiv_search.invoke({"query": "AI testing"})

        assert "Test Paper" in result
        assert "Author A" in result

    @patch("backend.tools.arxiv_tool.get_arxiv_client")
    def test_arxiv_search_no_results(self, mock_get_client):
        """测试 ArXiv 无结果"""
        mock_client = MagicMock()
        mock_client.results.return_value = []
        mock_get_client.return_value = mock_client

        mock_arxiv = MagicMock()
        mock_arxiv.Search.return_value = MagicMock()
        mock_arxiv.SortCriterion.Relevance = "relevance"

        with patch.dict("sys.modules", {"arxiv": mock_arxiv}):
            from backend.tools.arxiv_tool import arxiv_search
            result = arxiv_search.invoke({"query": "nonexistent topic"})

        assert "未找到" in result

    @patch("backend.tools.arxiv_tool.get_arxiv_client")
    def test_arxiv_search_error(self, mock_get_client):
        """测试 ArXiv 搜索错误"""
        mock_client = MagicMock()
        mock_client.results.side_effect = Exception("Network Error")
        mock_get_client.return_value = mock_client

        mock_arxiv = MagicMock()
        mock_arxiv.Search.return_value = MagicMock()
        mock_arxiv.SortCriterion.Relevance = "relevance"

        with patch.dict("sys.modules", {"arxiv": mock_arxiv}):
            from backend.tools.arxiv_tool import arxiv_search
            result = arxiv_search.invoke({"query": "test"})

        assert "搜索失败" in result


class TestArxivDownload:
    """论文下载测试（兼容 arxiv 2.x / 4.x API）"""

    def test_download_success_4x(self, tmp_path):
        """arxiv 4.x：无 pdf_url，通过 source_url 下载"""
        import backend.tools.arxiv_tool as arxiv_mod

        mock_paper = MagicMock()
        mock_paper.title = "DL Paper"
        mock_paper.source_url = "http://arxiv.org/pdf/2301.12345v1"
        mock_paper.pdf_url = None  # 4.x 无此属性
        author_mock = MagicMock()
        author_mock.name = "Author A"
        mock_paper.authors = [author_mock]

        mock_client = MagicMock()
        mock_client.results.return_value = [mock_paper]
        mock_arxiv = MagicMock()
        mock_arxiv.Search.return_value = MagicMock()

        page = MagicMock()
        page.get_text.return_value = "extracted text "
        mock_doc = MagicMock()
        mock_doc.__iter__.return_value = iter([page])
        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_resp = MagicMock()
        mock_resp.content = b"%PDF-1.4 fake"
        mock_get = MagicMock(return_value=mock_resp)

        with patch.object(arxiv_mod, "OUTPUT_DIR", tmp_path), \
             patch("backend.tools.arxiv_tool.get_arxiv_client", return_value=mock_client), \
             patch.dict("sys.modules", {"arxiv": mock_arxiv, "fitz": mock_fitz}), \
             patch("backend.tools.arxiv_tool.requests.get", mock_get):
            from backend.tools.arxiv_tool import arxiv_download
            result = arxiv_download.invoke({"paper_id": "2301.12345"})

        assert "DL Paper" in result
        assert "extracted text" in result
        mock_get.assert_called_once()
        assert "paas" not in mock_get.call_args.args[0]
        assert "arxiv.org/pdf" in mock_get.call_args.args[0]

    def test_download_no_results(self, tmp_path):
        """论文不存在时返回提示"""
        mock_client = MagicMock()
        mock_client.results.return_value = []
        mock_arxiv = MagicMock()
        mock_arxiv.Search.return_value = MagicMock()

        with patch("backend.tools.arxiv_tool.get_arxiv_client", return_value=mock_client), \
             patch.dict("sys.modules", {"arxiv": mock_arxiv}):
            from backend.tools.arxiv_tool import arxiv_download
            result = arxiv_download.invoke({"paper_id": "9999.99999"})

        assert "未找到论文" in result


class TestVisualizationTools:
    """可视化工具测试"""

    def test_generate_trend_chart(self, tmp_path):
        """测试趋势图生成"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_trend_chart
            data = json.dumps({
                "title": "测试趋势",
                "x_label": "年份",
                "y_label": "亿元",
                "series": [
                    {"name": "市场规模", "x": [2022, 2023, 2024], "y": [100, 200, 300]}
                ]
            })
            result = generate_trend_chart.invoke({"data_json": data, "chart_name": "test_trend"})

            assert "图表已生成" in result

    def test_generate_trend_chart_empty_series(self, tmp_path):
        """测试空 series 数据"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_trend_chart
            data = json.dumps({
                "title": "空数据",
                "series": []
            })
            result = generate_trend_chart.invoke({"data_json": data, "chart_name": "empty"})

            assert "错误" in result

    def test_generate_trend_chart_invalid_json(self, tmp_path):
        """测试无效 JSON"""
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_trend_chart
            result = generate_trend_chart.invoke({"data_json": "not valid json", "chart_name": "bad"})

            assert "JSON" in result or "错误" in result

    def test_generate_competition_chart_pie(self, tmp_path):
        """测试竞争格局饼图生成"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_competition_chart
            data = json.dumps({
                "title": "测试份额",
                "chart_type": "pie",
                "items": [
                    {"name": "公司A", "value": 40},
                    {"name": "公司B", "value": 35},
                    {"name": "公司C", "value": 25}
                ]
            })
            result = generate_competition_chart.invoke({"data_json": data, "chart_name": "test_pie"})

            assert "图表已生成" in result

    def test_generate_competition_chart_bar(self, tmp_path):
        """测试竞争格局柱状图生成"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_competition_chart
            data = json.dumps({
                "title": "测试柱状",
                "chart_type": "bar",
                "items": [
                    {"name": "A", "value": 50},
                    {"name": "B", "value": 30}
                ]
            })
            result = generate_competition_chart.invoke({"data_json": data, "chart_name": "test_bar"})

            assert "图表已生成" in result

    def test_generate_competition_chart_empty_items(self, tmp_path):
        """测试空 items 数据"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_competition_chart
            data = json.dumps({
                "title": "空数据",
                "items": []
            })
            result = generate_competition_chart.invoke({"data_json": data, "chart_name": "empty"})

            assert "错误" in result

    def test_generate_comparison_chart(self, tmp_path):
        """测试多维度对比柱状图"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_comparison_chart
            data = json.dumps({
                "title": "对比图",
                "categories": ["维度1", "维度2", "维度3"],
                "groups": [
                    {"name": "对象A", "values": [80, 90, 70]},
                    {"name": "对象B", "values": [60, 85, 95]}
                ]
            })
            result = generate_comparison_chart.invoke({"data_json": data, "chart_name": "test_compare"})

            assert "图表已生成" in result

    def test_generate_comparison_chart_empty(self, tmp_path):
        """测试空 categories/groups"""
        import json
        from unittest.mock import patch

        with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
            from backend.tools.visualization import generate_comparison_chart
            data = json.dumps({
                "title": "空数据",
                "categories": [],
                "groups": []
            })
            result = generate_comparison_chart.invoke({"data_json": data, "chart_name": "empty"})

            assert "错误" in result
