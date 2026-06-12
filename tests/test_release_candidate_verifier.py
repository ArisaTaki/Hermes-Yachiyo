"""Release-candidate verification entrypoint tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import verify_release_candidate as rc


def test_release_candidate_verifier_runs_source_and_artifact_guards(tmp_path, monkeypatch, capsys):
    (tmp_path / "release").mkdir()
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    assert rc.verify_release_candidate(root=tmp_path) == 0

    assert calls == [
        {"root": tmp_path},
        {
            "root": tmp_path,
            "paths": (Path("release"),),
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
    ]
    output = capsys.readouterr().out
    assert "source release guards: passed" in output
    assert "built artifact guards: passed" in output
    assert "manual release-candidate checks:" in output


def test_release_candidate_verifier_writes_report_json(tmp_path, monkeypatch):
    (tmp_path / "release").mkdir()

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("release/rc-verification.json"),
    ) == 0

    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_release_guards"]["status"] == "passed"
    assert report["built_artifact_guards"]["status"] == "passed"
    assert report["built_artifact_guards"]["artifact_paths"] == ["release"]
    assert report["electron_ui_smoke"]["status"] == "skipped"
    assert report["manual_release_candidate_check_status"] == "manual_required"
    assert report["manual_release_candidate_checks"] == list(rc.MANUAL_RELEASE_CANDIDATE_CHECKS)


def test_release_candidate_verifier_requires_artifacts_when_requested(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(root=tmp_path, require_artifacts=True) == 1

    output = capsys.readouterr().out
    assert "release candidate artifacts not found" in output


def test_release_candidate_verifier_writes_failed_report_json(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        require_artifacts=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["built_artifact_guards"]["findings"] == [
        {
            "path": str(tmp_path),
            "message": "release candidate artifacts not found under dist/backend, dist/electron, or release",
        }
    ]


def test_release_candidate_verifier_runs_electron_ui_smoke_scripts(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    first = scripts / "smoke_alpha_ui.mjs"
    second = scripts / "smoke_beta_ui.mjs"
    first.write_text("console.log('alpha')\n", encoding="utf-8")
    second.write_text("console.log('beta')\n", encoding="utf-8")
    commands: list[dict[str, object]] = []

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fake_run(command, *, cwd, check):
        commands.append({"command": command, "cwd": cwd, "check": check})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(root=tmp_path, run_ui_smoke=True) == 0

    assert commands == [
        {"command": ["node", "scripts/smoke_alpha_ui.mjs"], "cwd": tmp_path, "check": False},
        {"command": ["node", "scripts/smoke_beta_ui.mjs"], "cwd": tmp_path, "check": False},
    ]


def test_release_candidate_verifier_reports_electron_ui_smoke_failure(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    smoke = scripts / "smoke_fail_ui.mjs"
    smoke.write_text("process.exit(7)\n", encoding="utf-8")

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(
        rc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )

    assert rc.verify_release_candidate(root=tmp_path, run_ui_smoke=True) == 1

    output = capsys.readouterr().out
    assert "scripts/smoke_fail_ui.mjs failed with exit code 7" in output


def test_release_candidate_verifier_reports_electron_ui_smoke_start_failure(
    tmp_path, monkeypatch, capsys
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    smoke = scripts / "smoke_missing_node_ui.mjs"
    smoke.write_text("console.log('missing node')\n", encoding="utf-8")

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fake_run(*_args, **_kwargs):
        raise OSError("node not found")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_ui_smoke=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "scripts/smoke_missing_node_ui.mjs could not start: node not found" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["electron_ui_smoke"] == {
        "status": "failed",
        "scripts": [
            {
                "script": "scripts/smoke_missing_node_ui.mjs",
                "exit_code": None,
                "error": "node not found",
            }
        ],
        "run_requested": True,
    }
