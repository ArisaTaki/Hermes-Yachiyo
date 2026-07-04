"""Runtime secret redaction verifier tests."""

from __future__ import annotations

from scripts import verify_secret_redaction as verifier


def test_contains_sensitive_text_detects_unredacted_secret_and_tool_call():
    assert verifier.contains_sensitive_text("api_key=sk-runtime-secret123456") is True
    assert verifier.contains_sensitive_text("<tool_call>{\"token\":\"abc123456\"}</tool_call>") is True
    assert verifier.contains_sensitive_text("api_key=[redacted]") is False
    assert verifier.contains_sensitive_text("token=[redacted]provider failed api_key=[redacted]") is False


def test_verify_secret_redaction_reports_file_without_echoing_secret(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    leaked_secret = "sk-runtime-secret123456"
    (runtime_dir / "backend.log").write_text(f"provider failed api_key={leaked_secret}\n", encoding="utf-8")
    (runtime_dir / "clean.json").write_text('{"token":"[redacted]"}\n', encoding="utf-8")

    findings = verifier.verify_secret_redaction(paths=[runtime_dir])

    assert len(findings) == 1
    assert findings[0].path.name == "backend.log"
    assert findings[0].line == 1
    formatted = findings[0].format(root=tmp_path)
    assert leaked_secret not in formatted
    assert "contains unredacted secret-like text" in formatted


def test_verify_secret_redaction_scans_binary_sqlite_like_files(tmp_path):
    db_path = tmp_path / "chat.db"
    db_path.write_bytes(b"\x00\x01token=db-secret-123456\x00")

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert len(findings) == 1
    assert findings[0].path == db_path


def test_verify_secret_redaction_skips_large_non_text_runtime_assets(tmp_path):
    asset_dir = tmp_path / ".oha-yachiyo" / "assets" / "tts" / "voice"
    asset_dir.mkdir(parents=True)
    (asset_dir / "voice.ckpt").write_bytes(b"\x00" * 1024)
    (asset_dir / "voice.pth").write_bytes(b"\x00" * 1024)

    findings = verifier.verify_secret_redaction(
        paths=[asset_dir],
        max_file_bytes=128,
    )

    assert findings == []


def test_verify_secret_redaction_uses_default_runtime_home(monkeypatch, tmp_path):
    runtime_home = tmp_path / ".oha-yachiyo"
    runtime_home.mkdir()
    (runtime_home / "activity.log").write_text("password=[redacted]\n", encoding="utf-8")
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(runtime_home))
    monkeypatch.setenv("OHA_YACHIYO_CONFIG_HOME", str(tmp_path / "missing-config"))

    assert verifier.default_scan_paths() == [runtime_home]
    assert verifier.verify_secret_redaction() == []


def test_cli_failure_does_not_print_secret(capsys, tmp_path):
    leaked_secret = "ghp_runtimeSecretSecret"
    log_path = tmp_path / "backend.log"
    log_path.write_text(f"authorization: bearer {leaked_secret}\n", encoding="utf-8")

    exit_code = verifier.main([str(log_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert leaked_secret not in output
    assert "secret redaction verification failed" in output
    assert "backend.log:1" in output
