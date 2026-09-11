"""状态定义测试"""
import typing
from backend.graph.state import AgentState


def _resolve_annotation(ann):
    """解析注解值，支持 ForwardRef、字符串和实际类型"""
    if isinstance(ann, typing.ForwardRef):
        return ann.__forward_arg__
    if isinstance(ann, str):
        return ann
    return ann.__name__ if hasattr(ann, '__name__') else str(ann)


def test_agent_state_fields():
    """验证 AgentState 包含所有必需字段"""
    annotations = AgentState.__annotations__

    required_fields = [
        "messages", "topic", "model_name", "current_phase",
        "search_results", "analysis_data",
        "report_draft", "review_feedback",
        "final_report", "revision_count", "max_revisions",
        "references", "charts"
    ]

    for field in required_fields:
        assert field in annotations, f"缺少字段: {field}"


def test_agent_state_references_type():
    """验证 references 字段类型"""
    annotations = AgentState.__annotations__
    assert "references" in annotations


def test_agent_state_charts_type():
    """验证 charts 字段类型"""
    annotations = AgentState.__annotations__
    assert "charts" in annotations


def test_agent_state_topic_type():
    """验证 topic 字段类型"""
    annotations = AgentState.__annotations__
    assert "topic" in annotations
    # from __future__ import annotations 使值为字符串
    assert _resolve_annotation(annotations["topic"]) == "str"


def test_agent_state_current_phase_type():
    """验证 current_phase 字段类型"""
    annotations = AgentState.__annotations__
    assert "current_phase" in annotations
    assert _resolve_annotation(annotations["current_phase"]) == "str"


def test_agent_state_revision_count_type():
    """验证 revision_count 字段类型"""
    annotations = AgentState.__annotations__
    assert "revision_count" in annotations
    assert _resolve_annotation(annotations["revision_count"]) == "int"


def test_agent_state_max_revisions_type():
    """验证 max_revisions 字段类型"""
    annotations = AgentState.__annotations__
    assert "max_revisions" in annotations
    assert _resolve_annotation(annotations["max_revisions"]) == "int"


def test_agent_state_report_draft_type():
    """验证 report_draft 字段类型"""
    annotations = AgentState.__annotations__
    assert "report_draft" in annotations
    assert _resolve_annotation(annotations["report_draft"]) == "str"


def test_agent_state_final_report_type():
    """验证 final_report 字段类型"""
    annotations = AgentState.__annotations__
    assert "final_report" in annotations
    assert _resolve_annotation(annotations["final_report"]) == "str"


def test_agent_state_model_name_type():
    """验证 model_name 字段类型"""
    annotations = AgentState.__annotations__
    assert "model_name" in annotations
    assert _resolve_annotation(annotations["model_name"]) == "str"
