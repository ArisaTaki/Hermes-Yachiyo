"""Provider model catalog synchronization.

This module keeps volatile provider model metadata out of source code.  It can
be run manually or by a future daily scheduler, then model profile flows can use
the cache as a hint while still relying on real connection tests for final
availability.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from apps.core.tls import urlopen_with_bundled_ca
from apps.shell.model_provider_adapters import (
    NATIVE_PROVIDER_API_KEY_NAMES,
    NATIVE_PROVIDER_LABELS,
    resolve_provider_adapter,
)
from packages.security import redact_api_error_text

CACHE_SCHEMA = 1
CACHE_FILE_NAME = "provider-capabilities.json"
DEFAULT_STALE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ProviderCatalogAdapter:
    provider: str
    label: str
    base_url: str
    models_path: str = "/models"
    requires_api_key: bool = True
    api_key_names: tuple[str, ...] = ()
    enabled_by_default: bool = True


DEFAULT_PROVIDER_CATALOG_ADAPTERS: tuple[ProviderCatalogAdapter, ...] = (
    ProviderCatalogAdapter("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", requires_api_key=False),
    ProviderCatalogAdapter("openai", "OpenAI", "https://api.openai.com/v1"),
    ProviderCatalogAdapter("xiaomi", "Xiaomi MiMo", "https://api.mimo-v2.com/v1"),
    ProviderCatalogAdapter("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ProviderCatalogAdapter("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ProviderCatalogAdapter("alibaba", "阿里云百炼 / Qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ProviderCatalogAdapter("kimi-coding", "Moonshot / Kimi", "https://api.moonshot.ai/v1"),
    ProviderCatalogAdapter("zai", "智谱 GLM / Z.AI", "https://open.bigmodel.cn/api/paas/v4"),
    ProviderCatalogAdapter("minimax", "MiniMax", "https://api.minimax.io/v1"),
    ProviderCatalogAdapter("stepfun", "阶跃星辰 StepFun", "https://api.stepfun.com/v1"),
    ProviderCatalogAdapter("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
    ProviderCatalogAdapter("xai", "xAI", "https://api.x.ai/v1"),
    ProviderCatalogAdapter("huggingface", "Hugging Face", "https://router.huggingface.co/v1"),
    ProviderCatalogAdapter("lmstudio", "LM Studio", "http://127.0.0.1:1234/v1", requires_api_key=False, enabled_by_default=False),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oha_yachiyo_home() -> Path:
    root = Path(os.getenv("OHA_YACHIYO_HOME", os.path.expanduser("~/.oha-yachiyo")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_provider_catalog_cache_path() -> Path:
    return _oha_yachiyo_home() / CACHE_FILE_NAME


def _adapter_map() -> dict[str, ProviderCatalogAdapter]:
    return {adapter.provider: adapter for adapter in DEFAULT_PROVIDER_CATALOG_ADAPTERS}


def list_provider_catalog_adapters() -> list[dict[str, Any]]:
    adapters = []
    for adapter in DEFAULT_PROVIDER_CATALOG_ADAPTERS:
        adapters.append(
            {
                "provider": adapter.provider,
                "label": adapter.label,
                "base_url": adapter.base_url,
                "models_path": adapter.models_path,
                "requires_api_key": adapter.requires_api_key,
                "api_key_names": list(_api_key_names(adapter)),
                "enabled_by_default": adapter.enabled_by_default,
            }
        )
    return adapters


def _api_key_names(adapter: ProviderCatalogAdapter) -> tuple[str, ...]:
    if adapter.api_key_names:
        return adapter.api_key_names
    return tuple(NATIVE_PROVIDER_API_KEY_NAMES.get(adapter.provider, ()))


def _configured_api_key(adapter: ProviderCatalogAdapter) -> tuple[str, str]:
    for name in _api_key_names(adapter):
        value = os.getenv(name, "").strip()
        if value:
            return name, value
    return "", ""


def _auth_headers(base_url: str, api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if not api_key:
        return headers
    headers["Authorization"] = f"Bearer {api_key}"
    host = (urlparse(base_url or "").hostname or "").lower()
    if host == "mimo-v2.com" or host.endswith(".mimo-v2.com") or host == "xiaomimimo.com" or host.endswith(".xiaomimimo.com"):
        headers["api-key"] = api_key
    return headers


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _pricing_is_free(pricing: dict[str, Any]) -> bool:
    if not pricing:
        return False
    try:
        return float(str(pricing.get("prompt", "0") or "0")) == 0 and float(str(pricing.get("completion", "0") or "0")) == 0
    except ValueError:
        return False


def _provider_key(model_id: str, owned_by: str, fallback_provider: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lstrip("~")
    if owned_by:
        return owned_by.strip().lstrip("~")
    return fallback_provider.strip().lstrip("~")


def _model_supports_vision(model: dict[str, Any]) -> bool | None:
    input_modalities = {str(item).strip().lower() for item in model.get("input_modalities", []) if str(item).strip()}
    modality = str(model.get("modality") or "").strip().lower()
    if "image" in input_modalities or "vision" in modality or "multimodal" in modality:
        return True
    if input_modalities and input_modalities <= {"text", "file", "audio", "video"}:
        return False
    return None


def normalize_provider_models(payload: Any, *, provider: str, source_url: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_models = payload.get("data")
        if raw_models is None:
            raw_models = payload.get("models")
    else:
        raw_models = payload
    if not isinstance(raw_models, list):
        raise ValueError("模型列表响应格式无法识别")

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_models:
        if isinstance(item, str):
            model_id = item.strip()
            owned_by = ""
            display_name = ""
            model_info: dict[str, Any] = {}
        elif isinstance(item, dict):
            display_name = str(item.get("name") or "").strip()
            model_id = str(item.get("id") or item.get("model") or display_name or "").strip()
            owned_by = str(item.get("owned_by") or item.get("owner") or "").strip()
            architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
            top_provider = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
            model_info = {
                "canonical_slug": str(item.get("canonical_slug") or "").strip(),
                "context_length": _as_int(item.get("context_length")) or _as_int(top_provider.get("context_length")),
                "default_parameters": item.get("default_parameters") if isinstance(item.get("default_parameters"), dict) else {},
                "description": str(item.get("description") or "").strip(),
                "input_modalities": _as_string_list(architecture.get("input_modalities")),
                "is_free": _pricing_is_free(pricing) if pricing else None,
                "is_moderated": bool(top_provider.get("is_moderated")) if "is_moderated" in top_provider else None,
                "max_completion_tokens": _as_int(top_provider.get("max_completion_tokens")),
                "modality": str(architecture.get("modality") or "").strip(),
                "name": display_name,
                "output_modalities": _as_string_list(architecture.get("output_modalities")),
                "pricing": pricing,
                "supported_parameters": _as_string_list(item.get("supported_parameters")),
            }
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model = {
            "id": model_id,
            "owned_by": owned_by,
            "provider_key": _provider_key(model_id, owned_by, provider),
            "source_url": source_url,
        }
        for key, value in model_info.items():
            if value not in ("", None, [], {}):
                model[key] = value
        supports_vision = _model_supports_vision(model)
        model["capability_hint"] = {
            "supports_vision": supports_vision,
            "confidence": "provider_catalog" if supports_vision is not None else "unknown",
        }
        models.append(model)
    return models


def _fetch_adapter_models(adapter: ProviderCatalogAdapter, *, timeout: float) -> dict[str, Any]:
    api_key_name, api_key = _configured_api_key(adapter)
    if adapter.requires_api_key and not api_key:
        return {
            "provider": adapter.provider,
            "label": adapter.label,
            "base_url": adapter.base_url,
            "status": "skipped",
            "error": "未配置 API Key 环境变量",
            "api_key_names": list(_api_key_names(adapter)),
            "models": [],
            "count": 0,
            "synced_at": _now(),
        }

    base_url = adapter.base_url.rstrip("/")
    models_url = f"{base_url}{adapter.models_path}"
    request = urlrequest.Request(models_url, method="GET", headers=_auth_headers(base_url, api_key))
    started = time.time()
    with urlopen_with_bundled_ca(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = normalize_provider_models(payload, provider=adapter.provider, source_url=models_url)
    return {
        "provider": adapter.provider,
        "label": adapter.label,
        "base_url": adapter.base_url,
        "status": "ok",
        "error": "",
        "api_key_name": api_key_name,
        "api_key_configured": bool(api_key),
        "models": models,
        "count": len(models),
        "latency_ms": int((time.time() - started) * 1000),
        "synced_at": _now(),
    }


def load_provider_catalog_cache(cache_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(cache_path) if cache_path is not None else default_provider_catalog_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": CACHE_SCHEMA, "generated_at": "", "providers": {}}
    if not isinstance(payload, dict):
        return {"schema": CACHE_SCHEMA, "generated_at": "", "providers": {}}
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        payload["providers"] = {}
    payload.setdefault("schema", CACHE_SCHEMA)
    payload.setdefault("generated_at", "")
    return payload


def save_provider_catalog_cache(payload: dict[str, Any], cache_path: Path | str | None = None) -> Path:
    path = Path(cache_path) if cache_path is not None else default_provider_catalog_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _cache_is_fresh(cache: dict[str, Any], max_age_seconds: int) -> bool:
    generated_at = str(cache.get("generated_at") or "")
    if not generated_at:
        return False
    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - generated).total_seconds() < max_age_seconds


def sync_provider_catalogs(
    *,
    providers: list[str] | None = None,
    cache_path: Path | str | None = None,
    timeout: float = 20.0,
    if_stale: bool = False,
    max_age_seconds: int = DEFAULT_STALE_SECONDS,
) -> dict[str, Any]:
    cache = load_provider_catalog_cache(cache_path)
    if if_stale and _cache_is_fresh(cache, max_age_seconds):
        return {
            "ok": True,
            "skipped": True,
            "reason": "cache_fresh",
            "cache_path": str(Path(cache_path) if cache_path is not None else default_provider_catalog_cache_path()),
            "cache": cache,
        }

    requested = {provider.strip().lower() for provider in (providers or []) if provider.strip()}
    adapters = [
        adapter
        for adapter in DEFAULT_PROVIDER_CATALOG_ADAPTERS
        if (not requested and adapter.enabled_by_default) or adapter.provider in requested
    ]
    adapter_by_id = _adapter_map()
    for provider in sorted(requested):
        if provider not in adapter_by_id:
            adapters.append(
                ProviderCatalogAdapter(
                    provider=provider,
                    label=NATIVE_PROVIDER_LABELS.get(provider, provider),
                    base_url="",
                    requires_api_key=True,
                    enabled_by_default=False,
                )
            )

    results: dict[str, Any] = {}
    previous_providers = cache.get("providers") if isinstance(cache.get("providers"), dict) else {}
    next_providers = dict(previous_providers)
    for adapter in adapters:
        if not adapter.base_url:
            results[adapter.provider] = {
                "provider": adapter.provider,
                "status": "skipped",
                "error": "没有内置模型目录 Base URL",
                "models": [],
                "count": 0,
                "synced_at": _now(),
            }
            continue
        try:
            result = _fetch_adapter_models(adapter, timeout=timeout)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError, urlerror.URLError) as exc:
            result = {
                "provider": adapter.provider,
                "label": adapter.label,
                "base_url": adapter.base_url,
                "status": "failed",
                "error": redact_api_error_text(exc),
                "models": [],
                "count": 0,
                "synced_at": _now(),
            }
        results[adapter.provider] = result
        if result.get("status") == "ok":
            next_providers[adapter.provider] = result
        elif adapter.provider not in next_providers:
            next_providers[adapter.provider] = result

    payload = {
        "schema": CACHE_SCHEMA,
        "generated_at": _now(),
        "providers": next_providers,
    }
    path = save_provider_catalog_cache(payload, cache_path)
    ok_count = sum(1 for result in results.values() if result.get("status") == "ok")
    return {
        "ok": ok_count > 0 or not results,
        "cache_path": str(path),
        "generated_at": payload["generated_at"],
        "providers": results,
        "provider_count": len(results),
        "ok_count": ok_count,
    }


def cached_provider_models(
    provider: str,
    *,
    base_url: str = "",
    cache_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    adapter = resolve_provider_adapter(provider, base_url)
    provider_id = str(adapter.get("native_provider") or provider or "").strip().lower()
    cache = load_provider_catalog_cache(cache_path)
    providers = cache.get("providers")
    if not isinstance(providers, dict):
        return []
    provider_payload = providers.get(provider_id)
    if not isinstance(provider_payload, dict):
        return []
    models = provider_payload.get("models")
    if not isinstance(models, list):
        return []
    return [model for model in models if isinstance(model, dict) and str(model.get("id") or "").strip()]


def cached_model_metadata(
    provider: str,
    model_id: str,
    *,
    base_url: str = "",
    cache_path: Path | str | None = None,
) -> dict[str, Any]:
    clean_model_id = (model_id or "").strip()
    if not clean_model_id:
        return {}
    model_lower = clean_model_id.lower()
    for model in cached_provider_models(provider, base_url=base_url, cache_path=cache_path):
        candidate = str(model.get("id") or "").strip()
        if candidate.lower() == model_lower:
            return dict(model)
    return {}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync provider model capability catalogs.")
    parser.add_argument("--provider", action="append", default=[], help="Provider id to sync. Can be repeated.")
    parser.add_argument("--cache-path", default="", help="Override cache JSON path.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument("--if-stale", action="store_true", help="Skip sync if cache is newer than max age.")
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--list-providers", action="store_true", help="Print supported sync adapters and exit.")
    args = parser.parse_args(argv)

    if args.list_providers:
        print(json.dumps({"providers": list_provider_catalog_adapters()}, ensure_ascii=False, indent=2))
        return 0

    providers: list[str] = []
    for value in args.provider:
        providers.extend(part.strip() for part in value.split(",") if part.strip())
    result = sync_provider_catalogs(
        providers=providers or None,
        cache_path=args.cache_path or None,
        timeout=args.timeout,
        if_stale=args.if_stale,
        max_age_seconds=args.max_age_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
