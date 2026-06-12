from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_electron_ui_smokes as runner


def test_electron_ui_smoke_runner_discovers_scripts_and_writes_report(
    tmp_path, monkeypatch, capsys
):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "smoke_beta_ui.mjs").write_text("console.log('beta')\n", encoding="utf-8")
    (scripts_dir / "smoke_alpha_ui.mjs").write_text("console.log('alpha')\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "cwd": kwargs.get("cwd"), "check": kwargs.get("check")})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.run_electron_ui_smokes(
        root=tmp_path,
        report_json=Path("release/electron-ui-smoke.json"),
    ) == 0

    assert calls == [
        {
            "command": ["node", "scripts/smoke_alpha_ui.mjs"],
            "cwd": tmp_path,
            "check": False,
        },
        {
            "command": ["node", "scripts/smoke_beta_ui.mjs"],
            "cwd": tmp_path,
            "check": False,
        },
    ]
    output = capsys.readouterr().out
    assert "Electron UI smoke: node scripts/smoke_alpha_ui.mjs" in output
    assert "Electron UI smoke report: release/electron-ui-smoke.json" in output
    report = json.loads((tmp_path / "release" / "electron-ui-smoke.json").read_text(encoding="utf-8"))
    assert report == {
        "ok": True,
        "script_count": 2,
        "scripts": [
            {"script": "scripts/smoke_alpha_ui.mjs", "exit_code": 0},
            {"script": "scripts/smoke_beta_ui.mjs", "exit_code": 0},
        ],
    }


def test_electron_ui_smoke_runner_fails_when_script_fails(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "smoke_fail_ui.mjs").write_text("throw new Error('fail')\n", encoding="utf-8")

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=9),
    )

    assert runner.run_electron_ui_smokes(
        root=tmp_path,
        report_json=Path("release/electron-ui-smoke.json"),
    ) == 1

    report = json.loads((tmp_path / "release" / "electron-ui-smoke.json").read_text(encoding="utf-8"))
    assert report == {
        "ok": False,
        "script_count": 1,
        "scripts": [
            {"script": "scripts/smoke_fail_ui.mjs", "exit_code": 9},
        ],
    }
