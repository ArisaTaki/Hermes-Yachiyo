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


def test_release_candidate_verifier_source_only_skips_existing_artifacts(tmp_path, monkeypatch, capsys):
    (tmp_path / "dist" / "electron").mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    assert calls == [{"root": tmp_path}]
    output = capsys.readouterr().out
    assert "source release guards: passed" in output
    assert "built artifact guards: skipped by --source-only" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_release_guards"]["status"] == "passed"
    assert report["built_artifact_guards"] == {
        "status": "skipped",
        "artifact_paths": [],
        "findings": [],
    }


def test_release_candidate_verifier_source_only_rejects_require_artifacts(tmp_path, monkeypatch, capsys):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        require_artifacts=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --require-artifacts" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_artifact_paths(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        artifact_paths=(Path("release"),),
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with artifact paths" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_ui_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    def fail_run(*_args, **_kwargs):
        raise AssertionError("source-only must not run UI smoke")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_ui_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-ui-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_dmg_mount(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        check_dmg_mount=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --check-dmg-mount" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_dmg_app_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_dmg_app_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-dmg-app-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["dmg_app_smoke"]["status"] == "skipped"


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
    assert report["dmg_mount_guards"]["status"] == "skipped"
    assert report["dmg_app_smoke"]["status"] == "skipped"
    assert report["electron_ui_smoke"]["status"] == "skipped"
    assert report["manual_release_candidate_check_status"] == "manual_required"
    assert report["manual_release_candidate_checks"] == list(rc.MANUAL_RELEASE_CANDIDATE_CHECKS)


def test_release_candidate_verifier_checks_mounted_dmg_app(tmp_path, monkeypatch, capsys):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg_path = release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg_path.write_bytes(b"fake dmg")
    calls: list[dict[str, object]] = []
    commands: list[list[str]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            (mount_dir / "Oha-Yachiyo.app" / "Contents" / "Resources").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        check_dmg_mount=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    mount_path = Path(commands[0][commands[0].index("-mountpoint") + 1])
    assert calls == [
        {"root": tmp_path},
        {
            "root": tmp_path,
            "paths": (Path("release"),),
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
        {
            "root": tmp_path,
            "paths": (mount_path / "Oha-Yachiyo.app" / "Contents" / "Resources",),
            "check_required_files": False,
            "check_release_security_guards": False,
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
    ]
    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["hdiutil", "detach"]
    output = capsys.readouterr().out
    assert "DMG mount guards: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_mount_guards"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "findings": [],
        "run_requested": True,
    }


def test_release_candidate_verifier_dmg_mount_fails_without_dmgs(tmp_path, monkeypatch, capsys):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        check_dmg_mount=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate DMG mount check requested but no .dmg artifacts were found" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["dmg_mount_guards"]["status"] == "failed"


def test_release_candidate_verifier_runs_dmg_app_startup_smoke(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")
    commands: list[list[str]] = []
    popen_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,"task_counts":{},"native_agent_ready":false}'

    class FakeProcess:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, "cwd": kwargs.get("cwd"), "env": kwargs.get("env")})
        return FakeProcess()

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: 49123)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda url, timeout: FakeResponse())

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_app_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["hdiutil", "detach"]
    assert len(popen_calls) == 1
    assert popen_calls[0]["command"][0].endswith("/Oha-Yachiyo.app/Contents/MacOS/Oha-Yachiyo")
    assert popen_calls[0]["cwd"].endswith("/Oha-Yachiyo.app")
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49123"
    assert env["OHA_YACHIYO_HOME"].endswith("/.oha-yachiyo")
    output = capsys.readouterr().out
    assert "DMG app startup smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_app_smoke"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "findings": [],
        "run_requested": True,
    }


def test_release_candidate_dmg_app_startup_smoke_requires_executable(
    tmp_path, monkeypatch
):
    dmg_path = tmp_path / "release" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg_path.parent.mkdir()
    dmg_path.write_bytes(b"fake dmg")

    def fake_run(command, **kwargs):
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            (mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("missing executable must not be launched")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fail_popen)

    findings = rc.verify_dmg_app_startup(tmp_path, (Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),))

    assert findings == [
        rc.Finding(
            Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),
            "mounted Oha-Yachiyo.app must contain executable Oha-Yachiyo",
        )
    ]


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


def test_release_candidate_verifier_rejects_report_json_outside_root(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("../outside-rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate report: failed" in output
    assert "release candidate report path must stay inside project root" in output
    assert not (tmp_path.parent / "outside-rc-verification.json").exists()


def test_release_candidate_verifier_reports_report_json_write_failure(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fail_write(_path, _report):
        raise OSError("disk full")

    monkeypatch.setattr(rc, "_write_report", fail_write)

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate report: failed" in output
    assert "disk full" in output


def test_release_candidate_verifier_rejects_artifact_paths_outside_root(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("invalid artifact paths must not be mounted")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("../outside-release"),),
        check_dmg_mount=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    assert calls == [{"root": tmp_path}]
    output = capsys.readouterr().out
    assert "built artifact guards: failed" in output
    assert "DMG mount guards: skipped because artifact paths failed validation" in output
    assert "release candidate artifact path must stay inside project root" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["built_artifact_guards"] == {
        "status": "failed",
        "artifact_paths": ["../outside-release"],
        "findings": [
            {
                "path": str(tmp_path),
                "message": "release candidate artifact path must stay inside project root: ../outside-release",
            }
        ],
    }
    assert report["dmg_mount_guards"]["status"] == "skipped"


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


def test_release_candidate_verifier_rejects_smoke_scripts_outside_root(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fail_run(*_args, **_kwargs):
        raise AssertionError("outside smoke script must not run")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_ui_smoke=True,
        smoke_scripts=(Path("../outside-smoke-ui.mjs"),),
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "Electron UI smoke: failed" in output
    assert "release candidate smoke script path must stay inside project root" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["electron_ui_smoke"] == {
        "status": "failed",
        "scripts": [
            {
                "script": "../outside-smoke-ui.mjs",
                "exit_code": None,
                "error": (
                    "release candidate smoke script path must stay inside project root: "
                    "../outside-smoke-ui.mjs"
                ),
            }
        ],
        "run_requested": True,
    }


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
