from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_electron_single_instance.py"
RUN_SMOKE = os.environ.get("OHA_YACHIYO_RUN_ELECTRON_SINGLE_INSTANCE_SMOKE") == "1"


def _load_smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_oha_electron_single_instance_smoke_under_test",
        SMOKE_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_focus_probe_accepts_the_first_visible_restored_attempt(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    ledger = tmp_path / "electron-lifecycle.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "event": "window.focus",
                "electron_pid": 123,
                "source": "second-instance",
                "attempt": 0,
                "focused": True,
                "visible": True,
                "minimized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert smoke._second_instance_focus_event(  # noqa: SLF001 - smoke seam
        ledger,
        electron_pid=123,
        require_focus=False,
    ) == {
        "event": "window.focus",
        "electron_pid": 123,
        "source": "second-instance",
        "attempt": 0,
        "focused": True,
        "visible": True,
        "minimized": False,
    }


def test_required_focus_probe_rejects_an_unfocused_attempt(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    ledger = tmp_path / "electron-lifecycle.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "event": "window.focus",
                "electron_pid": 123,
                "source": "second-instance",
                "attempt": 10,
                "focused": False,
                "visible": True,
                "minimized": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert smoke._second_instance_focus_event(  # noqa: SLF001 - smoke seam
        ledger,
        electron_pid=123,
        require_focus=True,
    ) is None


@pytest.mark.skipif(
    not RUN_SMOKE or sys.platform != "darwin",
    reason="real Electron process smoke is opt-in and requires a macOS GUI session",
)
@pytest.mark.parametrize(
    ("death_signal", "kill_before_backend_ready"),
    (("term", False), ("kill", False), ("kill", True)),
)
def test_real_electron_secondary_and_backend_takeover(
    death_signal: str,
    kill_before_backend_ready: bool,
) -> None:
    early_kill_args = ["--kill-before-backend-ready"] if kill_before_backend_ready else []
    result = subprocess.run(
        [
            sys.executable,
            str(SMOKE_SCRIPT),
            "--death-signal",
            death_signal,
            "--timeout-seconds",
            "15",
            *early_kill_args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
