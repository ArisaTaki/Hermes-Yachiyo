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


def _bridge_endpoint_from_env(config: object) -> tuple[str, int]:
    bridge_url = os.getenv("HERMES_YACHIYO_BRIDGE_URL", "").strip()
    if bridge_url:
        parsed = urlparse(bridge_url)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if parsed.scheme == "http" and parsed.hostname and port:
            return parsed.hostname, port
        logging.getLogger(__name__).warning(
            "忽略无效 HERMES_YACHIYO_BRIDGE_URL=%r，使用保存的 Bridge 配置",
            bridge_url,
        )
    return (
        str(getattr(config, "bridge_host", "127.0.0.1")),
        int(getattr(config, "bridge_port", 8420)),
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

    from apps.bridge.deps import set_runtime
    from apps.bridge.server import start_bridge, stop_bridge
    from apps.core.runtime import HermesRuntime
    from apps.installer.hermes_check import check_hermes_installation
    from apps.shell.config import load_config

    config = load_config()
    bridge_host, bridge_port = _bridge_endpoint_from_env(config)
    install_info = check_hermes_installation()
    runtime = HermesRuntime(config)
    runtime.start(install_info=install_info)
    set_runtime(runtime)

    def _shutdown(_signum: int, _frame: object) -> None:
        stop_bridge()
        runtime.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        start_bridge(host=bridge_host, port=bridge_port)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
