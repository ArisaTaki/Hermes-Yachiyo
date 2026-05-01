"""Hermes capability helpers shared by shell APIs."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from apps.installer.hermes_check import locate_hermes_binary

logger = logging.getLogger(__name__)

_HERMES_CONFIG_TIMEOUT = 5.0
_VALID_IMAGE_INPUT_MODES = {"auto", "native", "text"}

_XIAOMI_NATIVE_IMAGE_MODELS = {
    "mimo-v2.5",
    "mimo-v2-omni",
}
_XIAOMI_VISION_TEXT_FALLBACK_MODELS = {
    "mimo-v2.5-pro",
}
_XIAOMI_TEXT_ONLY_MODELS = {
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


def build_hermes_image_input_capability(
    *,
    provider: str,
    model: str,
    config_path: Path,
) -> dict[str, Any]:
    """Summarize whether chat can submit images for the active Hermes model.

    Hermes supports two image paths: native multimodal input and a text
    pre-analysis path backed by ``vision_analyze``.  Yachiyo should not submit
    images silently when the active model would require an unconfigured vision
    pre-analysis pipeline.
    """
    image_config = read_hermes_image_input_config(config_path)
    mode = image_config["mode"]
    explicit_aux_vision = bool(image_config["auxiliary_vision_configured"])
    supports_vision = lookup_model_supports_vision(provider, model)
    if not provider or not model:
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="blocked",
            can_attach=False,
            requires_vision_pipeline=True,
            reason="Hermes 模型配置未完成，暂不能提交图片。",
        )

    if mode == "text":
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason="图片会先交给 Hermes vision 链路分析，再把结果发给当前模型。",
        )

    if mode == "native":
        can_attach = supports_vision is not False
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="native" if can_attach else "blocked",
            can_attach=can_attach,
            requires_vision_pipeline=False,
            reason=(
                "当前模型支持原生图片输入。"
                if supports_vision is True
                else "未能确认当前模型支持原生图片输入；如发送失败，请切回自动或配置 vision 链路。"
                if supports_vision is None
                else "当前模型未声明多模态能力，不能强制原生发送图片。"
            ),
        )

    if explicit_aux_vision:
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason="已检测到辅助 vision 配置，图片会先分析成文本再发送。",
        )

    if supports_vision is True:
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="native",
            can_attach=True,
            requires_vision_pipeline=False,
            reason="当前模型支持原生图片输入。",
        )

    if _uses_provider_vision_text_fallback(provider, model):
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="vision_text",
            can_attach=True,
            requires_vision_pipeline=True,
            reason=(
                "当前 Xiaomi Pro 模型不走稳定的原生图片输入；"
                "图片会先交给 Xiaomi vision 链路分析，再把结果发给当前模型。"
            ),
        )

    if supports_vision is False:
        return _image_input_payload(
            provider=provider,
            model=model,
            mode=mode,
            supports_vision=supports_vision,
            route="blocked",
            can_attach=False,
            requires_vision_pipeline=True,
            reason=(
                "当前模型未声明多模态能力。请切换支持图片的模型，或把图片输入设为 vision 预分析并配置辅助 vision。"
            ),
        )

    return _image_input_payload(
        provider=provider,
        model=model,
        mode=mode,
        supports_vision=supports_vision,
        route="unknown",
        can_attach=True,
        requires_vision_pipeline=False,
        reason="未能确认当前模型能力；允许提交图片，若失败请切换多模态模型或配置 vision 链路。",
    )


def _normalized_provider_model(provider: str, model: str) -> tuple[str, str]:
    return (provider or "").strip().lower(), (model or "").strip().lower()


def _uses_provider_vision_text_fallback(provider: str, model: str) -> bool:
    provider_id, model_id = _normalized_provider_model(provider, model)
    return provider_id == "xiaomi" and model_id in _XIAOMI_VISION_TEXT_FALLBACK_MODELS


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
    if can_attach and route == "native":
        label = "图片可用"
    elif can_attach and route == "vision_text":
        label = "需 vision 链路"
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
    mode = values.get(("agent", "image_input_mode"), "auto").strip().lower()
    if mode not in _VALID_IMAGE_INPUT_MODES:
        mode = "auto"
    vision_provider = values.get(("auxiliary", "vision", "provider"), "").strip().lower()
    vision_model = values.get(("auxiliary", "vision", "model"), "").strip()
    vision_base_url = values.get(("auxiliary", "vision", "base_url"), "").strip()
    vision_api_key = values.get(("auxiliary", "vision", "api_key"), "").strip()
    explicit = bool((vision_provider and vision_provider != "auto") or vision_model or vision_base_url or vision_api_key)
    return {
        "mode": mode,
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
        if model_id_raw in _XIAOMI_VISION_TEXT_FALLBACK_MODELS or model_id_raw in _XIAOMI_TEXT_ONLY_MODELS:
            return False

    provider_id = _PROVIDER_TO_MODELS_DEV.get((provider or "").strip().lower())
    model_id = (model or "").strip()
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
