"""FastAPI 应用入口 — Multi-Agent 行业研究系统"""
from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.graph.builder import build_graph
from backend.graph.checkpointer import get_checkpointer, setup_checkpointer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化 checkpointer 和图，关闭时清理资源"""

    # ── Startup ─────────────────────────────────────────────
    logger.info("正在初始化 checkpointer 和 LangGraph 图...")

    # 配置校验
    if not settings.openai_api_key:
        logger.warning("⚠️ OPENAI_API_KEY 未配置，LLM 调用将失败")
    if not settings.tavily_api_key:
        logger.warning("⚠️ TAVILY_API_KEY 未配置，搜索功能将不可用")

    # 使用 AsyncExitStack 确保异常时也能正确清理资源
    exit_stack = AsyncExitStack()
    async with exit_stack:
        checkpointer = get_checkpointer()
        checkpointer = await exit_stack.enter_async_context(checkpointer)
        await setup_checkpointer(checkpointer)

        graph = build_graph(checkpointer=checkpointer)

        app.state.graph = graph
        app.state.checkpointer = checkpointer

        logger.info("系统初始化完成 ✓")
        yield
    # exit_stack 自动处理 cleanup


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  创建 FastAPI 应用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = FastAPI(
    title="Multi-Agent 行业研究系统",
    description="基于 LangGraph 的多智能体协作行业研究平台",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS 配置 ─────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:3000", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ──────────────────────────────────────────────────
from backend.api.routes import router  # noqa: E402

app.include_router(router)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  直接运行入口（开发用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
