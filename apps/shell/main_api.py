"""主界面 WebView API

为 Control Center 主控台提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
集成 ChatAPI 提供聊天功能。
"""

import ast
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import urlparse

import apps.shell.config as shell_config
from apps.installer.workspace_init import get_workspace_status
from apps.shell.assets import DEFAULT_BUBBLE_AVATAR_PATH, data_uri
from apps.shell.chat_api import ChatAPI
from apps.shell.chat_bridge import ChatBridge
from apps.shell.activity_api import list_activity_events
from apps.shell.config import ModelSummary
from apps.shell.effect_policy import build_effects_summary
from apps.shell.model_capabilities import lookup_model_supports_vision
from apps.shell.integration_status import get_integration_snapshot
from apps.shell.mode_catalog import list_mode_options
from apps.shell.mode_settings import (
    apply_settings_changes,
    build_display_settings,
    effective_display_mode,
    serialize_mode_settings,
)
from apps.shell.model_profiles import ModelProfileError, get_model_profile_service
from apps.shell.native_capabilities import get_native_image_input_capability
from apps.shell.model_provider_adapters import provider_api_key_names, resolve_provider_adapter
from packages.security import redact_api_error_text

if TYPE_CHECKING:
    from apps.core.runtime import AppRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)
_NATIVE_CONNECTION_TEST_TIMEOUT = 45.0
_NATIVE_CONNECTION_TEST_PROMPT = (
    "This is an Oha-Yachiyo Native provider connectivity check. "
    "Reply with exactly: OK"
)
_NATIVE_CONNECTION_CACHE_SCHEMA = 1
_NATIVE_CONNECTION_CACHE_FILE = "native_connection.json"
_NATIVE_IMAGE_CONNECTION_TEST_TIMEOUT = 90.0
_NATIVE_IMAGE_CONNECTION_CACHE_SCHEMA = 1
_NATIVE_IMAGE_CONNECTION_CACHE_FILE = "native_image_connection.json"
_NATIVE_DIAGNOSTIC_CACHE_SCHEMA = 1
_NATIVE_DIAGNOSTIC_CACHE_FILE = "native_diagnostics.json"
_NATIVE_TOOL_CONFIG_FILE = "native_tool_config.json"
_NATIVE_IMAGE_INPUT_MODES = {"auto", "native", "text"}
_NATIVE_IMAGE_INPUT_MODE_ALIASES = {
    "vision": "text",
    "yachiyo_vision": "text",
}
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_REDACTIONS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
)
_NATIVE_PROVIDER_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "xiaomi",
        "label": "Xiaomi MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "api_key_names": ("XIAOMI_API_KEY",),
        "base_url_env": "XIAOMI_BASE_URL",
        "models": ("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"),
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_names": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
        "base_url_env": "OPENROUTER_BASE_URL",
        "models": (
            "anthropic/claude-sonnet-4.6",
            "openai/gpt-5.4",
            "google/gemini-3-pro-preview",
            "deepseek/deepseek-chat",
        ),
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key_names": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
        "base_url_env": "ANTHROPIC_BASE_URL",
        "models": ("claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"),
    },
    {
        "id": "gemini",
        "label": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_names": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "base_url_env": "GEMINI_BASE_URL",
        "models": ("gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro"),
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_names": ("DEEPSEEK_API_KEY",),
        "base_url_env": "DEEPSEEK_BASE_URL",
        "models": ("deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"),
    },
    {
        "id": "xai",
        "label": "xAI",
        "base_url": "https://api.x.ai/v1",
        "api_key_names": ("XAI_API_KEY",),
        "base_url_env": "XAI_BASE_URL",
        "models": ("grok-4.1", "grok-4.1-fast", "grok-4-fast"),
    },
    {
        "id": "kimi-coding",
        "label": "Kimi / Moonshot",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_names": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
        "base_url_env": "KIMI_BASE_URL",
        "models": ("kimi-k2.5", "kimi-k2-thinking", "kimi-k2-turbo-preview"),
    },
    {
        "id": "zai",
        "label": "Z.AI / GLM",
        "base_url": "https://api.z.ai/api/paas/v4",
        "api_key_names": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        "base_url_env": "GLM_BASE_URL",
        "models": ("glm-4.6", "glm-4.5", "glm-4.5-air"),
    },
    {
        "id": "huggingface",
        "label": "Hugging Face",
        "base_url": "https://router.huggingface.co/v1",
        "api_key_names": ("HF_TOKEN",),
        "base_url_env": "HF_BASE_URL",
        "models": ("openai/gpt-oss-120b", "Qwen/Qwen3-Coder-480B-A35B-Instruct"),
    },
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key_names": ("LM_API_KEY",),
        "base_url_env": "LM_BASE_URL",
        "models": ("local-model",),
    },
    {
        "id": "nous",
        "label": "Nous Portal",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "api_key_names": (),
        "auth_type": "oauth_device_code",
        "models": ("deepseek/deepseek-chat", "anthropic/claude-sonnet-4.6"),
    },
    {
        "id": "custom",
        "label": "Custom endpoint",
        "base_url": "",
        "api_key_names": ("CUSTOM_API_KEY",),
        "models": (),
    },
)
_PROVIDER_PRESET_BY_ID = {str(item["id"]): item for item in _NATIVE_PROVIDER_PRESETS}
_PREFERRED_AUXILIARY_VISION_MODELS = {
    "xiaomi": "mimo-v2.5",
}
_FAL_IMAGE_GEN_MODELS = (
    "fal-ai/flux-2/klein/9b",
    "fal-ai/flux-2-pro",
    "fal-ai/z-image/turbo",
    "fal-ai/nano-banana-pro",
    "fal-ai/ideogram/v3",
    "fal-ai/recraft/v4/pro/text-to-image",
    "fal-ai/qwen-image",
)
_OPENAI_IMAGE_GEN_MODELS = (
    "gpt-image-2-low",
    "gpt-image-2-medium",
    "gpt-image-2-high",
)
_XAI_IMAGE_GEN_MODELS = (
    "grok-imagine-image",
)
_IMAGE_GEN_MODEL_OPTIONS = {
    "fal": _FAL_IMAGE_GEN_MODELS,
    "openai": _OPENAI_IMAGE_GEN_MODELS,
    "openai-codex": _OPENAI_IMAGE_GEN_MODELS,
    "xai": _XAI_IMAGE_GEN_MODELS,
}
_NATIVE_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "web": ("web", "search", "web_search", "web_extract"),
    "browser": ("browser", "browser_navigate", "browser_click"),
    "browser-cdp": ("browser", "browser_cdp", "browser-cdp"),
    "image_gen": ("image_gen", "image_generate"),
    "terminal": ("terminal", "process"),
    "file": ("file", "read_file", "write_file", "patch", "search_files"),
    "skills": ("skills", "skills_list", "skill_view", "skill_manage"),
    "code_execution": ("code_execution", "execute_code"),
    "memory": ("memory",),
    "session_search": ("session_search",),
    "todo": ("todo",),
    "cronjob": ("cronjob",),
    "messaging": ("messaging", "send_message"),
    "discord": ("discord", "discord_admin"),
    "homeassistant": (
        "homeassistant",
        "ha_list_entities",
        "ha_get_state",
        "ha_list_services",
        "ha_call_service",
    ),
    "spotify": ("spotify",),
    "yuanbao": ("yuanbao"),
    "moa": ("moa", "mixture_of_agents"),
    "rl": ("rl",),
    "tts": ("tts", "text_to_speech"),
    "clarify": ("clarify",),
    "delegation": ("delegation", "delegate_task"),
}
_NATIVE_TOOL_CONFIG_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "web",
        "title": "联网与网页读取",
        "summary": "配置 Native web_search / web_extract 使用的搜索与网页读取后端。",
        "fields": (
            {
                "key": "web.backend",
                "config_key": "web.backend",
                "label": "Web Provider",
                "kind": "select",
                "default": "firecrawl",
                "options": (
                    {"value": "firecrawl", "label": "Firecrawl"},
                    {"value": "exa", "label": "Exa"},
                    {"value": "parallel", "label": "Parallel"},
                    {"value": "tavily", "label": "Tavily"},
                ),
            },
            {
                "key": "FIRECRAWL_API_KEY",
                "env_key": "FIRECRAWL_API_KEY",
                "label": "Firecrawl API Key",
                "kind": "password",
                "help": "Firecrawl Cloud 搜索、抓取与网页读取。",
                "visible_when": {"field": "web.backend", "equals": "firecrawl"},
            },
            {
                "key": "FIRECRAWL_API_URL",
                "env_key": "FIRECRAWL_API_URL",
                "label": "Firecrawl 自托管 URL",
                "kind": "text",
                "required": False,
                "placeholder": "http://localhost:3002",
                "visible_when": {"field": "web.backend", "equals": "firecrawl"},
            },
            {
                "key": "EXA_API_KEY",
                "env_key": "EXA_API_KEY",
                "label": "Exa API Key",
                "kind": "password",
                "visible_when": {"field": "web.backend", "equals": "exa"},
            },
            {
                "key": "PARALLEL_API_KEY",
                "env_key": "PARALLEL_API_KEY",
                "label": "Parallel API Key",
                "kind": "password",
                "visible_when": {"field": "web.backend", "equals": "parallel"},
            },
            {
                "key": "TAVILY_API_KEY",
                "env_key": "TAVILY_API_KEY",
                "label": "Tavily API Key",
                "kind": "password",
                "visible_when": {"field": "web.backend", "equals": "tavily"},
            },
        ),
    },
    {
        "id": "browser",
        "title": "浏览器自动化",
        "summary": "配置 browser_navigate / browser_click 等基础浏览器工具。",
        "fields": (
            {
                "key": "browser.cloud_provider",
                "config_key": "browser.cloud_provider",
                "label": "浏览器 Provider",
                "kind": "select",
                "default": "local",
                "options": (
                    {"value": "local", "label": "本机 Chromium"},
                    {"value": "browser-use", "label": "Browser Use Cloud"},
                    {"value": "browserbase", "label": "Browserbase"},
                    {"value": "firecrawl", "label": "Firecrawl Browser"},
                    {"value": "camofox", "label": "Camofox"},
                ),
            },
            {
                "key": "browser.auto_local_for_private_urls",
                "config_key": "browser.auto_local_for_private_urls",
                "label": "私有地址自动走本机浏览器",
                "kind": "checkbox",
                "default": True,
            },
            {
                "key": "BROWSER_USE_API_KEY",
                "env_key": "BROWSER_USE_API_KEY",
                "label": "Browser Use API Key",
                "kind": "password",
                "visible_when": {"field": "browser.cloud_provider", "equals": "browser-use"},
            },
            {
                "key": "BROWSERBASE_API_KEY",
                "env_key": "BROWSERBASE_API_KEY",
                "label": "Browserbase API Key",
                "kind": "password",
                "visible_when": {"field": "browser.cloud_provider", "equals": "browserbase"},
            },
            {
                "key": "BROWSERBASE_PROJECT_ID",
                "env_key": "BROWSERBASE_PROJECT_ID",
                "label": "Browserbase Project ID",
                "kind": "text",
                "visible_when": {"field": "browser.cloud_provider", "equals": "browserbase"},
            },
            {
                "key": "CAMOFOX_URL",
                "env_key": "CAMOFOX_URL",
                "label": "Camofox URL",
                "kind": "text",
                "placeholder": "http://localhost:9377",
                "visible_when": {"field": "browser.cloud_provider", "equals": "camofox"},
            },
        ),
    },
    {
        "id": "browser-cdp",
        "title": "浏览器 CDP 高级控制",
        "summary": "连接已经开启远程调试端口的 Chrome，用于 CDP 级别的高级浏览器操作。",
        "action": "launch_browser_cdp",
        "fields": (
            {
                "key": "browser.cdp_url",
                "config_key": "browser.cdp_url",
                "label": "CDP Endpoint",
                "kind": "text",
                "placeholder": "http://127.0.0.1:9222",
            },
            {
                "key": "browser.allow_private_urls",
                "config_key": "browser.allow_private_urls",
                "label": "允许云浏览器访问私有地址",
                "kind": "checkbox",
                "default": False,
            },
        ),
    },
    {
        "id": "image_gen",
        "title": "图片生成",
        "summary": "配置 Native image_generate 工具；内置路径使用 FAL，插件路径使用 image_gen.provider。",
        "fields": (
            {
                "key": "image_gen.provider",
                "config_key": "image_gen.provider",
                "label": "Image Provider",
                "kind": "select",
                "default": "fal",
                "help": "保持和当前 Native image_gen provider 一致。",
                "options_factory": "image_gen_provider_options",
            },
            {
                "key": "image_gen.model",
                "config_key": "image_gen.model",
                "label": "图片模型",
                "kind": "select",
                "default": _FAL_IMAGE_GEN_MODELS[0],
                "help": "模型列表会随 provider 变化。",
                "options": tuple({"value": model, "label": model} for model in _FAL_IMAGE_GEN_MODELS),
                "option_groups_factory": "image_gen_model_option_groups",
                "options_follow_field": "image_gen.provider",
            },
            {
                "key": "FAL_KEY",
                "env_key": "FAL_KEY",
                "label": "FAL API Key",
                "kind": "password",
                "visible_when": {"field": "image_gen.provider", "equals": "fal"},
            },
            {
                "key": "OPENAI_API_KEY",
                "env_key": "OPENAI_API_KEY",
                "label": "OpenAI API Key",
                "kind": "password",
                "visible_when": {"field": "image_gen.provider", "in": ("openai", "openai-codex")},
            },
            {
                "key": "XAI_API_KEY",
                "env_key": "XAI_API_KEY",
                "label": "xAI API Key",
                "kind": "password",
                "visible_when": {"field": "image_gen.provider", "equals": "xai"},
            },
        ),
    },
    {
        "id": "discord",
        "title": "Discord",
        "summary": "配置 Discord Bot 凭据；read 与 admin 工具共用同一 token。",
        "fields": (
            {
                "key": "DISCORD_BOT_TOKEN",
                "env_key": "DISCORD_BOT_TOKEN",
                "label": "Discord Bot Token",
                "kind": "password",
            },
            {
                "key": "DISCORD_ALLOWED_USERS",
                "env_key": "DISCORD_ALLOWED_USERS",
                "label": "允许用户",
                "kind": "text",
                "required": False,
                "placeholder": "逗号分隔的 Discord user id",
            },
        ),
    },
    {
        "id": "homeassistant",
        "title": "Home Assistant",
        "summary": "配置 Home Assistant REST API 地址和长期访问 token。",
        "fields": (
            {
                "key": "HASS_URL",
                "env_key": "HASS_URL",
                "label": "Home Assistant URL",
                "kind": "text",
                "placeholder": "http://homeassistant.local:8123",
            },
            {
                "key": "HASS_TOKEN",
                "env_key": "HASS_TOKEN",
                "label": "Long-Lived Access Token",
                "kind": "password",
            },
        ),
    },
    {
        "id": "moa",
        "title": "MoA",
        "summary": "Native mixture_of_agents 目前依赖 OpenRouter。",
        "fields": (
            {
                "key": "OPENROUTER_API_KEY",
                "env_key": "OPENROUTER_API_KEY",
                "label": "OpenRouter API Key",
                "kind": "password",
            },
        ),
    },
    {
        "id": "rl",
        "title": "RL",
        "summary": "配置 Tinker / Atropos 与 Weights & Biases 凭据。",
        "fields": (
            {
                "key": "TINKER_API_KEY",
                "env_key": "TINKER_API_KEY",
                "label": "Tinker API Key",
                "kind": "password",
            },
            {
                "key": "WANDB_API_KEY",
                "env_key": "WANDB_API_KEY",
                "label": "WandB API Key",
                "kind": "password",
            },
        ),
    },
    {
        "id": "messaging",
        "title": "消息通知",
        "summary": "跨平台消息发送涉及 Telegram/Slack/Matrix/Webhook 等多组凭据，第一版保留原生向导入口。",
        "fields": (),
        "terminal_command": "native setup",
    },
    {
        "id": "spotify",
        "title": "Spotify",
        "summary": "Spotify 使用 OAuth 流程，第一版请通过 Native 原生 tools/setup 向导完成授权。",
        "fields": (),
        "terminal_command": "native setup",
    },
    {
        "id": "yuanbao",
        "title": "腾讯元宝",
        "summary": "元宝扩展配置由 Native yuanbao 工具维护，第一版只提供状态与原生向导入口。",
        "fields": (),
        "terminal_command": "native setup",
    },
)
_NATIVE_TOOL_CONFIG_BY_ID = {str(item["id"]): item for item in _NATIVE_TOOL_CONFIG_CATALOG}
_TERMINAL_COMMAND_THROTTLE_SECONDS = 1.2
_TERMINAL_COMMAND_LOCK = threading.Lock()
_LAST_TERMINAL_COMMAND_AT = 0.0
def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _build_vision_test_png() -> bytes:
    width = 64
    height = 32
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if x < width // 2:
                color = (242, 82, 82) if y < height // 2 else (255, 215, 90)
            else:
                color = (80, 180, 130) if y < height // 2 else (90, 150, 255)
            row.extend(color)
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


