"""Agent 模块 - 导出所有 Agent 节点函数

提供多智能体协作系统中的核心 Agent：
- searcher_agent: 搜索员，负责联网搜索收集行业信息
- analyst_agent: 分析师，负责从搜索结果中提取关键数据
- writer_agent: 撰稿人，负责将分析数据整合成结构化报告
- supervisor_router: Supervisor 路由，根据当前阶段决定下一步
- should_continue_or_end: 审核后路由，决定结束还是返工
"""

from backend.agents.analyst import analyst_agent
from backend.agents.searcher import searcher_agent
from backend.agents.supervisor import should_continue_or_end, supervisor_router
from backend.agents.writer import writer_agent

__all__ = [
    "searcher_agent",
    "analyst_agent",
    "writer_agent",
    "supervisor_router",
    "should_continue_or_end",
]
