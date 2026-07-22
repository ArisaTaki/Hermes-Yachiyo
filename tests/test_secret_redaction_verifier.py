"""Runtime secret redaction verifier tests."""

from __future__ import annotations

import pytest

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


def test_verify_secret_redaction_ignores_control_interrupted_redacted_placeholder(tmp_path):
    db_path = tmp_path / "chat.db"
    db_path.write_bytes(b"SQLite format 3\x00token=[red\x00ac\x01ted]\x00")

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert findings == []


def test_verify_secret_redaction_still_detects_contiguous_printable_token(tmp_path):
    db_path = tmp_path / "chat.db"
    db_path.write_bytes(b"SQLite format 3\x00token=fixture-token-123456\x00")

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert len(findings) == 1
    assert findings[0].path == db_path


def test_verify_secret_redaction_scans_real_sqlite_wal_sidecar_name(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    wal_path = runtime_dir / "chat.db-wal"
    wal_path.write_bytes(
        b"SQLite WAL fixture\x00token=sidecar-fixture-token-123456\x00"
    )

    findings = verifier.verify_secret_redaction(paths=[runtime_dir])

    assert len(findings) == 1
    assert findings[0].path == wal_path


@pytest.mark.parametrize(
    "credential_ref",
    (
        "model_source:source_0123456789ab:api_key:0123456789abcdef0123456789abcdef",
        "model_profile:profile_0123456789ab:api_key:0123456789abcdef0123456789abcdef",
        "agent:agent-daily-helper:model_api_key:0123456789abcdef0123456789abcdef",
    ),
)
def test_verify_secret_redaction_allows_strict_keychain_credential_refs(
    tmp_path,
    credential_ref,
):
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite format 3\x00credential_ref\x00previous-column-1"
        + credential_ref.encode("ascii")
        + b"\x00"
    )

    assert verifier.verify_secret_redaction(paths=[db_path]) == []


@pytest.mark.parametrize(
    "secret_like_run",
    (
        "model_source:source_0123456789ab:api_key:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "model_source:source_0123456789ab:api_key:0123456789abcdef0123456789abcde",
        (
            "api_key=model_source:source_0123456789ab:api_key:"
            "0123456789abcdef0123456789abcdef"
        ),
        (
            "agent:agent-daily-helper:model_api_key:"
            "0123456789abcdef0123456789abcdef:api_key=sk-nested-secret123456"
        ),
        "api_key=sk-runtime-secret123456",
        "Authorization: Bearer runtimeBearerSecret123456",
    ),
)
def test_verify_secret_redaction_does_not_exempt_malformed_refs_or_real_secrets(
    tmp_path,
    secret_like_run,
):
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite format 3\x00" + secret_like_run.encode("ascii") + b"\x00"
    )

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert len(findings) == 1
    assert findings[0].path == db_path


def test_verify_secret_redaction_streams_sqlite_files_larger_than_limit(tmp_path):
    db_path = tmp_path / "runtime.sqlite3"
    db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 256)

    findings = verifier.verify_secret_redaction(
        paths=[db_path],
        max_file_bytes=32,
    )

    assert findings == []


def test_verify_secret_redaction_stream_detects_secret_beyond_size_limit(tmp_path):
    wal_path = tmp_path / "runtime.sqlite3-wal"
    wal_path.write_bytes(
        b"SQLite WAL fixture\x00"
        + b"\x00" * 256
        + b"api_key=sk-streamed-secret123456\x00"
    )

    findings = verifier.verify_secret_redaction(
        paths=[wal_path],
        max_file_bytes=32,
    )

    assert len(findings) == 1
    assert findings[0].path == wal_path


def test_verify_secret_redaction_stream_detects_printable_run_across_chunks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(verifier, "_SQLITE_SCAN_CHUNK_BYTES", 16)
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite\x00"
        + b"\x00" * 7
        + b"api_key=sk-cross-chunk-secret123456\x00"
    )

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert len(findings) == 1
    assert findings[0].path == db_path


def test_verify_secret_redaction_stream_allows_credential_ref_across_chunks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(verifier, "_SQLITE_SCAN_CHUNK_BYTES", 16)
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite\x00previous-column-1"
        b"model_source:source_0123456789ab:api_key:"
        b"0123456789abcdef0123456789abcdef\x00"
    )

    assert verifier.verify_secret_redaction(paths=[db_path]) == []


@pytest.mark.parametrize("fragment", ("workspace", "core"))
def test_verify_secret_redaction_allows_exact_task_id_overflow_continuation(
    tmp_path,
    fragment,
):
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite format 3\x00"
        + f"sk-{fragment}-0123456789ab\",\"next_field\":true".encode("ascii")
        + b"\x00"
    )

    assert verifier.verify_secret_redaction(paths=[db_path]) == []


def test_verify_secret_redaction_workspace_fragment_does_not_hide_real_sk_key(
    tmp_path,
):
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite format 3\x00"
        b"sk-workspace-0123456789abcdef-real-secret\"\x00"
    )

    findings = verifier.verify_secret_redaction(paths=[db_path])

    assert len(findings) == 1
    assert findings[0].path == db_path


def test_verify_secret_redaction_workspace_overflow_continuation_across_chunks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(verifier, "_SQLITE_SCAN_CHUNK_BYTES", 16)
    db_path = tmp_path / "runtime.db"
    db_path.write_bytes(
        b"SQLite\x00padding\x00"
        b"sk-workspace-0123456789ab\",\"next_field\":true\x00"
    )

    assert verifier.verify_secret_redaction(paths=[db_path]) == []


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
