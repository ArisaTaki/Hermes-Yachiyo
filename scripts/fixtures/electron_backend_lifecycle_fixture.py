#!/usr/bin/env python3
"""Lightweight backend fixture for the Electron single-instance smoke."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.runtime.runtime_instance_lock import RuntimeProcessInstanceLock  # noqa: E402

try:
    from apps.desktop_backend.parent_watchdog import start_electron_parent_watchdog  # noqa: E402
except ImportError:
    start_electron_parent_watchdog = None  # type: ignore[assignment]


SMOKE_MODE_ENV = "OHA_YACHIYO_DESKTOP_SMOKE_MODE"
SMOKE_LEDGER_ENV = "OHA_YACHIYO_ELECTRON_SMOKE_LEDGER"
PARENT_PID_ENV = "OHA_YACHIYO_ELECTRON_PARENT_PID"
PARENT_TOKEN_ENV = "OHA_YACHIYO_ELECTRON_PARENT_TOKEN"
LOCK_DELAY_ENV = "OHA_YACHIYO_ELECTRON_SMOKE_LOCK_DELAY_MS"


def _parent_pid() -> int | None:
    try:
        value = int(str(os.environ.get(PARENT_PID_ENV) or "").strip())
    except ValueError:
        return None
    return value if value > 1 else None


def _record(event: str, **details: Any) -> None:
    if os.environ.get(SMOKE_MODE_ENV) != "1":
        return
    ledger_value = str(os.environ.get(SMOKE_LEDGER_ENV) or "").strip()
    if not ledger_value:
        return
    ledger_path = Path(ledger_value)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    parent_token = str(os.environ.get(PARENT_TOKEN_ENV) or "")
    payload = {
        "event": event,
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "source": "backend-fixture",
        "parent_pid": _parent_pid(),
        "parent_token_hash": hashlib.sha256(parent_token.encode()).hexdigest()[:16],
        **details,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(
        ledger_path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def main() -> int:
    shutdown_requested = threading.Event()

    def _shutdown(_signum: int, _frame: object) -> None:
        shutdown_requested.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    watchdog = (
        start_electron_parent_watchdog(interval_seconds=0.1)
        if start_electron_parent_watchdog is not None
        else None
    )
    oha_home = Path(os.environ.get("OHA_YACHIYO_HOME") or Path.home() / ".oha-yachiyo")
    runtime_lock = RuntimeProcessInstanceLock(
        db_path=oha_home / "electron-single-instance-smoke.db",
        workspace_dir=oha_home,
    )
    try:
        lock_delay_seconds = min(
            5.0,
            max(0.0, int(str(os.environ.get(LOCK_DELAY_ENV) or "0")) / 1000),
        )
    except ValueError:
        lock_delay_seconds = 0.0
    lock_acquired = False
    _record(
        "backend.watchdog-ready",
        lock_acquired=False,
        watchdog_enabled=watchdog is not None,
    )
    try:
        if lock_delay_seconds and shutdown_requested.wait(lock_delay_seconds):
            return 0
        if not runtime_lock.acquire():
            _record("backend.lock-failed")
            return 73
        lock_acquired = True
        _record(
            "backend.ready",
            watchdog_enabled=watchdog is not None,
            runtime_lock=str(runtime_lock.path),
        )
        while not shutdown_requested.wait(0.1):
            pass
    finally:
        if watchdog is not None:
            watchdog.stop()
        if lock_acquired:
            runtime_lock.release()
        _record("backend.exit", runtime_lock_acquired=lock_acquired)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
