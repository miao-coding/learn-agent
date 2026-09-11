"""API 请求和响应模型"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class ResearchRequest(BaseModel):
    """提交研究任务请求"""
    topic: str = Field(..., min_length=1, max_length=200, description="研究主题")
    model_name: Optional[str] = Field(
        None,
        max_length=100,
        description="指定研究模型（须在服务端可用列表内），留空使用默认模型",
    )

    @field_validator("topic")
    @classmethod
    def topic_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("研究主题不能为空")
        return v.strip()


class ResearchResponse(BaseModel):
    """提交研究任务响应"""
    thread_id: str
    status: str = "started"
    topic: str


class AvailableModelsResponse(BaseModel):
    """可用模型列表响应"""
    models: list[str] = []
    default: str = ""


class AdminStatusResponse(BaseModel):
    """配置状态响应（不包含任何密钥明文）"""
    admin_enabled: bool = False
    openai_key_set: bool = False
    tavily_key_set: bool = False
    openai_base_url: str = ""
    model_name: str = ""


class AdminConfigRequest(BaseModel):
    """管理员配置更新请求"""
    password: str = Field(..., min_length=1, description="管理员口令")
    openai_api_key: Optional[str] = Field(
        None, max_length=300, description="新的 OPENAI_API_KEY，留空不修改"
    )
    openai_base_url: Optional[str] = Field(
        None, max_length=300, description="新的 OPENAI_BASE_URL，留空不修改"
    )
    openai_model: Optional[str] = Field(
        None, max_length=100, description="新的默认模型名（如 deepseek-chat），留空不修改"
    )
    tavily_api_key: Optional[str] = Field(
        None, max_length=300, description="新的 TAVILY_API_KEY，留空不修改"
    )


class AdminConfigResponse(BaseModel):
    """配置更新响应"""
    message: str = ""
    updated: list[str] = []


class AdminTestRequest(BaseModel):
    """获取模型列表 / 连接测试请求（留空的字段用当前已保存配置）"""
    password: str = Field(..., min_length=1, description="管理员口令")
    openai_api_key: Optional[str] = Field(
        None, max_length=300, description="OPENAI_API_KEY，留空用当前已保存配置"
    )
    openai_base_url: Optional[str] = Field(
        None, max_length=300, description="OPENAI_BASE_URL，留空用当前已保存配置"
    )
    openai_model: Optional[str] = Field(
        None, max_length=100, description="待测试的模型名，留空用当前默认模型"
    )


class AdminModelsResponse(BaseModel):
    """接口可用模型列表响应"""
    models: list[str] = []
    error: str = ""


class AdminTestResponse(BaseModel):
    """连接测试响应"""
    ok: bool = False
    message: str = ""
    latency_ms: int = 0


class ReviewRequest(BaseModel):
    """人工审核请求"""
    feedback: str  # "通过" 或修改意见


class ReviewResponse(BaseModel):
    """审核响应"""
    thread_id: str
    status: str  # "approved" 或 "revising"
    message: str


class ReportResponse(BaseModel):
    """报告响应"""
    thread_id: str
    topic: str
    report: str
    status: str
    references: list[dict] = []
    charts: list[str] = []


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "1.0.0"


class HistoryItem(BaseModel):
    """历史任务条目"""
    thread_id: str
    topic: str = ""
    status: str = ""
    updated_at: str = ""
