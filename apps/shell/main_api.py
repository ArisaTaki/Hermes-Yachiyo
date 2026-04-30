"""主界面 WebView API

为 Control Center 主控台提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
集成 ChatAPI 提供聊天功能。
"""

import logging
import os
import re
import subprocess
import threading
import time
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from apps.installer.hermes_check import locate_hermes_binary
from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_api import ChatAPI
from apps.shell.chat_bridge import ChatBridge
from apps.shell.config import ModelSummary
from apps.shell.effect_policy import build_effects_summary
from apps.shell.integration_status import get_integration_snapshot
from apps.shell.mode_catalog import list_mode_options
from apps.shell.mode_settings import (
    apply_settings_changes,
    build_display_settings,
    serialize_mode_settings,
)

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)
_HERMES_CONNECTION_TEST_TIMEOUT = 45.0
_HERMES_CONNECTION_TEST_PROMPT = (
    "This is a Hermes-Yachiyo provider connectivity check. "
    "Reply with exactly: OK"
)
_HERMES_CONFIG_TIMEOUT = 20.0
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_REDACTIONS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
)
_HERMES_PROVIDER_PRESETS: tuple[dict[str, Any], ...] = (
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
        "models": ("anthropic/claude-sonnet-4.6", "openai/gpt-5.4", "google/gemini-3-pro-preview", "deepseek/deepseek-chat"),
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
_PROVIDER_PRESET_BY_ID = {str(item["id"]): item for item in _HERMES_PROVIDER_PRESETS}
_TERMINAL_COMMAND_THROTTLE_SECONDS = 1.2
_TERMINAL_COMMAND_LOCK = threading.Lock()
_LAST_TERMINAL_COMMAND_AT = 0.0


def _is_desktop_backend() -> bool:
    return os.environ.get("HERMES_YACHIYO_DESKTOP_BACKEND") == "1"


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


def _public_command(argv: list[str]) -> str:
    if "-z" not in argv:
        return " ".join(argv)
    index = argv.index("-z")
    return " ".join(argv[: index + 1] + ["<connectivity-check>"] + argv[index + 2:])


def _hermes_command_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": "setup",
            "label": "重新配置向导",
            "command": "hermes setup",
            "description": "重新选择模型、provider、API Key 与工具开关。",
        },
        {
            "id": "model",
            "label": "选择模型",
            "command": "hermes model",
            "description": "只调整默认 provider 与模型，不重走完整 setup。",
        },
        {
            "id": "config-edit",
            "label": "编辑配置文件",
            "command": "hermes config edit",
            "description": "用 Hermes 原生命令打开配置文件，适合修正 base URL 等高级项。",
        },
        {
            "id": "config-check",
            "label": "检查配置结构",
            "command": "hermes config check",
            "description": "检查缺失或过期配置，不会发起模型请求。",
        },
        {
            "id": "doctor",
            "label": "运行诊断",
            "command": "hermes doctor",
            "description": "检查 Hermes 依赖、配置和运行环境。",
        },
        {
            "id": "auth-list",
            "label": "查看凭据池",
            "command": "hermes auth list",
            "description": "查看 Hermes 记录的 provider 凭据状态，不在 Yachiyo 中显示密钥内容。",
        },
    ]


def _allowed_terminal_commands() -> set[str]:
    return {item["command"] for item in _hermes_command_catalog()}


def _is_macos_prerequisite_command(cmd: str) -> bool:
    return (
        "Hermes-Yachiyo macOS 基础工具检查" in cmd
        and "xcode-select --install" in cmd
        and "brew install git curl" in cmd
    )


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


