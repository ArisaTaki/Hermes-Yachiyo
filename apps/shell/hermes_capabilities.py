"""Hermes capability helpers shared by shell APIs."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.installer.hermes_check import locate_hermes_binary

logger = logging.getLogger(__name__)

_HERMES_CONFIG_TIMEOUT = 5.0
_VALID_IMAGE_INPUT_MODES = {"auto", "native", "text"}

_XIAOMI_NATIVE_IMAGE_MODELS = {
    "mimo-v2.5",
    "mimo-v2-omni",
}
_XIAOMI_TEXT_ONLY_MODELS = {
    "mimo-v2.5-pro",
    "mimo-v2-pro",
    "mimo-v2-flash",
}

_PROVIDER_TO_MODELS_DEV = {
    "openrouter": "openrouter",
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-codex": "openai",
    "deepseek": "deepseek",
    "gemini": "google",
    "google": "google",
    "xai": "xai",
    "xiaomi": "xiaomi",
    "zai": "zai",
    "kimi-coding": "kimi-for-coding",
    "huggingface": "huggingface",
    "lmstudio": "",
    "custom": "",
}
_PROVIDER_ALIASES = {
    "google": "gemini",
    "google-ai": "gemini",
    "google-ai-studio": "gemini",
    "x-ai": "xai",
    "moonshot": "kimi-coding",
    "kimi": "kimi-coding",
    "glm": "zai",
    "z-ai": "zai",
}
_AUTO_PROVIDER_VALUES = {"", "auto", "main"}
_PROVIDER_HOST_HINTS: tuple[tuple[str, str], ...] = (
    ("openrouter.ai", "openrouter"),
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("api.xiaomimimo.com", "xiaomi"),
    ("token-plan-cn.xiaomimimo.com", "xiaomi"),
    ("api.deepseek.com", "deepseek"),
    ("api.x.ai", "xai"),
    ("api.moonshot.ai", "kimi-coding"),
    ("api.moonshot.cn", "kimi-coding"),
    ("api.kimi.com", "kimi-coding"),
    ("api.z.ai", "zai"),
    ("open.bigmodel.cn", "zai"),
    ("router.huggingface.co", "huggingface"),
)
_OPENROUTER_MODEL_PREFIXES = (
    "anthropic/",
    "openai/",
    "google/",
    "deepseek/",
    "x-ai/",
    "meta-llama/",
    "mistralai/",
    "qwen/",
    "minimax/",
)


def get_current_hermes_image_input_capability() -> dict[str, Any]:
    """Return the current Hermes image-input capability summary."""
    hermes_path, _ = locate_hermes_binary()
    config_path = _run_config_path_command(hermes_path or "hermes", "path")
    model = read_hermes_model_config(config_path)
    return build_hermes_image_input_capability(
        provider=model.get("provider", ""),
        model=model.get("default", ""),
        config_path=config_path,
    )


def infer_effective_hermes_provider(provider: str, base_url: str = "", model: str = "") -> str:
    """Infer the concrete provider behind Hermes' ``auto`` provider setting."""
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


def build_hermes_image_input_capability(
    *,
    provider: str,
    model: str,
    config_path: Path,
) -> dict[str, Any]:
    """Summarize whether chat can submit images for the active Hermes model.

    Yachiyo intentionally routes every image through its own vision pre-analysis
    path.  Hermes native multimodal input and Hermes' ``vision_analyze`` tool
    are not advertised as available routes here.
    """
    image_config = read_hermes_image_input_config(config_path)
    model_config = read_hermes_model_config(config_path)
    effective_provider = (
        infer_effective_hermes_provider(
            provider,
            model_config.get("base_url", ""),
            model or model_config.get("default", ""),
        )
        or (provider or "").strip().lower()
    )
    mode = "text"
    explicit_aux_vision = bool(image_config["auxiliary_vision_configured"])
    supports_vision = lookup_model_supports_vision(effective_provider, model)
    if not effective_provider or not model:
        return _image_input_payload(
            provider=effective_provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="blocked",
            can_attach=False,
            requires_vision_pipeline=True,
            reason="Hermes 模型配置未完成，暂不能提交图片。",
        )

    if explicit_aux_vision:
        return _image_input_payload(
            provider=effective_provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason="图片会先由 Yachiyo vision 预分析，再把结果交给当前主模型。",
        )

    if effective_provider == "xiaomi" and supports_vision is False:
        return _image_input_payload(
            provider=effective_provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason=(
                "当前小米主模型不走原生图片入口；Yachiyo 会自动使用 mimo-v2.5 "
                "预分析图片，再把结果交给主模型。"
            ),
        )

    if supports_vision is True:
        return _image_input_payload(
            provider=effective_provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason="当前主模型支持图片；Yachiyo 会直接调用它做 vision 预分析，不再走 Hermes 原生图片输入。",
        )

    if supports_vision is False:
        return _image_input_payload(
            provider=effective_provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="blocked",
            can_attach=False,
            requires_vision_pipeline=True,
            reason=(
                "当前主模型未声明图片输入能力。请切换支持图片的模型，或在图片识别链路中选择单独图片模型后再发送图片。"
            ),
        )

    return _image_input_payload(
        provider=effective_provider,
        model=model,
        mode=mode,
        supports_vision=supports_vision,
        route="vision_text",
        can_attach=True,
        requires_vision_pipeline=True,
        reason="未能确认当前模型图片能力；Yachiyo 会尝试直接 vision 预分析，若测试失败请配置单独图片模型。",
    )


