from __future__ import annotations

import json
import threading
from pathlib import Path

from apps.desktop_backend import parent_watchdog as watchdog_module

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_BACKEND_APP = ROOT / "apps" / "desktop_backend" / "app.py"


def test_parent_watchdog_is_disabled_without_explicit_electron_owner(monkeypatch) -> None:
    monkeypatch.delenv(watchdog_module.ELECTRON_PARENT_PID_ENV, raising=False)
    monkeypatch.delenv(watchdog_module.ELECTRON_PARENT_TOKEN_ENV, raising=False)

    assert watchdog_module.start_electron_parent_watchdog(interval_seconds=0.01) is None


def test_parent_watchdog_is_disabled_for_invalid_pid_or_missing_token(monkeypatch) -> None:
    monkeypatch.setenv(watchdog_module.ELECTRON_PARENT_PID_ENV, "not-a-pid")
    monkeypatch.setenv(watchdog_module.ELECTRON_PARENT_TOKEN_ENV, "token")
    assert watchdog_module.start_electron_parent_watchdog(interval_seconds=0.01) is None

    monkeypatch.setenv(watchdog_module.ELECTRON_PARENT_PID_ENV, "4321")
    monkeypatch.setenv(watchdog_module.ELECTRON_PARENT_TOKEN_ENV, "")
    assert watchdog_module.start_electron_parent_watchdog(interval_seconds=0.01) is None


def test_parent_watchdog_requests_shutdown_once_when_parent_disappears() -> None:
    shutdown_requested = threading.Event()
    observations = iter((True, False, False))
    shutdown_calls: list[str] = []

    def request_shutdown() -> None:
        shutdown_calls.append("SIGTERM")
        shutdown_requested.set()

    watchdog = watchdog_module.ElectronParentWatchdog(
        parent_pid=4321,
        parent_token="unique-parent-token",
        interval_seconds=0.01,
        parent_is_alive=lambda _pid: next(observations, False),
        request_shutdown=request_shutdown,
    )
    watchdog.start()
    try:
        assert shutdown_requested.wait(1)
    finally:
        watchdog.stop()

    assert shutdown_calls == ["SIGTERM"]


def test_packaged_onefile_parent_probe_tracks_live_electron_owner_across_bootstrap() -> None:
    signals: list[tuple[int, int]] = []

    assert watchdog_module._posix_parent_is_alive(
        4321,
        # PyInstaller --onefile keeps a bootstrap process between Electron and
        # the Python worker, so the worker's direct PPID is not Electron's PID.
        get_parent_pid=lambda: 9876,
        signal_process=lambda pid, selected: signals.append((pid, selected)),
    ) is True
    assert signals == [(4321, 0)]


def test_posix_parent_probe_treats_missing_process_as_dead() -> None:
    def missing_process(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    assert watchdog_module._posix_parent_is_alive(
        4321,
        get_parent_pid=lambda: 4321,
        signal_process=missing_process,
    ) is False


def test_smoke_ledger_only_writes_inside_temp_directory(monkeypatch, tmp_path) -> None:
    ledger_path = tmp_path / "electron-lifecycle.jsonl"
    monkeypatch.setenv(watchdog_module.DESKTOP_SMOKE_MODE_ENV, "1")
    monkeypatch.setenv(watchdog_module.ELECTRON_SMOKE_LEDGER_ENV, str(ledger_path))
    monkeypatch.setenv(watchdog_module.ELECTRON_PARENT_PID_ENV, "4321")

    watchdog_module.record_electron_smoke_event("backend.exit", reason="parent-lost")

    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["event"] == "backend.exit"
    assert payload["source"] == "desktop-backend"
    assert payload["parent_pid"] == 4321
    assert payload["reason"] == "parent-lost"


def test_smoke_ledger_ignores_non_smoke_and_non_temp_paths(monkeypatch, tmp_path) -> None:
    ledger_path = tmp_path / "disabled.jsonl"
    monkeypatch.setenv(watchdog_module.ELECTRON_SMOKE_LEDGER_ENV, str(ledger_path))
    monkeypatch.delenv(watchdog_module.DESKTOP_SMOKE_MODE_ENV, raising=False)

    watchdog_module.record_electron_smoke_event("backend.exit")

    assert ledger_path.exists() is False

    monkeypatch.setenv(watchdog_module.DESKTOP_SMOKE_MODE_ENV, "1")
    monkeypatch.setenv(watchdog_module.ELECTRON_SMOKE_LEDGER_ENV, "/outside-temp/ledger.jsonl")
    watchdog_module.record_electron_smoke_event("backend.exit")
    assert ledger_path.exists() is False


def test_smoke_ledger_does_not_follow_final_symlink(monkeypatch, tmp_path) -> None:
    target_path = tmp_path / "target.jsonl"
    target_path.write_text("unchanged\n", encoding="utf-8")
    ledger_path = tmp_path / "electron-lifecycle.jsonl"
    ledger_path.symlink_to(target_path)
    monkeypatch.setenv(watchdog_module.DESKTOP_SMOKE_MODE_ENV, "1")
    monkeypatch.setenv(watchdog_module.ELECTRON_SMOKE_LEDGER_ENV, str(ledger_path))

    watchdog_module.record_electron_smoke_event("backend.exit")

    assert ledger_path.is_symlink()
    assert target_path.read_text(encoding="utf-8") == "unchanged\n"


def test_desktop_backend_starts_parent_watchdog_before_runtime_lock_acquisition() -> None:
    source = DESKTOP_BACKEND_APP.read_text(encoding="utf-8")

    runtime_start_index = source.index("runtime.start()")
    signal_handler_index = source.index("signal.signal(signal.SIGTERM, _shutdown)")
    watchdog_index = source.index("parent_watchdog = start_electron_parent_watchdog()")
    bridge_index = source.index("start_bridge(host=bridge_host, port=bridge_port)")

    assert signal_handler_index < watchdog_index < runtime_start_index < bridge_index