def _read_hermes_model_config(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        return {"provider": "", "default": "", "base_url": ""}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"provider": "", "default": "", "base_url": ""}

    model: dict[str, str] = {"provider": "", "default": "", "base_url": ""}
    in_model_block = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            in_model_block = line.startswith("model:")
            if in_model_block:
                inline = line.split(":", 1)[1].strip()
                if inline and not inline.startswith(("{", "[")):
                    model["default"] = _strip_yaml_scalar(inline)
            continue
        if not in_model_block:
            continue
        match = re.match(r"\s+([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        if key in model:
            model[key] = _strip_yaml_scalar(raw_value)
    return model


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


@lru_cache(maxsize=1)
def _load_installed_hermes_provider_models() -> dict[str, list[str]]:
    """Best-effort read of Hermes' own static provider model catalog.

    Hermes can update provider/model catalogs independently from Yachiyo.  The
    installed source is optional here; if it is unavailable or contains dynamic
    expressions we safely fall back to the bundled presets.
    """
    candidates = [
        Path.home() / ".hermes" / "hermes-agent" / "hermes_cli" / "models.py",
    ]
    catalog: dict[str, list[str]] = {}
    for path in candidates:
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in tree.body:
            value_node = None
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "_PROVIDER_MODELS" for target in node.targets)
            ):
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_PROVIDER_MODELS":
                value_node = node.value
            if not isinstance(value_node, ast.Dict):
                continue
            for key_node, provider_models_node in zip(value_node.keys, value_node.values):
                if key_node is None:
                    continue
                try:
                    provider = ast.literal_eval(key_node)
                except Exception:
                    continue
                if not isinstance(provider, str) or not isinstance(provider_models_node, ast.List):
                    continue
                models: list[str] = []
                for item in provider_models_node.elts:
                    try:
                        value = ast.literal_eval(item)
                    except Exception:
                        continue
                    if isinstance(value, str) and value:
                        models.append(value)
                if models:
                    catalog[provider] = models
        if catalog:
            return catalog
    return {}


def _preset_models(provider_id: str, preset: dict[str, Any]) -> list[str]:
    installed = _load_installed_hermes_provider_models().get(provider_id, [])
    fallback = [str(item) for item in preset.get("models", ()) if item]
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*installed, *fallback]:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return merged


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


def _provider_api_key_names(provider: str) -> tuple[str, ...]:
    normalized = provider.strip().lower()
    if not normalized:
        return ()
    preset = _PROVIDER_PRESET_BY_ID.get(normalized)
    if preset:
        return tuple(str(item) for item in preset.get("api_key_names", ()) if item)
    return (f"{normalized.upper().replace('-', '_')}_API_KEY",)


