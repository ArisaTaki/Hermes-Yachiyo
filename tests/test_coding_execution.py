from __future__ import annotations

import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import apps.shell.coding_execution as coding_mod
from apps.shell.coding_execution import CodingExecutionService, CommandResult, parse_start_code_command


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "app.txt").write_text("app\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    return path


def _service(tmp_path: Path) -> CodingExecutionService:
    return CodingExecutionService(
        db_path=tmp_path / "coding.db",
        workspace_dir=tmp_path / "yachiyo",
    )


def _wait_terminal(service: CodingExecutionService, job_id: str) -> dict:
    for _ in range(80):
        job = service.get_job(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    pytest.fail(f"job did not finish: {service.get_job(job_id)}")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_provider_health_reports_manual_and_mock_available(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        assert service.health_check_provider("manual_review")["availability"] == "available"
        assert service.health_check_provider("mock")["availability"] == "available"
        opendesign = service.health_check_provider("opendesign")
        assert any(action["id"] == "upgrade" for action in opendesign["actions"])
    finally:
        service.close()


def test_opendesign_daemon_health_uses_loopback_api(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/api/health":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"version":"0.6-test"}')

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service = _service(tmp_path)
    try:
        port = server.server_address[1]
        config = service.update_config(
            {
                "opendesign_daemon_url": f"http://127.0.0.1:{port}",
                "opendesign_web_url": f"http://127.0.0.1:{port}",
                "opendesign_auth_token": "secret-token",
                "opendesign_auto_start": True,
            }
        )
        assert config["opendesign_auth_token"] == "[configured]"
        assert config["opendesign_auth_token_configured"] is True
        status = service.health_check_provider("opendesign")
        assert status["availability"] == "available"
        assert status["version"] == "0.6-test"
        assert status["capabilities"]["daemon_url"] == f"http://127.0.0.1:{port}"
        assert status["capabilities"]["web_url"] == f"http://127.0.0.1:{port}"
        assert status["capabilities"]["daemon_reachable"] is True
        assert status["capabilities"]["direct_execution"] is True
        result = service.test_provider_config("opendesign")
        assert result["available"] is True
    finally:
        service.close()
        server.shutdown()


def test_opendesign_detects_managed_source_dir(tmp_path: Path) -> None:
    service = _service(tmp_path)
    managed = tmp_path / "yachiyo" / "external" / "open-design"
    managed.mkdir(parents=True)
    (managed / "package.json").write_text('{"name":"open-design"}', encoding="utf-8")
    (managed / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    service.update_config({"opendesign_app_path": str(managed)})
    service._discover_opendesign_daemon = lambda token="": {"checked": True, "reachable": False}
    try:
        status = service.health_check_provider("opendesign")
        assert status["availability"] == "installed_stopped"
        assert status["capabilities"]["app_source"] == "configured"
        assert status["capabilities"]["managed_path"] == str(managed)
    finally:
        service.close()


def test_coding_config_load_save_defaults(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        config = service.get_config()
        assert config["default_provider"] == "local_claude_code"
        updated = service.update_config(
            {
                "default_repo_path": str(tmp_path / "repo"),
                "default_writable_scopes": "src, tests",
                "default_provider": "mock",
                "default_review_strategy": "manual_only",
                "default_design_mode": "brief_only",
            }
        )
        assert updated["default_provider"] == "mock"
        assert updated["default_writable_scopes"] == ["src", "tests"]

        reopened = _service(tmp_path)
        try:
            assert reopened.get_config()["default_provider"] == "mock"
            assert reopened.get_config()["default_writable_scopes"] == ["src", "tests"]
        finally:
            reopened.close()
    finally:
        service.close()


def test_provider_env_config_is_redacted_and_testable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    _write_executable(
        claude,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'claude fake 1.0'; exit 0; fi\n"
        "if [ \"$1\" = \"--help\" ]; then echo 'Usage: claude -p --output-format'; exit 0; fi\n"
        "echo ok\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    service = _service(tmp_path)
    try:
        config = service.update_config(
            {
                "claude_credential_mode": "api_env",
                "anthropic_base_url": "https://gateway.example.com",
                "anthropic_api_key": "test-secret-key",
            }
        )
        assert config["anthropic_api_key"] == "[configured]"
        assert config["anthropic_api_key_configured"] is True
        env = service._provider_env("local_claude_code")
        assert env["ANTHROPIC_BASE_URL"] == "https://gateway.example.com"
        assert env["ANTHROPIC_API_KEY"] == "test-secret-key"
        result = service.test_provider_config("local_claude_code")
        assert result["available"] is True
        assert result["credential_mode"] == "api_env"
        assert result["isolated_auth"] is True
        assert result["api_key_configured"] is True
        assert "ANTHROPIC_API_KEY" in result["env_keys"]
        status = service.health_check_provider("local_claude_code")
        assert status["auth_required"] is False
        assert "API Env" in status["auth_hint"]
        isolated_env = service._provider_env("local_claude_code", job_id="job123")
        assert isolated_env["HOME"].endswith("runs/coding/job123/provider-auth/local_claude_code/home")
        assert "provider-auth/local_claude_code" in isolated_env["CLAUDE_CONFIG_DIR"]
    finally:
        service.close()


def test_cli_login_mode_does_not_inject_saved_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-secret-key")
    service = _service(tmp_path)
    try:
        service.update_config(
            {
                "claude_credential_mode": "cli_login",
                "anthropic_base_url": "https://gateway.example.com",
                "anthropic_api_key": "saved-secret-key",
            }
        )
        env = service._provider_env("local_claude_code")
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_BASE_URL" not in env
    finally:
        service.close()


def test_start_code_parser_uses_defaults_and_flags(tmp_path: Path) -> None:
    parsed = parse_start_code_command(
        "/start-code --scope src,tests --provider mock --review manual_only --task bugfix --design brief_only 修复按钮",
        {"default_repo_path": str(tmp_path / "repo")},
    )
    assert parsed is not None
    assert parsed["ok"] is True
    request = parsed["request"]
    assert request["repo_path"] == str(tmp_path / "repo")
    assert request["writable_scopes"] == ["src", "tests"]
    assert request["preferred_provider"] == "mock"
    assert request["review_strategy"] == "manual_only"
    assert request["task_type"] == "bugfix"
    assert request["design_mode"] == "brief_only"
    assert request["user_request"] == "修复按钮"


def test_start_code_parser_reports_missing_repo_and_invalid_provider() -> None:
    missing_repo = parse_start_code_command("/start-code 做一个 UI 改动", {})
    assert missing_repo is not None
    assert missing_repo["ok"] is False
    assert missing_repo["needs_config"] is True

    invalid = parse_start_code_command("/start-code --provider shell 做一个 UI 改动", {"default_repo_path": "/tmp/repo"})
    assert invalid is not None
    assert invalid["ok"] is False
    assert "provider" in invalid["error"]


def test_claude_missing_returns_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CodingExecutionService, "_which_command", lambda self, name: None if name == "claude" else coding_mod.shutil.which(name))
    service = _service(tmp_path)
    try:
        status = service.health_check_provider("local_claude_code")
        assert status["availability"] == "not_installed"
        assert "claude" in status["blocking_reason"]
    finally:
        service.close()


def test_claude_cli_login_requires_authenticated_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    _write_executable(
        claude,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'claude fake 1.0'; exit 0; fi\n"
        "if [ \"$1\" = \"--help\" ]; then echo 'Usage: claude -p --output-format'; exit 0; fi\n"
        "if [ \"$1\" = \"auth\" ] && [ \"$2\" = \"status\" ]; then echo '{\"loggedIn\":false,\"authMethod\":\"none\",\"apiProvider\":\"firstParty\"}'; exit 1; fi\n"
        "echo ok\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    service = _service(tmp_path)
    try:
        status = service.health_check_provider("local_claude_code")
        assert status["availability"] == "not_authenticated"
        assert status["auth_required"] is True
        assert status["capabilities"]["auth_status"]["logged_in"] is False
    finally:
        service.close()


def test_codex_review_health_reads_version_from_fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    _write_executable(
        codex,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'codex-cli 9.9.9'; exit 0; fi\n"
        "if [ \"$1\" = \"review\" ]; then echo 'Run a code review non-interactively --uncommitted --base --commit'; exit 0; fi\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"status\" ]; then echo 'Logged in using ChatGPT'; exit 0; fi\n"
        "echo 'Codex CLI'; exit 0\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    service = _service(tmp_path)
    try:
        status = service.health_check_provider("codex_review")
        assert status["availability"] == "available"
        assert status["display_name"] == "Codex CLI"
        assert status["version"] == "codex-cli 9.9.9"
        assert status["capabilities"]["review_uncommitted"] is True
    finally:
        service.close()


def test_provider_installer_uses_allowlisted_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)

    def fake_run(install_id: str, argv: list[str]) -> CommandResult:
        service._append_install_line(install_id, "token=supersecretvalue")
        return CommandResult(returncode=0, stdout="done")

    monkeypatch.setattr(service, "_run_install_argv", fake_run)
    try:
        started = service.install_provider("codex_review", "install")
        assert started["provider_id"] == "codex_review"
        for _ in range(40):
            install = service.get_provider_install(started["install_id"])
            if install["status"] != "running":
                break
            time.sleep(0.05)
        assert install["status"] == "completed"
        assert install["returncode"] == 0
        assert any("[redacted]" in line for line in install["lines"])
        with pytest.raises(coding_mod.CodingExecutionError):
            service.install_provider("codex_review", "shell")
        service._discover_opendesign_daemon = lambda token="": {"checked": True, "reachable": False}
        service._find_opendesign_source_candidates = lambda: []
        scan = service.install_provider("opendesign", "scan")
        assert scan["status"] == "completed"
        assert not any("Connection refused" in line for line in scan["lines"])
        upgrade = service.install_provider("opendesign", "upgrade")
        for _ in range(40):
            upgrade = service.get_provider_install(upgrade["install_id"])
            if upgrade["status"] != "running":
                break
            time.sleep(0.05)
        assert upgrade["status"] == "failed"
        assert upgrade["kind"] == "opendesign_upgrade"
        assert "Yachiyo 管辖目录" in upgrade["error"]
    finally:
        service.close()


def test_mock_job_requires_approval_before_execution(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    service = _service(tmp_path)
    try:
        job = service.create_job(
            {
                "user_request": "touch nothing",
                "repo_path": str(repo),
                "preferred_provider": "mock",
                "writable_scopes": ["."],
                "review_strategy": "manual_only",
            }
        )
        assert job["status"] == "awaiting_approval"
        branches = subprocess.run(
            ["git", "branch", "--list", job["branch_name"]],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert branches.stdout.strip() == ""

        approved = service.approve_job(job["job_id"])
        assert approved["status"] == "running"
        finished = _wait_terminal(service, job["job_id"])
        assert finished["status"] == "completed"
        assert (tmp_path / "yachiyo" / "artifacts" / "coding" / job["job_id"] / "brief.md").exists()
    finally:
        service.close()


def test_unavailable_claude_blocks_job_without_hapi_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(CodingExecutionService, "_which_command", lambda self, name: None if name == "claude" else coding_mod.shutil.which(name))
    service = _service(tmp_path)
    try:
        job = service.create_job(
            {
                "user_request": "make a change",
                "repo_path": str(repo),
                "preferred_provider": "local_claude_code",
                "writable_scopes": ["src"],
            }
        )
        assert job["status"] == "blocked"
        assert job["blockers"][0]["reason"] == "not_installed"
        assert any(option["id"] == "manual_review" for option in job["fallback_options"])
    finally:
        service.close()


def test_out_of_scope_provider_changes_fail_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    _write_executable(
        claude,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'claude fake 1.0'; exit 0; fi\n"
        "if [ \"$1\" = \"--help\" ]; then echo 'Usage: claude -p --output-format'; exit 0; fi\n"
        "echo outside > outside.txt\n"
        "echo 'provider done'\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    service = _service(tmp_path)
    try:
        service.update_config({"claude_credential_mode": "api_env", "anthropic_api_key": "test-key"})
        job = service.create_job(
            {
                "user_request": "write outside file",
                "repo_path": str(repo),
                "preferred_provider": "local_claude_code",
                "writable_scopes": ["src"],
                "review_strategy": "manual_only",
            }
        )
        assert job["status"] == "awaiting_approval"
        service.approve_job(job["job_id"])
        finished = _wait_terminal(service, job["job_id"])
        assert finished["status"] == "failed"
        assert "越界文件变更" in finished["error"]
        artifacts = service.list_artifacts(job["job_id"])["artifacts"]
        assert any(item["path"] == "rollback.md" for item in artifacts)
    finally:
        service.close()


def test_dirty_out_of_scope_file_modified_by_provider_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("user dirty change\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    _write_executable(
        claude,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'claude fake 1.0'; exit 0; fi\n"
        "if [ \"$1\" = \"--help\" ]; then echo 'Usage: claude -p --output-format'; exit 0; fi\n"
        "echo provider change >> README.md\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    service = _service(tmp_path)
    try:
        service.update_config({"claude_credential_mode": "api_env", "anthropic_api_key": "test-key"})
        job = service.create_job(
            {
                "user_request": "modify README",
                "repo_path": str(repo),
                "preferred_provider": "local_claude_code",
                "writable_scopes": ["src"],
                "review_strategy": "manual_only",
            }
        )
        assert job["status"] == "awaiting_approval"
        assert job["dirty_summary"]["dirty"] is True
        service.approve_job(job["job_id"])
        finished = _wait_terminal(service, job["job_id"])
        assert finished["status"] == "failed"
        assert finished["changed_files"] == ["README.md"]
        assert "README.md" in finished["error"]
    finally:
        service.close()
