"""Credential handling for external desktop providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


DESKTOP_PROVIDER_TOKEN_ENV = "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN"
DESKTOP_PROVIDER_SECRET_ENV_KEYS = frozenset(
    {
        DESKTOP_PROVIDER_TOKEN_ENV,
        "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_TOKEN",
    }
)


def desktop_provider_token_from_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Resolve a provider token without exposing it in contract evidence."""

    payload = manifest if isinstance(manifest, Mapping) else {}
    authentication = payload.get("authentication")
    auth = authentication if isinstance(authentication, Mapping) else {}
    direct = str(payload.get("token") or auth.get("token") or "").strip()
    if direct:
        return direct
    token_env = str(payload.get("token_env") or auth.get("token_env") or "").strip()
    if not token_env:
        return ""
    source = environment if environment is not None else os.environ
    return str(source.get(token_env) or "").strip()


def public_desktop_provider_env(
    environment: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return provider environment metadata with credential values omitted."""

    if not isinstance(environment, Mapping):
        return {}
    return {
        str(key): str(value)
        for key, value in environment.items()
        if str(key).strip()
        and str(key).strip() not in DESKTOP_PROVIDER_SECRET_ENV_KEYS
    }


__all__ = [
    "DESKTOP_PROVIDER_SECRET_ENV_KEYS",
    "DESKTOP_PROVIDER_TOKEN_ENV",
    "desktop_provider_token_from_manifest",
    "public_desktop_provider_env",
]
