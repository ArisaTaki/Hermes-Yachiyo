"""Terminal execution helper for controlled Agent tools."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

from packages.security import (
    redact_api_error_text,
    redact_sensitive_text,
    scrubbed_subprocess_env,
)

_TERMINAL_PROCESS_LOCK = threading.RLock()
_TERMINAL_PROCESSES: set[subprocess.Popen[Any]] = set()


def cancel_terminal_process_groups() -> None:
    with _TERMINAL_PROCESS_LOCK:
        processes = list(_TERMINAL_PROCESSES)
    for process in processes:
        if process.poll() is not None:
            with _TERMINAL_PROCESS_LOCK:
                _TERMINAL_PROCESSES.discard(process)
            continue
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass


def run_terminal_command(
    command: str,
    *,
    workdir: Path,
    timeout_seconds: int = 30,
    shell: bool = False,
) -> dict[str, Any]:
    clean_command = str(command or "").strip()
    if not clean_command:
        return {"ok": False, "error": "terminal.run 命令不能为空"}
    try:
        argv: str | list[str] = clean_command if shell else shlex.split(clean_command)
    except ValueError as exc:
        return {"ok": False, "error": f"terminal.run 命令解析失败：{exc}"}
    if not shell and not argv:
        return {"ok": False, "error": "terminal.run 命令不能为空"}
    env = scrubbed_subprocess_env()
    try:
        process = subprocess.Popen(
            argv,
            cwd=workdir,
            shell=bool(shell),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "returncode": None,
            "timed_out": False,
            "shell": bool(shell),
            "stdout": "",
            "stderr": redact_api_error_text(exc),
        }
    with _TERMINAL_PROCESS_LOCK:
        _TERMINAL_PROCESSES.add(process)
    timed_out = False
    try:
        stdout, stderr = process.communicate(
            timeout=max(1, min(int(timeout_seconds or 30), 120))
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        stdout, stderr = process.communicate()
    finally:
        with _TERMINAL_PROCESS_LOCK:
            _TERMINAL_PROCESSES.discard(process)
    return {
        "ok": process.returncode == 0 and not timed_out,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "shell": bool(shell),
        "stdout": _redact_secrets(stdout)[-8000:],
        "stderr": _redact_secrets(stderr)[-8000:],
    }


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )
