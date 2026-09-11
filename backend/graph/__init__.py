"""backend.graph — 多智能体协作图的定义与构建

导出:
    - AgentState: 全局状态 TypedDict
    - build_graph: 图构建函数
"""
from backend.graph.builder import build_graph
from backend.graph.state import AgentState

__all__ = ["AgentState", "build_graph"]
