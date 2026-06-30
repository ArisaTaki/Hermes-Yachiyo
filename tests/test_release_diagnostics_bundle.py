from __future__ import annotations

import json
import zipfile

from scripts import collect_release_diagnostics as diagnostics


def test_collect_release_diagnostics_writes_redacted_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "ROOT", tmp_path)
    release_report = tmp_path / "tmp" / "rc-verification-abc12345-release-readiness.json"
    release_report.parent.mkdir(parents=True, exist_ok=True)
    release_report.write_text(
        json.dumps(
            {
                "status": "incomplete",
                "api_key": "sk-release-secret123456",
                "blockers": [{"error": "token=sk-blocker-secret123456"}],
            }
        ),
        encoding="utf-8",
    )
    log_path = tmp_path / "tmp" / "native-agent.log"
    log_path.write_text(
        "request failed Authorization: Bearer abcdefghijklmnop\n",
        encoding="utf-8",
    )
    output_zip = tmp_path / "tmp" / "diagnostics.zip"

    manifest = diagnostics.collect_release_diagnostics(
        label="abc12345",
        output_zip=output_zip,
        includes=[log_path],
    )

    assert manifest["ok"] is True
    assert manifest["included_count"] == 2
    with zipfile.ZipFile(output_zip) as archive:
        names = set(archive.namelist())
        assert "diagnostics/tmp/rc-verification-abc12345-release-readiness.json" in names
        assert "diagnostics/tmp/native-agent.log" in names
        assert "diagnostics/manifest.json" in names
        rendered = "\n".join(
            archive.read(name).decode("utf-8") for name in sorted(names)
        )

    assert "sk-release-secret123456" not in rendered
    assert "sk-blocker-secret123456" not in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "[redacted]" in rendered


def test_collect_release_diagnostics_skips_binary_and_large_files(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "ROOT", tmp_path)
    binary_path = tmp_path / "tmp" / "binary.log"
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_bytes(b"safe\0binary")
    large_path = tmp_path / "tmp" / "large.log"
    large_path.write_text("safe\n" * 100, encoding="utf-8")
    output_zip = tmp_path / "tmp" / "diagnostics.zip"

    manifest = diagnostics.collect_release_diagnostics(
        label="abc12345",
        output_zip=output_zip,
        includes=[binary_path, large_path],
        max_file_bytes=16,
    )

    assert manifest["ok"] is False
    skipped = {item["source"]: item["reason"] for item in manifest["skipped"]}
    assert skipped["tmp/binary.log"] == "binary"
    assert skipped["tmp/large.log"] == "too_large"
    with zipfile.ZipFile(output_zip) as archive:
        assert archive.namelist() == ["diagnostics/manifest.json"]


def test_collect_release_diagnostics_skips_files_that_still_look_sensitive(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(diagnostics, "ROOT", tmp_path)
    monkeypatch.setattr(
        diagnostics,
        "contains_sensitive_text",
        lambda value: "still-sensitive" in str(value),
    )
    log_path = tmp_path / "tmp" / "agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("still-sensitive\n", encoding="utf-8")
    output_zip = tmp_path / "tmp" / "diagnostics.zip"

    manifest = diagnostics.collect_release_diagnostics(
        label="abc12345",
        output_zip=output_zip,
        includes=[log_path],
    )

    assert manifest["ok"] is False
    skipped = {item["source"]: item["reason"] for item in manifest["skipped"]}
    assert skipped["tmp/agent.log"] == "redaction_failed"
    with zipfile.ZipFile(output_zip) as archive:
        assert archive.namelist() == ["diagnostics/manifest.json"]


def test_collect_release_diagnostics_cli_writes_bundle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "rc-signoff-abc12345-current.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("Gatekeeper: manual_required\n", encoding="utf-8")
    output_zip = tmp_path / "tmp" / "cli-diagnostics.zip"

    exit_code = diagnostics.main(
        [
            "--label",
            "abc12345",
            "--output-zip",
            str(output_zip),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["included_count"] == 1
    with zipfile.ZipFile(output_zip) as archive:
        assert "diagnostics/tmp/rc-signoff-abc12345-current.md" in archive.namelist()
