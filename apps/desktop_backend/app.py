"""Headless Hermes-Yachiyo backend for the Electron desktop shell.

This process owns Python runtime state and the internal HTTP bridge. It does not
create desktop windows; Electron owns all UI surfaces.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from urllib.parse import urlparse

DEV_BRIDGE_HOST = "127.0.0.1"
DEV_BRIDGE_PORT = 8420
PACKAGED_BRIDGE_PORT = 18420


def _running_from_packaged_backend() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bridge_endpoint_from_env(config: object) -> tuple[str, int]:
    bridge_url = os.getenv("HERMES_YACHIYO_BRIDGE_URL", "").strip()
    if bridge_url:
        parsed = urlparse(bridge_url)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if parsed.scheme == "http" and parsed.hostname and port:
            if port == PACKAGED_BRIDGE_PORT and not _running_from_packaged_backend():
                return DEV_BRIDGE_HOST, DEV_BRIDGE_PORT
            return parsed.hostname, port
        logging.getLogger(__name__).warning(
            "忽略无效 HERMES_YACHIYO_BRIDGE_URL=%r，使用保存的 Bridge 配置",
            bridge_url,
        )
    return (
        str(getattr(config, "bridge_host", DEV_BRIDGE_HOST)),
        int(getattr(config, "bridge_port", DEV_BRIDGE_PORT)),
    )


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    _setup_logging()
    os.environ["HERMES_YACHIYO_DESKTOP_BACKEND"] = "1"

    from apps.core.tls import install_bundled_ca_env

    install_bundled_ca_env()

    from apps.bridge.deps import set_runtime
    from apps.bridge.server import start_bridge, stop_bridge
    from apps.core.activity_store import close_activity_store
    from apps.core.chat_store import close_chat_store
    from apps.core.runtime import HermesRuntime
    from apps.installer.hermes_check import check_hermes_installation
    from apps.shell.config import load_config

    config = load_config()
    bridge_host, bridge_port = _bridge_endpoint_from_env(config)
    config.bridge_host = bridge_host
    config.bridge_port = bridge_port
    install_info = check_hermes_installation()
    runtime = HermesRuntime(config)
    runtime.start(install_info=install_info)
    set_runtime(runtime)

    def _shutdown(_signum: int, _frame: object) -> None:
        stop_bridge()
        runtime.stop()
        close_chat_store()
        close_activity_store()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        start_bridge(host=bridge_host, port=bridge_port)
    finally:
        runtime.stop()
        close_chat_store()
        close_activity_store()


if __name__ == "__main__":
    main()
