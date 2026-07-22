"""Exit the desktop backend when its owning Electron process disappears."""

from __future__ import annotations

import json
import logging
import os
import signal
import stat
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

ELECTRON_PARENT_PID_ENV = "OHA_YACHIYO_ELECTRON_PARENT_PID"
ELECTRON_PARENT_TOKEN_ENV = "OHA_YACHIYO_ELECTRON_PARENT_TOKEN"
ELECTRON_SMOKE_LEDGER_ENV = "OHA_YACHIYO_ELECTRON_SMOKE_LEDGER"
DESKTOP_SMOKE_MODE_ENV = "OHA_YACHIYO_DESKTOP_SMOKE_MODE"
DEFAULT_INTERVAL_SECONDS = 0.5


def _configured_parent_pid() -> int | None:
    try:
        value = int(str(os.environ.get(ELECTRON_PARENT_PID_ENV) or "").strip())
    except ValueError:
        return None
    return value if value > 1 else None


def _configured_parent_token() -> str:
    return str(os.environ.get(ELECTRON_PARENT_TOKEN_ENV) or "").strip()


def _posix_parent_is_alive(
    expected_parent_pid: int,
    *,
    get_parent_pid: Callable[[], int] = os.getppid,
    signal_process: Callable[[int, int], None] = os.kill,
) -> bool:
    # A PyInstaller ``--onefile`` executable keeps a bootstrap process between
    # Electron and the Python worker.  The worker therefore cannot require its
    # direct PPID to equal the Electron owner PID.  Electron supplies the owner
    # PID explicitly; monitor that process itself so both source and packaged
    # runtimes follow the same lifetime contract.
    del get_parent_pid
    try:
        signal_process(expected_parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _request_sigterm_shutdown() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


class ElectronParentWatchdog:
    """Monitor one Electron owner process and request graceful shutdown on loss."""

    def __init__(
        self,
        *,
        parent_pid: int,
        parent_token: str,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        parent_is_alive: Callable[[int], bool] | None = None,
        request_shutdown: Callable[[], None] = _request_sigterm_shutdown,
    ) -> None:
        self.parent_pid = int(parent_pid)
        self.parent_token = str(parent_token)
        self.interval_seconds = max(0.01, float(interval_seconds))
        self._parent_is_alive = parent_is_alive or _posix_parent_is_alive
        self._request_shutdown = request_shutdown
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="electron-parent-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.interval_seconds * 2))

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            if not self._parent_is_alive(self.parent_pid):
                LOGGER.warning(
                    "Electron parent process disappeared; stopping desktop backend (parent_pid=%s)",
                    self.parent_pid,
                )
                self._request_shutdown()
                return
            self._stop_requested.wait(self.interval_seconds)


def start_electron_parent_watchdog(
    *,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> ElectronParentWatchdog | None:
    """Start a watchdog only for an explicitly Electron-owned POSIX backend."""

    parent_pid = _configured_parent_pid()
    parent_token = _configured_parent_token()
    if parent_pid is None or not parent_token:
        return None
    if os.name != "posix":
        LOGGER.warning(
            "Electron parent watchdog is not enabled on platform %s",
            os.name,
        )
        return None
    watchdog = ElectronParentWatchdog(
        parent_pid=parent_pid,
        parent_token=parent_token,
        interval_seconds=interval_seconds,
    )
    watchdog.start()
    return watchdog


def record_electron_smoke_event(event: str, **details: Any) -> None:
    """Append backend lifecycle evidence only inside an isolated smoke root."""

    if os.environ.get(DESKTOP_SMOKE_MODE_ENV) != "1":
        return
    configured_path = str(os.environ.get(ELECTRON_SMOKE_LEDGER_ENV) or "").strip()
    if not configured_path:
        return
    configured_ledger_path = Path(configured_path).expanduser()
    if not configured_ledger_path.is_absolute():
        LOGGER.warning("Ignoring non-absolute Electron smoke ledger path")
        return
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=False)
    ledger_parent = configured_ledger_path.parent.resolve(strict=False)
    try:
        ledger_parent.relative_to(temporary_root)
    except ValueError:
        LOGGER.warning("Ignoring Electron smoke ledger outside the system temporary directory")
        return
    ledger_path = ledger_parent / configured_ledger_path.name
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ledger_stat = ledger_path.lstat()
    except FileNotFoundError:
        ledger_stat = None
    if ledger_stat is not None and (
        stat.S_ISLNK(ledger_stat.st_mode) or not stat.S_ISREG(ledger_stat.st_mode)
    ):
        LOGGER.warning("Ignoring Electron smoke ledger that is not a regular file")
        return
    payload = {
        "event": str(event),
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "source": "desktop-backend",
        "parent_pid": _configured_parent_pid(),
        **details,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(
        ledger_path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            LOGGER.warning("Ignoring Electron smoke ledger that did not stay a regular file")
            return
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
