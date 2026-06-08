"""TLS helpers for packaged HTTP clients."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.parse import urlparse


def bundled_ca_file() -> str | None:
    """Return the bundled certifi CA bundle path when it is available."""
    try:
        import certifi
    except Exception:
        return None
    try:
        ca_path = Path(certifi.where())
    except Exception:
        return None
    return str(ca_path) if ca_path.exists() else None


def install_bundled_ca_env() -> str | None:
    ca_file = bundled_ca_file()
    if not ca_file:
        return None
    os.environ.setdefault("SSL_CERT_FILE", ca_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)
    return ca_file


def ssl_context_for_url(url: str) -> ssl.SSLContext | None:
    if urlparse(url).scheme.lower() != "https":
        return None
    ca_file = install_bundled_ca_env()
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()


def urlopen_with_bundled_ca(request: Any, *, timeout: float | None = None) -> Any:
    url = getattr(request, "full_url", str(request))
    context = ssl_context_for_url(str(url))
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if context is not None:
        kwargs["context"] = context
    return urlrequest.urlopen(request, **kwargs)
