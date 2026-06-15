"""Lightweight title generator configuration tests."""

from apps.core.title_generator import (
    _chat_completions_url,
    _extract_chat_completion_text,
    looks_like_title_prompt_echo,
    resolve_title_llm_config,
)


def test_resolve_title_llm_config_reads_openai_compatible_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: deepseek\n"
        "  default: deepseek-chat\n"
        "  base_url: https://api.deepseek.com/v1\n",
        encoding="utf-8",
    )
    env_path.write_text("DEEPSEEK_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.setenv("OHA_YACHIYO_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("OHA_YACHIYO_ENV_FILE", str(env_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("apps.core.title_generator._read_default_chat_model_profile", lambda: None)

    config = resolve_title_llm_config()

    assert config is not None
    assert config.provider == "deepseek"
    assert config.model == "deepseek-chat"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key == "sk-test"


def test_resolve_title_llm_config_skips_unsupported_direct_provider(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: anthropic\n"
        "  default: claude-sonnet-4-6\n"
        "  base_url: https://api.anthropic.com\n",
        encoding="utf-8",
    )
    env_path.write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.setenv("OHA_YACHIYO_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("OHA_YACHIYO_ENV_FILE", str(env_path))
    monkeypatch.setattr("apps.core.title_generator._read_default_chat_model_profile", lambda: None)

    assert resolve_title_llm_config() is None


def test_extract_chat_completion_text_reads_message_content():
    assert _extract_chat_completion_text({
        "choices": [{"message": {"content": "  新标题  "}}],
    }) == "新标题"


def test_chat_completions_url_uses_openai_compatible_endpoint():
    assert _chat_completions_url("https://api.example.com/v1") == "https://api.example.com/v1/chat/completions"
    assert _chat_completions_url("https://api.example.com/v1/chat/completions") == "https://api.example.com/v1/chat/completions"


def test_looks_like_title_prompt_echo_detects_prompt_summaries():
    assert looks_like_title_prompt_echo("首先，用户要求为这段持续对话生成一个会话列表标题。") is True
    assert looks_like_title_prompt_echo("当前标题：早安闲聊\n最近对话：测试") is True
    assert looks_like_title_prompt_echo("Chrome 登录态确认") is False