_VISION_TEST_PNG = _build_vision_test_png()


def _serialize_summary(summary: Optional[ModelSummary]) -> Dict[str, Any]:
    """将 ModelSummary 转为 JSON 安全字典，None 时返回空摘要。"""
    if summary is None:
        return {"available": False}
    return {
        "available": not summary.is_empty(),
        "model3_json": summary.model3_json,
        "moc3_file": summary.moc3_file,
        "found_in_subdir": summary.found_in_subdir,
        "subdir_name": summary.subdir_name,
        "extra_moc3_count": summary.extra_moc3_count,
        # 主候选绝对路径 — 供 Electron Live2D renderer 消费
        "primary_model3_json_abs": summary.primary_model3_json_abs,
        "primary_moc3_abs": summary.primary_moc3_abs,
        "renderer_entry": summary.renderer_entry,  # 推荐入口（model3.json 优先）
    }


def _compact_command_output(text: str, limit: int = 900) -> str:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    elif not isinstance(text, str):
        text = str(text or "")
    cleaned = _ANSI_RE.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern in _SECRET_REDACTIONS:
        cleaned = pattern.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}[redacted]"
                if len(match.groups()) >= 3
                else "[redacted]"
            ),
            cleaned,
        )
    lines = [line.rstrip() for line in cleaned.split("\n") if line.strip()]
    if not lines:
        return ""
    detail = "\n".join(lines[-8:])
    if len(detail) > limit:
        return "..." + detail[-limit:]
    return detail


def _sanitize_command_output(text: str, limit: int = 30000) -> str:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    elif not isinstance(text, str):
        text = str(text or "")
    cleaned = _ANSI_RE.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern in _SECRET_REDACTIONS:
        cleaned = pattern.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}[redacted]"
                if len(match.groups()) >= 3
                else "[redacted]"
            ),
            cleaned,
        )
    cleaned = cleaned.rstrip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n\n[output truncated]"


def _public_command(argv: list[str]) -> str:
    if "-z" not in argv:
        return " ".join(argv)
    index = argv.index("-z")
    return " ".join(argv[: index + 1] + ["<connectivity-check>"] + argv[index + 2:])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_cache_path() -> Path:
    return Path(shell_config._CONFIG_DIR) / _NATIVE_CONNECTION_CACHE_FILE


def _image_connection_cache_path() -> Path:
    return Path(shell_config._CONFIG_DIR) / _NATIVE_IMAGE_CONNECTION_CACHE_FILE


def _diagnostic_cache_path() -> Path:
    return Path(shell_config._CONFIG_DIR) / _NATIVE_DIAGNOSTIC_CACHE_FILE


def _native_tool_config_path() -> Path:
    return Path(shell_config._CONFIG_DIR) / _NATIVE_TOOL_CONFIG_FILE


def _load_native_tool_config_projection() -> dict[str, Any]:
    path = _native_tool_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "config": {}, "env_configured": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "config": {}, "env_configured": {}}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    env_configured = data.get("env_configured") if isinstance(data.get("env_configured"), dict) else {}
    return {
        "schema_version": 1,
        "config": {str(key): value for key, value in config.items()},
        "env_configured": {str(key): bool(value) for key, value in env_configured.items()},
    }


def _store_native_tool_config_projection(projection: dict[str, Any]) -> None:
    record = {
        "schema_version": 1,
        "updated_at": _utc_now_iso(),
        "config": projection.get("config") if isinstance(projection.get("config"), dict) else {},
        "env_configured": (
            projection.get("env_configured") if isinstance(projection.get("env_configured"), dict) else {}
        ),
    }
    path = _native_tool_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("写入 Native 工具配置投影失败: %s", exc)
        raise


def _tool_projection_values(projection: dict[str, Any]) -> tuple[dict[tuple[str, ...], str], dict[str, str]]:
    config = projection.get("config") if isinstance(projection.get("config"), dict) else {}
    env_configured = projection.get("env_configured") if isinstance(projection.get("env_configured"), dict) else {}
    config_values = {
        tuple(str(key).split(".")): str(value)
        for key, value in config.items()
        if str(key).strip()
    }
    env_values = {str(key): "[configured]" for key, value in env_configured.items() if bool(value)}
    return config_values, env_values


def _connection_fingerprint_payload(configuration: dict[str, Any]) -> dict[str, Any]:
    model = configuration.get("model") if isinstance(configuration.get("model"), dict) else {}
    api_key = configuration.get("api_key") if isinstance(configuration.get("api_key"), dict) else {}
    return {
        "provider": str(model.get("provider") or ""),
        "model": str(model.get("default") or ""),
        "base_url": str(model.get("base_url") or ""),
        "api_key_name": str(api_key.get("name") or ""),
        "api_key_configured": bool(api_key.get("configured")),
    }


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _connection_fingerprint(configuration: dict[str, Any]) -> str:
    return _fingerprint_payload(_connection_fingerprint_payload(configuration))


def _diagnostic_fingerprint_payload(configuration: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection": _connection_fingerprint_payload(configuration),
        "tool_config_state": configuration.get("tool_config_state") or {},
    }


def _diagnostic_fingerprint(configuration: dict[str, Any]) -> str:
    return _fingerprint_payload(_diagnostic_fingerprint_payload(configuration))


def _connection_cache_matches_configuration(data: dict[str, Any], configuration: dict[str, Any]) -> bool:
    payload = _connection_fingerprint_payload(configuration)
    return (
        str(data.get("provider") or "") == payload["provider"]
        and str(data.get("model") or "") == payload["model"]
        and str(data.get("base_url") or "") == payload["base_url"]
        and str(data.get("api_key_name") or "") == payload["api_key_name"]
    )


def _image_connection_fingerprint_payload(configuration: dict[str, Any]) -> dict[str, Any]:
    image_input = configuration.get("image_input") if isinstance(configuration.get("image_input"), dict) else {}
    vision = configuration.get("vision") if isinstance(configuration.get("vision"), dict) else {}
    return {
        "connection": _connection_fingerprint_payload(configuration),
        "image_input": {
            "mode": str(image_input.get("mode") or ""),
            "route": str(image_input.get("route") or ""),
            "provider": str(image_input.get("provider") or ""),
            "model": str(image_input.get("model") or ""),
            "supports_native_vision": image_input.get("supports_native_vision"),
            "requires_vision_pipeline": bool(image_input.get("requires_vision_pipeline")),
        },
        "vision": {
            "configured": bool(vision.get("configured")),
            "provider": str(vision.get("provider") or ""),
            "model": str(vision.get("model") or ""),
            "base_url": str(vision.get("base_url") or ""),
            "api_key_name": str(vision.get("api_key_name") or ""),
            "api_key_configured": bool(vision.get("api_key_configured")),
            "effective_provider": str(vision.get("effective_provider") or ""),
            "effective_model": str(vision.get("effective_model") or ""),
            "effective_base_url": str(vision.get("effective_base_url") or ""),
        },
    }


def _image_connection_fingerprint(configuration: dict[str, Any]) -> str:
    return _fingerprint_payload(_image_connection_fingerprint_payload(configuration))


def _image_connection_cache_matches_configuration(data: dict[str, Any], configuration: dict[str, Any]) -> bool:
    payload = _image_connection_fingerprint_payload(configuration)
    image_input = payload["image_input"]
    return (
        str(data.get("route") or "") == image_input["route"]
        and str(data.get("provider") or "") == image_input["provider"]
        and str(data.get("model") or "") == image_input["model"]
    )


def _load_connection_validation(configuration: dict[str, Any]) -> dict[str, Any]:
    cache_path = _connection_cache_path()
    fingerprint = _connection_fingerprint(configuration)
    base = {
        "verified": False,
        "success": False,
        "fingerprint": fingerprint,
        "cache_path": str(cache_path),
    }
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict) or data.get("schema_version") != _NATIVE_CONNECTION_CACHE_SCHEMA:
        return base
    if data.get("fingerprint") != fingerprint and not _connection_cache_matches_configuration(data, configuration):
        return {
            **base,
            "reason": "config_changed",
            "previous_provider": data.get("provider"),
            "previous_model": data.get("model"),
            "last_tested_at": data.get("tested_at") or data.get("verified_at"),
        }
    return {
        **base,
        "verified": bool(data.get("verified")),
        "success": bool(data.get("verified")),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "base_url": data.get("base_url"),
        "api_key_name": data.get("api_key_name"),
        "message": data.get("message"),
        "error": data.get("error"),
        "tested_at": data.get("tested_at"),
        "verified_at": data.get("verified_at"),
        "elapsed_seconds": data.get("elapsed_seconds"),
    }


def _store_connection_validation(
    configuration: dict[str, Any],
    *,
    success: bool,
    message: str = "",
    error: str = "",
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    model = configuration.get("model") if isinstance(configuration.get("model"), dict) else {}
    api_key = configuration.get("api_key") if isinstance(configuration.get("api_key"), dict) else {}
    now = _utc_now_iso()
    record: dict[str, Any] = {
        "schema_version": _NATIVE_CONNECTION_CACHE_SCHEMA,
        "fingerprint": _connection_fingerprint(configuration),
        "verified": success,
        "provider": str(model.get("provider") or ""),
        "model": str(model.get("default") or ""),
        "base_url": str(model.get("base_url") or ""),
        "api_key_name": str(api_key.get("name") or ""),
        "message": message if success else "",
        "error": "" if success else error,
        "tested_at": now,
        "elapsed_seconds": elapsed_seconds,
    }
    if success:
        record["verified_at"] = now
    path = _connection_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("写入 Native 连接验证缓存失败: %s", exc)
    return _load_connection_validation(configuration)


def _load_image_connection_validation(configuration: dict[str, Any]) -> dict[str, Any]:
    cache_path = _image_connection_cache_path()
    fingerprint = _image_connection_fingerprint(configuration)
    base = {
        "verified": False,
        "success": False,
        "fingerprint": fingerprint,
        "cache_path": str(cache_path),
    }
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict) or data.get("schema_version") != _NATIVE_IMAGE_CONNECTION_CACHE_SCHEMA:
        return base
    if data.get("fingerprint") != fingerprint and not _image_connection_cache_matches_configuration(data, configuration):
        return {
            **base,
            "reason": "config_changed",
            "previous_route": data.get("route"),
            "previous_provider": data.get("provider"),
            "previous_model": data.get("model"),
            "last_tested_at": data.get("tested_at") or data.get("verified_at"),
        }
    return {
        **base,
        "verified": bool(data.get("verified")),
        "success": bool(data.get("verified")),
        "route": data.get("route"),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "message": data.get("message"),
        "error": data.get("error"),
        "tested_at": data.get("tested_at"),
        "verified_at": data.get("verified_at"),
        "elapsed_seconds": data.get("elapsed_seconds"),
    }


