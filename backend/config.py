"""应用配置模块 - 集中管理所有配置项"""
import os
import re
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings(BaseSettings):
    """应用全局配置"""

    # OpenAI 配置
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"

    # Tavily 搜索配置
    tavily_api_key: str = ""

    # 可用模型白名单（逗号分隔）。配置后前端显示模型选择框，用户提交任务时可自选；
    # 留空表示不开放自选，所有任务使用上面的默认模型配置。
    # 每个模型可通过专属环境变量覆盖密钥/接口地址，变量名为模型名中
    # 非字母数字字符替换为下划线并大写，例如：
    #   deepseek-chat -> DEEPSEEK_CHAT_API_KEY / DEEPSEEK_CHAT_BASE_URL
    #   gpt-4o        -> GPT_4O_API_KEY / GPT_4O_BASE_URL
    #   qwen-plus     -> QWEN_PLUS_API_KEY / QWEN_PLUS_BASE_URL
    available_models: str = ""

    # 应用配置
    debug: bool = False

    # 管理口令：配置后可在前端“系统设置”中在线修改 API Key（口令保护，
    # 修改即时生效并持久化回 .env）；留空表示禁用在线配置功能
    admin_password: str = ""

    def get_available_models(self) -> list[str]:
        """解析可用模型白名单（逗号分隔，忽略空白项）"""
        return [m.strip() for m in self.available_models.split(",") if m.strip()]

    def resolve_llm_config(self, model_name: str | None = None) -> dict:
        """解析指定模型的 LLM 连接配置

        优先读取模型专属环境变量（<MODEL>_API_KEY / <MODEL>_BASE_URL），
        未配置的项回退到全局 openai_* 默认配置。

        Args:
            model_name: 模型名称；None/空串使用默认模型 openai_model

        Returns:
            包含 model / api_key / base_url 的字典，可直接解包给 ChatOpenAI
        """
        name = (model_name or "").strip() or self.openai_model
        prefix = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").upper()
        api_key = os.getenv(f"{prefix}_API_KEY", "") or self.openai_api_key
        base_url = os.getenv(f"{prefix}_BASE_URL", "") or self.openai_base_url
        return {"model": name, "api_key": api_key, "base_url": base_url}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局配置实例
settings = Settings()

# 项目根目录的 .env 文件路径（在线配置持久化用）
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def update_env_file(updates: dict[str, str]) -> None:
    """将键值对写回项目根目录的 .env 文件（存在则替换，不存在则追加）

    用于在线配置的持久化，使服务重启后配置仍然生效。

    Args:
        updates: 环境变量名到新值的映射
    """
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    for key, value in updates.items():
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