def _normalized_provider_model(provider: str, model: str) -> tuple[str, str]:
    return (provider or "").strip().lower(), (model or "").strip().lower()


def _image_input_payload(
    *,
    provider: str,
    model: str,
    mode: str,
    supports_vision: bool | None,
    route: str,
    can_attach: bool,
    requires_vision_pipeline: bool,
    reason: str,
) -> dict[str, Any]:
    if can_attach and route == "vision_text":
        label = "Yachiyo vision"
    elif can_attach:
        label = "能力未确认"
    else:
        label = "图片不可用"
    return {
        "can_attach_images": can_attach,
        "mode": mode,
        "route": route,
        "supports_native_vision": supports_vision,
        "requires_vision_pipeline": requires_vision_pipeline,
        "native_disabled": True,
        "provider": provider,
        "model": model,
        "label": label,
        "reason": reason,
    }


def read_hermes_model_config(config_path: Path) -> dict[str, str]:
    values = _read_yaml_paths(config_path, {("model", "provider"), ("model", "default"), ("model", "base_url")})
    return {
        "provider": values.get(("model", "provider"), ""),
        "default": values.get(("model", "default"), ""),
        "base_url": values.get(("model", "base_url"), ""),
    }


def read_hermes_image_input_config(config_path: Path) -> dict[str, Any]:
    values = _read_yaml_paths(
        config_path,
        {
            ("agent", "image_input_mode"),
            ("auxiliary", "vision", "provider"),
            ("auxiliary", "vision", "model"),
            ("auxiliary", "vision", "base_url"),
            ("auxiliary", "vision", "api_key"),
        },
    )
    stored_mode = values.get(("agent", "image_input_mode"), "auto").strip().lower()
    mode = stored_mode
    if mode not in _VALID_IMAGE_INPUT_MODES:
        mode = "auto"
    vision_provider = values.get(("auxiliary", "vision", "provider"), "").strip().lower()
    vision_model = values.get(("auxiliary", "vision", "model"), "").strip()
    vision_base_url = values.get(("auxiliary", "vision", "base_url"), "").strip()
    vision_api_key = values.get(("auxiliary", "vision", "api_key"), "").strip()
    explicit = bool((vision_provider and vision_provider != "auto") or vision_model or vision_base_url or vision_api_key)
    return {
        "mode": "text",
        "stored_mode": mode,
        "auxiliary_vision_configured": explicit,
        "auxiliary_vision_provider": vision_provider,
        "auxiliary_vision_model": vision_model,
        "auxiliary_vision_base_url": vision_base_url,
        "auxiliary_vision_base_url_configured": bool(vision_base_url),
        "auxiliary_vision_api_key_configured": bool(vision_api_key),
    }


def lookup_model_supports_vision(provider: str, model: str) -> bool | None:
    provider_id_raw, model_id_raw = _normalized_provider_model(provider, model)
    if provider_id_raw == "xiaomi":
        if model_id_raw in _XIAOMI_NATIVE_IMAGE_MODELS:
            return True
        if model_id_raw in _XIAOMI_TEXT_ONLY_MODELS:
            return False

    provider_id = _PROVIDER_TO_MODELS_DEV.get((provider or "").strip().lower())
    model_id = (model or "").strip()
    cache_result = _lookup_models_dev_supports_vision(provider_id, model_id)
    if cache_result is not None:
        return cache_result

    return None


def _lookup_models_dev_supports_vision(provider_id: str, model_id: str) -> bool | None:
    if not provider_id or not model_id:
        return None

    data = _load_models_dev_cache()
    provider_data = data.get(provider_id)
    if not isinstance(provider_data, dict):
        return None
    models = provider_data.get("models")
    if not isinstance(models, dict):
        return None

    entry = models.get(model_id)
    if not isinstance(entry, dict):
        model_lower = model_id.lower()
        entry = next(
            (item for item_id, item in models.items() if item_id.lower() == model_lower and isinstance(item, dict)),
            None,
        )
    if not isinstance(entry, dict):
        return None

    modalities = entry.get("modalities")
    input_modalities: list[Any] = []
    if isinstance(modalities, dict):
        raw_input = modalities.get("input")
        if isinstance(raw_input, list):
            input_modalities = raw_input
    return bool(entry.get("attachment", False)) or "image" in input_modalities


def _load_models_dev_cache() -> dict[str, Any]:
    cache_path = Path.home() / ".hermes" / "models_dev_cache.json"
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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


def _read_yaml_paths(path: Path, wanted: set[tuple[str, ...]]) -> dict[tuple[str, ...], str]:
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.debug("读取 Hermes 配置失败: %s", exc)
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