def _store_image_connection_validation(
    configuration: dict[str, Any],
    *,
    success: bool,
    message: str = "",
    error: str = "",
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    image_input = configuration.get("image_input") if isinstance(configuration.get("image_input"), dict) else {}
    now = _utc_now_iso()
    record: dict[str, Any] = {
        "schema_version": _NATIVE_IMAGE_CONNECTION_CACHE_SCHEMA,
        "fingerprint": _image_connection_fingerprint(configuration),
        "verified": success,
        "route": str(image_input.get("route") or ""),
        "provider": str(image_input.get("provider") or ""),
        "model": str(image_input.get("model") or ""),
        "message": message if success else "",
        "error": "" if success else error,
        "tested_at": now,
        "elapsed_seconds": elapsed_seconds,
    }
    if success:
        record["verified_at"] = now
    path = _image_connection_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("写入 Native 图片链路验证缓存失败: %s", exc)
    return _load_image_connection_validation(configuration)


_IMAGE_PROBE_BAD_MARKERS = (
    "看不到",
    "无法",
    "不能读取",
    "未能读取",
    "没有收到图片",
    "没有加载",
    "api key",
    "api 密钥",
    "密钥问题",
    "cannot see",
    "unable to see",
    "no image",
    "not see",
)


def _parse_stream_bridge_probe(stdout: str) -> tuple[str, str, bool]:
    """Return (response, error, failed) from newline-delimited bridge events."""
    parts: list[str] = []
    final_response = ""
    error_message = ""
    failed = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
        elif event_type == "error":
            message = event.get("message")
            if isinstance(message, str) and message.strip():
                error_message = message.strip()
                failed = True
        elif event_type == "done":
            response = event.get("response")
            if isinstance(response, str):
                final_response = response.strip()
            failed = failed or bool(event.get("failed"))
            error = event.get("error")
            if isinstance(error, str) and error.strip():
                error_message = error.strip()
    response_text = final_response or "".join(parts).strip() or stdout.strip()
    return response_text, error_message, failed


def _image_probe_response_ok(response: str) -> bool:
    value = str(response or "").strip()
    if not value:
        return False
    lower = value.lower()
    if any(marker in lower for marker in _IMAGE_PROBE_BAD_MARKERS):
        return False
    return value.upper() == "OK" or "绿" in value or "green" in lower


def _load_diagnostic_cache(configuration: dict[str, Any]) -> dict[str, Any]:
    cache_path = _diagnostic_cache_path()
    fingerprint = _diagnostic_fingerprint(configuration)
    base: dict[str, Any] = {
        "schema_version": _NATIVE_DIAGNOSTIC_CACHE_SCHEMA,
        "fingerprint": fingerprint,
        "cache_path": str(cache_path),
        "stale": False,
        "commands": {},
    }
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict) or data.get("schema_version") != _NATIVE_DIAGNOSTIC_CACHE_SCHEMA:
        return base

    stale = data.get("fingerprint") != fingerprint
    commands: dict[str, Any] = {}
    raw_commands = data.get("commands")
    if isinstance(raw_commands, dict):
        allowed_ids = {item["id"] for item in _diagnostic_command_catalog()}
        for command_id, value in raw_commands.items():
            if command_id not in allowed_ids or not isinstance(value, dict):
                continue
            commands[command_id] = {**deepcopy(value), "stale": stale}

    return {
        **base,
        "stale": stale,
        "reason": "config_changed" if stale else "",
        "previous_fingerprint": data.get("fingerprint") if stale else "",
        "updated_at": data.get("updated_at"),
        "commands": commands,
    }


def _store_diagnostic_result(
    configuration: dict[str, Any],
    action: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    cache_path = _diagnostic_cache_path()
    fingerprint = _diagnostic_fingerprint(configuration)
    commands: dict[str, Any] = {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(data, dict)
            and data.get("schema_version") == _NATIVE_DIAGNOSTIC_CACHE_SCHEMA
            and data.get("fingerprint") == fingerprint
            and isinstance(data.get("commands"), dict)
        ):
            commands = deepcopy(data["commands"])
    except (OSError, json.JSONDecodeError):
        commands = {}

    now = _utc_now_iso()
    cached_payload = deepcopy(payload)
    cached_payload.pop("dashboard", None)
    cached_payload["cached_at"] = now
    cached_payload["stale"] = False
    commands[str(action["id"])] = cached_payload
    record = {
        "schema_version": _NATIVE_DIAGNOSTIC_CACHE_SCHEMA,
        "fingerprint": fingerprint,
        "updated_at": now,
        "commands": commands,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("写入 Native 诊断缓存失败: %s", exc)
    return _load_diagnostic_cache(configuration)


def _parse_doctor_diagnostic_output(output: str) -> dict[str, Any]:
    return {
        "readiness_level": "native",
        "available_tools": [],
        "limited_tools": [],
        "limited_tool_details": {},
        "doctor_issues_count": 0 if output else 1,
    }


def _native_command_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": "setup",
            "label": "打开模型配置",
            "command": "native setup",
            "description": "兼容入口：模型与密钥现在由 Model Profile 管理。",
        },
        {
            "id": "model",
            "label": "选择默认模型",
            "command": "native model",
            "description": "兼容入口：选择默认 Chat/Vision Model Profile。",
        },
        {
            "id": "config-edit",
            "label": "编辑 Native 配置",
            "command": "native config edit",
            "description": "兼容入口：Native Runtime 不再依赖 Native 配置文件。",
        },
        {
            "id": "config-check",
            "label": "检查 Native 配置",
            "command": "native config check",
            "description": "检查默认模型、工具投影与桌面运行时状态，不发起模型请求。",
        },
        {
            "id": "doctor",
            "label": "运行 Native 诊断",
            "command": "native doctor",
            "description": "检查 Native Agent readiness、工作区和工具配置投影。",
        },
        {
            "id": "auth-list",
            "label": "查看凭据状态",
            "command": "native auth list",
            "description": "查看 Model Profile 凭据配置状态，不显示密钥内容。",
        },
    ]


def _allowed_terminal_commands() -> set[str]:
    return {item["command"] for item in _native_command_catalog()}


def _diagnostic_command_catalog() -> list[dict[str, str]]:
    return [
        item
        for item in _native_command_catalog()
        if item.get("id") in {"config-check", "doctor", "auth-list"}
    ]


def _diagnostic_command_by_command(command: str) -> dict[str, str] | None:
    normalized = " ".join((command or "").strip().split())
    return next(
        (item for item in _diagnostic_command_catalog() if item["command"] == normalized),
        None,
    )


def _is_macos_prerequisite_command(cmd: str) -> bool:
    return (
        "Oha-Yachiyo macOS 基础工具检查" in cmd
        and "xcode-select --install" in cmd
        and "brew install git curl" in cmd
    )


def _is_gpt_sovits_service_command(cmd: str) -> bool:
    if "Oha-Yachiyo GPT-SoVITS 服务启动" in cmd:
        return "cd " in cmd and ("api_v2.py" in cmd or "api.py" in cmd)
    if "Oha-Yachiyo GPT-SoVITS 一键部署" in cmd:
        return (
            "github.com/RVC-Boss/GPT-SoVITS" in cmd
            and "git clone" in cmd
            and ("api_v2.py" in cmd or "api.py" in cmd)
        )
    return False


def _reset_terminal_command_gate() -> None:
    global _LAST_TERMINAL_COMMAND_AT
    with _TERMINAL_COMMAND_LOCK:
        _LAST_TERMINAL_COMMAND_AT = 0.0


