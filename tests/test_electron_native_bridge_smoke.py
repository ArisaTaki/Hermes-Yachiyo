from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import smoke_electron_native_bridge as smoke


def test_electron_native_bridge_smoke_runs_compiled_electron(monkeypatch, tmp_path):
    electron_bin = tmp_path / "electron"
    electron_main = tmp_path / "main.js"
    electron_bin.write_text("", encoding="utf-8")
    electron_main.write_text("", encoding="utf-8")
    monkeypatch.setattr(smoke, "ELECTRON_BIN", electron_bin)
    monkeypatch.setattr(smoke, "ELECTRON_MAIN", electron_main)
    monkeypatch.setattr(smoke, "FRONTEND_DIR", tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["npm", "exec", "tsc"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        payload = {
            "ok": True,
            "mode": "electron_native_bridge_smoke",
            "native_runtime_url": "http://127.0.0.1:54321",
            "checks": {
                "native_bridge_started": True,
                "unauthenticated_rejected": True,
                "authenticated_status_ok": True,
            },
        }
        return SimpleNamespace(
            returncode=0,
            stdout=f"noise\n{smoke.SMOKE_PREFIX}{json.dumps(payload)}\n",
            stderr="",
        )

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    result = smoke.run_smoke(focus_app="Calculator")

    assert result["ok"] is True
    assert result["electron_returncode"] == 0
    assert result["checks"]["electron_process_ok"] is True
    assert result["checks"]["smoke_output_found"] is True
    assert calls[0][0] == ["npm", "exec", "tsc", "--", "-p", "tsconfig.electron.json"]
    assert calls[1][0] == [str(electron_bin), str(electron_main)]
    assert calls[1][1]["env"][smoke.SMOKE_ENV] == "1"
    assert calls[1][1]["env"][smoke.SMOKE_APP_ENV] == "Calculator"


def test_electron_native_bridge_smoke_reports_missing_electron(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "ELECTRON_BIN", tmp_path / "missing-electron")

    result = smoke.run_smoke()

    assert result["ok"] is False
    assert result["error"] == "electron_not_installed"
    assert result["checks"]["electron_bin_exists"] is False


def test_electron_native_bridge_smoke_reports_compile_failure(monkeypatch, tmp_path):
    electron_bin = tmp_path / "electron"
    electron_bin.write_text("", encoding="utf-8")
    monkeypatch.setattr(smoke, "ELECTRON_BIN", electron_bin)
    monkeypatch.setattr(
        smoke,
        "_run_compile",
        lambda: {
            "ok": False,
            "returncode": 2,
            "stdout": "",
            "stderr": "compile failed",
        },
    )

    result = smoke.run_smoke()

    assert result["ok"] is False
    assert result["error"] == "electron_main_compile_failed"
    assert result["compile"]["stderr"] == "compile failed"