def _provider_options(
    *,
    current_provider: str,
    config_path: Path,
    env_values: dict[str, str],
) -> list[dict[str, Any]]:
    overrides = _read_user_provider_overrides(config_path)
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preset in _HERMES_PROVIDER_PRESETS:
        provider_id = str(preset["id"])
        override = overrides.get(provider_id, {})
        base_url_env = str(preset.get("base_url_env") or "")
        api_key_names = tuple(str(item) for item in preset.get("api_key_names", ()) if item)
        models = _preset_models(provider_id, preset)
        configured_key = next((name for name in api_key_names if env_values.get(name)), "")
        configured = bool(configured_key) or str(preset.get("auth_type") or "") != "api_key" and not api_key_names
        base_url = env_values.get(base_url_env) if base_url_env else ""
        base_url = override.get("base_url") or base_url or str(preset.get("base_url") or "")
        default_model = override.get("model") or override.get("default") or (
            models[0] if models else ""
        )
        options.append(
            {
                "id": provider_id,
                "label": str(preset.get("label") or provider_id),
                "base_url": base_url,
                "default_model": default_model,
                "models": models,
                "api_key_names": list(api_key_names),
                "api_key_name": configured_key or (api_key_names[0] if api_key_names else ""),
                "api_key_configured": configured,
                "auth_type": str(preset.get("auth_type") or "api_key"),
                "source": "hermes",
                "is_current": provider_id == current_provider,
            }
        )
        seen.add(provider_id)

    for provider_id, override in overrides.items():
        if provider_id in seen:
            continue
        api_key_names = _provider_api_key_names(provider_id)
        configured_key = next((name for name in api_key_names if env_values.get(name)), "")
        options.append(
            {
                "id": provider_id,
                "label": override.get("name") or provider_id,
                "base_url": override.get("base_url") or "",
                "default_model": override.get("model") or override.get("default") or "",
                "models": [override["model"]] if override.get("model") else [],
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
        configured_key = next((name for name in api_key_names if env_values.get(name)), "")
        options.insert(
            0,
            {
                "id": current_provider,
                "label": current_provider,
                "base_url": "",
                "default_model": "",
                "models": [],
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


def _run_config_path_command(hermes_path: str, subcommand: str) -> Path:
    fallback_name = "config.yaml" if subcommand == "path" else ".env"
    fallback = Path.home() / ".hermes" / fallback_name
    try:
        result = subprocess.run(
            [hermes_path, "config", subcommand],
            capture_output=True,
            text=True,
            timeout=_HERMES_CONFIG_TIMEOUT,
            check=False,
        )
    except Exception:
        return fallback
    if result.returncode != 0:
        return fallback
    path = (result.stdout or "").strip().splitlines()
    if not path:
        return fallback
    return Path(path[-1]).expanduser()


class MainWindowAPI:
    """Control Center 主控台 API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
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

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()

            hermes_info = status.get("hermes", {})

            return {
                "app": {
                    "version": status.get("version", "0.1.0"),
                    "running": status.get("running", False),
                    "uptime_seconds": round(status.get("uptime_seconds", 0), 1),
                },
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "version": hermes_info.get("version"),
                    "platform": hermes_info.get("platform", "unknown"),
                    "command_exists": hermes_info.get("command_exists", False),
                    "hermes_home": hermes_info.get("hermes_home", ""),
                    "ready": self._runtime.is_hermes_ready(),
                    "readiness_level": hermes_info.get("readiness_level", "unknown"),
                    "limited_tools": hermes_info.get("limited_tools", []),
                    "doctor_issues_count": hermes_info.get("doctor_issues_count", 0),
                    "configuration_actions": _hermes_command_catalog(),
                },
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
                    "current": self._config.display_mode,
                    "items": list_mode_options(),
                },
                "chat": self._chat_bridge.get_conversation_overview(
                    summary_count=self._config.window_mode.recent_messages_limit,
                    session_limit=self._config.window_mode.recent_sessions_limit,
                ),
            }
        except Exception as e:
            logger.error("获取仪表盘数据失败: %s", e)
            return {"error": str(e)}

    def get_settings_data(self) -> Dict[str, Any]:
        """获取设置页数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()
            hermes_info = status.get("hermes", {})

            return {
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "version": hermes_info.get("version"),
                    "platform": hermes_info.get("platform", "unknown"),
                    "command_exists": hermes_info.get("command_exists", False),
                    "hermes_home": hermes_info.get("hermes_home", ""),
                    "ready": self._runtime.is_hermes_ready(),
                    "readiness_level": hermes_info.get("readiness_level", "unknown"),
                    "limited_tools": hermes_info.get("limited_tools", []),
                    "doctor_issues_count": hermes_info.get("doctor_issues_count", 0),
                    "configuration_actions": _hermes_command_catalog(),
                },
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
                "assistant": {
                    "persona_prompt": self._config.assistant.persona_prompt,
                    "user_address": self._config.assistant.user_address,
                },
                "bridge": snap.bridge.to_dict(),
                "integrations": {
                    "astrbot": snap.astrbot.to_dict(),
                    "hapi": snap.hapi.to_dict(),
                },
                "app": {
                    "version": status.get("version", "0.1.0"),
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
            return {"error": str(e)}

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
            "display_mode": self._config.display_mode,
            "mode_settings": serialize_mode_settings(self._config),
            "assistant": {
                "persona_prompt": self._config.assistant.persona_prompt,
                "user_address": self._config.assistant.user_address,
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

        操作流程：
          1. 检查 bridge_enabled
          2. 调用 server.restart_bridge() 停止旧实例 + 启动新线程
          3. 刷新 _bridge_boot_config（重新对齐）
          4. 返回最新 app_state 供前端刷新
        """
        from apps.bridge.server import restart_bridge as _restart

        if not self._config.bridge_enabled:
            return {
                "ok": False,
                "error": "Bridge 未启用，请先在设置中启用 Bridge",
                "app_state": self._current_app_state(),
            }

        host = self._config.bridge_host
        port = self._config.bridge_port

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
            cmd: 要在终端中运行的命令字符串，如 "hermes setup"

        Returns:
            {"success": bool, "error": str | None}
        """
        global _LAST_TERMINAL_COMMAND_AT

        cmd = (cmd or "").strip()
        logger.info("open_terminal_command: cmd=%r", cmd)
        if not cmd:
            return {"success": False, "error": "终端命令为空"}
        if cmd not in _allowed_terminal_commands() and not _is_macos_prerequisite_command(cmd):
            return {
                "success": False,
                "error": "不支持的 Hermes 终端命令",
                "unsupported": True,
            }

        with _TERMINAL_COMMAND_LOCK:
            now = time.monotonic()
            if now - _LAST_TERMINAL_COMMAND_AT < _TERMINAL_COMMAND_THROTTLE_SECONDS:
                return {
                    "success": False,
                    "error": "上一个 Hermes 操作还在打开中，请稍后再试",
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
            return {"success": False, "error": str(exc)}

    def test_hermes_connection(self) -> Dict[str, Any]:
        """用一次轻量 Hermes oneshot 调用验证当前 provider/API Key 是否可用。

        ``hermes doctor`` 和 ``hermes config check`` 更偏静态检查；真正的 API Key、
        provider、base URL 是否能工作，只有发起一次模型请求才可靠。
        """
        hermes_path, needs_env_refresh = locate_hermes_binary()
        if hermes_path is None:
            hermes_path = "hermes"

        argv = [hermes_path, "-z", _HERMES_CONNECTION_TEST_PROMPT]
        started_at = time.monotonic()
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_HERMES_CONNECTION_TEST_TIMEOUT,
                check=False,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "success": False,
                "error": "hermes 命令未找到，请先安装 Hermes Agent",
                "command": "hermes -z <connectivity-check>",
                "needs_env_refresh": needs_env_refresh,
            }
        except subprocess.TimeoutExpired as exc:
            detail = _compact_command_output(
                "\n".join(part for part in (exc.stdout or "", exc.stderr or "") if part)
            )
            return {
                "ok": False,
                "success": False,
                "error": "Hermes 模型连接测试超时，请检查网络、provider 或 base URL",
                "detail": detail,
                "command": _public_command(argv),
                "elapsed_seconds": round(time.monotonic() - started_at, 2),
                "needs_env_refresh": needs_env_refresh,
            }

        elapsed = round(time.monotonic() - started_at, 2)
        stdout = _compact_command_output(result.stdout)
        stderr = _compact_command_output(result.stderr)
        if result.returncode == 0 and stdout:
            return {
                "ok": True,
                "success": True,
                "message": "Hermes provider/API Key 连接测试通过",
                "output_preview": stdout,
                "command": _public_command(argv),
                "elapsed_seconds": elapsed,
                "needs_env_refresh": needs_env_refresh,
            }

        detail = stderr or stdout
        error = (
            f"Hermes 模型连接测试失败：{detail}"
            if detail
            else f"Hermes 模型连接测试失败（exit={result.returncode}）"
        )
        return {
            "ok": False,
            "success": False,
            "error": error,
            "output_preview": stdout,
            "stderr_preview": stderr,
            "returncode": result.returncode,
            "command": _public_command(argv),
            "elapsed_seconds": elapsed,
            "needs_env_refresh": needs_env_refresh,
        }

    def get_hermes_configuration(self) -> Dict[str, Any]:
        """读取 Hermes provider/model 配置摘要。不会返回密钥明文。"""
        hermes_path, needs_env_refresh = locate_hermes_binary()
        command_exists = hermes_path is not None
        if hermes_path is None:
            hermes_path = "hermes"

        config_path = _run_config_path_command(hermes_path, "path")
        env_path = _run_config_path_command(hermes_path, "env-path")
        model = _read_hermes_model_config(config_path)
        provider = model.get("provider", "")
        env_values = _read_env_values(env_path)
        provider_options = _provider_options(
            current_provider=provider,
            config_path=config_path,
            env_values=env_values,
        )
        selected_provider = next(
            (option for option in provider_options if option.get("id") == provider),
            provider_options[0] if provider_options else {},
        )
        api_key_name = str(selected_provider.get("api_key_name") or _provider_api_key_name(provider))
        api_key_configured = bool(selected_provider.get("api_key_configured"))
        return {
            "ok": True,
            "command_exists": command_exists,
            "needs_env_refresh": needs_env_refresh,
            "config_path": str(config_path),
            "env_path": str(env_path),
            "model": {
                "provider": provider,
                "default": model.get("default", ""),
                "base_url": model.get("base_url", ""),
            },
            "provider_options": provider_options,
            "api_key": {
                "name": api_key_name,
                "configured": api_key_configured,
                "display": "已配置" if api_key_configured else "未配置",
            },
        }

    def update_hermes_configuration(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """用 Hermes CLI 写入 provider/model/API Key 配置。"""
        provider = str(changes.get("provider") or "").strip()
        model = str(changes.get("model") or "").strip()
        base_url = str(changes.get("base_url") or "").strip()
        api_key = str(changes.get("api_key") or "").strip()
        if not provider:
            return {"ok": False, "error": "Provider 不能为空"}
        if not model:
            return {"ok": False, "error": "模型名称不能为空"}

        hermes_path, needs_env_refresh = locate_hermes_binary()
        if hermes_path is None:
            return {
                "ok": False,
                "error": "hermes 命令未找到，请先安装 Hermes Agent",
                "needs_env_refresh": needs_env_refresh,
            }

        commands: list[tuple[str, str]] = [
            ("model.provider", provider),
            ("model.default", model),
            ("model.base_url", base_url),
        ]
        api_key_name = _provider_api_key_name(provider)
        if api_key:
            commands.append((api_key_name, api_key))

        for key, value in commands:
            try:
                result = subprocess.run(
                    [hermes_path, "config", "set", key, value],
                    capture_output=True,
                    text=True,
                    timeout=_HERMES_CONFIG_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": f"写入 Hermes 配置超时：{key}"}
            except Exception as exc:
                return {"ok": False, "error": f"写入 Hermes 配置失败：{exc}"}
            if result.returncode != 0:
                detail = _compact_command_output(result.stderr or result.stdout)
                return {
                    "ok": False,
                    "error": f"写入 Hermes 配置失败：{key}{'，' + detail if detail else ''}",
                    "returncode": result.returncode,
                }

        return {
            "ok": True,
            "message": "Hermes 配置已保存",
            "configuration": self.get_hermes_configuration(),
        }

    def recheck_hermes(self) -> Dict[str, Any]:
        """重新检测 Hermes 安装 / 就绪状态，并刷新仪表盘数据。

        用于用户完成 hermes setup / hermes doctor 后手动触发重新检测。

        Returns:
            get_dashboard_data() 的最新结果（包含 hermes.readiness_level 等字段）
        """
        logger.info("手动触发 Hermes 就绪状态重检...")
        executor_refresh = {
            "updated": False,
            "executor": "unknown",
            "previous_executor": None,
            "reason": "refresh_failed",
        }
        try:
            self._runtime.refresh_hermes_installation()
            executor_refresh = self._runtime.refresh_task_runner_executor()
        except Exception as exc:
            logger.warning("重新检测 Hermes 状态失败: %s", exc)

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
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False}
        return {
            "executor": runner.executor.name,
            "available": True,
        }

    def open_chat(self) -> Dict[str, Any]:
        """打开独立聊天窗口"""
        from apps.shell.chat_window import open_chat_window
        ok = open_chat_window(self._runtime)
        return {"ok": ok}

    def open_mode_settings(self, mode_id: str) -> Dict[str, Any]:
        """打开指定模式的独立设置窗口。"""
        from apps.shell.settings import open_mode_settings_window

        ok = open_mode_settings_window(config=self._config, mode_id=mode_id)
        return {"ok": ok, "mode_id": mode_id}

    def quit_app(self) -> Dict[str, Any]:
        """执行退出前清理；主窗口由前端随后关闭。"""
        try:
            from apps.shell.window import request_app_exit
            request_app_exit()
            return {"ok": True}
        except Exception as exc:
            logger.error("退出应用失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_uninstall_preview(
        self,
        scope: str = "yachiyo_only",
        keep_config: bool = True,
    ) -> Dict[str, Any]:
        """生成卸载预览，不修改文件系统。"""
        try:
            from apps.installer.uninstall import build_uninstall_plan

            plan = build_uninstall_plan(scope, keep_config_snapshot=bool(keep_config))
            return {"ok": True, "plan": plan.to_dict()}
        except Exception as exc:
            logger.error("生成卸载预览失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def run_uninstall(
        self,
        scope: str = "yachiyo_only",
        keep_config: bool = True,
        confirm_text: str = "",
    ) -> Dict[str, Any]:
        """执行 Hermes-Yachiyo 卸载，并在成功后安排应用退出。"""
        try:
            from apps.installer.uninstall import execute_uninstall

            result = execute_uninstall(
                scope,
                keep_config_snapshot=bool(keep_config),
                confirm_text=confirm_text,
            )
            payload = result.to_dict()
            if result.ok:
                if _is_desktop_backend():
                    payload["exit_scheduled"] = False
                    payload["desktop_quit_required"] = True
                    return payload
                try:
                    from apps.shell.window import request_app_exit

                    request_app_exit()
                    payload["exit_scheduled"] = True
                except Exception as exc:
                    logger.error("卸载后退出应用失败: %s", exc)
                    payload["exit_scheduled"] = False
                    payload["exit_error"] = str(exc)
            return payload
        except Exception as exc:
            logger.error("执行卸载失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_backup_status(self) -> Dict[str, Any]:
        """获取 Hermes-Yachiyo 备份状态。"""
        try:
            from apps.installer.backup import get_backup_status

            return {"ok": True, **get_backup_status()}
        except Exception as exc:
            logger.error("读取备份状态失败: %s", exc)
            return {"ok": False, "error": str(exc), "has_backup": False}

    def create_backup(self, overwrite_latest: bool = False) -> Dict[str, Any]:
        """主动生成 Hermes-Yachiyo 本地资料备份。"""
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
            return {"ok": False, "error": str(exc)}

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
            return {"ok": False, "error": str(exc)}

    def restore_backup(self, backup_path: str = "") -> Dict[str, Any]:
        """恢复最近或指定版本备份，并安排应用重启。"""
        try:
            from apps.installer.backup import import_backup

            result = import_backup(backup_path or None)
            payload = result.to_dict()
            if result.ok:
                try:
                    from apps.shell.window import request_app_restart

                    request_app_restart()
                    payload["restart_scheduled"] = True
                except Exception as exc:
                    logger.error("恢复备份后重启失败: %s", exc)
                    payload["restart_scheduled"] = False
                    payload["restart_error"] = str(exc)
            return payload
        except Exception as exc:
            logger.error("恢复备份失败: %s", exc)
            return {"ok": False, "errors": [str(exc)]}

    def delete_backup(self, backup_path: str) -> Dict[str, Any]:
        """删除指定备份。"""
        try:
            from apps.installer.backup import delete_backup, get_backup_status

            deleted = delete_backup(backup_path)
            return {"ok": True, "deleted": deleted.to_dict(), "status": get_backup_status()}
        except Exception as exc:
            logger.error("删除备份失败: %s", exc)
            return {"ok": False, "error": str(exc)}

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
            return {"ok": False, "error": str(exc)}