def _strip_yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if value in {"", "null", "None", "~"}:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def _read_yaml_paths(config_path: Path, wanted: set[tuple[str, ...]]) -> dict[tuple[str, ...], str]:
    if not config_path.exists():
        return {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
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
        flat_path_key = tuple(key.split("."))
        if flat_path_key in wanted:
            values[flat_path_key] = _strip_yaml_scalar(raw_value)
    return values


def _read_user_provider_overrides(config_path: Path) -> dict[str, dict[str, str]]:
    if not config_path.exists():
        return {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    providers: dict[str, dict[str, str]] = {}
    in_providers = False
    current_provider = ""
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            in_providers = line.startswith("providers:")
            current_provider = ""
            continue
        if not in_providers:
            continue
        provider_match = re.match(r"\s{2}([A-Za-z0-9_.-]+):\s*$", line)
        if provider_match:
            current_provider = provider_match.group(1)
            providers.setdefault(current_provider, {})
            continue
        field_match = re.match(r"\s{4}([A-Za-z0-9_-]+):\s*(.*)$", line)
        if field_match and current_provider:
            key, raw_value = field_match.groups()
            providers[current_provider][key] = _strip_yaml_scalar(raw_value)
    return providers


def _preset_models(provider_id: str, preset: dict[str, Any]) -> list[str]:
    fallback = [str(item) for item in preset.get("models", ()) if item]
    merged: list[str] = []
    seen: set[str] = set()
    for item in fallback:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return merged


def _vision_capable_models(provider_id: str, models: list[str]) -> list[str]:
    supported = [
        model
        for model in models
        if lookup_model_supports_vision(provider_id, model) is True
    ]
    if supported:
        return supported
    return models


def _default_auxiliary_vision_model(provider_id: str, models: list[str]) -> str:
    provider = provider_id.strip().lower()
    preferred = _PREFERRED_AUXILIARY_VISION_MODELS.get(provider)
    if preferred and (not models or preferred in models):
        return preferred
    supported = _vision_capable_models(provider, models)
    return supported[0] if supported else ""


def _normalize_auxiliary_vision_model(provider_id: str, model: str) -> str:
    provider = provider_id.strip().lower()
    model_name = model.strip()
    models = _preset_models(provider, _PROVIDER_PRESET_BY_ID.get(provider, {}))
    if not model_name:
        return _default_auxiliary_vision_model(provider, models)
    if lookup_model_supports_vision(provider, model_name) is False:
        replacement = _default_auxiliary_vision_model(provider, models)
        if replacement:
            return replacement
    return model_name


def _read_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return values


def _provider_api_key_name(provider: str) -> str:
    names = _provider_api_key_names(provider)
    return names[0] if names else ""


def _model_profile_config_for_native(profile_id: str, capability: str) -> dict[str, str]:
    from apps.shell.model_profiles import get_model_profile_service

    profile = get_model_profile_service().get_profile_private(profile_id)
    actual_capability = str(profile.get("capability") or "chat")
    if actual_capability != capability:
        raise ValueError(f"{capability} Profile 类型不匹配")
    if str(profile.get("status") or "") != "available":
        raise ValueError("只能选择已通过连接测试的模型 Profile")
    if not profile.get("enabled", True):
        raise ValueError("不能选择已暂停的模型 Profile")
    provider = str(profile.get("provider") or "openai_compatible").strip()
    model = str(profile.get("model") or "").strip()
    base_url = str(profile.get("base_url") or "").strip()
    api_key = str(profile.get("api_key") or "").strip()
    missing = [
        key
        for key, value in (("provider", provider), ("model", model), ("base_url", base_url), ("api_key", api_key))
        if not value
    ]
    if missing:
        raise ValueError(f"模型 Profile 配置不完整：缺少 {', '.join(missing)}")
    provider = _model_profile_provider_for_native(provider, base_url, model)
    if not provider:
        raise ValueError("当前模型源不能映射到 Native Runtime 支持的 Provider")
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }


def _provider_api_key_names(provider: str) -> tuple[str, ...]:
    normalized = provider.strip().lower()
    if not normalized:
        return ()
    preset = _PROVIDER_PRESET_BY_ID.get(normalized)
    if preset:
        return tuple(str(item) for item in preset.get("api_key_names", ()) if item)
    return provider_api_key_names(normalized)


def _model_profile_provider_for_native(provider: str, base_url: str = "", model: str = "") -> str:
    adapter = resolve_provider_adapter(provider, base_url, model)
    return str(adapter.get("native_provider") or "")


def _configured_api_key_name(
    api_key_names: tuple[str, ...],
    env_values: dict[str, str],
    provider: str,
) -> str:
    configured_key = next((name for name in api_key_names if env_values.get(name)), "")
    if configured_key:
        return configured_key
    if (provider or "").strip().lower() == "openrouter" and env_values.get("AUTO_API_KEY"):
        return api_key_names[0] if api_key_names else "OPENROUTER_API_KEY"
    return ""


def _effective_provider_id(provider: str, base_url: str = "", model: str = "") -> str:
    adapter = resolve_provider_adapter(provider, base_url, model)
    return str(adapter.get("native_provider") or (provider or "").strip().lower())


def _normalize_image_input_mode(mode: Any) -> str:
    normalized = str(mode or "auto").strip().lower()
    normalized = _NATIVE_IMAGE_INPUT_MODE_ALIASES.get(normalized, normalized)
    return normalized if normalized in _NATIVE_IMAGE_INPUT_MODES else "auto"


def _provider_options(
    *,
    current_provider: str,
    config_path: Path,
    env_values: dict[str, str],
) -> list[dict[str, Any]]:
    overrides = _read_user_provider_overrides(config_path)
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preset in _NATIVE_PROVIDER_PRESETS:
        provider_id = str(preset["id"])
        override = overrides.get(provider_id, {})
        base_url_env = str(preset.get("base_url_env") or "")
        api_key_names = tuple(str(item) for item in preset.get("api_key_names", ()) if item)
        models = _preset_models(provider_id, preset)
        configured_key = _configured_api_key_name(api_key_names, env_values, provider_id)
        configured = (
            bool(configured_key)
            or str(preset.get("auth_type") or "") != "api_key" and not api_key_names
        )
        base_url = env_values.get(base_url_env) if base_url_env else ""
        base_url = override.get("base_url") or base_url or str(preset.get("base_url") or "")
        default_model = override.get("model") or override.get("default") or (
            models[0] if models else ""
        )
        vision_models = _vision_capable_models(provider_id, models)
        options.append(
            {
                "id": provider_id,
                "label": str(preset.get("label") or provider_id),
                "base_url": base_url,
                "default_model": default_model,
                "default_vision_model": _default_auxiliary_vision_model(provider_id, models),
                "models": models,
                "vision_models": vision_models,
                "api_key_names": list(api_key_names),
                "api_key_name": configured_key or (api_key_names[0] if api_key_names else ""),
                "api_key_configured": configured,
                "auth_type": str(preset.get("auth_type") or "api_key"),
                "source": "native",
                "is_current": provider_id == current_provider,
            }
        )
        seen.add(provider_id)

    for provider_id, override in overrides.items():
        if provider_id in seen:
            continue
        api_key_names = _provider_api_key_names(provider_id)
        configured_key = _configured_api_key_name(api_key_names, env_values, provider_id)
        models = [override["model"]] if override.get("model") else []
        options.append(
            {
                "id": provider_id,
                "label": override.get("name") or provider_id,
                "base_url": override.get("base_url") or "",
                "default_model": override.get("model") or override.get("default") or "",
                "default_vision_model": _default_auxiliary_vision_model(provider_id, models),
                "models": models,
                "vision_models": _vision_capable_models(provider_id, models),
                "api_key_names": list(api_key_names),
                "api_key_name": configured_key or (api_key_names[0] if api_key_names else ""),
                "api_key_configured": bool(configured_key),
                "auth_type": override.get("auth_type") or "api_key",
                "source": "user-config",
                "is_current": provider_id == current_provider,
            }
        )

    if current_provider and current_provider not in {option["id"] for option in options}:
        api_key_names = _provider_api_key_names(current_provider)
        configured_key = _configured_api_key_name(api_key_names, env_values, current_provider)
        options.insert(
            0,
            {
                "id": current_provider,
                "label": current_provider,
                "base_url": "",
                "default_model": "",
                "default_vision_model": "",
                "models": [],
                "vision_models": [],
                "api_key_names": list(api_key_names),
                "api_key_name": configured_key or (api_key_names[0] if api_key_names else ""),
                "api_key_configured": bool(configured_key),
                "auth_type": "api_key",
                "source": "current-config",
                "is_current": True,
            },
        )

    return sorted(
        options,
        key=lambda item: (
            not bool(item.get("is_current")),
            not bool(item.get("api_key_configured")),
            str(item.get("label") or item.get("id") or "").lower(),
        ),
    )


def _vision_configuration_summary(
    *,
    config_path: Path,
    env_values: dict[str, str],
    chat_provider: str,
    chat_model: str,
    chat_base_url: str,
) -> dict[str, Any]:
    image_config: dict[str, Any] = {}
    configured_provider = ""
    effective_chat_provider = _effective_provider_id(chat_provider, chat_base_url, chat_model)
    configured_base_url = ""
    configured_model = ""
    provider = configured_provider if configured_provider and configured_provider != "auto" else ""
    provider_for_key = (
        _effective_provider_id(configured_provider, configured_base_url or chat_base_url, configured_model or chat_model)
        if configured_provider
        else effective_chat_provider
    )
    effective_provider = provider_for_key or provider or effective_chat_provider
    effective_model = _normalize_auxiliary_vision_model(
        effective_provider,
        configured_model or chat_model or "",
    )
    api_key_names = _provider_api_key_names(provider_for_key)
    configured_key = _configured_api_key_name(api_key_names, env_values, provider_for_key)
    return {
        "configured": False,
        "provider": provider,
        "model": configured_model,
        "base_url": configured_base_url,
        "api_key_name": configured_key or (api_key_names[0] if api_key_names else ""),
        "api_key_configured": bool(configured_key),
        "effective_provider": effective_provider,
        "effective_model": effective_model,
        "effective_base_url": str(configured_base_url or chat_base_url or ""),
    }


def _canonical_tool_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _read_image_gen_plugin_options() -> tuple[dict[str, str], ...]:
    return ()


def _image_gen_provider_options() -> tuple[dict[str, str], ...]:
    options: list[dict[str, str]] = [{"value": "fal", "label": "FAL.ai"}]
    seen = {"fal"}
    for option in _read_image_gen_plugin_options():
        value = option["value"]
        if value in seen:
            continue
        seen.add(value)
        options.append(option)
    # Keep the known bundled plugin choices when no plugin source is available.
    if len(options) == 1:
        for value, label in (
            ("openai", "OpenAI plugin"),
            ("openai-codex", "OpenAI Codex plugin"),
            ("xai", "xAI plugin"),
        ):
            options.append({"value": value, "label": label})
    return tuple(options)


def _image_gen_model_option_groups() -> dict[str, tuple[dict[str, str], ...]]:
    providers = {option["value"] for option in _image_gen_provider_options()}
    return {
        provider: tuple({"value": model, "label": model} for model in models)
        for provider, models in _IMAGE_GEN_MODEL_OPTIONS.items()
        if provider in providers
    }


def _field_dynamic_options(field: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    factory = str(field.get("options_factory") or "")
    if factory == "image_gen_provider_options":
        return _image_gen_provider_options()
    options = field.get("options")
    if not options:
        return ()
    return tuple(options)


def _field_dynamic_option_groups(field: dict[str, Any]) -> dict[str, Any]:
    factory = str(field.get("option_groups_factory") or "")
    if factory == "image_gen_model_option_groups":
        return _image_gen_model_option_groups()
    groups = field.get("option_groups")
    if isinstance(groups, dict):
        return groups
    return {}


def _tool_aliases(tool_id: str) -> tuple[str, ...]:
    normalized = str(tool_id or "").strip()
    aliases = _NATIVE_TOOL_ALIASES.get(normalized)
    if aliases:
        return aliases
    return (normalized,)


def _tool_matches(names: list[str] | tuple[str, ...], tool_id: str) -> bool:
    candidates = {_canonical_tool_name(name) for name in names}
    return any(_canonical_tool_name(alias) in candidates for alias in _tool_aliases(tool_id))


def _all_tool_config_paths() -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for tool in _NATIVE_TOOL_CONFIG_CATALOG:
        for field in tool.get("fields", ()):
            config_key = str(field.get("config_key") or "")
            if config_key:
                paths.add(tuple(config_key.split(".")))
    return paths


def _bool_config_value(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _tool_config_state(config_path: Path, env_values: dict[str, str]) -> dict[str, Any]:
    config_values = _read_yaml_paths(config_path, _all_tool_config_paths())
    safe_config: dict[str, Any] = {}
    env_configured: dict[str, bool] = {}
    for tool in _NATIVE_TOOL_CONFIG_CATALOG:
        for field in tool.get("fields", ()):
            config_key = str(field.get("config_key") or "")
            env_key = str(field.get("env_key") or "")
            if config_key:
                path = tuple(config_key.split("."))
                raw = config_values.get(path)
                if raw is None and "default" in field:
                    raw = field.get("default")
                if field.get("kind") == "checkbox":
                    safe_config[config_key] = _bool_config_value(raw, bool(field.get("default", False)))
                else:
                    safe_config[config_key] = "" if raw is None else str(raw)
            if env_key:
                env_configured[env_key] = bool(env_values.get(env_key))
    return {
        "config": safe_config,
        "env_configured": env_configured,
    }


def _field_visible_for_state(field: dict[str, Any], state: dict[str, Any]) -> bool:
    condition = field.get("visible_when")
    if not isinstance(condition, dict) or not condition.get("field"):
        return True
    config_state = state.get("config") if isinstance(state.get("config"), dict) else {}
    current = str(config_state.get(str(condition.get("field")), "")).strip()
    if "equals" in condition:
        return current == str(condition.get("equals"))
    if isinstance(condition.get("in"), (list, tuple)):
        return current in {str(item) for item in condition["in"]}
    return True


def _field_is_configured(field: dict[str, Any], state: dict[str, Any]) -> bool:
    config_key = str(field.get("config_key") or "")
    env_key = str(field.get("env_key") or "")
    if config_key:
        config_state = state.get("config") if isinstance(state.get("config"), dict) else {}
        value = config_state.get(config_key)
        return bool(value) or "default" in field or field.get("kind") == "checkbox"
    if env_key:
        env_state = state.get("env_configured") if isinstance(state.get("env_configured"), dict) else {}
        return bool(env_state.get(env_key))
    return True


def _required_tool_fields(tool: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field in tool.get("fields", ()):
        if field.get("required") is False:
            continue
        if not _field_visible_for_state(field, state):
            continue
        if field.get("target") == "none":
            continue
        if not (field.get("config_key") or field.get("env_key")):
            continue
        fields.append(field)
    return fields


def _tool_config_field_payload(
    field: dict[str, Any],
    *,
    config_values: dict[tuple[str, ...], str],
    env_values: dict[str, str],
) -> dict[str, Any]:
    kind = str(field.get("kind") or "text")
    config_key = str(field.get("config_key") or "")
    env_key = str(field.get("env_key") or "")
    configured = False
    value: Any = ""
    if config_key:
        raw = config_values.get(tuple(config_key.split(".")))
        configured = raw is not None and raw != ""
        if raw is None and "default" in field:
            raw = field.get("default")
        if kind == "checkbox":
            value = _bool_config_value(raw, bool(field.get("default", False)))
        else:
            value = "" if raw is None else str(raw)
    elif env_key:
        configured = bool(env_values.get(env_key))
        value = ""
    payload: dict[str, Any] = {
        "key": str(field.get("key") or config_key or env_key),
        "label": str(field.get("label") or config_key or env_key),
        "kind": kind,
        "configured": configured,
        "value": value,
        "secret": kind == "password",
        "target": "env" if env_key else "config" if config_key else "none",
    }
    if config_key:
        payload["config_key"] = config_key
    if env_key:
        payload["env_key"] = env_key
    if field.get("placeholder"):
        payload["placeholder"] = str(field["placeholder"])
    if field.get("help"):
        payload["help"] = str(field["help"])
    options = _field_dynamic_options(field)
    if options:
        payload["options"] = list(options)
    if field.get("visible_when"):
        payload["visible_when"] = field["visible_when"]
    option_groups = _field_dynamic_option_groups(field)
    if option_groups:
        payload["option_groups"] = option_groups
    if field.get("options_follow_field"):
        payload["options_follow_field"] = str(field["options_follow_field"])
    if field.get("allow_custom"):
        payload["allow_custom"] = True
    return payload


def _tool_config_payload(
    tool: dict[str, Any],
    *,
    config_values: dict[tuple[str, ...], str],
    env_values: dict[str, str],
) -> dict[str, Any]:
    fields = [
        _tool_config_field_payload(field, config_values=config_values, env_values=env_values)
        for field in tool.get("fields", ())
    ]
    configured_count = sum(1 for field in fields if field.get("configured"))
    payload: dict[str, Any] = {
        "id": str(tool["id"]),
        "title": str(tool.get("title") or tool["id"]),
        "summary": str(tool.get("summary") or ""),
        "fields": fields,
        "configured_count": configured_count,
        "configurable": bool(fields),
    }
    if tool.get("action"):
        payload["action"] = str(tool["action"])
    if tool.get("terminal_command"):
        payload["terminal_command"] = str(tool["terminal_command"])
    return payload


def _field_options(field: dict[str, Any]) -> set[str]:
    if field.get("allow_custom"):
        return set()
    options = _field_dynamic_options(field)
    if not options:
        return set()
    return {str(item.get("value") or "") for item in options if item.get("value") is not None}


def _test_browser_cdp_endpoint(config_state: dict[str, Any]) -> dict[str, str]:
    config_values = config_state.get("config") if isinstance(config_state.get("config"), dict) else {}
    raw_url = str(config_values.get("browser.cdp_url") or "").strip()
    if not raw_url:
        return {"label": "CDP 端口", "status": "warn", "detail": "未配置 browser.cdp_url"}
    parsed = urlparse(raw_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return {"label": "CDP 端口", "status": "pass", "detail": f"可以连接 {host}:{port}"}
    except OSError as exc:
        return {"label": "CDP 端口", "status": "fail", "detail": f"无法连接 {host}:{port}：{exc}"}


def _doctor_status_for_tool(summary: dict[str, Any], tool_id: str) -> tuple[str, str]:
    available = [str(item) for item in summary.get("available_tools") or []]
    limited = [str(item) for item in summary.get("limited_tools") or []]
    details = summary.get("limited_tool_details")
    detail_map = details if isinstance(details, dict) else {}
    if _tool_matches(available, tool_id):
        return "pass", "Doctor 已确认该工具可用"
    if _tool_matches(limited, tool_id):
        for alias in _tool_aliases(tool_id):
            canonical = _canonical_tool_name(alias)
            match = next(
                (value for key, value in detail_map.items() if _canonical_tool_name(str(key)) == canonical),
                "",
            )
            if match:
                return "fail", f"Doctor 标记受限：{match}"
        return "fail", "Doctor 标记该工具受限"
    return "warn", "Doctor 输出未包含该工具的明确结论"


def _toolset_delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    before_map = {str(item.get("id")): item for item in before}
    after_map = {str(item.get("id")): item for item in after}
    before_ids = set(before_map)
    after_ids = set(after_map)
    changed: list[dict[str, Any]] = []
    for tool_id in sorted(before_ids & after_ids):
        before_enabled = bool(before_map[tool_id].get("enabled"))
        after_enabled = bool(after_map[tool_id].get("enabled"))
        if before_enabled != after_enabled:
            changed.append({"id": tool_id, "before_enabled": before_enabled, "after_enabled": after_enabled})
    return {
        "added": sorted(after_ids - before_ids),
        "removed": sorted(before_ids - after_ids),
        "changed": changed,
    }


def _avatar_data_uri(path_value: str, *, fallback: bool = True) -> str:
    raw_path = str(path_value or "").strip()
    if not raw_path and not fallback:
        return ""
    avatar_path = Path(raw_path or str(DEFAULT_BUBBLE_AVATAR_PATH)).expanduser()
    if not avatar_path.exists():
        if not fallback:
            return ""
        avatar_path = DEFAULT_BUBBLE_AVATAR_PATH
    try:
        return data_uri(avatar_path)
    except Exception:
        return data_uri(DEFAULT_BUBBLE_AVATAR_PATH) if fallback else ""


def _assistant_settings_payload(config: "AppConfig") -> dict[str, Any]:
    assistant = config.assistant
    return {
        "agent_name": assistant.agent_name,
        "agent_nickname": assistant.agent_nickname,
        "agent_avatar_path": assistant.agent_avatar_path,
        "agent_avatar_url": _avatar_data_uri(assistant.agent_avatar_path, fallback=True),
        "persona_prompt": assistant.persona_prompt,
        "user_address": assistant.user_address,
        "user_name": assistant.user_name,
        "user_avatar_path": assistant.user_avatar_path,
        "user_avatar_url": _avatar_data_uri(assistant.user_avatar_path, fallback=False),
        "user_profile": assistant.user_profile,
        "user_preferences": assistant.user_preferences,
    }


class MainWindowAPI:
    """Control Center 主控台 API。"""

    def __init__(self, runtime: "AppRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_api = ChatAPI(runtime)
        self._chat_bridge = ChatBridge(runtime)
        # 记录 bridge 启动时的配置快照，用于检测配置漂移
        self._bridge_boot_config = {
            "enabled": config.bridge_enabled,
            "host": config.bridge_host,
            "port": config.bridge_port,
        }

    def _bridge_status(self) -> str:
        """组合 config.bridge_enabled 与实际运行状态，返回四状态字符串。"""
        snap = get_integration_snapshot(self._config, self._bridge_boot_config)
        return snap.bridge.state

    def _get_snapshot(self):
        """获取集成服务统一快照。"""
        return get_integration_snapshot(self._config, self._bridge_boot_config)

    def _native_runtime_compat_status(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        status = status or self._runtime.get_status()
        readiness = status.get("native_agent") if isinstance(status.get("native_agent"), dict) else None
        if readiness is None:
            try:
                readiness = self._runtime.native_agent_readiness()
            except Exception as exc:
                readiness = {
                    "ready": False,
                    "code": "native_agent_not_ready",
                    "reason": "model_profile_unavailable",
                    "message": redact_api_error_text(exc),
                    "capabilities": {},
                }
        capabilities = readiness.get("capabilities") if isinstance(readiness.get("capabilities"), dict) else {}
        ready = bool(readiness.get("ready"))
        limited_tools = [] if capabilities.get("tools") else ["tools"]
        limited_tool_details = {} if capabilities.get("tools") else {
            "tools": "Native ToolBroker/Approval 尚未全部接入；不再回退到 Native 工具。"
        }
        return {
            "status": "ready" if ready else "needs_configuration",
            "version": status.get("version", "0.4.0"),
            "release_date": None,
            "platform": "native",
            "command_exists": True,
            "ready": ready,
            "readiness_level": "full_ready" if ready else str(readiness.get("reason") or "model_profile_required"),
            "available_tools": ["model"] if capabilities.get("model") else [],
            "limited_tools": limited_tools,
            "limited_tool_details": limited_tool_details,
            "doctor_issues_count": 0 if ready else 1,
            "configuration_actions": _native_command_catalog(),
            "native_agent": readiness,
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()

            native_status = self._native_runtime_compat_status(status)

            return {
                "app": {
                    "version": status.get("version", "0.4.0"),
                    "running": status.get("running", False),
                    "uptime_seconds": round(status.get("uptime_seconds", 0), 1),
                },
                "native_agent": native_status,
                "workspace": {
                    "path": workspace.get("workspace_path", ""),
                    "initialized": workspace.get("initialized", False),
                    "created_at": workspace.get("created_at"),
                },
                "tasks": status.get("task_counts", {}),
                "bridge": snap.bridge.to_dashboard_dict(),
                "integrations": {
                    "astrbot": snap.astrbot.to_dict(),
                    "hapi": snap.hapi.to_dict(),
                },
                "modes": {
                    "current": effective_display_mode(self._config),
                    "items": list_mode_options(),
                },
                "assistant": {
                    "agent_name": self._config.assistant.agent_name,
                    "agent_nickname": self._config.assistant.agent_nickname,
                    "agent_avatar_url": _avatar_data_uri(self._config.assistant.agent_avatar_path, fallback=True),
                },
                "chat": self._chat_bridge.get_conversation_overview(
                    summary_count=self._config.window_mode.recent_messages_limit,
                    session_limit=self._config.window_mode.recent_sessions_limit,
                ),
                "activities": self._dashboard_activity_events(limit=8),
            }
        except Exception as e:
            logger.error("获取仪表盘数据失败: %s", e)
            return {"error": redact_api_error_text(e)}

    @staticmethod
    def _dashboard_activity_events(limit: int = 8) -> list[dict[str, Any]]:
        try:
            return list_activity_events(limit=limit).get("events", [])
        except Exception as exc:
            logger.debug("读取仪表盘活动流失败: %s", exc, exc_info=True)
            return []

    def get_settings_data(self) -> Dict[str, Any]:
        """获取设置页数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()
            native_status = self._native_runtime_compat_status(status)

            return {
                "native_agent": native_status,
                "workspace": {
                    "path": workspace.get("workspace_path", ""),
                    "initialized": workspace.get("initialized", False),
                    "created_at": workspace.get("created_at"),
                    "dirs": workspace.get("dirs", {}),
                },
                "display": {
                    **build_display_settings(self._config),
                },
                "mode_settings": serialize_mode_settings(self._config),
                "assistant": _assistant_settings_payload(self._config),
                "tts": {
                    "enabled": self._config.tts.enabled,
                    "provider": self._config.tts.provider,
                    "endpoint": self._config.tts.endpoint,
                    "command": self._config.tts.command,
                    "voice": self._config.tts.voice,
                    "timeout_seconds": self._config.tts.timeout_seconds,
                    "max_chars": self._config.tts.max_chars,
                    "trigger_probability": self._config.tts.trigger_probability,
                    "notification_prompt": self._config.tts.notification_prompt,
                    "gsv_base_url": self._config.tts.gsv_base_url,
                    "gsv_service_workdir": self._config.tts.gsv_service_workdir,
                    "gsv_service_command": self._config.tts.gsv_service_command,
                    "gsv_gpt_weights_path": self._config.tts.gsv_gpt_weights_path,
                    "gsv_sovits_weights_path": self._config.tts.gsv_sovits_weights_path,
                    "gsv_ref_audio_path": self._config.tts.gsv_ref_audio_path,
                    "gsv_ref_audio_text": self._config.tts.gsv_ref_audio_text,
                    "gsv_ref_audio_language": self._config.tts.gsv_ref_audio_language,
                    "gsv_aux_ref_audio_path": self._config.tts.gsv_aux_ref_audio_path,
                    "gsv_text_language": self._config.tts.gsv_text_language,
                    "gsv_top_k": self._config.tts.gsv_top_k,
                    "gsv_top_p": self._config.tts.gsv_top_p,
                    "gsv_temperature": self._config.tts.gsv_temperature,
                    "gsv_text_split_method": self._config.tts.gsv_text_split_method,
                    "gsv_batch_size": self._config.tts.gsv_batch_size,
                    "gsv_batch_threshold": self._config.tts.gsv_batch_threshold,
                    "gsv_split_bucket": self._config.tts.gsv_split_bucket,
                    "gsv_speed_factor": self._config.tts.gsv_speed_factor,
                    "gsv_fragment_interval": self._config.tts.gsv_fragment_interval,
                    "gsv_streaming_mode": self._config.tts.gsv_streaming_mode,
                    "gsv_seed": self._config.tts.gsv_seed,
                    "gsv_parallel_infer": self._config.tts.gsv_parallel_infer,
                    "gsv_repetition_penalty": self._config.tts.gsv_repetition_penalty,
                    "gsv_media_type": self._config.tts.gsv_media_type,
                },
                "bridge": snap.bridge.to_dict(),
                "integrations": {
                    "astrbot": snap.astrbot.to_dict(),
                    "hapi": snap.hapi.to_dict(),
                },
                "app": {
                    "version": status.get("version", "0.4.0"),
                    "log_level": self._config.log_level,
                    "start_minimized": self._config.start_minimized,
                    "tray_enabled": self._config.tray_enabled,
                },
                "window_mode": {
                    "width": self._config.window_mode.width,
                    "height": self._config.window_mode.height,
                    "recent_sessions_limit": self._config.window_mode.recent_sessions_limit,
                    "recent_messages_limit": self._config.window_mode.recent_messages_limit,
                    "open_chat_on_start": self._config.window_mode.open_chat_on_start,
                    "show_runtime_panel": self._config.window_mode.show_runtime_panel,
                    "show_mode_overview": self._config.window_mode.show_mode_overview,
                },
                "backup": {
                    "auto_cleanup_enabled": self._config.backup.auto_cleanup_enabled,
                    "retention_count": self._config.backup.retention_count,
                },
            }
        except Exception as e:
            logger.error("获取设置数据失败: %s", e)
            return {"error": redact_api_error_text(e)}

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """修改配置项并持久化。"""
        previous_display_mode = self._config.display_mode
        result = apply_settings_changes(self._config, changes)
        if result.get("ok"):
            applied = result.get("applied", {})
            if applied:
                logger.info("配置已保存: %s", applied)
                result["app_state"] = self._current_app_state()
                if "effects" not in result:
                    result["effects"] = build_effects_summary(list(applied.keys()))
                if (
                    "display_mode" in applied
                    and applied["display_mode"] != previous_display_mode
                ):
                    result["mode_switch_scheduled"] = True
                    result["target_display_mode"] = applied["display_mode"]
        return result

    def _current_app_state(self) -> Dict[str, Any]:
        """返回当前可编辑配置的最新状态快照，供保存后即时刷新 UI。

        包含 bridge 完整状态（含配置漂移检测和差异明细）以及集成服务状态。
        """
        snap = self._get_snapshot()
        return {
            "display_mode": effective_display_mode(self._config),
            "mode_settings": serialize_mode_settings(self._config),
            "assistant": _assistant_settings_payload(self._config),
            "tts": {
                "enabled": self._config.tts.enabled,
                "provider": self._config.tts.provider,
                "endpoint": self._config.tts.endpoint,
                "command": self._config.tts.command,
                "voice": self._config.tts.voice,
                "timeout_seconds": self._config.tts.timeout_seconds,
                "max_chars": self._config.tts.max_chars,
                "trigger_probability": self._config.tts.trigger_probability,
                "notification_prompt": self._config.tts.notification_prompt,
                "gsv_base_url": self._config.tts.gsv_base_url,
                "gsv_service_workdir": self._config.tts.gsv_service_workdir,
                "gsv_service_command": self._config.tts.gsv_service_command,
                "gsv_gpt_weights_path": self._config.tts.gsv_gpt_weights_path,
                "gsv_sovits_weights_path": self._config.tts.gsv_sovits_weights_path,
                "gsv_ref_audio_path": self._config.tts.gsv_ref_audio_path,
                "gsv_ref_audio_text": self._config.tts.gsv_ref_audio_text,
                "gsv_ref_audio_language": self._config.tts.gsv_ref_audio_language,
                "gsv_aux_ref_audio_path": self._config.tts.gsv_aux_ref_audio_path,
                "gsv_text_language": self._config.tts.gsv_text_language,
                "gsv_top_k": self._config.tts.gsv_top_k,
                "gsv_top_p": self._config.tts.gsv_top_p,
                "gsv_temperature": self._config.tts.gsv_temperature,
                "gsv_text_split_method": self._config.tts.gsv_text_split_method,
                "gsv_batch_size": self._config.tts.gsv_batch_size,
                "gsv_batch_threshold": self._config.tts.gsv_batch_threshold,
                "gsv_split_bucket": self._config.tts.gsv_split_bucket,
                "gsv_speed_factor": self._config.tts.gsv_speed_factor,
                "gsv_fragment_interval": self._config.tts.gsv_fragment_interval,
                "gsv_streaming_mode": self._config.tts.gsv_streaming_mode,
                "gsv_seed": self._config.tts.gsv_seed,
                "gsv_parallel_infer": self._config.tts.gsv_parallel_infer,
                "gsv_repetition_penalty": self._config.tts.gsv_repetition_penalty,
                "gsv_media_type": self._config.tts.gsv_media_type,
            },
            "bridge": snap.bridge.to_dashboard_dict(),
            "tray_enabled": self._config.tray_enabled,
            "integrations": {
                "astrbot": snap.astrbot.to_dict(),
                "hapi": snap.hapi.to_dict(),
            },
        }

    def restart_bridge(self) -> Dict[str, Any]:
        """重启 Bridge 并用当前已保存的配置重新对齐。

        Electron 前端本身也依赖这个 HTTP 服务通信，所以桌面后端模式下不能
        在处理 ``/ui/bridge/restart`` 请求时直接停止 uvicorn。实际重启由
        Electron 主进程完成；这里仅返回明确的桌面壳动作要求，避免请求把
        自己所在的服务停掉后导致前端永久断联。

        操作流程：
          1. 检查 bridge_enabled
          2. Electron 模式：返回 desktop_restart_backend_required
          3. 非 Electron 模式：调用 server.restart_bridge() 停止旧实例 + 启动新线程
          4. 刷新 _bridge_boot_config（重新对齐）
          5. 返回最新 app_state 供前端刷新
        """
        if not self._config.bridge_enabled:
            return {
                "ok": False,
                "error": "Bridge 未启用，请先在设置中启用 Bridge",
                "app_state": self._current_app_state(),
            }

        host = self._config.bridge_host
        port = self._config.bridge_port
        if os.getenv("OHA_YACHIYO_DESKTOP_BACKEND") == "1":
            return {
                "ok": True,
                "pending": True,
                "desktop_restart_backend_required": True,
                "message": "Bridge 重启需要由 Electron 桌面壳执行",
                "bridge_url": f"http://{host}:{port}",
                "app_state": self._current_app_state(),
            }

        from apps.bridge.server import restart_bridge as _restart

        try:
            result = _restart(host=host, port=port)
        except Exception as exc:
            logger.error("Bridge 重启异常: %s", exc)
            return {
                "ok": False,
                "error": f"Bridge 重启失败: {exc}",
                "app_state": self._current_app_state(),
            }

        if result.get("ok"):
            # 重启成功 → 刷新 boot_config 使 config_dirty 归零
            self._bridge_boot_config = {
                "enabled": self._config.bridge_enabled,
                "host": host,
                "port": port,
            }
            logger.info("Bridge 重启成功，boot_config 已刷新")
        else:
            logger.warning("Bridge 重启失败: %s", result.get("error"))

        return {
            "ok": result.get("ok", False),
            "error": result.get("error"),
            "pending": result.get("pending", False),
            "app_state": self._current_app_state(),
        }

    def open_terminal_command(self, cmd: str) -> Dict[str, Any]:
        """在系统终端中执行指定命令（交互式，需要用户参与）。

        macOS：通过临时 .command 文件在 Terminal.app 新窗口中运行。
        Linux：按优先级尝试 gnome-terminal / xfce4-terminal / xterm。

        Args:
            cmd: 要在终端中运行的命令字符串，如 "native setup"

        Returns:
            {"success": bool, "error": str | None}
        """
        global _LAST_TERMINAL_COMMAND_AT

        cmd = (cmd or "").strip()
        logger.info("open_terminal_command: cmd=%r", cmd)
        if not cmd:
            return {"success": False, "error": "终端命令为空"}
        if cmd in _allowed_terminal_commands():
            return {
                "success": False,
                "error": "Native Runtime 不再通过外部终端向导配置模型；请在模型配置页管理 Model Profile。",
                "unsupported": True,
                "code": "native_configuration_required",
            }
        if not _is_macos_prerequisite_command(cmd) and not _is_gpt_sovits_service_command(cmd):
            return {
                "success": False,
                "error": "不支持的终端命令",
                "unsupported": True,
            }

        with _TERMINAL_COMMAND_LOCK:
            now = time.monotonic()
            if now - _LAST_TERMINAL_COMMAND_AT < _TERMINAL_COMMAND_THROTTLE_SECONDS:
                return {
                    "success": False,
                    "error": "上一个终端操作还在打开中，请稍后再试",
                    "throttled": True,
                }
            _LAST_TERMINAL_COMMAND_AT = now

        try:
            from apps.shell.terminal import open_terminal_command

            success, error = open_terminal_command(cmd)
            if not success:
                _reset_terminal_command_gate()
                return {"success": False, "error": error}
            logger.info("已在系统终端中启动命令: %r", cmd)
            return {"success": True, "error": None}

        except Exception as exc:
            _reset_terminal_command_gate()
            logger.error("open_terminal_command 失败: %s", exc)
            return {"success": False, "error": redact_api_error_text(exc)}

    def run_native_diagnostic_command(self, cmd: str) -> Dict[str, Any]:
        """Compatibility diagnostic entry point backed by Native Runtime state."""
        action = _diagnostic_command_by_command(cmd)
        if action is None:
            return {
                "ok": False,
                "success": False,
                "error": "不支持的诊断命令",
                "unsupported": True,
            }

        started_at = time.monotonic()
        runtime_status = self._native_runtime_compat_status()
        readiness = runtime_status.get("native_agent") if isinstance(runtime_status.get("native_agent"), dict) else {}
        configuration = self.get_native_configuration()
        tool_config = self.get_native_tool_config()
        profiles = get_model_profile_service().list_profiles()
        defaults = profiles.get("defaults") if isinstance(profiles.get("defaults"), dict) else {}
        output_lines = [
            f"Native Agent ready: {bool(readiness.get('ready'))}",
            f"Readiness reason: {readiness.get('reason') or 'ok'}",
            f"Default chat profile: {defaults.get('chat') or '<missing>'}",
            f"Default vision profile: {defaults.get('vision') or '<optional>'}",
            f"Tool config projection: {tool_config.get('config_path')}",
        ]
        if action.get("id") == "auth-list":
            configured = [
                {
                    "profile_id": profile.get("profile_id"),
                    "capability": profile.get("capability"),
                    "name": profile.get("name"),
                    "api_key_configured": bool(profile.get("api_key_configured")),
                }
                for profile in profiles.get("profiles", [])
                if isinstance(profile, dict)
            ]
            output_lines = [json.dumps({"model_profiles": configured}, ensure_ascii=False, indent=2)]

        output = _sanitize_command_output("\n".join(output_lines))
        success = bool(readiness.get("ready")) if action.get("id") in {"doctor", "config-check"} else True
        payload: Dict[str, Any] = {
            "ok": True,
            "success": success,
            "action_id": action.get("id"),
            "label": action.get("label"),
            "description": action.get("description"),
            "command": action["command"],
            "returncode": 0,
            "stdout": output,
            "stderr": "",
            "output": output,
            "elapsed_seconds": round(time.monotonic() - started_at, 2),
            "needs_env_refresh": False,
            "configuration": configuration,
        }
        if success:
            payload["message"] = f"{action['label']} 完成"
        else:
            payload["error"] = str(readiness.get("message") or "Native Agent 尚未就绪")
            payload["code"] = str(readiness.get("code") or "native_agent_not_ready")
            payload["reason"] = str(readiness.get("reason") or "model_profile_required")

        if action.get("id") == "doctor":
            payload["doctor_summary"] = {
                "readiness_level": runtime_status.get("readiness_level", "unknown"),
                "available_tools": runtime_status.get("available_tools", []),
                "limited_tools": runtime_status.get("limited_tools", []),
                "limited_tool_details": runtime_status.get("limited_tool_details", {}),
                "doctor_issues_count": runtime_status.get("doctor_issues_count", 0),
            }
            payload["dashboard"] = self.get_dashboard_data()

        payload["diagnostic_cache"] = self._record_diagnostic_result(action, payload)
        return payload

    def _record_diagnostic_result(self, action: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
        try:
            configuration = self.get_native_configuration()
        except Exception as exc:
            logger.warning("读取 Native 配置以记录诊断缓存失败: %s", exc)
            return {"stale": False, "commands": {}, "error": redact_api_error_text(exc)}
        return _store_diagnostic_result(configuration, action, result)

    def get_native_diagnostic_cache(self) -> dict[str, Any]:
        try:
            configuration = self.get_native_configuration()
        except Exception as exc:
            logger.warning("读取 Native 配置以获取诊断缓存失败: %s", exc)
            return {
                "schema_version": _NATIVE_DIAGNOSTIC_CACHE_SCHEMA,
                "stale": False,
                "commands": {},
                "error": redact_api_error_text(exc),
            }
        return _load_diagnostic_cache(configuration)

    def test_native_connection(self) -> Dict[str, Any]:
        """Validate the default Native Chat ModelProfile."""
        service = get_model_profile_service()
        profile_id = str(service.get_defaults().get("chat") or "").strip()
        if not profile_id:
            payload = {
                "ok": False,
                "success": False,
                "code": "native_agent_not_ready",
                "reason": "model_profile_required",
                "error": "请先配置并选择默认对话模型。",
                "command": "native:model-profile:test:chat",
                "needs_env_refresh": False,
            }
            payload["connection_validation"] = self._record_connection_validation(payload)
            return payload

        started_at = time.monotonic()
        try:
            result = service.test_profile(profile_id)
        except (KeyError, ModelProfileError) as exc:
            result = {"ok": False, "success": False, "message": redact_api_error_text(exc)}

        elapsed = round(time.monotonic() - started_at, 2)
        message = _compact_command_output(str(result.get("message") or ""))
        if bool(result.get("success") or result.get("ok")):
            payload = {
                "ok": True,
                "success": True,
                "message": "Native Chat ModelProfile 连接测试通过",
                "output_preview": message,
                "command": "native:model-profile:test:chat",
                "elapsed_seconds": elapsed,
                "needs_env_refresh": False,
                "profile": result.get("profile"),
            }
            payload["connection_validation"] = self._record_connection_validation(payload)
            return payload

        error = f"Native Chat ModelProfile 连接测试失败：{message}" if message else "Native Chat ModelProfile 连接测试失败"
        payload = {
            "ok": False,
            "success": False,
            "error": error,
            "output_preview": message,
            "stderr_preview": "",
            "returncode": 1,
            "command": "native:model-profile:test:chat",
            "elapsed_seconds": elapsed,
            "needs_env_refresh": False,
            "profile": result.get("profile"),
        }
        payload["connection_validation"] = self._record_connection_validation(payload)
        return payload

    def test_native_image_connection(self) -> Dict[str, Any]:
        """Validate the Native image-input route."""
        configuration = self.get_native_configuration()
        image_input = configuration.get("image_input") if isinstance(configuration.get("image_input"), dict) else {}
        route = str(image_input.get("route") or "").strip()
        if route == "blocked":
            payload = {
                "ok": False,
                "success": False,
                "error": str(image_input.get("reason") or "当前模型/图片模式不支持图片输入"),
                "route": route,
                "image_input": image_input,
            }
            payload["image_connection_validation"] = _store_image_connection_validation(
                configuration,
                success=False,
                error=str(payload["error"]),
            )
            return payload
        service = get_model_profile_service()
        defaults = service.get_defaults()
        profile_id = str(image_input.get("profile_id") or "").strip()
        if not profile_id:
            profile_id = str(defaults.get("vision") or defaults.get("chat") or "").strip()
        if not profile_id:
            payload = {
                "ok": False,
                "success": False,
                "code": "native_agent_not_ready",
                "reason": "vision_model_profile_required",
                "error": "请先配置默认图片识别模型或支持图片输入的默认对话模型。",
                "route": route,
                "image_input": image_input,
                "needs_env_refresh": False,
            }
            payload["image_connection_validation"] = _store_image_connection_validation(
                configuration,
                success=False,
                error=str(payload["error"]),
            )
            return payload

        started_at = time.monotonic()
        try:
            result = service.test_profile(profile_id)
        except (KeyError, ModelProfileError) as exc:
            result = {"ok": False, "success": False, "message": redact_api_error_text(exc)}

        elapsed = round(time.monotonic() - started_at, 2)
        message = _compact_command_output(str(result.get("message") or ""))
        if bool(result.get("success") or result.get("ok")):
            payload = {
                "ok": True,
                "success": True,
                "message": "Native 图片链路测试通过",
                "output_preview": message,
                "stderr_preview": "",
                "route": route,
                "image_input": image_input,
                "elapsed_seconds": elapsed,
                "needs_env_refresh": False,
                "profile": result.get("profile"),
            }
            payload["image_connection_validation"] = _store_image_connection_validation(
                configuration,
                success=True,
                message=str(payload["message"]),
                elapsed_seconds=elapsed,
            )
            return payload

        error = f"Native 图片链路测试失败：{message}" if message else "Native 图片链路测试失败"
        payload = {
            "ok": False,
            "success": False,
            "error": error,
            "output_preview": message,
            "stderr_preview": "",
            "returncode": 1,
            "route": route,
            "image_input": image_input,
            "elapsed_seconds": elapsed,
            "needs_env_refresh": False,
            "profile": result.get("profile"),
        }
        payload["image_connection_validation"] = _store_image_connection_validation(
            configuration,
            success=False,
            error=error,
            elapsed_seconds=elapsed,
        )
        return payload

    def _record_connection_validation(self, result: dict[str, Any]) -> dict[str, Any]:
        try:
            configuration = self.get_native_configuration()
        except Exception as exc:
            logger.warning("读取 Native 配置以记录连接验证状态失败: %s", exc)
            return {"verified": False, "success": False, "error": redact_api_error_text(exc)}
        return _store_connection_validation(
            configuration,
            success=bool(result.get("success")),
            message=str(result.get("message") or ""),
            error=str(result.get("error") or ""),
            elapsed_seconds=result.get("elapsed_seconds"),
        )

    def get_native_configuration(self) -> Dict[str, Any]:
        """Read Native ModelProfile configuration through the legacy endpoint shape."""
        service = get_model_profile_service()
        profiles_payload = service.list_profiles()
        defaults = profiles_payload.get("defaults") if isinstance(profiles_payload.get("defaults"), dict) else {}
        profile_rows = [item for item in profiles_payload.get("profiles", []) if isinstance(item, dict)]
        chat_profile_id = str(defaults.get("chat") or "").strip()
        vision_profile_id = str(defaults.get("vision") or "").strip()
        chat_profile = next((item for item in profile_rows if str(item.get("profile_id")) == chat_profile_id), {})
        vision_profile = next((item for item in profile_rows if str(item.get("profile_id")) == vision_profile_id), {})
        raw_provider = str(chat_profile.get("provider") or "")
        default_model = str(chat_profile.get("model") or "")
        base_url = str(chat_profile.get("base_url") or "")
        provider = _effective_provider_id(raw_provider, base_url, default_model)
        provider_options = _provider_options(
            current_provider=provider,
            config_path=Path(),
            env_values={},
        )
        for profile in profile_rows:
            if str(profile.get("capability") or "chat") != "chat":
                continue
            profile_provider = _effective_provider_id(
                str(profile.get("provider") or ""),
                str(profile.get("base_url") or ""),
                str(profile.get("model") or ""),
            )
            if not profile_provider:
                continue
            option = next((item for item in provider_options if item.get("id") == profile_provider), None)
            if option is None:
                option = {
                    "id": profile_provider,
                    "label": profile_provider,
                    "base_url": str(profile.get("base_url") or ""),
                    "default_model": str(profile.get("model") or ""),
                    "default_vision_model": "",
                    "models": [],
                    "vision_models": [],
                    "api_key_names": list(_provider_api_key_names(profile_provider)),
                    "api_key_name": _provider_api_key_name(profile_provider),
                    "api_key_configured": False,
                    "auth_type": "api_key",
                    "source": "model-profile",
                    "is_current": profile_provider == provider,
                }
                provider_options.append(option)
            option["api_key_configured"] = bool(option.get("api_key_configured") or profile.get("api_key_configured"))
            option["is_current"] = bool(option.get("is_current") or profile_provider == provider)
            models = option.setdefault("models", [])
            if isinstance(models, list) and profile.get("model") and profile.get("model") not in models:
                models.append(str(profile["model"]))
        selected_provider = next((option for option in provider_options if option.get("id") == provider), {})
        api_key_name = str(chat_profile.get("api_key_name") or selected_provider.get("api_key_name") or _provider_api_key_name(provider))
        api_key_configured = bool(chat_profile.get("api_key_configured"))
        projection = _load_native_tool_config_projection()
        config_values, env_values = _tool_projection_values(projection)
        configuration = {
            "ok": True,
            "command_exists": True,
            "needs_env_refresh": False,
            "config_path": str(_native_tool_config_path()),
            "env_path": "",
            "model": {
                "provider": provider,
                "raw_provider": raw_provider,
                "default": default_model,
                "base_url": base_url,
                "profile_id": chat_profile_id,
                "status": str(chat_profile.get("status") or ""),
            },
            "provider_options": provider_options,
            "api_key": {
                "name": api_key_name,
                "configured": api_key_configured,
                "display": "已配置" if api_key_configured else "未配置",
            },
            "vision": {
                "configured": bool(vision_profile),
                "provider": str(vision_profile.get("provider") or ""),
                "model": str(vision_profile.get("model") or ""),
                "base_url": str(vision_profile.get("base_url") or ""),
                "api_key_name": str(vision_profile.get("api_key_name") or ""),
                "api_key_configured": bool(vision_profile.get("api_key_configured")),
                "effective_provider": _effective_provider_id(
                    str(vision_profile.get("provider") or provider),
                    str(vision_profile.get("base_url") or base_url),
                    str(vision_profile.get("model") or default_model),
                ),
                "effective_model": str(vision_profile.get("model") or default_model),
                "effective_base_url": str(vision_profile.get("base_url") or base_url),
                "profile_id": vision_profile_id,
                "status": str(vision_profile.get("status") or ""),
            },
        }
        configuration["tool_config_state"] = _tool_config_state(Path(), env_values)
        configuration["tool_config_state"]["config"].update(
            {".".join(path): value for path, value in config_values.items()}
        )
        configuration["image_input"] = get_native_image_input_capability()
        configuration["connection_validation"] = _load_connection_validation(configuration)
        configuration["image_connection_validation"] = _load_image_connection_validation(configuration)
        if isinstance(configuration["image_input"], dict):
            configuration["image_input"]["validation"] = configuration["image_connection_validation"]
        return configuration

    def update_native_configuration(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Update Native ModelProfile defaults through the legacy endpoint shape."""
        provider = str(changes.get("provider") or "").strip()
        model = str(changes.get("model") or "").strip()
        base_url = str(changes.get("base_url") or "").strip()
        api_key = str(changes.get("api_key") or "").strip()
        chat_profile_id = str(changes.get("chat_profile_id") or "").strip()
        vision_profile_id = str(changes.get("vision_profile_id") or "").strip()
        image_input_mode = _normalize_image_input_mode(changes.get("image_input_mode"))
        vision_provider = str(changes.get("vision_provider") or "").strip()
        vision_model = str(changes.get("vision_model") or "").strip()
        vision_base_url = str(changes.get("vision_base_url") or "").strip()
        vision_api_key = str(changes.get("vision_api_key") or "").strip()
        service = get_model_profile_service()
        try:
            if chat_profile_id:
                profile = service.get_profile(chat_profile_id)
                if str(profile.get("capability") or "") != "chat":
                    raise ValueError("chat Profile 类型不匹配")
                if not profile.get("enabled", True):
                    raise ValueError("不能选择已暂停的模型 Profile")
                service.set_defaults({"chat": chat_profile_id})
            if vision_profile_id:
                profile = service.get_profile(vision_profile_id)
                if str(profile.get("capability") or "") != "vision":
                    raise ValueError("vision Profile 类型不匹配")
                if not profile.get("enabled", True):
                    raise ValueError("不能选择已暂停的图片识别 Profile")
                service.set_defaults({"vision": vision_profile_id})
        except (KeyError, ValueError) as exc:
            return {"ok": False, "error": redact_api_error_text(exc)}

        defaults = service.get_defaults()
        if provider or model or base_url or api_key:
            existing_id = str(defaults.get("chat") or "").strip()
            if existing_id:
                try:
                    existing = service.get_profile(existing_id)
                except KeyError:
                    existing = {}
                payload = {
                    "name": str(existing.get("name") or "Default Chat"),
                    "capability": "chat",
                    "provider": provider or str(existing.get("provider") or "openai_compatible"),
                    "base_url": base_url or str(existing.get("base_url") or ""),
                    "model": model or str(existing.get("model") or ""),
                    "enabled": True,
                }
                if api_key:
                    payload["api_key"] = api_key
                profile = service.update_profile(existing_id, payload)
            else:
                if not provider:
                    return {"ok": False, "error": "Provider 不能为空"}
                if not model:
                    return {"ok": False, "error": "模型名称不能为空"}
                profile = service.create_profile(
                    {
                        "name": "Default Chat",
                        "capability": "chat",
                        "provider": provider,
                        "base_url": base_url,
                        "model": model,
                        "api_key": api_key,
                        "enabled": True,
                    }
                )
            service.set_defaults({"chat": str(profile["profile_id"])})

        has_vision_changes = any(
            key in changes
            for key in ("vision_profile_id", "vision_provider", "vision_model", "vision_base_url", "vision_api_key")
        )
        if has_vision_changes and "image_input_mode" in changes and image_input_mode == "text" and not (
            vision_provider or provider
        ):
            return {"ok": False, "error": "vision 预分析需要可用的 Provider"}
        if has_vision_changes:
            existing_id = str(service.get_defaults().get("vision") or "").strip()
            if existing_id:
                try:
                    existing = service.get_profile(existing_id)
                except KeyError:
                    existing = {}
                payload = {
                    "name": str(existing.get("name") or "Default Vision"),
                    "capability": "vision",
                    "provider": vision_provider or provider or str(existing.get("provider") or "openai_compatible"),
                    "base_url": vision_base_url or base_url or str(existing.get("base_url") or ""),
                    "model": vision_model or str(existing.get("model") or ""),
                    "enabled": True,
                }
                if vision_api_key:
                    payload["api_key"] = vision_api_key
                profile = service.update_profile(existing_id, payload)
            else:
                if not (vision_provider or provider):
                    return {"ok": False, "error": "vision Provider 不能为空"}
                if not vision_model:
                    return {"ok": False, "error": "vision 模型名称不能为空"}
                profile = service.create_profile(
                    {
                        "name": "Default Vision",
                        "capability": "vision",
                        "provider": vision_provider or provider,
                        "base_url": vision_base_url or base_url,
                        "model": vision_model,
                        "api_key": vision_api_key,
                        "enabled": True,
                    }
                )
            service.set_defaults({"vision": str(profile["profile_id"])})

        if "image_input_mode" in changes:
            projection = _load_native_tool_config_projection()
            config = projection.get("config") if isinstance(projection.get("config"), dict) else {}
            config["agent.image_input_mode"] = image_input_mode
            projection["config"] = config
            try:
                _store_native_tool_config_projection(projection)
            except OSError as exc:
                return {"ok": False, "error": redact_api_error_text(f"写入 Native 配置失败：{exc}")}

        return {
            "ok": True,
            "message": "Native 模型配置已保存",
            "configuration": self.get_native_configuration(),
        }

    def get_native_tool_config(self) -> Dict[str, Any]:
        """读取工具配置目录与安全状态。

        返回值只包含配置项值、环境变量名和“是否已配置”的布尔值；所有 env
        字段都不会返回明文内容，避免把 token/key 暴露给 renderer。
        """
        projection = _load_native_tool_config_projection()
        config_values, env_values = _tool_projection_values(projection)
        config_path = _native_tool_config_path()
        native_toolsets = [
            {
                "id": str(tool["id"]),
                "canonical_id": _canonical_tool_name(str(tool["id"])),
                "label": str(tool.get("title") or tool["id"]),
                "enabled": True,
            }
            for tool in _NATIVE_TOOL_CONFIG_CATALOG
        ]
        tools = [
            _tool_config_payload(tool, config_values=config_values, env_values=env_values)
            for tool in _NATIVE_TOOL_CONFIG_CATALOG
        ]
        return {
            "ok": True,
            "command_exists": True,
            "needs_env_refresh": False,
            "config_path": str(config_path),
            "env_path": "",
            "native_toolsets": native_toolsets,
            "tools": tools,
            "tool_config_state": {
                "config": {
                    ".".join(path): value
                    for path, value in config_values.items()
                },
                "env_configured": {key: True for key in env_values},
            },
        }

    def update_native_tool_config(self, tool_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        """保存单个工具的配置项，响应不回显 secret 值。"""
        normalized_tool_id = str(tool_id or "").strip()
        tool = _NATIVE_TOOL_CONFIG_BY_ID.get(normalized_tool_id)
        if not tool:
            return {"ok": False, "error": "未知工具配置项", "tool_id": normalized_tool_id}
        if not isinstance(changes, dict):
            return {"ok": False, "error": "配置变更格式无效", "tool_id": normalized_tool_id}

        field_by_key = {
            str(field.get("key") or field.get("config_key") or field.get("env_key")): field
            for field in tool.get("fields", ())
        }
        unknown = [key for key in changes if key not in field_by_key]
        if unknown:
            return {
                "ok": False,
                "error": "包含不支持的配置项",
                "tool_id": normalized_tool_id,
                "fields": unknown,
            }

        projection = _load_native_tool_config_projection()
        config_projection = projection.get("config") if isinstance(projection.get("config"), dict) else {}
        env_configured = projection.get("env_configured") if isinstance(projection.get("env_configured"), dict) else {}
        applied: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        for key, raw_value in changes.items():
            field = field_by_key[key]
            field_kind = str(field.get("kind") or "text")
            config_key = str(field.get("config_key") or "")
            env_key = str(field.get("env_key") or "")
            target_key = env_key or config_key
            if not target_key:
                skipped.append({"key": key, "reason": "readonly"})
                continue

            if field_kind == "checkbox":
                value: Any = _bool_config_value(raw_value, bool(field.get("default", False)))
            else:
                value = str(raw_value or "").strip()

            if env_key and value == "":
                skipped.append({"key": key, "reason": "blank_env_value"})
                continue

            options = _field_options(field)
            if options and str(value) not in options:
                return {
                    "ok": False,
                    "error": "配置项取值不在允许范围内",
                    "tool_id": normalized_tool_id,
                    "field": key,
                }

            if env_key:
                env_configured[env_key] = True
            elif config_key:
                config_projection[config_key] = value
            applied.append({"key": key, "target": "env" if env_key else "config"})

        projection["config"] = config_projection
        projection["env_configured"] = env_configured
        try:
            _store_native_tool_config_projection(projection)
        except OSError as exc:
            return {
                "ok": False,
                "error": redact_api_error_text(f"保存工具配置失败：{exc}"),
                "tool_id": normalized_tool_id,
            }

        return {
            "ok": True,
            "message": "工具配置已保存",
            "tool_id": normalized_tool_id,
            "applied": applied,
            "skipped": skipped,
            "needs_env_refresh": False,
            "tool_config": self.get_native_tool_config(),
        }

    def test_native_tool_config(self, tool_id: str) -> Dict[str, Any]:
        """Run a safe validation pass for a single Native tool configuration."""
        normalized_tool_id = str(tool_id or "").strip()
        tool = _NATIVE_TOOL_CONFIG_BY_ID.get(normalized_tool_id)
        if not tool:
            return {"ok": False, "success": False, "error": "未知工具配置项", "tool_id": normalized_tool_id}

        projection = _load_native_tool_config_projection()
        config_values, env_values = _tool_projection_values(projection)
        state = {
            "config": {".".join(path): value for path, value in config_values.items()},
            "env_configured": {key: True for key in env_values},
        }
        checks: list[dict[str, str]] = []

        missing_fields: list[str] = []
        for field in _required_tool_fields(tool, state):
            if _field_is_configured(field, state):
                checks.append(
                    {
                        "label": str(field.get("label") or field.get("key")),
                        "status": "pass",
                        "detail": "已配置",
                    }
                )
            else:
                missing_fields.append(str(field.get("env_key") or field.get("config_key") or field.get("key")))
                checks.append(
                    {
                        "label": str(field.get("label") or field.get("key")),
                        "status": "fail",
                        "detail": "缺少必需配置",
                }
            )

        if not tool.get("fields"):
            checks.append(
                {
                    "label": "配置入口",
                    "status": "warn",
                    "detail": "此工具的 Native 配置入口尚未接入，执行时会返回 native_agent_not_ready。",
                }
            )

        if normalized_tool_id == "browser-cdp":
            checks.append(_test_browser_cdp_endpoint(state))

        started_at = time.monotonic()
        checks.append(
            {
                "label": "Native ToolBroker",
                "status": "warn",
                "detail": "工具执行链路仍需通过 ToolDescriptor、PolicyGate 与审批接入。",
            }
        )

        if any(check["status"] == "fail" for check in checks):
            status = "fail"
            message = "配置测试未通过"
        elif any(check["status"] == "warn" for check in checks):
            status = "warn"
            message = "配置测试完成，但仍有需要确认的项目"
        else:
            status = "pass"
            message = "配置测试通过"

        return {
            "ok": True,
            "success": status == "pass",
            "tool_id": normalized_tool_id,
            "status": status,
            "message": message,
            "checks": checks,
            "missing_fields": missing_fields,
            "elapsed_seconds": round(time.monotonic() - started_at, 2),
            "needs_env_refresh": False,
            "tool_config": self.get_native_tool_config(),
        }

    def check_native_agent_update(self) -> Dict[str, Any]:
        """Return native runtime update status; external execution-kernel updater is removed."""
        version = str(self._runtime.get_status().get("version") or "0.4.0")
        return {
            "ok": True,
            "success": True,
            "message": "Native Runtime 不再使用外部执行内核更新器；应用更新请走桌面应用更新入口。",
            "update_available": False,
            "behind_commits": 0,
            "version": version,
            "release_date": "",
            "summary": f"oha-yachiyo {version}",
            "version_output": "",
            "check_output": "external_execution_kernel_removed",
            "check_returncode": 0,
            "needs_env_refresh": False,
        }

    def update_native_agent(self, full_backup: bool = False) -> Dict[str, Any]:
        """Compatibility endpoint; external execution-kernel updater is removed."""
        return {
            "ok": False,
            "success": False,
            "unsupported": True,
            "code": "external_execution_kernel_removed",
            "message": "Native Runtime 不再支持外部执行内核更新；请使用应用更新入口更新 oha-yachiyo。",
            "returncode": 0,
            "output": "",
            "elapsed_seconds": 0,
            "needs_env_refresh": False,
            "version": self.check_native_agent_update(),
            "toolset_delta": {"added": [], "removed": [], "changed": []},
            "tool_config": self.get_native_tool_config(),
            "diagnostic_cache": self.get_native_diagnostic_cache(),
            "dashboard": self.get_dashboard_data(),
        }

    def launch_browser_cdp(self) -> Dict[str, Any]:
        """Best-effort 启动/连接本机 Chrome CDP，并写入 browser.cdp_url。"""
        host = "127.0.0.1"
        port = 9222
        url = f"http://{host}:{port}"
        manual_command = (
            'open -a "Google Chrome" --args --remote-debugging-port=9222 '
            '--user-data-dir="$HOME/.oha-yachiyo/chrome-debug" --no-first-run '
            "--no-default-browser-check"
        )

        def reachable() -> bool:
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    return True
            except OSError:
                return False

        launched = False
        if not reachable() and sys.platform == "darwin" and shutil.which("open"):
            try:
                subprocess.run(
                    [
                        "open",
                        "-a",
                        "Google Chrome",
                        "--args",
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={Path.home() / '.oha-yachiyo' / 'chrome-debug'}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8.0,
                    check=False,
                )
                launched = True
            except Exception as exc:
                logger.info("启动 Chrome 调试端口失败: %s", exc)
            for _ in range(12):
                if reachable():
                    break
                time.sleep(0.5)

        if not reachable():
            return {
                "ok": False,
                "success": False,
                "error": "未能自动启动或连接 Chrome 调试端口",
                "url": url,
                "manual_command": manual_command,
                "needs_env_refresh": False,
            }

        projection = _load_native_tool_config_projection()
        config_projection = projection.get("config") if isinstance(projection.get("config"), dict) else {}
        config_projection["browser.cdp_url"] = url
        projection["config"] = config_projection
        try:
            _store_native_tool_config_projection(projection)
        except OSError as exc:
            return {
                "ok": False,
                "success": False,
                "error": redact_api_error_text(f"保存 browser.cdp_url 失败：{exc}"),
                "url": url,
                "manual_command": manual_command,
                "needs_env_refresh": False,
            }

        return {
            "ok": True,
            "success": True,
            "message": "已连接 Chrome 调试端口并写入 browser.cdp_url",
            "url": url,
            "launched": launched,
            "manual_command": manual_command,
            "needs_env_refresh": False,
            "tool_config": self.get_native_tool_config(),
        }

    def recheck_native_agent(self) -> Dict[str, Any]:
        """Compatibility recheck endpoint for Native Agent readiness."""
        logger.info("手动触发 Native Agent 就绪状态重检...")
        executor_refresh = {
            "updated": False,
            "executor": "unknown",
            "previous_executor": None,
            "reason": "refresh_failed",
        }
        try:
            executor_refresh = self._runtime.refresh_task_runner_executor()
        except Exception as exc:
            logger.warning("重新检测 Native Agent 状态失败: %s", exc)

        data = self.get_dashboard_data()
        data["executor_refresh"] = executor_refresh
        return data

    # ──────────────────────────────────────────────────────────────────────────
    # 聊天 API（委托 ChatAPI）
    # ──────────────────────────────────────────────────────────────────────────

    def send_message(self, text: str) -> Dict[str, Any]:
        """发送用户消息"""
        return self._chat_api.send_message(text)

    def get_messages(self, limit: int = 50) -> Dict[str, Any]:
        """获取消息列表"""
        return self._chat_api.get_messages(limit)

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话元信息"""
        return self._chat_api.get_session_info()

    def clear_session(self) -> Dict[str, Any]:
        """清空会话"""
        return self._chat_api.clear_session()

    def get_executor_info(self) -> Dict[str, Any]:
        """获取当前执行器信息"""
        return self._chat_api.get_executor_info()

    def open_chat(self) -> Dict[str, Any]:
        """Electron opens chat windows through IPC; HTTP callers get an instruction."""
        return {
            "ok": False,
            "desktop_action_required": "open_chat",
            "message": "React/Electron 前端通过桌面 IPC 打开聊天窗口",
        }

    def open_mode_settings(self, mode_id: str) -> Dict[str, Any]:
        """Electron opens settings windows through IPC; HTTP callers get an instruction."""
        return {
            "ok": False,
            "mode_id": mode_id,
            "desktop_action_required": "open_mode_settings",
            "message": "React/Electron 前端通过桌面 IPC 打开模式设置",
        }

    def quit_app(self) -> Dict[str, Any]:
        """Electron owns the process quit request."""
        return {"ok": True, "desktop_quit_required": True}

    def get_uninstall_preview(
        self,
        scope: str = "oha_only",
        keep_config: bool = True,
        include_gpt_sovits: bool = False,
    ) -> Dict[str, Any]:
        """生成卸载预览，不修改文件系统。"""
        try:
            from apps.installer.uninstall import build_uninstall_plan

            plan = build_uninstall_plan(
                scope,
                keep_config_snapshot=bool(keep_config),
                include_gpt_sovits=bool(include_gpt_sovits),
            )
            return {"ok": True, "plan": plan.to_dict()}
        except Exception as exc:
            logger.error("生成卸载预览失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}

    def run_uninstall(
        self,
        scope: str = "oha_only",
        keep_config: bool = True,
        confirm_text: str = "",
        include_gpt_sovits: bool = False,
    ) -> Dict[str, Any]:
        """执行 Oha-Yachiyo 卸载，并在成功后安排应用退出。"""
        try:
            from apps.installer.uninstall import execute_uninstall

            result = execute_uninstall(
                scope,
                keep_config_snapshot=bool(keep_config),
                include_gpt_sovits=bool(include_gpt_sovits),
                confirm_text=confirm_text,
            )
            payload = result.to_dict()
            if result.ok:
                payload["exit_scheduled"] = False
                payload["desktop_quit_required"] = True
            return payload
        except Exception as exc:
            logger.error("执行卸载失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}

    def get_backup_status(self) -> Dict[str, Any]:
        """获取 Oha-Yachiyo 备份状态。"""
        try:
            from apps.installer.backup import get_backup_status

            return {"ok": True, **get_backup_status()}
        except Exception as exc:
            logger.error("读取备份状态失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc), "has_backup": False}

    def create_backup(self, overwrite_latest: bool = False) -> Dict[str, Any]:
        """主动生成 Oha-Yachiyo 本地资料备份。"""
        try:
            from apps.installer.backup import create_backup, get_backup_status

            backup = create_backup(
                source_context="manual_overwrite" if overwrite_latest else "manual",
                auto_cleanup=self._config.backup.auto_cleanup_enabled,
                retention_count=self._config.backup.retention_count,
                overwrite_latest=bool(overwrite_latest),
            )
            return {
                "ok": True,
                "backup": backup.to_dict(),
                "backup_path": backup.path,
                "backup_path_display": backup.display_path,
                "status": get_backup_status(),
            }
        except Exception as exc:
            logger.error("创建备份失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}

    def update_backup_settings(
        self,
        auto_cleanup_enabled: bool = True,
        retention_count: int = 10,
    ) -> Dict[str, Any]:
        """更新备份保留策略。"""
        try:
            changes = {
                "backup.auto_cleanup_enabled": bool(auto_cleanup_enabled),
                "backup.retention_count": retention_count,
            }
            validation = apply_settings_changes(
                deepcopy(self._config),
                changes,
                persist=False,
            )
            if not validation.get("ok") or validation.get("errors"):
                return {
                    "ok": False,
                    "error": validation.get("error")
                    or "；".join(validation.get("errors", [])),
                    "errors": validation.get("errors", []),
                }

            result = apply_settings_changes(self._config, changes)
            if not result.get("ok"):
                return result
            return {
                "ok": True,
                "backup": {
                    "auto_cleanup_enabled": self._config.backup.auto_cleanup_enabled,
                    "retention_count": self._config.backup.retention_count,
                },
                "applied": result.get("applied", {}),
                "effects": result.get("effects", {}),
            }
        except Exception as exc:
            logger.error("保存备份设置失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}

    def restore_backup(self, backup_path: str = "") -> Dict[str, Any]:
        """恢复最近或指定版本备份，并安排应用重启。"""
        try:
            from apps.installer.backup import import_backup

            result = import_backup(backup_path or None)
            payload = result.to_dict()
            if result.ok:
                payload["restart_scheduled"] = False
                payload["desktop_restart_required"] = True
            return payload
        except Exception as exc:
            logger.error("恢复备份失败: %s", exc)
            return {"ok": False, "errors": [redact_api_error_text(exc)]}

    def delete_backup(self, backup_path: str) -> Dict[str, Any]:
        """删除指定备份。"""
        try:
            from apps.installer.backup import delete_backup, get_backup_status

            deleted = delete_backup(backup_path)
            return {"ok": True, "deleted": deleted.to_dict(), "status": get_backup_status()}
        except Exception as exc:
            logger.error("删除备份失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}

    def open_backup_location(self, backup_path: str = "") -> Dict[str, Any]:
        """在系统文件管理器中打开备份位置。"""
        import platform
        import subprocess

        try:
            from apps.installer.backup import default_backup_root, resolve_managed_backup_path

            if backup_path:
                target = resolve_managed_backup_path(backup_path)
            else:
                target = default_backup_root().expanduser()
                target.mkdir(parents=True, exist_ok=True)
            system = platform.system()
            if system == "Darwin":
                command = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
            elif system == "Linux":
                command = ["xdg-open", str(target.parent if target.is_file() else target)]
            elif system == "Windows":
                if target.is_file():
                    command = ["explorer.exe", "/select,", str(target)]
                    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.startfile(str(target))  # type: ignore[attr-defined]
                return {"ok": True}
            else:
                return {"ok": False, "error": f"当前平台不支持自动打开位置: {system}"}
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True}
        except Exception as exc:
            logger.error("打开备份位置失败: %s", exc)
            return {"ok": False, "error": redact_api_error_text(exc)}
