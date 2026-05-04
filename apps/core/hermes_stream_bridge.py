"""Hermes streaming bridge.

Runs under Hermes Agent's own Python interpreter.  The parent process sends one
JSON payload on stdin and receives newline-delimited JSON events on stdout:

  {"type": "delta", "delta": "..."}
  {"type": "done", "response": "...", "session_id": "...", "title": "..."}
  {"type": "error", "message": "..."}

All Hermes CLI terminal output is redirected to stderr so the chat UI consumes
only agent text deltas, not Rich banners, tool lists, or startup messages.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Optional
from urllib.parse import urlparse


_EVENT_STDOUT = sys.stdout
_DEBUG_ROUTE_ENV = "HERMES_YACHIYO_DEBUG_ROUTE"
_DEBUG_ROUTE_TRUE_VALUES = {"1", "true", "yes", "on", "debug"}
_EMPTY_DETAIL_VALUES = {"", "none", "null"}
_FAILURE_DETAIL_KEYS = (
    "error",
    "error_message",
    "message",
    "exception",
    "detail",
    "details",
)
_ATTACHED_IMAGE_GUARD = (
    "本轮用户已经附加图片。请优先且尽量只根据这些附加图片回答；"
    "不要沿用历史消息里对旧图片的描述来回答本轮图片；"
    "不要调用桌面截图、活动窗口、浏览器视觉或其它实时桌面观察工具来替代附加图片，"
    "除非用户明确要求你操作当前电脑或重新观察屏幕。"
)
_XIAOMI_NATIVE_IMAGE_MODELS = {
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-omni",
}
_XIAOMI_TEXT_ONLY_IMAGE_MODELS = {
    "mimo-v2-pro",
    "mimo-v2-flash",
}
_PREFERRED_AUXILIARY_VISION_MODELS = {
    "xiaomi": "mimo-v2.5-pro",
}
_PROVIDER_API_KEY_NAMES = {
    "xiaomi": ("XIAOMI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "kimi-coding": ("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    "zai": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
    "huggingface": ("HF_TOKEN",),
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


class ImagePreprocessError(RuntimeError):
    """Raised when Yachiyo cannot turn image attachments into model context."""


def _emit(event_type: str, **payload: Any) -> None:
    payload["type"] = event_type
    _EVENT_STDOUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _EVENT_STDOUT.flush()


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _detail_text(value: Any, *, drop_empty_literals: bool = True) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value).strip()
    else:
        text = str(value).strip()
    if drop_empty_literals and text.lower() in _EMPTY_DETAIL_VALUES:
        return ""
    return text


def _failure_message_from_result(result: dict[str, Any]) -> str:
    for key in _FAILURE_DETAIL_KEYS:
        text = _detail_text(result.get(key))
        if text:
            return text
    errors = result.get("errors")
    if isinstance(errors, list):
        for item in errors:
            text = _detail_text(item)
            if text:
                return text
    return ""


def _resolve_toolsets(cli_config: dict[str, Any]) -> list[str]:
    try:
        from hermes_cli.tools_config import _get_platform_tools

        return sorted(_get_platform_tools(cli_config, "cli"))
    except Exception:
        return []


def _get_session_title(cli: Any, session_id: str) -> Optional[str]:
    session_db = getattr(cli, "_session_db", None)
    if session_db is None:
        return None
    try:
        title = session_db.get_session_title(session_id)
    except Exception:
        return None
    return title if isinstance(title, str) and title else None


def _is_debug_route_enabled() -> bool:
    value = os.environ.get(_DEBUG_ROUTE_ENV, "")
    return value.strip().lower() in _DEBUG_ROUTE_TRUE_VALUES


def _collect_image_paths(payload: dict[str, Any]) -> list[Path]:
    raw_paths = payload.get("image_paths")
    if not isinstance(raw_paths, list):
        return []
    images: list[Path] = []
    seen: set[str] = set()
    for value in raw_paths:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(key)
        images.append(resolved)
    return images


def _with_attached_image_guard(description: str, image_paths: list[Path]) -> str:
    if not image_paths:
        return description
    count = len(image_paths)
    return (
        "[Yachiyo 附件图片上下文]\n"
        f"{_ATTACHED_IMAGE_GUARD}\n"
        f"附加图片数量：{count}\n\n"
        f"{description}"
    )


def _configured_image_input_mode(cfg: dict[str, Any] | None) -> str:
    if not isinstance(cfg, dict):
        return "auto"
    agent_cfg = cfg.get("agent") or {}
    if not isinstance(agent_cfg, dict):
        return "auto"
    mode = str(agent_cfg.get("image_input_mode") or "auto").strip().lower()
    return mode if mode in {"auto", "native", "text"} else "auto"


def _lookup_model_supports_vision(provider: str, model: str) -> bool | None:
    try:
        from agent.models_dev import get_model_capabilities

        caps = get_model_capabilities(provider, model)
    except Exception:
        caps = None
    if caps is not None:
        return bool(getattr(caps, "supports_vision", False))

    provider_id = provider.strip().lower()
    model_id = model.strip().lower()
    if provider_id == "xiaomi":
        if model_id in _XIAOMI_NATIVE_IMAGE_MODELS:
            return True
        if model_id in _XIAOMI_TEXT_ONLY_IMAGE_MODELS:
            return False

    cache_result = _lookup_models_dev_cache_supports_vision(
        _PROVIDER_TO_MODELS_DEV.get(provider_id, provider_id),
        model.strip(),
    )
    if cache_result is not None:
        return cache_result
    return None


def _lookup_models_dev_cache_supports_vision(provider_id: str, model_id: str) -> bool | None:
    if not provider_id or not model_id:
        return None
    try:
        data = json.loads((Path.home() / ".hermes" / "models_dev_cache.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
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
            (item for item_id, item in models.items() if str(item_id).lower() == model_lower and isinstance(item, dict)),
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


def _correct_image_mode_for_provider(
    provider: str,
    model: str,
    cfg: dict[str, Any] | None,
    image_mode: str,
) -> str:
    provider_id = provider.strip().lower()
    configured_mode = _configured_image_input_mode(cfg)
    if configured_mode == "text":
        return "text"
    if configured_mode == "native":
        return "native"
    supports_vision = _lookup_model_supports_vision(provider, model)
    if supports_vision is True:
        return "native"
    if supports_vision is False:
        return "text"
    if provider_id != "xiaomi":
        return image_mode
    return image_mode


def _extract_vision_error(result: dict[str, Any]) -> str:
    for key in ("error", "message", "analysis", "detail"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "vision 预分析没有返回有效结果"


def _provider_api_key_names(provider: str) -> tuple[str, ...]:
    normalized = (provider or "").strip().lower()
    if not normalized:
        return ()
    return _PROVIDER_API_KEY_NAMES.get(normalized, (f"{normalized.upper().replace('-', '_')}_API_KEY",))


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


def _read_hermes_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    candidates = []
    env_path = os.environ.get("HERMES_ENV_FILE") or os.environ.get("HERMES_AGENT_ENV_FILE")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path.home() / ".hermes" / ".env")
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, raw_value = text.split("=", 1)
            values[key.strip()] = raw_value.strip().strip('"').strip("'")
        if values:
            break
    return values


def _configured_provider_api_key(provider: str) -> str:
    env_values: dict[str, str] | None = None
    for key in _provider_api_key_names(provider):
        value = os.environ.get(key, "").strip()
        if value:
            return value
        if env_values is None:
            env_values = _read_hermes_env_values()
        value = env_values.get(key, "").strip()
        if value:
            return value
    if (provider or "").strip().lower() == "openrouter":
        value = os.environ.get("AUTO_API_KEY", "").strip()
        if value:
            return value
        if env_values is None:
            env_values = _read_hermes_env_values()
        value = env_values.get("AUTO_API_KEY", "").strip()
        if value:
            return value
    return ""


def _text_attr(obj: Any, *names: str) -> str:
    for name in names:
        value = getattr(obj, name, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _resolve_auxiliary_provider_defaults(provider: str, model: str) -> dict[str, str]:
    try:
        from agent.auxiliary_client import resolve_provider_client

        client, resolved_model = resolve_provider_client(provider, model)
    except Exception:
        return {}
    return {
        "model": str(resolved_model or "").strip() or _text_attr(client, "model", "model_name"),
        "base_url": _text_attr(client, "base_url", "api_base", "api_base_url"),
        "api_key": _text_attr(client, "api_key", "key"),
    }


def _normalize_auxiliary_vision_model(provider: str, model: str) -> str:
    provider_id = (provider or "").strip().lower()
    model_id = (model or "").strip()
    if provider_id == "xiaomi":
        normalized = model_id.lower()
        if (
            not normalized
            or normalized in _XIAOMI_TEXT_ONLY_IMAGE_MODELS
        ):
            return _PREFERRED_AUXILIARY_VISION_MODELS["xiaomi"]
    return model_id


def _configured_auxiliary_vision_override() -> dict[str, str] | None:
    try:
        from hermes_cli.config import load_config
    except Exception:
        return None
    try:
        cfg = load_config()
    except Exception:
        return None
    if not isinstance(cfg, dict):
        return None
    auxiliary = cfg.get("auxiliary") if isinstance(cfg.get("auxiliary"), dict) else {}
    vision_cfg = auxiliary.get("vision") if isinstance(auxiliary.get("vision"), dict) else {}
    if not any(str(vision_cfg.get(key) or "").strip() for key in ("provider", "model", "base_url", "api_key")):
        return None

    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    chat_provider_raw = str(model_cfg.get("provider") or "").strip().lower()
    chat_model = str(model_cfg.get("default") or "").strip()
    chat_base_url = str(model_cfg.get("base_url") or "").strip()
    chat_provider = _effective_provider(chat_provider_raw, chat_base_url, chat_model) or chat_provider_raw
    vision_provider_raw = str(vision_cfg.get("provider") or "").strip().lower()
    model = str(vision_cfg.get("model") or "").strip() or chat_model
    base_url = str(vision_cfg.get("base_url") or "").strip()
    provider = (
        _effective_provider(
            vision_provider_raw,
            base_url or chat_base_url,
            model,
        )
        if vision_provider_raw
        else chat_provider
    )
    model = _normalize_auxiliary_vision_model(provider, model)
    api_key = str(vision_cfg.get("api_key") or "").strip()

    defaults = _resolve_auxiliary_provider_defaults(provider, model) if provider else {}
    model = _normalize_auxiliary_vision_model(provider, model or defaults.get("model", ""))
    base_url = base_url or defaults.get("base_url", "")
    if not base_url and provider == chat_provider:
        base_url = chat_base_url
    api_key = api_key or defaults.get("api_key", "") or _configured_provider_api_key(provider)

    missing = [
        label
        for label, value in (
            ("provider", provider),
            ("model", model),
            ("base_url", base_url),
            ("api_key", api_key),
        )
        if not value
    ]
    if missing:
        raise ImagePreprocessError(f"vision 链路配置不完整：缺少 {', '.join(missing)}")
    return {
        "model": model,
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
    }


def _configured_xiaomi_vision_override() -> dict[str, str] | None:
    """Use the user's Xiaomi base URL for Xiaomi text-model vision fallback.

    Some Xiaomi text models still need a dedicated multimodal model for
    pre-analysis.  Yachiyo's setup UI lets users choose a custom Xiaomi
    endpoint, so that path must inherit the endpoint or it can 401 while text
    chat still works.
    """
    try:
        from hermes_cli.config import load_config
    except Exception:
        return None
    try:
        cfg = load_config()
    except Exception:
        return None
    if not isinstance(cfg, dict):
        return None
    auxiliary = cfg.get("auxiliary") if isinstance(cfg.get("auxiliary"), dict) else {}
    vision_cfg = auxiliary.get("vision") if isinstance(auxiliary.get("vision"), dict) else {}
    vision_provider = str(vision_cfg.get("provider") or "").strip().lower()
    if (
        (vision_provider and vision_provider != "auto")
        or any(str(vision_cfg.get(key) or "").strip() for key in ("model", "base_url", "api_key"))
    ):
        return None
    model_cfg = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    provider_raw = str(model_cfg.get("provider") or "").strip().lower()
    chat_model = str(model_cfg.get("default") or "").strip()
    base_url = str(model_cfg.get("base_url") or "").strip()
    provider = _effective_provider(provider_raw, base_url, chat_model) or provider_raw
    if provider != "xiaomi" or _lookup_model_supports_vision(provider, chat_model) is True or not base_url:
        return None
    vision_model = _PREFERRED_AUXILIARY_VISION_MODELS["xiaomi"]
    try:
        from agent.auxiliary_client import resolve_provider_client

        client, _resolved = resolve_provider_client(provider, vision_model)
    except Exception:
        return None
    api_key = str(getattr(client, "api_key", "") or "").strip() if client is not None else ""
    if not api_key:
        return None
    return {
        "model": vision_model,
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
    }


async def _run_direct_vision_analysis(
    image_path: Path,
    prompt: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> str:
    from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning
    from tools.vision_tools import (
        _MAX_BASE64_BYTES,
        _RESIZE_TARGET_BYTES,
        _detect_image_mime_type,
        _image_to_base64_data_url,
        _is_image_size_error,
        _resize_image_for_vision,
    )

    mime_type = _detect_image_mime_type(image_path)
    if not mime_type:
        raise ValueError("Only real image files are supported for vision analysis.")
    image_data_url = _image_to_base64_data_url(image_path, mime_type=mime_type)
    if len(image_data_url) > _MAX_BASE64_BYTES:
        image_data_url = _resize_image_for_vision(image_path, mime_type=mime_type)
    if len(image_data_url) > _MAX_BASE64_BYTES:
        raise ValueError("Image too large for vision API after resizing.")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    call_kwargs = {
        "task": "vision",
        "provider": "custom",
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2000,
        "timeout": 120.0,
    }
    try:
        response = await async_call_llm(**call_kwargs)
    except Exception as exc:
        if _is_image_size_error(exc) and len(image_data_url) > _RESIZE_TARGET_BYTES:
            image_data_url = _resize_image_for_vision(image_path, mime_type=mime_type)
            messages[0]["content"][1]["image_url"]["url"] = image_data_url
            response = await async_call_llm(**call_kwargs)
        else:
            raise
    analysis = extract_content_or_reasoning(response).strip()
    if not analysis:
        response = await async_call_llm(**call_kwargs)
        analysis = extract_content_or_reasoning(response).strip()
    if not analysis:
        raise ValueError("vision API returned empty content")
    return analysis


def _run_vision_analysis(image_path: Path, prompt: str) -> str:
    override = _configured_auxiliary_vision_override() or _configured_xiaomi_vision_override()
    if override is not None:
        try:
            return asyncio.run(
                _run_direct_vision_analysis(
                    image_path,
                    prompt,
                    model=override["model"],
                    base_url=override["base_url"],
                    api_key=override["api_key"],
                )
            )
        except Exception as exc:
            raise ImagePreprocessError(f"{image_path.name} 分析失败：{exc}") from exc

    try:
        from tools.vision_tools import vision_analyze_tool
    except Exception as exc:
        raise ImagePreprocessError(f"vision 工具不可用：{exc}") from exc

    try:
        result_json = asyncio.run(
            vision_analyze_tool(image_url=str(image_path), user_prompt=prompt)
        )
    except Exception as exc:
        raise ImagePreprocessError(f"{image_path.name} 分析失败：{exc}") from exc

    try:
        result = json.loads(result_json)
    except json.JSONDecodeError as exc:
        raise ImagePreprocessError(f"{image_path.name} 返回了无法解析的 vision 结果") from exc
    if not isinstance(result, dict):
        raise ImagePreprocessError(f"{image_path.name} 返回了无效的 vision 结果")
    if not result.get("success"):
        raise ImagePreprocessError(f"{image_path.name} 分析失败：{_extract_vision_error(result)}")
    analysis = str(result.get("analysis") or "").strip()
    if not analysis:
        raise ImagePreprocessError(f"{image_path.name} 分析结果为空")
    return analysis


def _preprocess_images_with_vision(description: str, image_paths: list[Path]) -> str:
    prompt = (
        "请详细描述这张用户刚刚附加的图片。必须只根据图片内容回答，"
        "包括可见文字、人物/对象、界面布局、颜色和任何显著细节。"
    )
    parts: list[str] = []
    for index, image_path in enumerate(image_paths, start=1):
        analysis = _run_vision_analysis(image_path, prompt)
        parts.append(
            f"[Yachiyo 已预先分析第 {index} 张附件图片：\n{analysis}\n]"
        )
    return "\n\n".join(parts + [description])


def _route_images(cli: Any, description: str, image_paths: list[Path]) -> Any:
    if not image_paths:
        return description
    guarded_description = _with_attached_image_guard(description, image_paths)
    provider = str(getattr(cli, "provider", "") or "").strip()
    model = str(getattr(cli, "model", "") or "").strip()
    cfg: dict[str, Any] | None = None
    try:
        from agent.image_routing import build_native_content_parts, decide_image_input_mode
        from hermes_cli.config import load_config

        cfg = load_config()
        model_cfg = cfg.get("model") if isinstance(cfg, dict) and isinstance(cfg.get("model"), dict) else {}
        base_url = str(model_cfg.get("base_url") or "").strip()
        config_provider = str(model_cfg.get("provider") or "").strip()
        config_model = str(model_cfg.get("default") or "").strip()
        provider = _effective_provider(provider or config_provider, base_url, model or config_model) or provider
        model = model or config_model
        image_mode = decide_image_input_mode(
            provider,
            model,
            cfg,
        )
        image_mode = _correct_image_mode_for_provider(provider, model, cfg, image_mode)
    except Exception:
        image_mode = "text"

    if image_mode == "native":
        try:
            parts, skipped = build_native_content_parts(
                guarded_description,
                [str(path) for path in image_paths],
            )
            if any(part.get("type") == "image_url" for part in parts):
                if _is_debug_route_enabled() and skipped:
                    print(
                        f"[yachiyo-debug] skipped image paths={len(skipped)}",
                        file=sys.stderr,
                        flush=True,
                    )
                return parts
        except Exception as exc:
            if _is_debug_route_enabled():
                print(
                    f"[yachiyo-debug] native image routing failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    return _preprocess_images_with_vision(guarded_description, image_paths)


@contextlib.contextmanager
def _disable_agent_tools_for_image_turn(agent: Any, image_paths: list[Path]):
    if not image_paths or agent is None:
        yield
        return
    original_tools = getattr(agent, "tools", None)
    original_valid_tool_names = getattr(agent, "valid_tool_names", None)
    try:
        if hasattr(agent, "tools"):
            agent.tools = []
        if hasattr(agent, "valid_tool_names"):
            agent.valid_tool_names = set()
        yield
    finally:
        if hasattr(agent, "tools"):
            agent.tools = original_tools
        if hasattr(agent, "valid_tool_names"):
            agent.valid_tool_names = original_valid_tool_names


def _debug_route(route: Any) -> None:
    """按显式开关输出 route 结构，供开发者对比不同 provider 路径。

    只输出结构信息，不输出 value，避免泄漏 token、endpoint 或 request 配置。
    """
    if not _is_debug_route_enabled():
        return
    try:
        if route is None:
            print("[yachiyo-debug] route=None", file=sys.stderr, flush=True)
            return
        if isinstance(route, dict):
            print(
                f"[yachiyo-debug] route keys={list(route.keys())}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"[yachiyo-debug] route type={type(route).__name__}",
                file=sys.stderr,
                flush=True,
            )
    except Exception:
        pass


def _build_init_agent_kwargs(
    init_agent_fn: Any,
    *,
    model_override: Any,
    runtime_override: Any,
    route_label: Any,
    request_overrides: Any,
) -> dict[str, Any]:
    """运行时检查 _init_agent() 的签名，只传入函数实际接受的参数。

    Hermes 不同版本 / provider 路径下 _init_agent() 的签名并不稳定：
    - 某些版本支持 route_label 参数
    - 另一些版本不支持，直接传会引发 TypeError: unexpected keyword argument

    通过 inspect.signature 动态构建 kwargs，避免硬编码参数名与 Hermes 内部 API 绑定。
    """
    candidates: dict[str, Any] = {
        "model_override": model_override,
        "runtime_override": runtime_override,
        "route_label": route_label,
        "request_overrides": request_overrides,
    }

    try:
        sig = inspect.signature(init_agent_fn)
    except (ValueError, TypeError):
        # 获取签名失败时保守处理：只传最基础的两个参数
        return {
            "model_override": model_override,
            "runtime_override": runtime_override,
        }

    # 部分 Hermes 版本使用 **kwargs，此时所有候选均可传
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )
    if has_var_keyword:
        return {k: v for k, v in candidates.items() if v is not None}

    accepted = set(sig.parameters.keys())
    return {k: v for k, v in candidates.items() if k in accepted}


def _run(payload: dict[str, Any]) -> int:
    description = str(payload.get("description") or "")
    image_paths = _collect_image_paths(payload)
    resume = payload.get("resume")
    resume = resume if isinstance(resume, str) and resume else None
    if not description.strip() and not image_paths:
        _emit("error", message="消息内容不能为空")
        return 2
    if not description.strip() and image_paths:
        description = "What do you see in this image?"

    os.environ["HERMES_INTERACTIVE"] = "1"

    # Import inside redirected stdout because Hermes imports/config loading may print.
    with contextlib.redirect_stdout(sys.stderr):
        from cli import CLI_CONFIG, HermesCLI

        cli = HermesCLI(
            toolsets=_resolve_toolsets(CLI_CONFIG),
            verbose=False,
            compact=True,
            resume=resume,
        )
        cli.tool_progress_mode = "off"
        cli.streaming_enabled = False

        if not cli._ensure_runtime_credentials():
            _emit("error", message="Hermes runtime credentials are not available")
            return 1

        route = cli._resolve_turn_agent_config(description)

        # 诊断日志：记录 route 的完整结构，帮助对比 provider 路径差异
        _debug_route(route)

        # 防御式解析：_resolve_turn_agent_config 在不同 provider/api_mode（如
        # Nous Portal、MiMo 等）下返回的 dict 可能缺少 "label"、"model"、
        # "runtime"、"signature" 等字段，不能假定全部存在。
        if not isinstance(route, dict):
            _emit(
                "error",
                message=(
                    f"Hermes agent 路由配置类型不符（期望 dict，实际 {type(route).__name__}）"
                ),
            )
            return 1

        route_sig = route.get("signature")
        if route_sig != cli._active_agent_route_signature:
            cli.agent = None

        # label 字段在部分 provider 路径下可能不存在，此处安全降级为 None。
        route_label = route.get("label")

        # 使用签名检查构建 kwargs，避免向旧版 Hermes _init_agent 传入它不认识的参数
        init_kwargs = _build_init_agent_kwargs(
            cli._init_agent,
            model_override=route.get("model"),
            runtime_override=route.get("runtime"),
            route_label=route_label,
            request_overrides=route.get("request_overrides"),
        )
        if _is_debug_route_enabled():
            print(
                "[yachiyo-debug] _init_agent kwargs="
                f"{list(init_kwargs.keys())}, route_label_present={route_label is not None}",
                file=sys.stderr,
                flush=True,
            )
        try:
            ok = cli._init_agent(**init_kwargs)
        except TypeError as exc:
            # 签名检测失败兜底：去掉 route_label 后再试一次
            fallback_kwargs = {
                k: v for k, v in init_kwargs.items() if k != "route_label"
            }
            try:
                ok = cli._init_agent(**fallback_kwargs)
                if _is_debug_route_enabled():
                    print(
                        "[yachiyo-debug] _init_agent fallback succeeded "
                        "(removed route_label)",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc2:
                _emit(
                    "error",
                    message=f"Hermes agent 初始化参数不兼容（{exc2}）",
                )
                return 1
        except Exception as exc:
            _emit(
                "error",
                message=f"Hermes agent 初始化失败（{type(exc).__name__}）",
            )
            return 1

        if not ok:
            _emit("error", message="Hermes agent 初始化失败")
            return 1

        cli.agent.quiet_mode = True
        cli.agent.suppress_status_output = True
        try:
            description_for_agent = _route_images(cli, description, image_paths)
        except ImagePreprocessError as exc:
            _emit("error", message=f"图片预分析失败：{exc}")
            return 1

        def on_delta(delta: Any) -> None:
            if delta is None:
                _emit("boundary")
                return
            if not isinstance(delta, str):
                delta = str(delta)
            if delta:
                _emit("delta", delta=delta)

        with _disable_agent_tools_for_image_turn(cli.agent, image_paths):
            result = cli.agent.run_conversation(
                user_message=description_for_agent,
                conversation_history=cli.conversation_history,
                stream_callback=on_delta,
                task_id=cli.session_id,
                persist_user_message=description if image_paths else None,
            )

    if isinstance(result, dict):
        response = _detail_text(result.get("final_response"), drop_empty_literals=False)
        failed = bool(result.get("failed"))
        error = _failure_message_from_result(result) if failed else ""
    else:
        response = _detail_text(result)
        failed = False
        error = ""

    done_payload: dict[str, Any] = {
        "response": response,
        "session_id": getattr(cli, "session_id", None),
        "title": _get_session_title(cli, getattr(cli, "session_id", "")),
        "failed": failed,
    }
    if error:
        done_payload["error"] = error
    _emit("done", **done_payload)
    return 1 if failed else 0


def main() -> int:
    try:
        payload = _read_payload()
        return _run(payload)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit("error", message=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
