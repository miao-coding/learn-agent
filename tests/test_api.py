"""API 端点测试"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def mock_graph():
    """创建 mock 图对象"""
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=None)
    graph.aupdate_state = AsyncMock()
    return graph


@pytest.fixture
def client(mock_graph):
    """创建测试客户端，绕过 lifespan"""
    # Mock checkpointer 相关避免真实数据库连接
    with patch("backend.main.get_checkpointer"), \
         patch("backend.main.setup_checkpointer", new_callable=AsyncMock), \
         patch("backend.main.build_graph", return_value=mock_graph):

        from fastapi.testclient import TestClient
        from backend.main import app

        # 直接设置 app.state 避免 lifespan 执行
        app.state.graph = mock_graph
        app.state.checkpointer = MagicMock()

        yield TestClient(app)


def test_health_endpoint(client):
    """测试健康检查端点"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_research_endpoint_validation_empty_topic(client):
    """测试研究端点空主题校验"""
    response = client.post("/api/research", json={"topic": ""})
    assert response.status_code == 422


def test_research_endpoint_validation_whitespace_topic(client):
    """测试研究端点空白主题校验"""
    response = client.post("/api/research", json={"topic": "   "})
    assert response.status_code == 422


def test_research_endpoint_returns_thread_id(client):
    """测试研究端点返回 thread_id"""
    response = client.post("/api/research", json={"topic": "2026年储能市场"})
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert len(data["thread_id"]) > 0
    assert data["topic"] == "2026年储能市场"
    assert data["status"] == "started"


def test_research_endpoint_missing_topic(client):
    """测试缺少 topic 字段"""
    response = client.post("/api/research", json={})
    assert response.status_code == 422


def test_report_not_found(client, mock_graph):
    """测试获取不存在的报告"""
    mock_graph.aget_state = AsyncMock(return_value=None)

    response = client.get("/api/research/nonexistent-id/report")
    assert response.status_code == 404


def test_report_not_ready(client, mock_graph):
    """测试报告尚未就绪"""
    mock_state = MagicMock()
    mock_state.values = {"final_report": "", "topic": "测试", "current_phase": "writing"}
    mock_graph.aget_state = AsyncMock(return_value=mock_state)

    response = client.get("/api/research/test-id/report")
    assert response.status_code == 404


def test_report_success(client, mock_graph):
    """测试成功获取报告"""
    mock_state = MagicMock()
    mock_state.values = {
        "final_report": "# 测试报告\n内容",
        "topic": "AI行业",
        "current_phase": "completed",
        "references": [{"id": 1, "title": "来源1"}],
        "charts": ["output/charts/test.png"]
    }
    mock_graph.aget_state = AsyncMock(return_value=mock_state)

    response = client.get("/api/research/test-id/report")
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "test-id"
    assert data["report"] == "# 测试报告\n内容"
    assert data["status"] == "completed"
    assert len(data["references"]) == 1
    assert len(data["charts"]) == 1


def _reviewable_state():
    """构造处于等待审核状态的 mock state"""
    mock_state = MagicMock()
    mock_state.values = {
        "current_phase": "reviewing",
        "revision_count": 0,
        "max_revisions": 3,
        "final_report": "# 草稿",
    }
    return mock_state


def test_review_endpoint(client, mock_graph):
    """测试审核通过（update_state 注入 completed）"""
    mock_graph.aget_state = AsyncMock(return_value=_reviewable_state())
    response = client.post("/api/research/test-id/review", json={"feedback": "通过"})
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "test-id"
    assert data["status"] == "approved"
    mock_graph.aupdate_state.assert_awaited_once()
    assert mock_graph.aupdate_state.call_args.args[1]["current_phase"] == "completed"


def test_review_endpoint_revising(client, mock_graph):
    """测试审核返工（update_state 注入反馈并从断点继续）"""
    mock_graph.aget_state = AsyncMock(return_value=_reviewable_state())
    response = client.post("/api/research/test-id/review", json={"feedback": "需要修改数据部分"})
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "test-id"
    assert data["status"] == "revising"
    mock_graph.aupdate_state.assert_awaited_once()
    update_values = mock_graph.aupdate_state.call_args.args[1]
    assert update_values["current_phase"] == "writing"
    assert update_values["review_feedback"] == "需要修改数据部分"
    assert update_values["revision_count"] == 1


