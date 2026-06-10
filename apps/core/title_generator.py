"""Lightweight chat title generation helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from apps.core.tls import urlopen_with_bundled_ca

logger = logging.getLogger(__name__)

_DIRECT_TITLE_MAX_TOKENS = 80
_OPENAI_COMPATIBLE_PROVIDERS = {
    "custom",
    "deepseek",
    "huggingface",
    "kimi-coding",
    "lmstudio",
    "openai",
    "openai-codex",
    "openrouter",
    "xai",
    "xiaomi",
    "zai",
}
_PROVIDER_DEFAULT_BASE_URL = {
    "deepseek": "https://api.deepseek.com/v1",
    "huggingface": "https://router.huggingface.co/v1",
    "kimi-coding": "https://api.moonshot.ai/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "openai": "https://api.openai.com/v1",
    "openai-codex": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
    "xiaomi": "https://api.xiaomimimo.com/v1",
    "zai": "https://api.z.ai/api/paas/v4",
}
_PROVIDER_BASE_URL_ENV = {
    "deepseek": "DEEPSEEK_BASE_URL",
    "huggingface": "HF_BASE_URL",
    "kimi-coding": "KIMI_BASE_URL",
    "lmstudio": "LM_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "openai-codex": "OPENAI_BASE_URL",
    "openrouter": "OPENROUTER_BASE_URL",
    "xai": "XAI_BASE_URL",
    "xiaomi": "XIAOMI_BASE_URL",
    "zai": "GLM_BASE_URL",
}
_PROVIDER_API_KEY_NAMES = {
    "custom": ("CUSTOM_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "kimi-coding": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    "lmstudio": ("LM_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openai-codex": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "xai": ("XAI_API_KEY",),
    "xiaomi": ("XIAOMI_API_KEY",),
    "zai": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
}
_PROVIDER_ALIASES = {
    "google": "gemini",
    "google-ai": "gemini",
    "google-ai-studio": "gemini",
    "glm": "zai",
    "kimi": "kimi-coding",
    "moonshot": "kimi-coding",
    "x-ai": "xai",
    "z-ai": "zai",
}
_AUTO_PROVIDER_VALUES = {"", "auto", "main"}
_PROVIDER_HOST_HINTS: tuple[tuple[str, str], ...] = (
    ("openrouter.ai", "openrouter"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("api.mimo-v2.com", "xiaomi"),
    ("api.xiaomimimo.com", "xiaomi"),
    ("token-plan-cn.xiaomimimo.com", "xiaomi"),
    ("api.deepseek.com", "deepseek"),
    ("api.x.ai", "xai"),
    ("api.moonshot.ai", "kimi-coding"),
    ("api.moonshot.cn", "kimi-coding"),
    ("api.z.ai", "zai"),
    ("router.huggingface.co", "huggingface"),
)
_OPENROUTER_MODEL_PREFIXES = (
    "anthropic/",
    "deepseek/",
    "google/",
    "meta-llama/",
    "mistralai/",
    "openai/",
    "qwen/",
    "x-ai/",
)
_TITLE_PROMPT_ECHO_MARKERS = (
    "请为这段持续对话生成",
    "会话列表标题",
    "第一条用户消息",
    "最近对话",
    "当前标题",
    "只输出标题",
    "用户要求为这段",
    "要求包括",
)
_TITLE_PROMPT_TEMPLATE = """\
请为这段持续对话生成一个会话列表标题。

要求：
- 只输出标题本身，不要解释，不要加引号。
- 中文优先控制在 4 到 14 个字；英文控制在 2 到 6 个词。
- 保留必要专名、作品名、工具名。
- 不要使用“对话”“聊天”“总结”“请求”等空泛词。
- 不要照抄完整用户句子；如果旧标题已经准确，可以轻微优化或保持含义。

当前标题：
{current_title}

第一条用户消息：
{first_user_message}

