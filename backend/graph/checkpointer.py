"""Checkpointer 配置 — 使用 SQLite 实现状态持久化

数据库文件放在项目根目录（d:\\learn_agent\\checkpoints.db），
确保不会在 C 盘生成任何文件。
"""
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 数据库路径：项目根目录 / checkpoints.db
DB_PATH = str(Path(__file__).parent.parent.parent / "checkpoints.db")


def get_checkpointer() -> AsyncSqliteSaver:
    """创建并返回异步 SQLite checkpointer（异步上下文管理器）。

    使用方式::

        async with get_checkpointer() as checkpointer:
            setup_checkpointer(checkpointer)
            graph = build_graph(checkpointer)
    """
    return AsyncSqliteSaver.from_conn_string(DB_PATH)


async def setup_checkpointer(checkpointer: AsyncSqliteSaver) -> None:
    """在已有的 checkpointer 实例上执行初始化（创建表等）。

    需要在 ``async with get_checkpointer() as cp`` 之后调用。
    """
    await checkpointer.setup()
