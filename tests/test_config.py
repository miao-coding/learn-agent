"""配置模块测试 - 模型白名单与 LLM 配置解析"""
import pytest

import backend.config as config_module
from backend.config import settings, update_env_file


class TestGetAvailableModels:
    def test_empty_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(settings, "available_models", "")
        assert settings.get_available_models() == []

    def test_single_model(self, monkeypatch):
        monkeypatch.setattr(settings, "available_models", "deepseek-chat")
        assert settings.get_available_models() == ["deepseek-chat"]

    def test_multiple_models_with_spaces(self, monkeypatch):
        monkeypatch.setattr(settings, "available_models", "deepseek-chat, qwen-plus , gpt-4o")
        assert settings.get_available_models() == ["deepseek-chat", "qwen-plus", "gpt-4o"]

    def test_ignores_blank_entries(self, monkeypatch):
        monkeypatch.setattr(settings, "available_models", "a ,, b")
        assert settings.get_available_models() == ["a", "b"]


class TestResolveLlmConfig:
    def test_none_uses_default_model(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_CHAT_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_CHAT_BASE_URL", raising=False)
        cfg = settings.resolve_llm_config(None)
        assert cfg["model"] == settings.openai_model
        assert cfg["api_key"] == settings.openai_api_key
        assert cfg["base_url"] == settings.openai_base_url

    def test_empty_string_uses_default_model(self):
        cfg = settings.resolve_llm_config("")
        assert cfg["model"] == settings.openai_model

    def test_explicit_model_name(self):
        cfg = settings.resolve_llm_config("deepseek-chat")
        assert cfg["model"] == "deepseek-chat"

    def test_model_specific_env_override(self, monkeypatch):
        """模型专属环境变量优先于全局默认"""
        monkeypatch.setenv("DEEPSEEK_CHAT_API_KEY", "sk-test-key")
        monkeypatch.setenv("DEEPSEEK_CHAT_BASE_URL", "https://api.deepseek.com/v1")
        cfg = settings.resolve_llm_config("deepseek-chat")
        assert cfg["api_key"] == "sk-test-key"
        assert cfg["base_url"] == "https://api.deepseek.com/v1"
        assert cfg["model"] == "deepseek-chat"

    def test_fallback_to_global_when_no_override(self, monkeypatch):
        monkeypatch.delenv("SOME_MODEL_API_KEY", raising=False)
        monkeypatch.delenv("SOME_MODEL_BASE_URL", raising=False)
        cfg = settings.resolve_llm_config("some-model")
        assert cfg["api_key"] == settings.openai_api_key
        assert cfg["base_url"] == settings.openai_base_url

    def test_prefix_conversion(self, monkeypatch):
        """模型名特殊字符转下划线大写：gpt-4o -> GPT_4O_API_KEY"""
        monkeypatch.setenv("GPT_4O_API_KEY", "sk-gpt4o")
        cfg = settings.resolve_llm_config("gpt-4o")
        assert cfg["api_key"] == "sk-gpt4o"


class TestUpdateEnvFile:
    def test_creates_env_file(self, tmp_path, monkeypatch):
        """文件不存在时创建并写入"""
        env_path = tmp_path / ".env"
        monkeypatch.setattr(config_module, "ENV_FILE", env_path)
        update_env_file({"OPENAI_API_KEY": "sk-test"})
        assert env_path.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-test\n"

    def test_replaces_existing_key_keeps_others(self, tmp_path, monkeypatch):
        """替换已存在的键，其他行保持不变"""
        env_path = tmp_path / ".env"
        env_path.write_text("OPENAI_API_KEY=old\nDEBUG=false\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "ENV_FILE", env_path)
        update_env_file({"OPENAI_API_KEY": "new"})
        content = env_path.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=new\n" in content
        assert "old" not in content
        assert "DEBUG=false\n" in content

    def test_appends_missing_key(self, tmp_path, monkeypatch):
        """不存在的键追加到文件末尾"""
        env_path = tmp_path / ".env"
        env_path.write_text("DEBUG=false\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "ENV_FILE", env_path)
        update_env_file({"TAVILY_API_KEY": "tvly-1"})
        content = env_path.read_text(encoding="utf-8")
        assert "DEBUG=false\n" in content
        assert "TAVILY_API_KEY=tvly-1\n" in content