最近对话：
{dialogue}
"""


@dataclass(frozen=True)
class TitleLLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str = ""
    api_key_name: str = ""


def looks_like_title_prompt_echo(value: str | None) -> bool:
    normalized = re.sub(r"\s+", "", value or "")
    if not normalized:
        return False
    if any(marker.replace(" ", "") in normalized for marker in _TITLE_PROMPT_ECHO_MARKERS):
        return True
    return normalized.startswith(("首先用户要求", "首先，用户要求", "用户要求"))


def build_session_title_prompt(
    messages: list[Any],
    *,
    current_title: str = "",
    assistant_text: str = "",
    context_limit: int = 8,
) -> str:
    lines: list[str] = []
    first_user_message = ""
    for message in messages:
        role_value = getattr(getattr(message, "role", ""), "value", getattr(message, "role", ""))
        if role_value not in {"user", "assistant"}:
            continue
        content = str(getattr(message, "content", "") or "").strip()
        if not content and role_value == "assistant":
            content = assistant_text.strip()
        content = _compact_title_context(content)
        if not content:
            continue
        if role_value == "user" and not first_user_message:
            first_user_message = content
        label = "用户" if role_value == "user" else "Yachiyo"
        lines.append(f"{label}: {content}")
    dialogue = "\n".join(lines[-context_limit:]).strip()
    return _TITLE_PROMPT_TEMPLATE.format(
        current_title=_compact_title_context(current_title, 120) or "暂无",
        first_user_message=first_user_message or "暂无",
        dialogue=dialogue or "用户刚开始一个新对话。",
    )


async def generate_title_with_direct_api(prompt: str, *, timeout: float) -> str:
    config = resolve_title_llm_config()
    if config is None:
        return ""
    try:
        return await asyncio.to_thread(_call_openai_compatible_title_api, config, prompt, timeout)
    except Exception:
        logger.debug("直接模型 API 生成会话标题失败", exc_info=True)
        return ""


def resolve_title_llm_config() -> TitleLLMConfig | None:
    model_cfg = _read_default_chat_model_profile() or _read_model_config()
    raw_provider = str(model_cfg.get("provider") or "").strip()
    model = str(model_cfg.get("default") or "").strip()
    configured_base_url = str(model_cfg.get("base_url") or "").strip()
    configured_api_key = str(model_cfg.get("api_key") or "").strip()
    configured_api_key_name = str(model_cfg.get("api_key_name") or "").strip()
    provider = _effective_provider(raw_provider, configured_base_url, model) or raw_provider.strip().lower()
    if not provider or not model:
        return None
    provider = _PROVIDER_ALIASES.get(provider, provider)
    if provider not in _OPENAI_COMPATIBLE_PROVIDERS:
        return None

    env_values = _read_oha_env_values()
    base_url = (
        configured_base_url
        or _env_value(_PROVIDER_BASE_URL_ENV.get(provider, ""), env_values)
        or _PROVIDER_DEFAULT_BASE_URL.get(provider, "")
    ).rstrip("/")
    if not base_url:
        return None
    api_key_name, api_key = (
        (configured_api_key_name, configured_api_key)
        if configured_api_key
        else _configured_provider_api_key(provider, env_values)
    )
    if not api_key and _provider_requires_api_key(provider, base_url):
        return None
    return TitleLLMConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        api_key_name=api_key_name,
    )


def _call_openai_compatible_title_api(config: TitleLLMConfig, prompt: str, timeout: float) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个会话标题生成器。只输出简短标题，不输出解释。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": _DIRECT_TITLE_MAX_TOKENS,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urlrequest.Request(
        _chat_completions_url(config.base_url),
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen_with_bundled_ca(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"title API HTTP {exc.code}: {detail}") from exc
    parsed = json.loads(body)
    return _extract_chat_completion_text(parsed)


def _extract_chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        for key in ("content", "reasoning_content"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    return ""


def _chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _compact_title_context(value: str, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3].rstrip()}..."


def _read_default_chat_model_profile() -> dict[str, str] | None:
    try:
        from apps.shell.model_profiles import get_model_profile_service

        service = get_model_profile_service()
        profiles = service.list_profiles()
        defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), dict) else {}
        profile_id = str(defaults.get("chat") or "").strip()
        if not profile_id:
            return None
        profile = service.get_profile_private(profile_id)
    except Exception:
        return None

    return {
        "provider": str(profile.get("provider") or ""),
        "default": str(profile.get("model") or ""),
        "base_url": str(profile.get("base_url") or ""),
        "api_key": str(profile.get("api_key") or ""),
        "api_key_name": str(profile.get("api_key_name") or ""),
    }


def _read_model_config() -> dict[str, str]:
    explicit_config_path = os.getenv("OHA_YACHIYO_CONFIG_FILE", "").strip() or os.getenv("OHA_YACHIYO_CONFIG_PATH", "").strip()
    if explicit_config_path:
        return _read_model_config_from_path(Path(explicit_config_path).expanduser())
    return _read_model_config_from_path(_oha_config_path("config.yaml"))


def _read_model_config_from_path(config_path: Path) -> dict[str, str]:
    values = _read_yaml_paths(config_path, {("model", "provider"), ("model", "default"), ("model", "base_url")})
    return {
        "provider": values.get(("model", "provider"), ""),
        "default": values.get(("model", "default"), ""),
        "base_url": values.get(("model", "base_url"), ""),
    }


def _oha_config_path(fallback_name: str) -> Path:
    return Path.home() / ".oha-yachiyo" / fallback_name


def _read_yaml_paths(path: Path, wanted: set[tuple[str, ...]]) -> dict[tuple[str, ...], str]:
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[tuple[str, ...], str] = {}
    stack: list[str] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if not match:
            continue
        indent, key, raw_value = match.groups()
        level = len(indent.replace("\t", "  ")) // 2
        stack = stack[:level] + [key]
        path_key = tuple(stack)
        if path_key in wanted:
            values[path_key] = _strip_yaml_scalar(raw_value)
    return values


def _strip_yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if value in {"", "null", "None", "~"}:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def _read_oha_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    explicit_env_path = os.getenv("OHA_YACHIYO_ENV_FILE", "").strip()
    env_path = Path(explicit_env_path).expanduser() if explicit_env_path else _oha_config_path(".env")
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return values


def _configured_provider_api_key(provider: str, env_values: dict[str, str]) -> tuple[str, str]:
    for name in _PROVIDER_API_KEY_NAMES.get(provider, (f"{provider.upper().replace('-', '_')}_API_KEY",)):
        value = _env_value(name, env_values)
        if value:
            return name, value
    if provider == "openrouter":
        value = _env_value("AUTO_API_KEY", env_values)
        if value:
            return "AUTO_API_KEY", value
    return "", ""


def _env_value(name: str, env_values: dict[str, str]) -> str:
    if not name:
        return ""
    return os.getenv(name, "").strip() or str(env_values.get(name) or "").strip()


def _provider_requires_api_key(provider: str, base_url: str) -> bool:
    if provider == "lmstudio":
        return False
    host = (urlparse(base_url).hostname or "").lower()
    return host not in {"localhost", "127.0.0.1", "::1"}


def _effective_provider(provider: str, base_url: str = "", model: str = "") -> str:
    normalized = (provider or "").strip().lower()
    if normalized not in _AUTO_PROVIDER_VALUES:
        return _PROVIDER_ALIASES.get(normalized, normalized)
    host = (urlparse(base_url or "").hostname or "").lower()
    for suffix, provider_id in _PROVIDER_HOST_HINTS:
        if host == suffix or host.endswith(f".{suffix}"):
            return provider_id
    model_id = (model or "").strip().lower()
    if any(model_id.startswith(prefix) for prefix in _OPENROUTER_MODEL_PREFIXES):
        return "openrouter"
    return ""
