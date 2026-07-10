"""Credential handling for external desktop providers."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
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
    token_file = str(
        payload.get("token_file") or auth.get("token_file") or ""
    ).strip()
    if token_file:
        return desktop_provider_token_from_file(token_file)
    token_env = str(payload.get("token_env") or auth.get("token_env") or "").strip()
    if not token_env:
        return ""
    source = environment if environment is not None else os.environ
    return str(source.get(token_env) or "").strip()


def desktop_provider_token_from_file(token_file: str | Path) -> str:
    """Read a provider token from an owner-only regular file."""

    path = Path(token_file).expanduser()
    if not path.is_absolute():
        raise ValueError("desktop provider token file path must be absolute")
    if path.is_symlink():
        raise ValueError("desktop provider token file must not be a symlink")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ValueError("desktop provider token file is not readable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("desktop provider token file must be a regular file")
        if file_stat.st_uid != os.getuid():
            raise ValueError("desktop provider token file must be owned by this user")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise ValueError("desktop provider token file permissions must be 0600")
        if file_stat.st_size > 16_384:
            raise ValueError("desktop provider token file is too large")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            token = handle.read(16_385).strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("desktop provider token file is not readable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not token:
        raise ValueError("desktop provider token file is empty")
    if len(token) > 16_384:
        raise ValueError("desktop provider token file is too large")
    if "\n" in token or "\r" in token:
        raise ValueError("desktop provider token file must contain one token")
    return token


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
    "desktop_provider_token_from_file",
    "desktop_provider_token_from_manifest",
    "public_desktop_provider_env",
]
