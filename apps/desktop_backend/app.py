"""Headless Oha-Yachiyo backend for the Electron desktop shell.

This process owns Python runtime state and the internal HTTP bridge. It does not
create desktop windows; Electron owns all UI surfaces.
"""

from __future__ import annotations

import logging
import os
import secrets
import signal
import sys
from urllib.parse import urlparse

DEV_BRIDGE_HOST = "127.0.0.1"
DEV_BRIDGE_PORT = 8420
PACKAGED_BRIDGE_PORT = 18420
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_BRIDGE_TOKEN_ENV = "OHA_YACHIYO_BRIDGE_TOKEN"


def _running_from_packaged_backend() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bridge_endpoint_from_env(config: object) -> tuple[str, int]:
    bridge_url = os.getenv("OHA_YACHIYO_BRIDGE_URL", "").strip()
    if bridge_url:
        parsed = urlparse(bridge_url)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if parsed.scheme == "http" and parsed.hostname and port:
            if parsed.hostname not in _LOOPBACK_HOSTS:
                logging.getLogger(__name__).warning(
                    "拒绝非回环 Bridge host=%r，使用 127.0.0.1",
                    parsed.hostname,
                )
                return DEV_BRIDGE_HOST, port
            if port == PACKAGED_BRIDGE_PORT and not _running_from_packaged_backend():
                return DEV_BRIDGE_HOST, DEV_BRIDGE_PORT
            return parsed.hostname, port
        logging.getLogger(__name__).warning(
            "忽略无效 OHA_YACHIYO_BRIDGE_URL=%r，使用保存的 Bridge 配置",
            bridge_url,
        )
    configured_host = str(getattr(config, "bridge_host", DEV_BRIDGE_HOST))
    return (
        configured_host if configured_host in _LOOPBACK_HOSTS else DEV_BRIDGE_HOST,
        int(getattr(config, "bridge_port", DEV_BRIDGE_PORT)),
    )


def _setup_logging() -> None:
    from packages.security import install_logging_secret_redaction, install_secret_excepthook

    install_logging_secret_redaction()
    install_secret_excepthook()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _ensure_bridge_session_token() -> bool:
    """Ensure mutating Bridge routes require a local session token.

    Electron normally injects the token before spawning this process.  When the
    backend is launched directly as a desktop backend, generate an ephemeral
    process-local token instead of leaving mutating endpoints unauthenticated.
    The token itself is intentionally never logged.
    """
    if os.getenv(_BRIDGE_TOKEN_ENV, "").strip():
        return False
    os.environ[_BRIDGE_TOKEN_ENV] = secrets.token_urlsafe(32)
    return True


def main() -> None:
    _setup_logging()
    os.environ["OHA_YACHIYO_DESKTOP_BACKEND"] = "1"
    generated_bridge_token = _ensure_bridge_session_token()
    if generated_bridge_token:
        logging.getLogger(__name__).info("Bridge 会话 token 未注入，已生成临时本地 token")

    from apps.core.tls import install_bundled_ca_env

    install_bundled_ca_env()

    from apps.bridge.deps import set_runtime
    from apps.bridge.server import start_bridge, stop_bridge
    from apps.core.activity_store import close_activity_store
    from apps.core.chat_store import close_chat_store
    from apps.core.runtime import AppRuntime
    from apps.shell.agent_runtime import close_agent_runtime_service
    from apps.shell.config import load_config
    from apps.shell.model_profiles import close_model_profile_service

    config = load_config()
    bridge_host, bridge_port = _bridge_endpoint_from_env(config)
    config.bridge_host = bridge_host
    config.bridge_port = bridge_port
    runtime = AppRuntime(config)
    runtime.start()
    set_runtime(runtime)

    def _shutdown(_signum: int, _frame: object) -> None:
        stop_bridge()
        runtime.stop()
        close_agent_runtime_service()
        close_model_profile_service()
        close_chat_store()
        close_activity_store()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        start_bridge(host=bridge_host, port=bridge_port)
    finally:
        runtime.stop()
        close_agent_runtime_service()
        close_model_profile_service()
        close_chat_store()
        close_activity_store()


if __name__ == "__main__":
    main()
