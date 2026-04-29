"""Headless Hermes-Yachiyo backend for the Electron desktop shell.

This process owns Python runtime state and the internal HTTP bridge. It does not
create desktop windows; Electron owns all UI surfaces.
"""

from __future__ import annotations

import logging
import signal
import sys


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    _setup_logging()

    from apps.bridge.deps import set_runtime
    from apps.bridge.server import start_bridge, stop_bridge
    from apps.core.runtime import HermesRuntime
    from apps.installer.hermes_check import check_hermes_installation
    from apps.shell.config import load_config

    config = load_config()
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
        start_bridge(host=config.bridge_host, port=config.bridge_port)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
