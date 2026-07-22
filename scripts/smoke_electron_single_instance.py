#!/usr/bin/env python3
"""Exercise Electron's real 2+1 process ownership and backend lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "apps" / "frontend"
ELECTRON_MAIN = FRONTEND_DIR / "dist-electron" / "main.js"
ELECTRON_CLI = FRONTEND_DIR / "node_modules" / ".bin" / (
    "electron.cmd" if platform.system() == "Windows" else "electron"
)
ELECTRON_MAC_BINARY = (
    FRONTEND_DIR
    / "node_modules"
    / "electron"
    / "dist"
    / "Electron.app"
    / "Contents"
    / "MacOS"
    / "Electron"
)
BACKEND_FIXTURE = (
    PROJECT_ROOT / "scripts" / "fixtures" / "electron_backend_lifecycle_fixture.py"
)
SMOKE_MODE_ENV = "OHA_YACHIYO_DESKTOP_SMOKE_MODE"
SMOKE_ROOT_ENV = "OHA_YACHIYO_ELECTRON_SMOKE_ROOT"
SMOKE_LOCK_DELAY_ENV = "OHA_YACHIYO_ELECTRON_SMOKE_LOCK_DELAY_MS"
DEFAULT_TIMEOUT_SECONDS = 20.0


class SmokeError(RuntimeError):
    pass


class _RendererHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        body = b"<!doctype html><html><body>electron lifecycle smoke</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _RendererServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RendererHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _electron_binary() -> Path:
    if sys.platform == "darwin" and ELECTRON_MAC_BINARY.is_file():
        return ELECTRON_MAC_BINARY
    return ELECTRON_CLI


def _run_compile() -> dict[str, Any]:
    result = subprocess.run(
        ["npm", "exec", "tsc", "--", "-p", "tsconfig.electron.json"],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _wait_for(
    predicate: Callable[[], Any],
    description: str,
    *,
    timeout_seconds: float,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise SmokeError(f"timed out waiting for {description}")


def _event(
    ledger_path: Path,
    name: str,
    **expected: object,
) -> dict[str, Any] | None:
    for item in reversed(_read_events(ledger_path)):
        if item.get("event") != name:
            continue
        if all(item.get(key) == value for key, value in expected.items()):
            return item
    return None


def _second_instance_focus_event(
    ledger_path: Path,
    *,
    electron_pid: int,
    require_focus: bool,
) -> dict[str, Any] | None:
    expected: dict[str, object] = {
        "electron_pid": electron_pid,
        "source": "second-instance",
        "visible": True,
        "minimized": False,
    }
    if require_focus:
        expected["focused"] = True
    return _event(ledger_path, "window.focus", **expected)


def _wait_process_exit(process: subprocess.Popen[bytes], timeout_seconds: float) -> int:
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise SmokeError(f"process {process.pid} did not exit") from exc


def _signal_process(process: subprocess.Popen[bytes], selected: signal.Signals) -> None:
    if process.poll() is not None:
        return
    os.kill(process.pid, selected)


def _process_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_descendants(parent_pid: int) -> set[int]:
    if os.name != "posix":
        return set()
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid="],
        capture_output=True,
        text=True,
        check=False,
    )
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            pid, ppid = (int(field) for field in fields)
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    pending = list(children.get(parent_pid, []))
    descendants: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, []))
    return descendants


def _cleanup_pid(pid: int) -> None:
    if not _process_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _process_alive(pid):
        time.sleep(0.05)
    if _process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _write_backend_wrapper(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(BACKEND_FIXTURE))}\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _launch_electron(
    *,
    env: dict[str, str],
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], Any]:
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        [str(_electron_binary()), str(ELECTRON_MAIN)],
        cwd=FRONTEND_DIR,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def _log_tail(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-6000:]


def run_smoke(
    *,
    death_signal: signal.Signals,
    compile_electron: bool = True,
    kill_before_backend_ready: bool = False,
    require_focus: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if os.name != "posix":
        return {"ok": False, "error": "posix_smoke_required", "platform": sys.platform}
    electron_binary = _electron_binary()
    if not electron_binary.is_file():
        return {"ok": False, "error": "electron_not_installed", "path": str(electron_binary)}
    compile_result = _run_compile() if compile_electron else {"skipped": True, "ok": True}
    if compile_result.get("ok") is not True:
        return {"ok": False, "error": "electron_compile_failed", "compile": compile_result}
    if not ELECTRON_MAIN.is_file():
        return {"ok": False, "error": "electron_main_not_built"}

    renderer = _RendererServer()
    renderer.start()
    processes: list[subprocess.Popen[bytes]] = []
    log_handles: list[Any] = []
    observed_descendants: set[int] = set()
    report: dict[str, Any] = {
        "ok": False,
        "mode": "electron_single_instance_process_smoke",
        "death_signal": death_signal.name,
        "kill_before_backend_ready": kill_before_backend_ready,
        "focus_required": require_focus,
        "compile": compile_result,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="oha-electron-single-instance-") as raw_temp:
            temp_root = Path(raw_temp)
            smoke_root = temp_root / "electron-smoke"
            ledger_path = smoke_root / "electron-lifecycle.jsonl"
            home_dir = temp_root / "home"
            oha_home = home_dir / ".oha-yachiyo"
            backend_wrapper = temp_root / "fake-python"
            home_dir.mkdir(parents=True)
            oha_home.mkdir(parents=True)
            _write_backend_wrapper(backend_wrapper)
            env = {
                **os.environ,
                "HOME": str(home_dir),
                "OHA_YACHIYO_HOME": str(oha_home),
                "OHA_YACHIYO_FRONTEND_DEV_URL": renderer.url,
                "OHA_YACHIYO_BRIDGE_URL": f"http://127.0.0.1:{_free_loopback_port()}",
                "OHA_YACHIYO_PYTHON": str(backend_wrapper),
                SMOKE_MODE_ENV: "1",
                SMOKE_ROOT_ENV: str(smoke_root),
                SMOKE_LOCK_DELAY_ENV: "2000" if kill_before_backend_ready else "0",
                "ELECTRON_ENABLE_LOGGING": "1",
            }
            primary_log = temp_root / "primary.log"
            secondary_log = temp_root / "secondary.log"
            takeover_log = temp_root / "takeover.log"

            def capture_evidence() -> None:
                report["events"] = _read_events(ledger_path)
                for handle in log_handles:
                    handle.flush()
                report["logs"] = {
                    "primary": _log_tail(primary_log),
                    "secondary": _log_tail(secondary_log),
                    "takeover": _log_tail(takeover_log),
                }

            primary, primary_handle = _launch_electron(env=env, log_path=primary_log)
            processes.append(primary)
            log_handles.append(primary_handle)
            _wait_for(
                lambda: _event(ledger_path, "primary", electron_pid=primary.pid),
                "primary lock acquisition",
                timeout_seconds=timeout_seconds,
            )
            first_spawn = _wait_for(
                lambda: _event(ledger_path, "backend.spawn", electron_pid=primary.pid),
                "primary backend spawn",
                timeout_seconds=timeout_seconds,
            )
            first_backend_pid = int(first_spawn["backend_pid"])
            if kill_before_backend_ready:
                if death_signal != signal.SIGKILL:
                    raise SmokeError("early backend initialization smoke requires SIGKILL")
                watchdog_ready = _wait_for(
                    lambda: _event(
                        ledger_path,
                        "backend.watchdog-ready",
                        pid=first_backend_pid,
                        lock_acquired=False,
                    ),
                    "backend watchdog before runtime lock acquisition",
                    timeout_seconds=timeout_seconds,
                )
                if watchdog_ready.get("watchdog_enabled") is not True:
                    raise SmokeError("early backend did not enable the Electron parent watchdog")
                if watchdog_ready.get("parent_token_hash") != first_spawn.get("parent_token_hash"):
                    raise SmokeError("early backend parent token did not match Electron spawn")
                report["events"] = _read_events(ledger_path)
                observed_descendants.update(_process_descendants(primary.pid))
                _signal_process(primary, signal.SIGKILL)
                _wait_process_exit(primary, timeout_seconds)
                early_exit = _wait_for(
                    lambda: _event(
                        ledger_path,
                        "backend.exit",
                        pid=first_backend_pid,
                        source="backend-fixture",
                        runtime_lock_acquired=False,
                    ),
                    "backend exit before runtime lock acquisition",
                    timeout_seconds=timeout_seconds,
                )
                if early_exit.get("runtime_lock_acquired") is not False:
                    raise SmokeError("early backend unexpectedly acquired the runtime lock")
                if _event(ledger_path, "backend.ready", pid=first_backend_pid) is not None:
                    raise SmokeError("early backend reached ready after Electron parent death")

                takeover_env = {**env, SMOKE_LOCK_DELAY_ENV: "0"}
                takeover, takeover_handle = _launch_electron(
                    env=takeover_env,
                    log_path=takeover_log,
                )
                processes.append(takeover)
                log_handles.append(takeover_handle)
                _wait_for(
                    lambda: _event(ledger_path, "primary", electron_pid=takeover.pid),
                    "early-death takeover primary lock acquisition",
                    timeout_seconds=timeout_seconds,
                )
                second_spawn = _wait_for(
                    lambda: _event(ledger_path, "backend.spawn", electron_pid=takeover.pid),
                    "early-death takeover backend spawn",
                    timeout_seconds=timeout_seconds,
                )
                second_backend_pid = int(second_spawn["backend_pid"])
                takeover_ready = _wait_for(
                    lambda: _event(ledger_path, "backend.ready", pid=second_backend_pid),
                    "first takeover backend runtime lock readiness",
                    timeout_seconds=timeout_seconds,
                )
                if takeover_ready.get("parent_token_hash") != second_spawn.get(
                    "parent_token_hash"
                ):
                    raise SmokeError("early-death takeover parent token did not match")
                if _event(ledger_path, "backend.lock-failed", pid=second_backend_pid) is not None:
                    raise SmokeError("first takeover backend could not acquire the runtime lock")
                final_spawns = [
                    item
                    for item in _read_events(ledger_path)
                    if item.get("event") == "backend.spawn"
                ]
                if len(final_spawns) != 2:
                    raise SmokeError(
                        f"expected two early-death backend spawns, found {len(final_spawns)}"
                    )
                observed_descendants.update(_process_descendants(takeover.pid))
                _signal_process(takeover, signal.SIGTERM)
                _wait_process_exit(takeover, timeout_seconds)
                _wait_for(
                    lambda: _event(
                        ledger_path,
                        "backend.exit",
                        pid=second_backend_pid,
                        source="backend-fixture",
                    ),
                    "early-death takeover backend cleanup",
                    timeout_seconds=timeout_seconds,
                )
                report.update(
                    {
                        "ok": True,
                        "checks": {
                            "backend_watchdog_ready_before_runtime_lock": True,
                            "early_backend_exited_without_runtime_lock": True,
                            "first_takeover_acquired_runtime_lock": True,
                            "backend_spawn_count": len(final_spawns),
                        },
                        "events": _read_events(ledger_path),
                    }
                )
                return report

            first_ready = _wait_for(
                lambda: _event(ledger_path, "backend.ready", pid=first_backend_pid),
                "primary backend fixture readiness",
                timeout_seconds=timeout_seconds,
            )
            if first_ready.get("parent_token_hash") != first_spawn.get("parent_token_hash"):
                raise SmokeError("primary backend parent token did not match Electron spawn")
            _wait_for(
                lambda: _event(ledger_path, "window.created", electron_pid=primary.pid),
                "primary BrowserWindow creation",
                timeout_seconds=timeout_seconds,
            )

            secondary, secondary_handle = _launch_electron(env=env, log_path=secondary_log)
            processes.append(secondary)
            log_handles.append(secondary_handle)
            _wait_for(
                lambda: _event(ledger_path, "secondary", electron_pid=secondary.pid),
                "secondary lock rejection",
                timeout_seconds=timeout_seconds,
            )
            _wait_process_exit(secondary, timeout_seconds)
            _wait_for(
                lambda: _event(ledger_path, "second-instance", electron_pid=primary.pid),
                "primary second-instance callback",
                timeout_seconds=timeout_seconds,
            )
            try:
                focus_event = _wait_for(
                    lambda: _second_instance_focus_event(
                        ledger_path,
                        electron_pid=primary.pid,
                        require_focus=require_focus,
                    ),
                    "focused primary window" if require_focus else "primary window focus attempt",
                    timeout_seconds=timeout_seconds,
                )
            except SmokeError:
                capture_evidence()
                raise
            backend_spawns = [
                item for item in _read_events(ledger_path) if item.get("event") == "backend.spawn"
            ]
            if len(backend_spawns) != 1:
                raise SmokeError(
                    f"secondary launch changed backend spawn count to {len(backend_spawns)}"
                )

            observed_descendants.update(_process_descendants(primary.pid))
            _signal_process(primary, death_signal)
            _wait_process_exit(primary, timeout_seconds)
            try:
                _wait_for(
                    lambda: _event(
                        ledger_path,
                        "backend.exit",
                        pid=first_backend_pid,
                        source="backend-fixture",
                    ),
                    "orphan backend exit after primary death",
                    timeout_seconds=timeout_seconds,
                )
            except SmokeError:
                capture_evidence()
                raise

            takeover, takeover_handle = _launch_electron(env=env, log_path=takeover_log)
            processes.append(takeover)
            log_handles.append(takeover_handle)
            _wait_for(
                lambda: _event(ledger_path, "primary", electron_pid=takeover.pid),
                "takeover primary lock acquisition",
                timeout_seconds=timeout_seconds,
            )
            second_spawn = _wait_for(
                lambda: _event(ledger_path, "backend.spawn", electron_pid=takeover.pid),
                "takeover backend spawn",
                timeout_seconds=timeout_seconds,
            )
            second_backend_pid = int(second_spawn["backend_pid"])
            takeover_ready = _wait_for(
                lambda: _event(ledger_path, "backend.ready", pid=second_backend_pid),
                "takeover backend runtime lock readiness",
                timeout_seconds=timeout_seconds,
            )
            if takeover_ready.get("parent_token_hash") != second_spawn.get("parent_token_hash"):
                raise SmokeError("takeover backend parent token did not match Electron spawn")
            if takeover_ready.get("watchdog_enabled") is not True:
                raise SmokeError("takeover backend did not enable the Electron parent watchdog")
            final_spawns = [
                item for item in _read_events(ledger_path) if item.get("event") == "backend.spawn"
            ]
            if len(final_spawns) != 2:
                raise SmokeError(
                    f"expected two primary backend spawns, found {len(final_spawns)}"
                )

            observed_descendants.update(_process_descendants(takeover.pid))
            _signal_process(takeover, signal.SIGTERM)
            _wait_process_exit(takeover, timeout_seconds)
            _wait_for(
                lambda: _event(
                    ledger_path,
                    "backend.exit",
                    pid=second_backend_pid,
                    source="backend-fixture",
                ),
                "takeover backend cleanup",
                timeout_seconds=timeout_seconds,
            )
            events = _read_events(ledger_path)
            report.update(
                {
                    "ok": True,
                    "checks": {
                        "secondary_exited": True,
                        "secondary_backend_count_unchanged": True,
                        "primary_focus_requested": True,
                        "primary_focus_verified": bool(focus_event.get("focused")),
                        "primary_visible_and_restored": True,
                        "orphan_backend_exited": True,
                        "takeover_acquired_runtime_lock": True,
                        "backend_spawn_count": len(final_spawns),
                    },
                    "events": events,
                }
            )
            return report
    except Exception as exc:
        report.update(
            {
                "error": str(exc),
                "events": report.get("events") or (
                    _read_events(ledger_path) if "ledger_path" in locals() else []
                ),
                "logs": report.get("logs") or {
                    "primary": _log_tail(primary_log) if "primary_log" in locals() else "",
                    "secondary": _log_tail(secondary_log) if "secondary_log" in locals() else "",
                    "takeover": _log_tail(takeover_log) if "takeover_log" in locals() else "",
                },
            }
        )
        return report
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                try:
                    _signal_process(process, signal.SIGTERM)
                    process.wait(timeout=2)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        _signal_process(process, signal.SIGKILL)
                        process.wait(timeout=2)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        pass
        backend_pids = {
            int(item["backend_pid"])
            for item in report.get("events", [])
            if item.get("event") == "backend.spawn" and str(item.get("backend_pid") or "").isdigit()
        }
        for pid in sorted(backend_pids | observed_descendants, reverse=True):
            _cleanup_pid(pid)
        for handle in log_handles:
            handle.close()
        renderer.stop()


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--death-signal", choices=("term", "kill"), default="kill")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument(
        "--kill-before-backend-ready",
        action="store_true",
        help="Kill Electron after the backend watchdog starts but before runtime lock acquisition.",
    )
    parser.add_argument(
        "--require-focus",
        action="store_true",
        help=(
            "Fail unless BrowserWindow.isFocused() becomes true "
            "(requires an interactive GUI session)."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)
    selected_signal = signal.SIGTERM if args.death_signal == "term" else signal.SIGKILL
    report = run_smoke(
        death_signal=selected_signal,
        compile_electron=not args.no_compile,
        kill_before_backend_ready=args.kill_before_backend_ready,
        require_focus=args.require_focus,
        timeout_seconds=max(2.0, args.timeout_seconds),
    )
    if args.report_json is not None:
        _write_report(args.report_json, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