def test_review_max_revisions_reached(client, mock_graph):
    """测试超过最大返工次数时拒绝继续返工"""
    mock_state = MagicMock()
    mock_state.values = {
        "current_phase": "reviewing",
        "revision_count": 3,
        "max_revisions": 3,
        "final_report": "# 草稿",
    }
    mock_graph.aget_state = AsyncMock(return_value=mock_state)
    response = client.post("/api/research/test-id/review", json={"feedback": "再改一次"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert "最大返工次数" in response.json()["message"]
    mock_graph.aupdate_state.assert_not_awaited()


def test_review_task_not_ready_rejected(client, mock_graph):
    """测试任务未就绪时审核被拒（400）"""
    mock_state = MagicMock()
    mock_state.values = {"current_phase": "searching"}
    mock_graph.aget_state = AsyncMock(return_value=mock_state)
    response = client.post("/api/research/test-id/review", json={"feedback": "通过"})
    assert response.status_code == 400


def test_stream_not_found(client):
    """测试 SSE 流不存在的任务"""
    response = client.get("/api/research/nonexistent-id/stream")
    assert response.status_code == 404


def test_history_endpoint(client, mock_graph):
    """测试历史任务列表（持久化于 checkpoints.db）"""
    mock_state = MagicMock()
    mock_state.values = {"topic": "CH4卫星补全", "current_phase": "reviewing"}
    mock_graph.aget_state = AsyncMock(return_value=mock_state)

    with patch("backend.api.routes._load_history_threads", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = [("t-1", "2026-09-10T20:00:00")]
        response = client.get("/api/research/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["thread_id"] == "t-1"
        assert data[0]["topic"] == "CH4卫星补全"
        assert data[0]["status"] == "reviewing"
        assert data[0]["updated_at"] == "2026-09-10T20:00:00"


def test_models_endpoint(client):
    """测试可用模型列表端点"""
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert "default" in data


def test_research_with_model_name_passes_to_graph(client):
    """测试指定 model_name 会传入图初始状态"""
    with patch("backend.api.routes._run_graph", new_callable=AsyncMock) as mock_run, \
         patch("backend.api.routes.settings") as mock_settings:
        mock_settings.get_available_models.return_value = ["deepseek-chat", "gpt-4o"]
        response = client.post(
            "/api/research",
            json={"topic": "储能市场", "model_name": "deepseek-chat"},
        )
        assert response.status_code == 200
        assert mock_run.call_args.kwargs["model_name"] == "deepseek-chat"


def test_research_with_default_model_name_empty(client):
    """测试不传 model_name 时以空串传入图初始状态"""
    with patch("backend.api.routes._run_graph", new_callable=AsyncMock) as mock_run:
        response = client.post("/api/research", json={"topic": "储能市场"})
        assert response.status_code == 200
        assert mock_run.call_args.kwargs["model_name"] == ""


def test_research_with_unknown_model_rejected(client):
    """测试未在白名单内的模型被拒绝（400）"""
    with patch("backend.api.routes.settings") as mock_settings:
        mock_settings.get_available_models.return_value = ["gpt-4o"]
        response = client.post(
            "/api/research",
            json={"topic": "储能市场", "model_name": "hack-model"},
        )
        assert response.status_code == 400
        assert "模型不可用" in response.json()["detail"]


def test_admin_status_endpoint(client):
    """测试配置状态端点（不返回密钥明文）"""
    response = client.get("/api/admin/status")
    assert response.status_code == 200
    data = response.json()
    assert "admin_enabled" in data
    assert "openai_key_set" in data
    assert "tavily_key_set" in data
    assert "api_key" not in data


def test_admin_config_disabled_returns_403(client):
    """测试未设置 ADMIN_PASSWORD 时在线配置被禁用（403）"""
    with patch("backend.api.routes.settings") as mock_settings:
        mock_settings.admin_password = ""
        response = client.post("/api/admin/config", json={"password": "x"})
        assert response.status_code == 403


def test_admin_config_wrong_password_returns_401(client):
    """测试口令错误返回 401"""
    with patch("backend.api.routes.settings") as mock_settings:
        mock_settings.admin_password = "right-pass"
        response = client.post("/api/admin/config", json={"password": "wrong"})
        assert response.status_code == 401
        assert "口令错误" in response.json()["detail"]


def test_admin_config_success_updates_and_persists(client):
    """测试口令正确时更新配置：settings 热更新 + env 持久化 + Tavily 客户端重建"""
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.update_env_file") as mock_env, \
         patch("backend.api.routes.reload_tavily_client") as mock_reload:
        mock_settings.admin_password = "right-pass"
        response = client.post("/api/admin/config", json={
            "password": "right-pass",
            "openai_api_key": "sk-new",
            "tavily_api_key": "tvly-new",
        })
        assert response.status_code == 200
        data = response.json()
        assert set(data["updated"]) == {"OPENAI_API_KEY", "TAVILY_API_KEY"}
        assert mock_settings.openai_api_key == "sk-new"
        assert mock_settings.tavily_api_key == "tvly-new"
        mock_env.assert_called_once()
        mock_reload.assert_called_once()


def test_admin_config_empty_body_updates_nothing(client):
    """测试仅提交口令不修改任何配置"""
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.update_env_file") as mock_env:
        mock_settings.admin_password = "right-pass"
        response = client.post("/api/admin/config", json={"password": "right-pass"})
        assert response.status_code == 200
        assert response.json()["updated"] == []
        mock_env.assert_not_called()


def test_admin_list_models_success(client):
    """测试获取接口可用模型列表（口令正确）"""
    mock_resp = MagicMock()
    mock_resp.data = [MagicMock(id="model-b"), MagicMock(id="model-a")]
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=mock_resp)
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.AsyncOpenAI", return_value=mock_client):
        mock_settings.admin_password = "right-pass"
        mock_settings.openai_api_key = "sk-saved"
        response = client.post("/api/admin/list-models", json={"password": "right-pass"})
        assert response.status_code == 200
        data = response.json()
        assert data["models"] == ["model-a", "model-b"]
        assert data["error"] == ""
        mock_client.models.list.assert_awaited_once()


def test_admin_list_models_wrong_password(client):
    """测试获取模型列表口令错误返回 401"""
    with patch("backend.api.routes.settings") as mock_settings:
        mock_settings.admin_password = "right-pass"
        response = client.post("/api/admin/list-models", json={"password": "wrong"})
        assert response.status_code == 401


def test_admin_list_models_upstream_error(client):
    """测试接口不可达时返回 error 字段（200）"""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=RuntimeError("connection refused"))
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.AsyncOpenAI", return_value=mock_client):
        mock_settings.admin_password = "right-pass"
        mock_settings.openai_api_key = "sk-saved"
        response = client.post("/api/admin/list-models", json={"password": "right-pass"})
        assert response.status_code == 200
        assert "connection refused" in response.json()["error"]


def test_admin_test_model_success(client):
    """测试连接成功场景（真实最小调用被 mock）"""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock())
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.AsyncOpenAI", return_value=mock_client):
        mock_settings.admin_password = "right-pass"
        mock_settings.openai_api_key = "sk-saved"
        mock_settings.openai_model = "gpt-4o"
        response = client.post("/api/admin/test-model", json={
            "password": "right-pass", "openai_model": "deepseek-chat"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "deepseek-chat" in data["message"]
        # 测试用模型名优先于默认模型
        assert mock_client.chat.completions.create.call_args.kwargs["model"] == "deepseek-chat"


def test_admin_test_model_failure(client):
    """测试连接失败场景返回 ok=False 与错误信息"""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Error code: 404 - model not found")
    )
    with patch("backend.api.routes.settings") as mock_settings, \
         patch("backend.api.routes.AsyncOpenAI", return_value=mock_client):
        mock_settings.admin_password = "right-pass"
        mock_settings.openai_api_key = "sk-saved"
        response = client.post("/api/admin/test-model", json={"password": "right-pass"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "404" in data["message"]
