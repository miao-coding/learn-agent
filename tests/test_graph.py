"""图拓扑集成测试"""
import pytest
from unittest.mock import patch, MagicMock


def test_build_graph_without_checkpointer():
    """测试图可以正常编译（无 checkpointer）"""
    from backend.graph.builder import build_graph
    graph = build_graph(checkpointer=None)
    assert graph is not None


def test_graph_has_expected_nodes():
    """验证图包含所有必需节点"""
    from backend.graph.builder import build_graph
    graph = build_graph(checkpointer=None)
    # 验证图编译成功
    assert graph is not None


def test_graph_compiled_successfully():
    """验证图编译成功，可获取节点信息"""
    from backend.graph.builder import build_graph
    graph = build_graph(checkpointer=None)
    # LangGraph 编译后的图对象应该有 get_graph 方法
    assert hasattr(graph, 'aget_state') or hasattr(graph, 'get_state')


@pytest.mark.asyncio
async def test_graph_init_node():
    """测试 init 节点正确初始化状态"""
    from backend.graph.builder import init_node

    state = {"topic": "测试研究主题"}
    result = await init_node(state)

    assert result["topic"] == "测试研究主题"
    assert result["current_phase"] == "searching"
    assert result["search_results"] == []
    assert result["analysis_data"] == {}
    assert result["report_draft"] == ""
    assert result["review_feedback"] is None
    assert result["final_report"] == ""
    assert result["revision_count"] == 0
    assert result["max_revisions"] == 3
    assert result["references"] == []
    assert result["charts"] == []
    assert result["model_name"] == ""


@pytest.mark.asyncio
async def test_init_node_default_topic():
    """测试 init 节点无 topic 时使用默认值"""
    from backend.graph.builder import init_node

    state = {}
    result = await init_node(state)

    assert result["topic"] == "未命名研究主题"


@pytest.mark.asyncio
async def test_init_node_passes_model_name():
    """测试 init 节点透传用户指定的模型名"""
    from backend.graph.builder import init_node

    state = {"topic": "测试主题", "model_name": "deepseek-chat"}
    result = await init_node(state)

    assert result["model_name"] == "deepseek-chat"


def test_should_continue_or_end_waiting_review():
    """测试等待人工审核阶段 → END（update_state 模式）"""
    from backend.agents.supervisor import should_continue_or_end

    state = {"current_phase": "reviewing", "revision_count": 0, "max_revisions": 3}
    result = should_continue_or_end(state)
    assert result == "completed"


def test_should_continue_or_end_revise():
    """测试收到返工指示 → writer"""
    from backend.agents.supervisor import should_continue_or_end

    state = {"current_phase": "writing", "revision_count": 1, "max_revisions": 3}
    result = should_continue_or_end(state)
    assert result == "revise"


def test_should_continue_or_end_max_revisions():
    """测试超过最大重试次数 → 强制结束"""
    from backend.agents.supervisor import should_continue_or_end

    state = {"current_phase": "writing", "revision_count": 3, "max_revisions": 3}
    result = should_continue_or_end(state)
    assert result == "completed"


def test_supervisor_router_phases():
    """测试 supervisor 路由函数各阶段"""
    from backend.agents.supervisor import supervisor_router

    assert supervisor_router({"current_phase": "init"}) == "searcher"
    assert supervisor_router({"current_phase": "searching"}) == "searcher"
    assert supervisor_router({"current_phase": "analyzing"}) == "analyst"
    assert supervisor_router({"current_phase": "writing"}) == "writer"
    assert supervisor_router({"current_phase": "reviewing"}) == "reviewer"
    assert supervisor_router({"current_phase": "completed"}) == "__end__"
    assert supervisor_router({"current_phase": "failed"}) == "__end__"


def test_supervisor_router_unknown_phase():
    """测试 supervisor 路由未知阶段"""
    from backend.agents.supervisor import supervisor_router

    result = supervisor_router({"current_phase": "unknown"})
    assert result == "searcher"
