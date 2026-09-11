"""数据模型测试"""
import pytest
from pydantic import ValidationError
from backend.api.schemas import (
    ResearchRequest, ResearchResponse,
    ReviewRequest, ReviewResponse,
    ReportResponse, HealthResponse, AvailableModelsResponse,
    AdminConfigRequest, AdminStatusResponse, AdminTestRequest
)


class TestResearchRequest:
    def test_valid_request(self):
        req = ResearchRequest(topic="2026年储能市场")
        assert req.topic == "2026年储能市场"

    def test_empty_topic_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRequest(topic="")

    def test_whitespace_topic_rejected(self):
        with pytest.raises(ValidationError):
            ResearchRequest(topic="   ")

    def test_topic_stripped(self):
        req = ResearchRequest(topic="  储能市场  ")
        assert req.topic == "储能市场"

    def test_topic_max_length(self):
        """测试主题超过最大长度"""
        long_topic = "a" * 201
        with pytest.raises(ValidationError):
            ResearchRequest(topic=long_topic)

    def test_topic_at_max_length(self):
        """测试主题刚好在最大长度"""
        topic = "a" * 200
        req = ResearchRequest(topic=topic)
        assert req.topic == topic

    def test_model_name_optional_default_none(self):
        """不传 model_name 时默认为 None（使用服务端默认模型）"""
        req = ResearchRequest(topic="测试主题")
        assert req.model_name is None

    def test_model_name_provided(self):
        req = ResearchRequest(topic="测试主题", model_name="deepseek-chat")
        assert req.model_name == "deepseek-chat"

    def test_model_name_max_length(self):
        """测试模型名超过最大长度"""
        with pytest.raises(ValidationError):
            ResearchRequest(topic="测试主题", model_name="x" * 101)


class TestResearchResponse:
    def test_response_fields(self):
        resp = ResearchResponse(thread_id="test-id", topic="测试主题")
        assert resp.thread_id == "test-id"
        assert resp.topic == "测试主题"
        assert resp.status == "started"

    def test_response_custom_status(self):
        resp = ResearchResponse(thread_id="id", topic="主题", status="running")
        assert resp.status == "running"


class TestReviewRequest:
    def test_valid_review(self):
        req = ReviewRequest(feedback="通过")
        assert req.feedback == "通过"

    def test_empty_feedback_allowed(self):
        """空反馈是允许的（视为通过）"""
        req = ReviewRequest(feedback="")
        assert req.feedback == ""

    def test_detailed_feedback(self):
        req = ReviewRequest(feedback="第三部分数据需要更新")
        assert req.feedback == "第三部分数据需要更新"


class TestReviewResponse:
    def test_approved_response(self):
        resp = ReviewResponse(thread_id="id", status="approved", message="已审核通过")
        assert resp.status == "approved"
        assert resp.message == "已审核通过"

    def test_revising_response(self):
        resp = ReviewResponse(thread_id="id", status="revising", message="修改中")
        assert resp.status == "revising"


class TestReportResponse:
    def test_with_references_and_charts(self):
        resp = ReportResponse(
            thread_id="test-id",
            topic="测试",
            report="# 报告",
            status="completed",
            references=[{"id": 1, "title": "来源1"}],
            charts=["output/charts/test.png"]
        )
        assert len(resp.references) == 1
        assert len(resp.charts) == 1

    def test_defaults(self):
        resp = ReportResponse(
            thread_id="id",
            topic="主题",
            report="报告内容",
            status="completed"
        )
        assert resp.references == []
        assert resp.charts == []

    def test_multiple_references(self):
        refs = [{"id": i, "title": f"来源{i}"} for i in range(5)]
        resp = ReportResponse(
            thread_id="id", topic="主题", report="报告",
            status="completed", references=refs
        )
        assert len(resp.references) == 5


class TestHealthResponse:
    def test_default_values(self):
        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "1.0.0"

    def test_custom_values(self):
        resp = HealthResponse(status="error", version="2.0.0")
        assert resp.status == "error"
        assert resp.version == "2.0.0"


class TestAvailableModelsResponse:
    def test_default_values(self):
        resp = AvailableModelsResponse()
        assert resp.models == []
        assert resp.default == ""

    def test_with_models(self):
        resp = AvailableModelsResponse(
            models=["deepseek-chat", "gpt-4o"], default="gpt-4o"
        )
        assert len(resp.models) == 2
        assert resp.default == "gpt-4o"


class TestAdminConfigRequest:
    def test_password_required(self):
        """口令必填"""
        with pytest.raises(ValidationError):
            AdminConfigRequest()

    def test_optional_fields_default_none(self):
        """配置项默认为 None（不修改）"""
        req = AdminConfigRequest(password="p")
        assert req.openai_api_key is None
        assert req.openai_base_url is None
        assert req.tavily_api_key is None

    def test_with_all_fields(self):
        req = AdminConfigRequest(
            password="p",
            openai_api_key="sk-1",
            openai_base_url="https://api.deepseek.com/v1",
            tavily_api_key="tvly-1",
        )
        assert req.openai_api_key == "sk-1"
        assert req.openai_base_url == "https://api.deepseek.com/v1"
        assert req.tavily_api_key == "tvly-1"


class TestAdminStatusResponse:
    def test_default_values(self):
        resp = AdminStatusResponse()
        assert resp.admin_enabled is False
        assert resp.openai_key_set is False
        assert resp.tavily_key_set is False


class TestAdminTestRequest:
    def test_password_required(self):
        """口令必填"""
        with pytest.raises(ValidationError):
            AdminTestRequest()

    def test_optional_fields_default_none(self):
        """测试参数默认为 None（回退当前已保存配置）"""
        req = AdminTestRequest(password="p")
        assert req.openai_api_key is None
        assert req.openai_base_url is None
        assert req.openai_model is None
