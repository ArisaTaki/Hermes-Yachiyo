"""Controlled coding job runtime for Hermes-Yachiyo.

This module is intentionally independent from Hermes task execution.  It owns a
small, auditable job state machine and only runs known provider commands from
backend code after an explicit approval step.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.shell.assets import get_yachiyo_workspace_dir

logger = logging.getLogger(__name__)

_DB_FILENAME = "coding.db"
_CONFIG_FILENAME = "coding-config.json"
_ARTIFACT_MAX_INLINE_BYTES = 200 * 1024
_CLI_TIMEOUT_SECONDS = int(os.getenv("HERMES_YACHIYO_CODING_CLI_TIMEOUT_SECONDS", "1800"))
_REVIEW_TIMEOUT_SECONDS = int(os.getenv("HERMES_YACHIYO_CODING_REVIEW_TIMEOUT_SECONDS", "600"))
_INSTALL_TIMEOUT_SECONDS = int(os.getenv("HERMES_YACHIYO_CODING_INSTALL_TIMEOUT_SECONDS", "900"))
_PROVIDER_HEALTH_TIMEOUT_SECONDS = 8.0
_PROVIDER_API_TEST_TIMEOUT_SECONDS = 14.0
_VALID_JOB_STATUSES = {
    "draft",
    "planning",
    "blocked",
    "awaiting_approval",
    "running",
    "reviewing",
    "completed",
    "failed",
    "cancelled",
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|bearer)\b\s*[:=]\s*([^\s,;\"']{6,})"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{12,})\b"),
)
_TEXT_ARTIFACT_SUFFIXES = {".md", ".txt", ".json", ".log", ".diff", ".patch"}
_HIGH_RISK_TASK_TYPES = {"refactor", "packaging_check"}
_CODING_PROVIDERS = {"local_claude_code", "mock"}
_REVIEW_STRATEGIES = {"codex_if_available", "manual_only", "none"}
_TASK_TYPES = {"custom", "ui_redesign", "bugfix", "refactor", "docs", "packaging_check"}
_DESIGN_MODES = {
    "none",
    "brief_only",
    "opendesign_if_available",
    "opendesign_required",
    "import_existing_artifact",
    "opendesign_daemon_if_available",
    "opendesign_daemon_required",
    "manual_artifact_import",
}
_CREDENTIAL_MODES = {"cli_login", "api_env"}
_INSTALL_LOG_MAX_LINES = 600
_OPENDESIGN_HEALTH_TIMEOUT_SECONDS = 3.0
_OPENDESIGN_DEFAULT_DOCS_URL = "https://github.com/nexu-io/open-design"
_OPENDESIGN_RELEASES_URL = "https://github.com/nexu-io/open-design/releases"

_DEFAULT_CODING_CONFIG: dict[str, Any] = {
    "default_repo_path": "",
    "default_writable_scopes": ["."],
    "default_provider": "local_claude_code",
    "default_review_strategy": "codex_if_available",
    "default_design_mode": "none",
    "hapi_url": "",
    "opendesign_artifact_dir": "",
    "opendesign_daemon_url": "",
    "opendesign_web_url": "",
    "opendesign_auth_token": "",
    "opendesign_app_path": "",
    "opendesign_auto_start": False,
    "claude_credential_mode": "cli_login",
    "anthropic_base_url": "",
    "anthropic_model": "",
    "anthropic_api_key": "",
    "codex_credential_mode": "cli_login",
    "codex_base_url": "",
    "codex_model": "",
    "codex_api_key": "",
}


class CodingExecutionError(RuntimeError):
    """Expected coding runtime failure with user-visible text."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


@dataclass(frozen=True)
class ProviderActionSpec:
    action: str
    label: str
    kind: str
    argv: tuple[str, ...] = ()
    terminal_command: str = ""
    confirmation: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_dir() -> Path:
    root = get_yachiyo_workspace_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _default_db_path() -> Path:
    return _workspace_dir() / _DB_FILENAME


def _default_config_path() -> Path:
    return _workspace_dir() / _CONFIG_FILENAME


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _toml_string(value: Any) -> str:
    return json.dumps(str(value or ""))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _redact_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: f"{match.group(1)}=[redacted]" if match.lastindex and match.lastindex > 1 else "[redacted]",
            text,
        )
    if limit is not None and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _compact(value: Any, *, limit: int = 800) -> str:
    return _redact_text(" ".join(str(value or "").split()), limit=limit)


def _safe_relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise CodingExecutionError("artifact 路径越界")


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _normalize_scope(scope: str) -> str:
    value = str(scope or "").strip().replace("\\", "/").strip("/")
    return value or "."


def _normalize_scopes(scopes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for scope in scopes or ["."]:
        value = _normalize_scope(scope)
        if value not in normalized:
            normalized.append(value)
    return normalized or ["."]


def _split_scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        return _normalize_scopes([item.strip() for item in value.split(",") if item.strip()])
    if isinstance(value, list):
        return _normalize_scopes([str(item) for item in value])
    return ["."]


def _sanitize_config(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value or {}
    config = dict(_DEFAULT_CODING_CONFIG)
    config.update({key: source.get(key, config[key]) for key in config})
    config["default_repo_path"] = str(config.get("default_repo_path") or "").strip()
    config["default_writable_scopes"] = _split_scopes(config.get("default_writable_scopes"))
    provider = str(config.get("default_provider") or "local_claude_code").strip()
    config["default_provider"] = provider if provider in _CODING_PROVIDERS else "local_claude_code"
    review = str(config.get("default_review_strategy") or "codex_if_available").strip()
    config["default_review_strategy"] = review if review in _REVIEW_STRATEGIES else "codex_if_available"
    design = str(config.get("default_design_mode") or "none").strip()
    config["default_design_mode"] = design if design in _DESIGN_MODES else "none"
    config["hapi_url"] = str(config.get("hapi_url") or "").strip()
    config["opendesign_artifact_dir"] = str(config.get("opendesign_artifact_dir") or "").strip()
    config["opendesign_daemon_url"] = str(config.get("opendesign_daemon_url") or "").strip().rstrip("/")
    config["opendesign_web_url"] = str(config.get("opendesign_web_url") or "").strip()
    config["opendesign_auth_token"] = str(config.get("opendesign_auth_token") or "").strip()
    config["opendesign_app_path"] = str(config.get("opendesign_app_path") or "").strip()
    config["opendesign_auto_start"] = bool(config.get("opendesign_auto_start"))
    claude_mode = str(config.get("claude_credential_mode") or "cli_login").strip()
    config["claude_credential_mode"] = claude_mode if claude_mode in _CREDENTIAL_MODES else "cli_login"
    config["anthropic_base_url"] = str(config.get("anthropic_base_url") or "").strip()
    config["anthropic_model"] = str(config.get("anthropic_model") or "").strip()
    config["anthropic_api_key"] = str(config.get("anthropic_api_key") or "").strip()
    codex_mode = str(config.get("codex_credential_mode") or "cli_login").strip()
    config["codex_credential_mode"] = codex_mode if codex_mode in _CREDENTIAL_MODES else "cli_login"
    config["codex_base_url"] = str(config.get("codex_base_url") or "").strip()
    config["codex_model"] = str(config.get("codex_model") or "").strip()
    config["codex_api_key"] = str(config.get("codex_api_key") or "").strip()
    return config


def _file_in_scopes(path: str, scopes: list[str]) -> bool:
    rel = _normalize_scope(path)
    for scope in scopes:
        normalized = _normalize_scope(scope)
        if normalized in {".", "*"}:
            return True
        if rel == normalized or rel.startswith(f"{normalized}/"):
            return True
    return False


def _provider_status(
    *,
    provider_id: str,
    display_name: str,
    role: str,
    availability: str,
    version: str = "",
    executable_path: str = "",
    blocking_reason: str = "",
    install_hint: str = "",
    auth_hint: str = "",
    docs_url: str = "",
    risk_level: str = "medium",
    capabilities: dict[str, Any] | None = None,
    installable: bool = False,
    installed: bool = False,
    auth_required: bool = False,
    actions: list[dict[str, Any]] | None = None,
    install_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "display_name": display_name,
        "role": role,
        "availability": availability,
        "version": version,
        "executable_path": executable_path,
        "blocking_reason": blocking_reason,
        "install_hint": install_hint,
        "auth_hint": auth_hint,
        "docs_url": docs_url,
        "can_install_from_ui": installable,
        "can_open_docs": bool(docs_url),
        "installable": installable,
        "installed": installed,
        "auth_required": auth_required,
        "actions": actions or [],
        "install_progress": install_progress or {},
        "risk_level": risk_level,
        "capabilities": capabilities or {},
    }


def _open_url_command(url: str) -> str:
    quoted = shlex.quote(url)
    if platform.system() == "Darwin":
        return f"open {quoted}"
    if platform.system() == "Linux":
        return f"xdg-open {quoted}"
    return f"Open this URL manually: {url}"


def _shell_argv(command: str) -> tuple[str, ...]:
    shell = "/bin/zsh" if platform.system() == "Darwin" and Path("/bin/zsh").exists() else "/bin/bash"
    return (shell, "-lc", command)


def _node24_shell_prelude() -> str:
    return (
        'if [ -s "$HOME/.nvm/nvm.sh" ]; then . "$HOME/.nvm/nvm.sh"; nvm install 24; nvm use 24; fi\n'
        'NODE_MAJOR="$(node -p \'process.versions.node.split(".")[0]\' 2>/dev/null || echo 0)"\n'
        'if [ "$NODE_MAJOR" -lt 24 ]; then\n'
        '  echo "OpenDesign 需要 Node 24；请先安装/切换 Node 24，例如：nvm install 24 && nvm use 24";\n'
        "  exit 1\n"
        "fi\n"
        "corepack enable\n"
        "corepack pnpm --version\n"
    )


def _looks_like_opendesign_source_dir(path: Path) -> bool:
    return path.is_dir() and (path / "package.json").exists() and (
        (path / "tools-dev").exists()
        or (path / "pnpm-lock.yaml").exists()
        or (path / "apps").exists()
    )


def _opendesign_launch_command(path: str) -> str:
    candidate = Path(path).expanduser() if path else Path()
    if path and platform.system() == "Darwin" and candidate.suffix == ".app":
        return f"open {shlex.quote(str(candidate))}"
    if path and _looks_like_opendesign_source_dir(candidate):
        return f"{_node24_shell_prelude()}cd {shlex.quote(str(candidate))}\npnpm install\npnpm tools-dev run web"
    if path and candidate.exists():
        return shlex.quote(str(candidate))
    return _open_url_command(_OPENDESIGN_RELEASES_URL)


def _opendesign_install_command(path: str) -> str:
    target = Path(path).expanduser() if path else get_yachiyo_workspace_dir() / "external" / "open-design"
    parent = target.parent
    return "\n".join(
        [
            "set -e",
            'echo "Hermes-Yachiyo OpenDesign managed install"',
            _node24_shell_prelude(),
            f"mkdir -p {shlex.quote(str(parent))}",
            f"if [ ! -d {shlex.quote(str(target / '.git'))} ]; then",
            f"  git clone https://github.com/nexu-io/open-design.git {shlex.quote(str(target))}",
            "fi",
            f"cd {shlex.quote(str(target))}",
            "pnpm install",
            'echo "OpenDesign 已安装到 Yachiyo 管辖目录。回到 Coding 页面重新检测，然后启动后台 daemon。"',
        ]
    )


def _opendesign_stop_command(path: str) -> str:
    candidate = Path(path).expanduser() if path else Path()
    if path and _looks_like_opendesign_source_dir(candidate):
        return f"{_node24_shell_prelude()}cd {shlex.quote(str(candidate))}\npnpm tools-dev stop"
    return "echo 'OpenDesign desktop daemon should be stopped from the OpenDesign app.'"


def _opendesign_upgrade_command(path: str) -> str:
    candidate = Path(path).expanduser() if path else Path()
    if path and _looks_like_opendesign_source_dir(candidate):
        return "\n".join(
            [
                "set -e",
                'echo "Hermes-Yachiyo OpenDesign managed upgrade"',
                _node24_shell_prelude(),
                f"cd {shlex.quote(str(candidate))}",
                "git fetch origin --prune",
                'LOCAL_COMMIT="$(git rev-parse HEAD)"',
                'UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"',
                'if [ -n "$UPSTREAM" ]; then',
                '  REMOTE_COMMIT="$(git rev-parse "$UPSTREAM")"',
                "else",
                '  DEFAULT_BRANCH="$(git remote show origin | awk \'/HEAD branch/ {print $NF}\')"',
                '  REMOTE_COMMIT="$(git rev-parse "origin/${DEFAULT_BRANCH:-main}")"',
                "fi",
                'echo "Local commit:  $LOCAL_COMMIT"',
                'echo "Remote commit: $REMOTE_COMMIT"',
                'if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then',
                '  echo "OpenDesign already up to date."',
                "else",
                "  pnpm tools-dev stop || true",
                "  git pull --ff-only",
                "fi",
                "pnpm tools-dev stop || true",
                "pnpm install",
            ]
        )
    return _open_url_command(_OPENDESIGN_RELEASES_URL)


def _provider_actions(provider_id: str, installed: bool) -> list[dict[str, Any]]:
    if provider_id == "local_claude_code":
        actions = [
            {
                "id": "upgrade",
                "label": "检查最新版本并升级",
                "kind": "command",
                "available": installed,
                "command_preview": "claude update",
                "confirmation": "将执行白名单命令检查并升级 Claude Code CLI。",
            },
            {
                "id": "auth",
                "label": "打开 Claude 登录",
                "kind": "terminal",
                "available": installed,
                "confirmation": "将在系统终端打开固定命令：claude",
            }
        ]
        if not installed:
            actions.insert(
                0,
                {
                    "id": "install",
                    "label": "安装 Claude Code",
                    "kind": "command",
                    "available": platform.system() != "Windows",
                    "command_preview": "npm install -g @anthropic-ai/claude-code",
                    "confirmation": "将执行白名单命令安装 Claude Code CLI。",
                },
            )
        return actions
    if provider_id == "codex_review":
        actions = [
            {
                "id": "install",
                "label": "安装 Codex CLI",
                "kind": "command",
                "available": platform.system() != "Windows" and not installed,
                "command_preview": "npm install -g @openai/codex",
                "confirmation": "将执行白名单命令安装 Codex CLI。",
            },
            {
                "id": "upgrade",
                "label": "检查最新版本并升级",
                "kind": "command",
                "available": platform.system() != "Windows" and installed,
                "command_preview": "codex update",
                "confirmation": "将执行白名单命令检查并升级 Codex CLI。",
            },
            {
                "id": "auth",
                "label": "打开 Codex 登录",
                "kind": "terminal",
                "available": installed,
                "confirmation": "将在系统终端打开固定命令：codex login",
            },
        ]
        return actions
    if provider_id == "opendesign":
        actions = [
            {
                "id": "scan",
                "label": "检查全局 OpenDesign 项目",
                "kind": "command",
                "available": True,
                "command_preview": "scan ~/dev, ~/Developer, ~/Projects, Yachiyo managed path, PATH and running daemon",
                "confirmation": "将扫描本机常见目录、PATH 与本地 daemon health，不会执行任意 shell 命令。",
            },
            {
                "id": "install",
                "label": "安装到 Yachiyo 管辖目录",
                "kind": "command",
                "available": not installed,
                "command_preview": "nvm install/use 24 && corepack enable && git clone open-design && pnpm install",
                "confirmation": "将在 Yachiyo 管辖目录 clone OpenDesign、准备 Node 24/corepack 并执行 pnpm install。",
            },
            {
                "id": "start",
                "label": "一键启动 daemon",
                "kind": "command",
                "available": installed,
                "command_preview": "nvm install/use 24 && corepack enable && pnpm install && pnpm tools-dev run web",
                "confirmation": "将使用检测到的 OpenDesign 源码目录后台启动 web + daemon 服务。",
            },
            {
                "id": "open_web",
                "label": "打开 WebUI",
                "kind": "command",
                "available": installed,
                "command_preview": "open OpenDesign WebUI",
                "confirmation": "将打开 OpenDesign Web URL；如果尚未启动，请先一键启动 daemon。",
            },
            {
                "id": "upgrade",
                "label": "检查最新版本并升级",
                "kind": "command",
                "available": installed,
                "command_preview": "git pull --ff-only && pnpm install",
                "confirmation": "将检查远端更新并执行 git pull/pnpm install，日志会显示进度。",
            },
        ]
        return actions
    return []


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _version_at_least(value: str, minimum: str) -> bool:
    parsed = _parse_semver(value)
    required = _parse_semver(minimum)
    if not parsed or not required:
        return False
    return parsed >= required


def _api_url(base_url: str, suffix: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/{suffix.lstrip('/')}"


def _json_api_request(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = _PROVIDER_API_TEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4096).decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 300,
                "status": int(response.status),
                "detail": _compact(_redact_text(raw), limit=280),
            }
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(4096).decode("utf-8", errors="replace")
        except OSError:
            raw = ""
        return {
            "ok": False,
            "status": int(exc.code),
            "detail": _compact(_redact_text(raw), limit=280) or exc.reason,
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "detail": _compact(str(exc.reason), limit=280)}
    except (OSError, TimeoutError) as exc:
        return {"ok": False, "status": 0, "detail": _compact(str(exc), limit=280)}


def _api_check(label: str, result: dict[str, Any], *, warn_on_fail: bool = False) -> dict[str, str]:
    status = "pass" if result.get("ok") else "warn" if warn_on_fail else "fail"
    http_status = result.get("status")
    detail = str(result.get("detail") or "")
    if http_status:
        detail = f"HTTP {http_status}" + (f" · {detail}" if detail else "")
    return {"label": label, "status": status, "detail": detail or ("通过" if status == "pass" else "未通过")}


def _skipped_api_check(label: str, detail: str) -> dict[str, str]:
    return {"label": label, "status": "warn", "detail": detail}


def _provider_action_spec(provider_id: str, action: str, executable_path: str = "") -> ProviderActionSpec:
    provider_id = str(provider_id or "").strip()
    action = str(action or "install").strip()
    if provider_id == "local_claude_code" and action == "install":
        return ProviderActionSpec(
            action="install",
            label="安装 Claude Code",
            kind="command",
            argv=("npm", "install", "-g", "@anthropic-ai/claude-code"),
            confirmation="将执行白名单命令：npm install -g @anthropic-ai/claude-code",
        )
    if provider_id == "local_claude_code" and action == "auth":
        return ProviderActionSpec(
            action="auth",
            label="打开 Claude 登录",
            kind="terminal",
            terminal_command="claude",
            confirmation="将在系统终端打开固定命令：claude",
        )
    if provider_id == "local_claude_code" and action == "upgrade":
        executable = executable_path or shutil.which("claude") or "claude"
        return ProviderActionSpec(
            action="upgrade",
            label="检查最新版本并升级",
            kind="command",
            argv=(executable, "update"),
            confirmation="将执行白名单命令检查并升级 Claude Code CLI：claude update",
        )
    if provider_id == "codex_review" and action == "install":
        return ProviderActionSpec(
            action="install",
            label="安装 Codex CLI",
            kind="command",
            argv=("npm", "install", "-g", "@openai/codex"),
            confirmation="将执行白名单命令：npm install -g @openai/codex",
        )
    if provider_id == "codex_review" and action == "upgrade":
        executable = executable_path or shutil.which("codex") or "codex"
        return ProviderActionSpec(
            action="upgrade",
            label="检查最新版本并升级",
            kind="command",
            argv=(executable, "update"),
            confirmation="将执行白名单命令检查并升级 Codex CLI：codex update",
        )
    if provider_id == "codex_review" and action == "auth":
        return ProviderActionSpec(
            action="auth",
            label="打开 Codex 登录",
            kind="terminal",
            terminal_command="codex login",
            confirmation="将在系统终端打开固定命令：codex login",
        )
    if provider_id == "opendesign" and action == "upgrade":
        return ProviderActionSpec(
            action="upgrade",
            label="检查最新版本并升级",
            kind="opendesign_upgrade",
            terminal_command=executable_path,
            confirmation="仅支持 Yachiyo 管辖目录中的 OpenDesign；将对比 GitHub 远端 commit，必要时 pull、安装依赖并重启 daemon。",
        )
    if provider_id == "opendesign" and action == "scan":
        return ProviderActionSpec(
            action="scan",
            label="检查全局 OpenDesign 项目",
            kind="opendesign_scan",
            confirmation="将扫描本机常见目录、PATH 与本地 daemon health。",
        )
    if provider_id == "opendesign" and action == "install":
        return ProviderActionSpec(
            action="install",
            label="安装 OpenDesign",
            kind="command",
            argv=_shell_argv(_opendesign_install_command(executable_path)),
            confirmation="将在 Yachiyo 管辖目录 clone OpenDesign、准备 Node 24/corepack 并执行 pnpm install。",
        )
    if provider_id == "opendesign" and action == "start":
        return ProviderActionSpec(
            action="start",
            label="启动后台 daemon",
            kind="opendesign_start",
            terminal_command=executable_path,
            confirmation="将用已配置/检测到的 OpenDesign 路径后台启动 web + daemon。",
        )
    if provider_id == "opendesign" and action == "stop":
        return ProviderActionSpec(
            action="stop",
            label="停止 daemon",
            kind="command",
            argv=_shell_argv(_opendesign_stop_command(executable_path)),
            confirmation="如果 OpenDesign 是源码目录，将执行 pnpm tools-dev stop；桌面应用请在 OpenDesign 内退出。",
        )
    if provider_id == "opendesign" and action == "restart":
        return ProviderActionSpec(
            action="restart",
            label="重启 daemon",
            kind="command",
            argv=_shell_argv(f"{_opendesign_stop_command(executable_path)} && {_opendesign_launch_command(executable_path)}"),
            confirmation="将重启已配置/检测到的 OpenDesign daemon。",
        )
    if provider_id == "opendesign" and action == "open_web":
        url = executable_path if executable_path.startswith(("http://", "https://")) else ""
        return ProviderActionSpec(
            action="open_web",
            label="打开 WebUI",
            kind="command" if url else "noop",
            argv=_shell_argv(_open_url_command(url)) if url else (),
            terminal_command="" if url else "OpenDesign WebUI URL unavailable. Start the daemon first.",
            confirmation="将打开已配置的 OpenDesign WebUI URL。",
        )
    raise CodingExecutionError("不支持的 provider 安装动作")


def _secret_config_response(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    for key in ("anthropic_api_key", "codex_api_key", "opendesign_auth_token"):
        value = str(result.get(key) or "")
        result[key] = value if not value else "[configured]"
        result[f"{key}_configured"] = bool(value)
    return result


def parse_start_code_command(text: str, defaults: dict[str, Any] | None = None) -> dict[str, Any] | None:
    raw_text = str(text or "").strip()
    if not raw_text:
        return None
    first_line, separator, rest = raw_text.partition("\n")
    if not first_line.strip().startswith("/start-code"):
        return None
    try:
        tokens = shlex.split(first_line)
    except ValueError as exc:
        return {"ok": False, "error": f"/start-code 参数解析失败：{exc}", "needs_config": False}
    if not tokens or tokens[0] != "/start-code":
        return None

    config = _sanitize_config(defaults or {})
    request: dict[str, Any] = {
        "repo_path": config["default_repo_path"],
        "writable_scopes": list(config["default_writable_scopes"]),
        "preferred_provider": config["default_provider"],
        "review_strategy": config["default_review_strategy"],
        "task_type": "custom",
        "design_mode": config["default_design_mode"],
    }
    inline_body: list[str] = []
    expects_value = {"--repo", "--scope", "--provider", "--review", "--task", "--design"}
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in expects_value:
            if index + 1 >= len(tokens):
                return {"ok": False, "error": f"{token} 缺少参数值", "needs_config": False}
            value = tokens[index + 1]
            if token == "--repo":
                request["repo_path"] = value
            elif token == "--scope":
                request["writable_scopes"] = _split_scopes(value)
            elif token == "--provider":
                if value not in _CODING_PROVIDERS:
                    return {"ok": False, "error": f"不支持的 coding provider：{value}", "needs_config": False}
                request["preferred_provider"] = value
            elif token == "--review":
                if value not in _REVIEW_STRATEGIES:
                    return {"ok": False, "error": f"不支持的 review strategy：{value}", "needs_config": False}
                request["review_strategy"] = value
            elif token == "--task":
                if value not in _TASK_TYPES:
                    return {"ok": False, "error": f"不支持的 task type：{value}", "needs_config": False}
                request["task_type"] = value
            elif token == "--design":
                if value not in _DESIGN_MODES:
                    return {"ok": False, "error": f"不支持的 design mode：{value}", "needs_config": False}
                request["design_mode"] = value
            index += 2
            continue
        if token.startswith("--"):
            return {"ok": False, "error": f"未知 /start-code 参数：{token}", "needs_config": False}
        inline_body.append(token)
        index += 1

    body_parts = []
    if inline_body:
        body_parts.append(" ".join(inline_body).strip())
    if separator and rest.strip():
        body_parts.append(rest.strip())
    user_request = "\n".join(part for part in body_parts if part).strip()
    if not user_request:
        return {"ok": False, "error": "/start-code 需要提供需求正文", "needs_config": False}
    if not str(request.get("repo_path") or "").strip():
        return {
            "ok": False,
            "error": "缺少 repo path。请在 Coding > Defaults 配置默认仓库，或使用 --repo <path>。",
            "needs_config": True,
        }

    request["user_request"] = user_request
    request["repo_path"] = str(request["repo_path"]).strip()
    request["writable_scopes"] = _split_scopes(request.get("writable_scopes"))
    return {"ok": True, "request": request}


class CodingExecutionService:
    """Persistent, backend-controlled coding job service."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        workspace_dir: str | Path | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._workspace = Path(workspace_dir).expanduser() if workspace_dir else _workspace_dir()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(db_path).expanduser() if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path = Path(config_path).expanduser() if config_path else self._workspace / _CONFIG_FILENAME
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_flags: set[str] = set()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._install_threads: dict[str, threading.Thread] = {}
        self._install_processes: dict[str, subprocess.Popen[str]] = {}
        self._installs: dict[str, dict[str, Any]] = {}
        self._opendesign_process: subprocess.Popen[str] | None = None
        self._init_db()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS coding_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    preferred_provider TEXT NOT NULL DEFAULT '',
                    selected_provider TEXT NOT NULL DEFAULT '',
                    review_strategy TEXT NOT NULL DEFAULT 'codex_if_available',
                    selected_review_provider TEXT NOT NULL DEFAULT '',
                    design_mode TEXT NOT NULL DEFAULT 'none',
                    writable_scopes_json TEXT NOT NULL DEFAULT '[]',
                    readonly_scopes_json TEXT NOT NULL DEFAULT '[]',
                    branch_name TEXT NOT NULL DEFAULT '',
                    original_branch TEXT NOT NULL DEFAULT '',
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    requires_approval INTEGER NOT NULL DEFAULT 1,
                    plan_summary TEXT NOT NULL DEFAULT '',
                    blockers_json TEXT NOT NULL DEFAULT '[]',
                    fallback_options_json TEXT NOT NULL DEFAULT '[]',
                    dirty_summary_json TEXT NOT NULL DEFAULT '{}',
                    changed_files_json TEXT NOT NULL DEFAULT '[]',
                    artifacts_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_coding_jobs_updated
                    ON coding_jobs(updated_at);
                """
            )
            conn.commit()
        logger.info("CodingExecutionService 初始化完成: %s", self._db_path)

    # Config ------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            if not self._config_path.exists():
                return {"ok": True, **_secret_config_response(dict(_DEFAULT_CODING_CONFIG)), "config_path": str(self._config_path)}
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            config = _sanitize_config(data if isinstance(data, dict) else {})
            return {"ok": True, **_secret_config_response(config), "config_path": str(self._config_path)}

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self._read_config_private()
            merged = {key: current.get(key) for key in _DEFAULT_CODING_CONFIG}
            merged.update({key: changes.get(key) for key in _DEFAULT_CODING_CONFIG if key in changes})
            for key in ("anthropic_api_key", "codex_api_key", "opendesign_auth_token"):
                if changes.get(key) == "[configured]":
                    merged[key] = current.get(key, "")
            config = _sanitize_config(merged)
            tmp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
            tmp_path.write_text(_json(config), encoding="utf-8")
            tmp_path.replace(self._config_path)
            return {"ok": True, **_secret_config_response(config), "config_path": str(self._config_path)}

    def _read_config_private(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return dict(_DEFAULT_CODING_CONFIG)
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        return _sanitize_config(data if isinstance(data, dict) else {})

    # Provider registry -------------------------------------------------

    def provider_statuses(self) -> list[dict[str, Any]]:
        return [
            self.health_check_provider("local_claude_code"),
            self.health_check_provider("opendesign"),
        ]

    def review_provider_statuses(self) -> list[dict[str, Any]]:
        return [
            self.health_check_provider("codex_review"),
        ]

    def health_check_provider(self, provider_id: str) -> dict[str, Any]:
        provider_id = str(provider_id or "").strip()
        if provider_id == "local_claude_code":
            return self._health_claude_code()
        if provider_id == "codex_review":
            return self._health_codex_review()
        if provider_id == "manual_review":
            return _provider_status(
                provider_id="manual_review",
                display_name="Manual Review",
                role="review",
                availability="available",
                installed=True,
                blocking_reason="",
                risk_level="low",
                capabilities={"checklist": True, "agentless": True},
            )
        if provider_id in {"mock", "noop", "noop/mock", "noop_review"}:
            return _provider_status(
                provider_id="mock" if provider_id != "noop_review" else "noop_review",
                display_name="Mock Provider" if provider_id != "noop_review" else "Noop Review",
                role="mock" if provider_id != "noop_review" else "review",
                availability="available",
                installed=True,
                risk_level="low",
                capabilities={"test_only": True},
            )
        if provider_id == "hapi":
            return _provider_status(
                provider_id="hapi",
                display_name="Hapi Coding Backend",
                role="coding",
                availability="misconfigured",
                blocking_reason="Hapi 外置 coding execution backend 尚未配置；Phase 4 MVP 不依赖它。",
                install_hint="后续可在集成设置中配置 Hapi URL。",
                docs_url="",
                risk_level="high",
                actions=[],
            )
        if provider_id == "opendesign":
            config = self._read_config_private()
            install_info = self._detect_opendesign_install(config)
            daemon = self._probe_opendesign_daemon(config, discover=True)
            installed = bool(install_info.get("installed"))
            reachable = bool(daemon.get("reachable"))
            artifact_dir = str(config.get("opendesign_artifact_dir") or "").strip()
            artifact_ready = bool(artifact_dir and Path(artifact_dir).expanduser().exists())
            daemon_base_url = str(daemon.get("base_url") or config.get("opendesign_daemon_url") or "").strip()
            web_url = str(daemon.get("web_url") or config.get("opendesign_web_url") or "").strip()
            app_path = str(install_info.get("path") or "")
            managed_path = self._managed_opendesign_dir()
            managed_installed = _looks_like_opendesign_source_dir(managed_path)
            app_source_dir = bool(app_path and _looks_like_opendesign_source_dir(Path(app_path).expanduser()))
            actions = _provider_actions("opendesign", installed=installed or reachable)
            for action in actions:
                action_id = str(action.get("id") or "")
                if action_id == "install":
                    action["available"] = platform.system() != "Windows" and not managed_installed
                elif action_id == "start":
                    action["available"] = app_source_dir
                elif action_id == "open_web":
                    action["available"] = bool(web_url)
                elif action_id == "upgrade":
                    action["available"] = platform.system() != "Windows" and managed_installed
            if reachable:
                availability = "available"
                blocking_reason = ""
            elif installed:
                availability = "installed_stopped"
                blocking_reason = "已检测到 OpenDesign，但 daemon 未连接。请启动后台 daemon，或确认 Daemon URL。"
            elif config.get("opendesign_daemon_url"):
                availability = "unhealthy"
                blocking_reason = "已配置 OpenDesign Daemon URL，但 /api/health 不可达。请先手动启动 OpenDesign，或修正 URL。"
            else:
                availability = "not_installed"
                blocking_reason = "未检测到 OpenDesign。可安装桌面版/源码版，或配置已运行的 OpenDesign Daemon URL。"
            return _provider_status(
                provider_id="opendesign",
                display_name="OpenDesign Daemon",
                role="design",
                availability=availability,
                version=str(daemon.get("version") or install_info.get("version") or ""),
                executable_path=app_path,
                blocking_reason=blocking_reason,
                install_hint="OpenDesign 是 web app + local daemon。Yachiyo 通过 HTTP/SSE 连接 daemon；manual artifact import 只作为 fallback。",
                docs_url=_OPENDESIGN_DEFAULT_DOCS_URL,
                risk_level="medium",
                installed=installed,
                installable=platform.system() != "Windows",
                capabilities={
                    "optional": True,
                    "direct_execution": True,
                    "mode": "daemon_bridge",
                    "daemon_url": daemon_base_url,
                    "web_url": web_url,
                    "daemon_reachable": reachable,
                    "daemon_status": daemon,
                    "app_path": app_path,
                    "app_detected": installed,
                    "app_source": str(install_info.get("source") or ""),
                    "managed_path": str(managed_path),
                    "managed_installed": managed_installed,
                    "scan_candidates": install_info.get("candidates") or [],
                    "supports_sse": True,
                    "manual_artifact_import_available": artifact_ready,
                    "artifact_dir_configured": bool(artifact_dir),
                    "artifact_dir_exists": artifact_ready,
                },
                actions=actions,
            )
        if provider_id == "same_provider_review":
            return _provider_status(
                provider_id="same_provider_review",
                display_name="Same Provider Review",
                role="review",
                availability="misconfigured",
                blocking_reason="需要完成 coding provider 执行后才能判断是否可用。",
                risk_level="medium",
            )
        if provider_id == "hermes_review":
            return _provider_status(
                provider_id="hermes_review",
                display_name="Hermes Review",
                role="review",
                availability="misconfigured",
                blocking_reason="Hermes prompt-based diff review 留作后续接入；MVP 使用 manual review 兜底。",
                risk_level="medium",
            )
        return _provider_status(
            provider_id=provider_id or "unknown",
            display_name=provider_id or "Unknown",
            role="mock",
            availability="unknown_error",
            blocking_reason="未知 provider",
            risk_level="medium",
        )

    def _health_claude_code(self) -> dict[str, Any]:
        path = self._which_command("claude")
        config = self._read_config_private()
        credential_mode = str(config.get("claude_credential_mode") or "cli_login")
        use_api_env = credential_mode == "api_env"
        env_configured = bool(config.get("anthropic_api_key"))
        if not path:
            return _provider_status(
                provider_id="local_claude_code",
                display_name="Claude Code CLI",
                role="coding",
                availability="not_installed",
                blocking_reason="未检测到 claude 命令。",
                install_hint="请先按 Claude Code 官方文档安装 CLI；之后可选择登录或配置 Anthropic API。",
                docs_url="https://docs.claude.com/en/docs/claude-code/setup?office=4001217008",
                risk_level="high",
                installable=platform.system() != "Windows",
                installed=False,
                auth_required=credential_mode == "cli_login",
                auth_hint=self._credential_hint("local_claude_code", credential_mode, env_configured),
                actions=_provider_actions("local_claude_code", installed=False),
                capabilities={
                    "headless": False,
                    "credential_mode": credential_mode,
                    "isolated_auth": use_api_env,
                    "anthropic_env_configured": env_configured,
                    "anthropic_base_url_configured": bool(config.get("anthropic_base_url")),
                    "anthropic_model": str(config.get("anthropic_model") or ""),
                },
            )
        version = self._probe_version([path, "--version"])
        help_text = self._probe_help([path, "--help"])
        headless_flag = "-p" if re.search(r"(^|\s)-p(?:,|\s|$)", help_text) else ""
        if not headless_flag and "--print" in help_text:
            headless_flag = "--print"
        if not headless_flag:
            return _provider_status(
                provider_id="local_claude_code",
                display_name="Claude Code CLI",
                role="coding",
                availability="misconfigured",
                version=version,
                executable_path=path,
                blocking_reason="当前 claude --help 未暴露可用的 headless/print 参数。",
                risk_level="high",
                installable=True,
                installed=True,
                auth_required=credential_mode == "cli_login",
                auth_hint=self._credential_hint("local_claude_code", credential_mode, env_configured),
                actions=_provider_actions("local_claude_code", installed=True),
                capabilities={
                    "headless": False,
                    "credential_mode": credential_mode,
                    "isolated_auth": use_api_env,
                    "bare": "--bare" in help_text,
                    "anthropic_env_configured": env_configured,
                    "anthropic_base_url_configured": bool(config.get("anthropic_base_url")),
                    "anthropic_model": str(config.get("anthropic_model") or ""),
                },
            )
        if use_api_env and not env_configured:
            return _provider_status(
                provider_id="local_claude_code",
                display_name="Claude Code CLI",
                role="coding",
                availability="misconfigured",
                version=version,
                executable_path=path,
                blocking_reason="当前选择 API Env 模式，但未配置 ANTHROPIC_API_KEY。",
                auth_hint=self._credential_hint("local_claude_code", credential_mode, env_configured),
                docs_url="https://docs.claude.com/en/docs/claude-code/setup?office=4001217008",
                risk_level="high",
                installable=True,
                installed=True,
                auth_required=False,
                actions=_provider_actions("local_claude_code", installed=True),
                capabilities={
                    "headless": True,
                    "headless_flag": headless_flag,
                    "credential_mode": credential_mode,
                    "isolated_auth": True,
                    "bare": "--bare" in help_text,
                    "anthropic_env_configured": False,
                    "anthropic_base_url_configured": bool(config.get("anthropic_base_url")),
                    "anthropic_model": str(config.get("anthropic_model") or ""),
                },
            )
        auth_status = None
        if not use_api_env:
            auth_status = self._probe_claude_auth(path)
            if not auth_status.get("logged_in"):
                return _provider_status(
                    provider_id="local_claude_code",
                    display_name="Claude Code CLI",
                    role="coding",
                    availability="not_authenticated",
                    version=version,
                    executable_path=path,
                    blocking_reason="未检测到 Claude Code 登录态。请点击“打开 Claude 登录”完成登录，或切换到 API Env 模式。",
                    auth_hint=self._credential_hint("local_claude_code", credential_mode, env_configured),
                    docs_url="https://docs.claude.com/en/docs/claude-code/setup?office=4001217008",
                    risk_level="high",
                    installable=True,
                    installed=True,
                    auth_required=True,
                    actions=_provider_actions("local_claude_code", installed=True),
                    capabilities={
                        "headless": True,
                        "headless_flag": headless_flag,
                        "credential_mode": credential_mode,
                        "isolated_auth": False,
                        "output_format": "--output-format" in help_text,
                        "allowed_tools": "--allowedTools" in help_text,
                        "bare": "--bare" in help_text,
                        "anthropic_env_configured": env_configured,
                        "anthropic_base_url_configured": bool(config.get("anthropic_base_url")),
                        "anthropic_model": str(config.get("anthropic_model") or ""),
                        "auth_status": auth_status,
                    },
                )
        return _provider_status(
            provider_id="local_claude_code",
            display_name="Claude Code CLI",
            role="coding",
            availability="available",
            version=version,
            executable_path=path,
            auth_hint=self._credential_hint("local_claude_code", credential_mode, env_configured),
            docs_url="https://docs.claude.com/en/docs/claude-code/setup?office=4001217008",
            risk_level="high",
            installable=True,
            installed=True,
            auth_required=credential_mode == "cli_login",
            actions=_provider_actions("local_claude_code", installed=True),
            capabilities={
                "headless": True,
                "headless_flag": headless_flag,
                "credential_mode": credential_mode,
                "isolated_auth": use_api_env,
                "output_format": "--output-format" in help_text,
                "allowed_tools": "--allowedTools" in help_text,
                "bare": "--bare" in help_text,
                "anthropic_env_configured": env_configured,
                "anthropic_base_url_configured": bool(config.get("anthropic_base_url")),
                "anthropic_model": str(config.get("anthropic_model") or ""),
                "auth_status": auth_status or {"checked": False, "logged_in": False},
            },
        )

    def _health_codex_review(self) -> dict[str, Any]:
        path = self._which_command("codex")
        config = self._read_config_private()
        credential_mode = str(config.get("codex_credential_mode") or "cli_login")
        use_api_env = credential_mode == "api_env"
        env_configured = bool(config.get("codex_api_key"))
        if not path:
            return _provider_status(
                provider_id="codex_review",
                display_name="Codex CLI",
                role="review",
                availability="not_installed",
                blocking_reason="未检测到 codex 命令。",
                install_hint="请先安装 Codex CLI；未安装时 review 会降级到 manual_review。",
                docs_url="https://help.openai.com/en/articles/11096431",
                risk_level="medium",
                installable=platform.system() != "Windows",
                installed=False,
                auth_required=credential_mode == "cli_login",
                auth_hint=self._credential_hint("codex_review", credential_mode, env_configured),
                actions=_provider_actions("codex_review", installed=False),
                capabilities={
                    "review_uncommitted": False,
                    "credential_mode": credential_mode,
                    "isolated_auth": use_api_env,
                    "codex_env_configured": env_configured,
                    "codex_base_url_configured": bool(config.get("codex_base_url")),
                    "codex_model": str(config.get("codex_model") or ""),
                    "app_server_command": False,
                    "app_server_min_version": "0.130.0",
                    "app_server_version_ready": False,
                    "app_server_runtime_ready": False,
                    "app_server_status": "未检测到 Codex CLI",
                    "api_responses_required": True,
                },
            )
        version = self._probe_version([path, "--version"])
        main_help = self._probe_help([path, "--help"])
        help_text = self._probe_help([path, "review", "--help"])
        review_uncommitted = "--uncommitted" in help_text
        app_server_command = "app-server" in main_help
        app_server_min_version = "0.130.0"
        app_server_version_ready = _version_at_least(version, app_server_min_version)
        app_server_runtime_ready = app_server_command and app_server_version_ready
        availability = "available" if review_uncommitted else "misconfigured"
        blocking_reason = "" if review_uncommitted else "当前 Codex CLI 未暴露 review --uncommitted 能力。"
        auth_status = None
        if review_uncommitted and use_api_env and not env_configured:
            availability = "misconfigured"
            blocking_reason = "当前选择 API Env 模式，但未配置 OPENAI_API_KEY。"
        elif review_uncommitted and not use_api_env:
            auth_status = self._probe_codex_auth(path)
            if not auth_status.get("logged_in"):
                availability = "not_authenticated"
                blocking_reason = "未检测到 Codex CLI 登录态。请点击“打开 Codex 登录”完成登录，或切换到 API Env 模式。"
        return _provider_status(
            provider_id="codex_review",
            display_name="Codex CLI",
            role="review",
            availability=availability,
            version=version,
            executable_path=path,
            blocking_reason=blocking_reason,
            auth_hint=self._credential_hint("codex_review", credential_mode, env_configured),
            docs_url="https://help.openai.com/en/articles/11096431",
            risk_level="medium",
            installable=True,
            installed=True,
            auth_required=credential_mode == "cli_login",
            actions=_provider_actions("codex_review", installed=True),
            capabilities={
                "review_uncommitted": review_uncommitted,
                "review_base": "--base" in help_text,
                "review_commit": "--commit" in help_text,
                "credential_mode": credential_mode,
                "isolated_auth": use_api_env,
                "codex_env_configured": env_configured,
                "codex_base_url_configured": bool(config.get("codex_base_url")),
                "codex_model": str(config.get("codex_model") or ""),
                "auth_status": auth_status or {"checked": False, "logged_in": False},
                "app_server_command": app_server_command,
                "app_server_min_version": app_server_min_version,
                "app_server_version_ready": app_server_version_ready,
                "app_server_runtime_ready": app_server_runtime_ready,
                "app_server_status": (
                    "ready"
                    if app_server_runtime_ready
                    else f"需要 Codex CLI {app_server_min_version}+ 并完成 codex login"
                    if app_server_command
                    else "当前 Codex CLI 未暴露 app-server 命令"
                ),
                "api_responses_required": True,
            },
        )

    def _probe_claude_auth(self, path: str) -> dict[str, Any]:
        result = self._run_quick([path, "auth", "status"])
        output = (result.stdout or result.stderr or "").strip()
        auth_status: dict[str, Any] = {
            "checked": True,
            "logged_in": result.returncode == 0,
            "returncode": result.returncode,
            "summary": _compact(output, limit=240),
        }
        if output:
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                auth_status["logged_in"] = bool(data.get("loggedIn"))
                auth_status["auth_method"] = str(data.get("authMethod") or "")
                auth_status["api_provider"] = str(data.get("apiProvider") or "")
        return auth_status

    def _probe_codex_auth(self, path: str) -> dict[str, Any]:
        result = self._run_quick([path, "login", "status"])
        output = (result.stdout or result.stderr or "").strip()
        return {
            "checked": True,
            "logged_in": result.returncode == 0,
            "returncode": result.returncode,
            "summary": _compact(output, limit=240),
        }

    def _test_claude_api_env(self, config: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        api_key = str(config.get("anthropic_api_key") or "").strip()
        base_url = str(config.get("anthropic_base_url") or "https://api.anthropic.com").strip().rstrip("/")
        model = str(config.get("anthropic_model") or "").strip()
        if not api_key:
            return {
                "success": False,
                "checks": [{"label": "ANTHROPIC_API_KEY", "status": "fail", "detail": "未配置"}],
            }
        checks.append({"label": "ANTHROPIC_API_KEY", "status": "pass", "detail": "已配置"})
        if not model:
            checks.append(_skipped_api_check("Anthropic Messages", "请先填写模型名，再执行真实 API 测试"))
            return {"success": True, "checks": checks}
        result = _json_api_request(
            _api_url(base_url, "/v1/messages"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            body={
                "model": model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "reply only: pong"}],
            },
        )
        checks.append(_api_check("Anthropic Messages", result))
        return {
            "success": bool(result.get("ok")),
            "base_url": base_url,
            "model": model,
            "checks": checks,
        }

    def _test_codex_api_env(self, config: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        api_key = str(config.get("codex_api_key") or "").strip()
        base_url = str(config.get("codex_base_url") or "https://api.openai.com/v1").strip().rstrip("/")
        model = str(config.get("codex_model") or "").strip()
        if not api_key:
            return {
                "success": False,
                "models": False,
                "chat_completions": False,
                "responses": False,
                "codex_cli_compatible": False,
                "checks": [{"label": "OPENAI_API_KEY", "status": "fail", "detail": "未配置"}],
            }
        headers = {"Authorization": f"Bearer {api_key}"}
        checks.append({"label": "OPENAI_API_KEY", "status": "pass", "detail": "已配置"})
        models = _json_api_request(_api_url(base_url, "/models"), method="GET", headers=headers)
        checks.append(_api_check("OpenAI /models", models, warn_on_fail=True))

        chat_ok = False
        responses_ok = False
        if model:
            chat = _json_api_request(
                _api_url(base_url, "/chat/completions"),
                headers=headers,
                body={
                    "model": model,
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "reply only: pong"}],
                },
            )
            chat_ok = bool(chat.get("ok"))
            checks.append(_api_check("Chat Completions", chat, warn_on_fail=True))
            responses = _json_api_request(
                _api_url(base_url, "/responses"),
                headers=headers,
                body={"model": model, "input": "reply only: pong", "max_output_tokens": 8},
            )
            responses_ok = bool(responses.get("ok"))
            checks.append(_api_check("Responses API", responses))
        else:
            checks.append(_skipped_api_check("Chat Completions", "请先填写模型名，再执行真实 API 测试"))
            checks.append(_skipped_api_check("Responses API", "请先填写模型名；Codex CLI 需要 Responses API"))

        codex_cli_compatible = bool(responses_ok)
        checks.append(
            {
                "label": "Codex CLI API 兼容性",
                "status": "pass" if codex_cli_compatible else "fail",
                "detail": "Responses API 可用" if codex_cli_compatible else "当前网关不满足 Codex CLI 的 Responses API 要求",
            }
        )
        return {
            "success": codex_cli_compatible,
            "base_url": base_url,
            "model": model,
            "models": bool(models.get("ok")),
            "chat_completions": chat_ok,
            "responses": responses_ok,
            "codex_cli_compatible": codex_cli_compatible,
            "checks": checks,
        }

    def _detect_opendesign_install(self, config: dict[str, Any], *, deep: bool = False) -> dict[str, Any]:
        candidates = self._scan_opendesign_candidates(config, deep=deep)
        for item in candidates:
            source = str(item.get("source") or "")
            path = Path(str(item.get("path") or "")).expanduser()
            if path.exists() and (path.is_file() or path.suffix == ".app" or _looks_like_opendesign_source_dir(path)):
                return {"installed": True, "path": str(path), "source": source, "candidates": candidates}
        for command in ("open-design", "opendesign"):
            path = self._which_command(command)
            if path:
                return {"installed": True, "path": path, "source": "path", "candidates": candidates}
        return {"installed": False, "path": "", "source": "", "candidates": candidates}

    def _managed_opendesign_dir(self) -> Path:
        return self._workspace / "external" / "open-design"

    def _scan_opendesign_candidates(self, config: dict[str, Any], *, deep: bool = False) -> list[dict[str, str]]:
        candidates: list[tuple[str, Path]] = []
        configured = str(config.get("opendesign_app_path") or "").strip()
        if configured:
            candidates.append(("configured", Path(configured).expanduser()))
        candidates.extend(
            [
                ("source", Path.home() / "dev" / "open-design"),
                ("source", Path.home() / "Developer" / "open-design"),
                ("source", Path.home() / "Projects" / "open-design"),
                ("source", Path.home() / "open-design"),
                ("source", Path.cwd().parent / "open-design"),
            ]
        )
        candidates.append(("managed", self._managed_opendesign_dir()))
        if platform.system() == "Darwin":
            candidates.extend(
                [
                    ("macos_app", Path("/Applications/Open Design.app")),
                    ("macos_app", Path.home() / "Applications" / "Open Design.app"),
                ]
            )
        if platform.system() == "Linux":
            candidates.extend(
                [
                    ("linux_appimage", Path.home() / "Applications" / "Open Design.AppImage"),
                    ("linux_opt", Path("/opt/open-design/open-design")),
                ]
            )
        if platform.system() == "Darwin":
            candidates.extend(self._spotlight_opendesign_candidates())
        if deep:
            candidates.extend(self._find_opendesign_source_candidates())

        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for source, path in candidates:
            resolved = str(path.expanduser())
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append(
                {
                    "source": source,
                    "path": resolved,
                    "exists": "true" if path.expanduser().exists() else "false",
                }
            )
        return result

    def _spotlight_opendesign_candidates(self) -> list[tuple[str, Path]]:
        try:
            result = subprocess.run(
                [
                    "mdfind",
                    "(kMDItemFSName == 'Open Design.app' || kMDItemFSName == 'open-design')",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        candidates: list[tuple[str, Path]] = []
        for line in (result.stdout or "").splitlines()[:20]:
            path = Path(line.strip())
            if path.name in {"Open Design.app", "open-design"}:
                candidates.append(("spotlight", path))
        return candidates

    def _find_opendesign_source_candidates(self) -> list[tuple[str, Path]]:
        roots = [Path.home()]
        cwd_parent = Path.cwd().parent
        if cwd_parent != roots[0]:
            roots.append(cwd_parent)
        candidates: list[tuple[str, Path]] = []
        for root in roots:
            if not root.exists():
                continue
            try:
                result = subprocess.run(
                    [
                        "find",
                        str(root),
                        "-maxdepth",
                        "5",
                        "-type",
                        "d",
                        "-name",
                        "open-design",
                        "-not",
                        "-path",
                        "*/node_modules/*",
                        "-not",
                        "-path",
                        "*/.git/*",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            for line in (result.stdout or "").splitlines()[:30]:
                path = Path(line.strip())
                if path.name == "open-design":
                    candidates.append(("filesystem", path))
        return candidates

    def _probe_opendesign_daemon(self, config: dict[str, Any], *, discover: bool = False) -> dict[str, Any]:
        raw_url = str(config.get("opendesign_daemon_url") or "").strip().rstrip("/")
        if not raw_url:
            if discover:
                discovered = self._discover_opendesign_daemon(str(config.get("opendesign_auth_token") or ""))
                if discovered.get("reachable"):
                    return discovered
            return {"checked": False, "reachable": False, "summary": "daemon URL 未配置"}
        probed = self._probe_opendesign_url(raw_url, str(config.get("opendesign_auth_token") or ""))
        if probed.get("reachable") or not discover:
            return probed
        discovered = self._discover_opendesign_daemon(str(config.get("opendesign_auth_token") or ""))
        return discovered if discovered.get("reachable") else probed

    def _probe_opendesign_url(self, raw_url: str, token: str = "") -> dict[str, Any]:
        raw_url = str(raw_url or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return {
                "checked": True,
                "reachable": False,
                "summary": "OpenDesign daemon 首版只允许 loopback URL；如需远程访问，请先加受控代理策略。",
                "url": raw_url,
            }
        health_url = raw_url if raw_url.endswith("/api/health") else f"{raw_url}/api/health"
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(health_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=_OPENDESIGN_HEALTH_TIMEOUT_SECONDS) as response:
                body = response.read(32_000).decode("utf-8", errors="replace")
                status_code = getattr(response, "status", 0)
        except urllib.error.HTTPError as exc:
            detail = exc.read(800).decode("utf-8", errors="replace") if exc.fp else str(exc)
            return {
                "checked": True,
                "reachable": False,
                "status_code": exc.code,
                "summary": _compact(detail or str(exc), limit=240),
                "url": health_url,
            }
        except Exception as exc:
            return {
                "checked": True,
                "reachable": False,
                "summary": _compact(str(exc), limit=240),
                "url": health_url,
            }
        payload: Any
        try:
            payload = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        version = ""
        if isinstance(payload, dict):
            version = str(payload.get("version") or payload.get("appVersion") or payload.get("daemonVersion") or "")
        return {
            "checked": True,
            "reachable": 200 <= int(status_code or 0) < 300,
            "status_code": status_code,
            "version": version,
            "summary": _compact(body, limit=240),
            "url": health_url,
            "base_url": raw_url,
        }

    def _discover_opendesign_daemon(self, token: str = "") -> dict[str, Any]:
        ports = self._loopback_listening_ports()
        for port in ports:
            result = self._probe_opendesign_url(f"http://127.0.0.1:{port}", token)
            if result.get("reachable"):
                summary = str(result.get("summary") or "")
                if "open" in summary.lower() or "version" in summary.lower() or '"ok"' in summary.lower():
                    result["discovered"] = True
                    return result
        return {
            "checked": True,
            "reachable": False,
            "summary": f"未在 loopback listening ports 中发现 OpenDesign daemon；已检查 {len(ports)} 个端口。",
            "discovered": False,
        }

    def _loopback_listening_ports(self) -> list[int]:
        ports: set[int] = {7456, 7457}
        try:
            result = subprocess.run(
                ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
                capture_output=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return sorted(ports)
        pattern = re.compile(r"(?:(?:127\.0\.0\.1|localhost|\*)|(?:\[::1\]))[:.](\d+)\s+\(LISTEN\)")
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        for line in stdout.splitlines():
            if "TCP" not in line:
                continue
            lowered = line.lower()
            if not (lowered.startswith("node") or "open-design" in lowered or "electron" in lowered):
                continue
            match = pattern.search(line)
            if not match:
                continue
            try:
                port = int(match.group(1))
            except ValueError:
                continue
            if 1 <= port <= 65535:
                ports.add(port)
        return sorted(ports)

    def _append_opendesign_log_lines(self, install_id: str, log_path: Path, offset: int) -> int:
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read(16_000)
                next_offset = handle.tell()
        except OSError:
            return offset
        for line in chunk.splitlines():
            clean = _redact_text(line.strip())
            if clean:
                self._append_install_line(install_id, clean)
        return next_offset

    def _wait_for_opendesign_daemon(
        self,
        log_path: Path,
        timeout_seconds: float = 16.0,
        *,
        install_id: str = "",
        start_offset: int = 0,
        allow_discovery: bool = True,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_urls: dict[str, str] = {}
        log_offset = start_offset
        while time.monotonic() < deadline:
            if install_id:
                log_offset = self._append_opendesign_log_lines(install_id, log_path, log_offset)
            urls = self._opendesign_urls_from_log(log_path)
            if urls:
                last_urls = {**last_urls, **urls}
            daemon_url = urls.get("daemon")
            if daemon_url:
                result = self._probe_opendesign_url(daemon_url)
                if result.get("reachable"):
                    result["web_url"] = urls.get("web") or daemon_url
                    return result
            if allow_discovery:
                discovered = self._discover_opendesign_daemon()
                if discovered.get("reachable"):
                    if last_urls.get("web"):
                        discovered["web_url"] = last_urls["web"]
                    return discovered
            time.sleep(0.8)
        if install_id:
            self._append_opendesign_log_lines(install_id, log_path, log_offset)
        return {"reachable": False}

    def _opendesign_urls_from_log(self, log_path: Path) -> dict[str, str]:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        except OSError:
            return {}
        result: dict[str, str] = {}
        web_match = re.search(r"Web:\s*(https?://127\.0\.0\.1:\d+)", text)
        daemon_match = re.search(r"Daemon:\s*(https?://127\.0\.0\.1:\d+)", text)
        if web_match:
            result["web"] = web_match.group(1)
        if daemon_match:
            result["daemon"] = daemon_match.group(1)
        return result

    def _credential_hint(self, provider_id: str, credential_mode: str, api_key_configured: bool) -> str:
        if provider_id == "local_claude_code":
            if credential_mode == "api_env":
                return (
                    "API Env 模式：执行时只注入已保存的 ANTHROPIC_* 环境变量，并使用隔离 HOME，避免回落到本机 Claude 登录态。"
                    if api_key_configured
                    else "API Env 模式需要先配置 ANTHROPIC_API_KEY；未配置时不会启动 Claude Code。"
                )
            return "CLI Login 模式：使用本机 Claude Code 登录态；不会注入 Yachiyo 保存的 Anthropic API Key。"
        if credential_mode == "api_env":
            return (
                "API Env 模式：review 时只注入已保存的 OPENAI_* 环境变量，并使用隔离 HOME，避免回落到本机 Codex 登录态。"
                if api_key_configured
                else "API Env 模式需要先配置 OPENAI_API_KEY；未配置时不会启动 Codex review。"
            )
        return "CLI Login 模式：使用本机 Codex 登录态；不会注入 Yachiyo 保存的 OpenAI API Key。"

    def _which_command(self, name: str) -> str | None:
        path = shutil.which(name)
        if path:
            return path
        for shell_args in (["/bin/zsh", "-lc"], ["/bin/zsh", "-ic"], ["/bin/bash", "-lc"]):
            shell_path = shell_args[0]
            if not Path(shell_path).exists():
                continue
            try:
                result = subprocess.run(
                    [*shell_args, f"command -v {shlex.quote(name)}"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            candidate = (result.stdout or "").strip().splitlines()
            if candidate and Path(candidate[0]).exists():
                return candidate[0]
        common_dirs = [
            Path.cwd() / "apps" / "frontend" / "bin",
            Path.cwd() / "node_modules" / ".bin",
            Path.cwd() / "apps" / "frontend" / "node_modules" / ".bin",
            Path.home() / ".npm-global" / "bin",
            Path.home() / ".npm" / "bin",
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
        ]
        nvm_versions = Path.home() / ".nvm" / "versions" / "node"
        if nvm_versions.exists():
            common_dirs.extend(sorted((item / "bin" for item in nvm_versions.iterdir() if item.is_dir()), reverse=True))
        for directory in common_dirs:
            candidate = directory / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def _probe_version(self, argv: list[str]) -> str:
        result = self._run_quick(argv)
        output = (result.stdout or result.stderr).strip().splitlines()
        return output[0].strip() if output else ""

    def _probe_help(self, argv: list[str]) -> str:
        result = self._run_quick(argv)
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    def _run_quick(self, argv: list[str]) -> CommandResult:
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_PROVIDER_HEALTH_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(returncode=-1, stderr=str(exc))
        return CommandResult(
            returncode=result.returncode,
            stdout=_redact_text(result.stdout),
            stderr=_redact_text(result.stderr),
        )

    def test_provider_config(self, provider_id: str) -> dict[str, Any]:
        provider_id = str(provider_id or "").strip()
        if provider_id not in {"local_claude_code", "codex_review", "opendesign"}:
            raise CodingExecutionError("当前仅支持测试 Claude Code、Codex 与 OpenDesign 配置")
        status = self.health_check_provider(provider_id)
        config = self._read_config_private()
        if provider_id == "opendesign":
            daemon = status.get("capabilities", {}).get("daemon_status") or {}
            return {
                "ok": True,
                "provider_id": provider_id,
                "available": status["availability"] == "available",
                "status": status,
                "daemon_url_configured": bool(config.get("opendesign_daemon_url")),
                "auth_token_configured": bool(config.get("opendesign_auth_token")),
                "app_path_configured": bool(config.get("opendesign_app_path")),
                "message": (
                    "OpenDesign daemon 已连接；后续可通过 OpenDesignBridge 使用 HTTP/SSE 设计上下文。"
                    if status["availability"] == "available"
                    else status.get("blocking_reason") or daemon.get("summary") or "OpenDesign daemon 不可用"
                ),
            }
        if provider_id == "local_claude_code":
            configured = bool(config.get("anthropic_api_key"))
            credential_mode = str(config.get("claude_credential_mode") or "cli_login")
            try:
                env = self._provider_env("local_claude_code")
            except CodingExecutionError:
                env = {}
            api_test = self._test_claude_api_env(config) if credential_mode == "api_env" else {"success": True, "checks": []}
            cli_available = status["availability"] == "available"
            success = bool(cli_available and (credential_mode != "api_env" or api_test.get("success")))
            return {
                "ok": True,
                "success": success,
                "provider_id": provider_id,
                "available": cli_available,
                "status": status,
                "credential_mode": credential_mode,
                "isolated_auth": credential_mode == "api_env",
                "api_key_configured": configured,
                "base_url_configured": bool(config.get("anthropic_base_url")),
                "model": str(config.get("anthropic_model") or ""),
                "model_configured": bool(config.get("anthropic_model")),
                "env_keys": sorted(key for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY") if env.get(key)),
                "checks": [
                    {
                        "label": "Claude Code CLI",
                        "status": "pass" if cli_available else "fail",
                        "detail": status.get("version") or status.get("blocking_reason") or "",
                    },
                    *api_test.get("checks", []),
                ],
                "api_compatibility": api_test if credential_mode == "api_env" else None,
                "message": (
                    "Claude Code CLI 和 Anthropic API Env 测试通过。"
                    if credential_mode == "api_env" and success
                    else "Claude Code CLI 可用；API Env 模式会注入 ANTHROPIC_* 并隔离本机登录态。"
                    if credential_mode == "api_env" and cli_available
                    else "Claude Code CLI 可用；CLI Login 模式会使用本机登录态，不注入 Yachiyo 保存的 API Key。"
                )
                if cli_available
                else status.get("blocking_reason") or "Claude Code CLI 不可用",
            }
        configured = bool(config.get("codex_api_key"))
        credential_mode = str(config.get("codex_credential_mode") or "cli_login")
        try:
            env = self._provider_env("codex_review")
        except CodingExecutionError:
            env = {}
        api_test = self._test_codex_api_env(config) if credential_mode == "api_env" else {"success": True, "checks": []}
        cli_available = status["availability"] == "available"
        success = bool(cli_available and (credential_mode != "api_env" or api_test.get("success")))
        return {
            "ok": True,
            "success": success,
            "provider_id": provider_id,
            "available": cli_available,
            "status": status,
            "credential_mode": credential_mode,
            "isolated_auth": credential_mode == "api_env",
            "api_key_configured": configured,
            "base_url_configured": bool(config.get("codex_base_url")),
            "model": str(config.get("codex_model") or ""),
            "model_configured": bool(config.get("codex_model")),
            "env_keys": sorted(key for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY") if env.get(key)),
            "checks": [
                {
                    "label": "Codex CLI",
                    "status": "pass" if cli_available else "fail",
                    "detail": status.get("version") or status.get("blocking_reason") or "",
                },
                *api_test.get("checks", []),
            ],
            "api_compatibility": api_test if credential_mode == "api_env" else None,
            "message": (
                "Codex CLI API Env 测试通过；该 API 满足 Responses API 要求。"
                if credential_mode == "api_env" and success
                else "API Key 可访问，但当前网关不满足 Codex CLI 的 Responses API 要求。"
                if credential_mode == "api_env" and cli_available
                else "Codex CLI review 能力可用；CLI Login 模式会使用本机登录态，不注入 Yachiyo 保存的 API Key。"
            )
            if cli_available
            else status.get("blocking_reason") or "Codex CLI 不可用",
        }

    # Provider installer ------------------------------------------------

    def install_provider(self, provider_id: str, action: str = "install") -> dict[str, Any]:
        provider_id = str(provider_id or "").strip()
        action = str(action or "install").strip()
        status = self.health_check_provider(provider_id)
        action_target = str(status.get("executable_path") or "")
        if provider_id == "opendesign" and action == "install":
            action_target = str(self._managed_opendesign_dir())
        if provider_id == "opendesign" and action == "upgrade":
            action_target = str(self._managed_opendesign_dir())
        if provider_id == "opendesign" and action == "open_web":
            capabilities = status.get("capabilities") or {}
            action_target = str(capabilities.get("web_url") or "")
        spec = _provider_action_spec(provider_id, action, action_target)
        if platform.system() == "Windows" and spec.kind == "command":
            raise CodingExecutionError("当前首版安装器仅支持 macOS/Linux；Windows 请按官方文档手动安装。")

        install_id = uuid4().hex[:12]
        state = {
            "ok": True,
            "install_id": install_id,
            "provider_id": provider_id,
            "action": spec.action,
            "label": spec.label,
            "kind": spec.kind,
            "status": "running",
            "command_preview": spec.terminal_command or " ".join(spec.argv),
            "confirmation": spec.confirmation,
            "lines": [],
            "line_count": 0,
            "truncated": False,
            "started_at": _now(),
            "finished_at": None,
            "returncode": None,
            "error": "",
        }
        with self._lock:
            self._installs[install_id] = state

        if spec.kind == "opendesign_scan":
            self._complete_opendesign_scan_action(install_id)
            return self.get_provider_install(install_id)

        if spec.kind == "opendesign_start":
            thread = threading.Thread(
                target=self._run_opendesign_action_guarded,
                args=(install_id, spec),
                daemon=True,
                name=f"coding-provider-opendesign-{install_id}",
            )
            with self._lock:
                self._install_threads[install_id] = thread
            thread.start()
            return self.get_provider_install(install_id)

        if spec.kind == "opendesign_upgrade":
            thread = threading.Thread(
                target=self._run_opendesign_action_guarded,
                args=(install_id, spec),
                daemon=True,
                name=f"coding-provider-opendesign-{install_id}",
            )
            with self._lock:
                self._install_threads[install_id] = thread
            thread.start()
            return self.get_provider_install(install_id)

        if spec.kind == "noop":
            self._append_install_line(install_id, spec.terminal_command or "No external command is required.")
            self._finish_install(install_id, status="completed", returncode=0)
            return self.get_provider_install(install_id)

        if spec.kind == "terminal":
            self._complete_terminal_action(install_id, spec)
            return self.get_provider_install(install_id)

        thread = threading.Thread(
            target=self._run_install_guarded,
            args=(install_id, spec),
            daemon=True,
            name=f"coding-provider-install-{install_id}",
        )
        with self._lock:
            self._install_threads[install_id] = thread
        thread.start()
        return self.get_provider_install(install_id)

    def get_provider_install(self, install_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._installs.get(install_id)
            if state is None:
                raise KeyError(install_id)
            return dict(state, lines=list(state.get("lines") or []))

    def _complete_terminal_action(self, install_id: str, spec: ProviderActionSpec) -> None:
        try:
            from apps.shell.terminal import open_terminal_command

            success, error = open_terminal_command(spec.terminal_command)
            if success:
                self._append_install_line(install_id, f"Opened terminal command: {spec.terminal_command}")
                self._finish_install(install_id, status="completed", returncode=0)
            else:
                self._append_install_line(install_id, error or "打开终端失败")
                self._finish_install(install_id, status="failed", returncode=-1, error=error or "打开终端失败")
        except Exception as exc:
            self._append_install_line(install_id, str(exc))
            self._finish_install(install_id, status="failed", returncode=-1, error=str(exc))

    def _complete_opendesign_scan_action(self, install_id: str) -> None:
        try:
            config = self._read_config_private()
            install_info = self._detect_opendesign_install(config, deep=True)
            changes: dict[str, Any] = {}
            if install_info.get("installed") and install_info.get("path"):
                changes["opendesign_app_path"] = str(install_info["path"])
                self._append_install_line(install_id, f"Found OpenDesign: {install_info['path']} ({install_info.get('source')})")
            else:
                self._append_install_line(install_id, f"No OpenDesign source/app found. Managed install target: {self._managed_opendesign_dir()}")
            if changes:
                self.update_config(changes)
            self._finish_install(install_id, status="completed", returncode=0)
        except Exception as exc:
            self._append_install_line(install_id, str(exc))
            self._finish_install(install_id, status="failed", returncode=-1, error=str(exc))

    def _run_opendesign_action_guarded(self, install_id: str, spec: ProviderActionSpec) -> None:
        try:
            if spec.kind == "opendesign_start":
                self._complete_opendesign_start_action(install_id, spec.terminal_command)
                return
            if spec.kind == "opendesign_upgrade":
                self._complete_opendesign_upgrade_action(install_id, spec.terminal_command)
                return
            self._finish_install(install_id, status="failed", returncode=-1, error="不支持的 OpenDesign 动作")
        except Exception as exc:
            logger.exception("OpenDesign provider action failed: %s", install_id)
            self._append_install_line(install_id, str(exc))
            self._finish_install(install_id, status="failed", returncode=-1, error=str(exc))
        finally:
            with self._lock:
                self._install_threads.pop(install_id, None)
                self._install_processes.pop(install_id, None)

    def _complete_opendesign_upgrade_action(self, install_id: str, path: str) -> None:
        managed_path = self._managed_opendesign_dir()
        source_path = Path(path or managed_path).expanduser()
        if not _path_is_relative_to(source_path, managed_path) or not _looks_like_opendesign_source_dir(source_path):
            message = "OpenDesign 检查版本并升级仅支持 Yachiyo 管辖目录；本机自有项目请在项目目录自行 git pull/pnpm install。"
            self._append_install_line(install_id, message)
            self._finish_install(install_id, status="failed", returncode=-1, error=message)
            return
        result = self._run_install_argv(install_id, list(_shell_argv(_opendesign_upgrade_command(str(source_path)))))
        if not result.ok:
            error = result.stderr or result.stdout or "OpenDesign upgrade failed"
            self._finish_install(install_id, status="failed", returncode=result.returncode, error=error)
            return
        self._append_install_line(install_id, "OpenDesign upgrade check completed. Restarting managed daemon...")
        self._complete_opendesign_start_action(install_id, str(source_path), force_restart=True)

    def _complete_opendesign_start_action(self, install_id: str, path: str, *, force_restart: bool = False) -> None:
        try:
            config = self._read_config_private()
            source_path = Path(path or config.get("opendesign_app_path") or self._detect_opendesign_install(config).get("path") or "").expanduser()
            if not _looks_like_opendesign_source_dir(source_path):
                self._append_install_line(install_id, f"OpenDesign source dir not found: {source_path}")
                self._finish_install(install_id, status="failed", returncode=-1, error="未找到可启动的 OpenDesign 源码目录")
                return
            daemon = self._probe_opendesign_daemon(config, discover=True)
            if not force_restart and daemon.get("reachable") and daemon.get("base_url"):
                self.update_config({"opendesign_app_path": str(source_path), "opendesign_daemon_url": str(daemon["base_url"]), "opendesign_web_url": str(daemon.get("web_url") or "")})
                self._append_install_line(install_id, f"OpenDesign daemon already running: {daemon['base_url']}")
                if daemon.get("web_url"):
                    self._append_install_line(install_id, f"OpenDesign WebUI available: {daemon['web_url']}")
                self._finish_install(install_id, status="completed", returncode=0)
                return

            log_path = self._workspace / "runs" / "opendesign-daemon.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            command = _opendesign_launch_command(str(source_path))
            self._append_install_line(install_id, "$ " + command.replace("\n", " && "))
            log_offset = log_path.stat().st_size if log_path.exists() else 0
            log_file = log_path.open("a", encoding="utf-8")
            proc = subprocess.Popen(
                list(_shell_argv(command)),
                cwd=str(source_path),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            log_file.close()
            with self._lock:
                self._opendesign_process = proc
            self._append_install_line(install_id, f"Started OpenDesign daemon process pid={proc.pid}")
            self._append_install_line(install_id, f"Log: {log_path}")
            discovered = self._wait_for_opendesign_daemon(log_path, install_id=install_id, start_offset=log_offset, allow_discovery=not force_restart)
            if discovered.get("reachable") and discovered.get("base_url"):
                web_url = str(discovered.get("web_url") or "")
                self.update_config({"opendesign_app_path": str(source_path), "opendesign_daemon_url": str(discovered["base_url"]), "opendesign_web_url": web_url})
                self._append_install_line(install_id, f"OpenDesign daemon available: {discovered['base_url']}")
                if web_url:
                    self._append_install_line(install_id, f"OpenDesign WebUI available: {web_url}")
                self._finish_install(install_id, status="completed", returncode=0)
                return
            self.update_config({"opendesign_app_path": str(source_path)})
            self._append_install_line(install_id, "OpenDesign process started, but daemon health is not reachable yet. Use 重新检测 after it finishes booting.")
            self._finish_install(install_id, status="completed", returncode=0)
        except Exception as exc:
            self._append_install_line(install_id, str(exc))
            self._finish_install(install_id, status="failed", returncode=-1, error=str(exc))

    def _run_install_guarded(self, install_id: str, spec: ProviderActionSpec) -> None:
        try:
            result = self._run_install_argv(install_id, list(spec.argv))
            status = "completed" if result.ok else "failed"
            error = "" if result.ok else result.stderr or result.stdout or "安装命令失败"
            self._finish_install(install_id, status=status, returncode=result.returncode, error=error)
        except Exception as exc:
            logger.exception("provider installer failed: %s", install_id)
            self._append_install_line(install_id, str(exc))
            self._finish_install(install_id, status="failed", returncode=-1, error=str(exc))
        finally:
            with self._lock:
                self._install_threads.pop(install_id, None)
                self._install_processes.pop(install_id, None)

    def _run_install_argv(self, install_id: str, argv: list[str]) -> CommandResult:
        started = time.monotonic()
        self._append_install_line(install_id, "$ " + " ".join(self._public_argv(argv)))
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            self._append_install_line(install_id, str(exc))
            return CommandResult(returncode=-1, stderr=str(exc))
        with self._lock:
            self._install_processes[install_id] = proc
        output: list[str] = []
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if line:
                clean = _redact_text(line.rstrip("\n"))
                output.append(clean)
                self._append_install_line(install_id, clean)
            if proc.poll() is not None:
                rest = proc.stdout.read()
                if rest:
                    for rest_line in rest.splitlines():
                        clean = _redact_text(rest_line)
                        output.append(clean)
                        self._append_install_line(install_id, clean)
                break
            if time.monotonic() - started > _INSTALL_TIMEOUT_SECONDS:
                try:
                    proc.terminate()
                except OSError:
                    pass
                stdout, stderr = self._collect_after_terminate(proc)
                for timeout_line in stdout.splitlines():
                    self._append_install_line(install_id, timeout_line)
                return CommandResult(proc.returncode or -1, stdout="\n".join(output), stderr=stderr or "安装命令超时", timed_out=True)
        return CommandResult(proc.returncode or 0, stdout="\n".join(output))

    def _append_install_line(self, install_id: str, line: str) -> None:
        with self._lock:
            state = self._installs.get(install_id)
            if state is None:
                return
            lines = list(state.get("lines") or [])
            lines.append(_redact_text(line))
            state["line_count"] = int(state.get("line_count") or 0) + 1
            if len(lines) > _INSTALL_LOG_MAX_LINES:
                lines = lines[-_INSTALL_LOG_MAX_LINES:]
                state["truncated"] = True
            state["lines"] = lines

    def _finish_install(self, install_id: str, *, status: str, returncode: int, error: str = "") -> None:
        with self._lock:
            state = self._installs.get(install_id)
            if state is None:
                return
            state["status"] = status
            state["returncode"] = returncode
            state["error"] = _compact(error, limit=800)
            state["finished_at"] = _now()

    # Job API -----------------------------------------------------------

    def create_job_from_start_code(self, text: str) -> dict[str, Any] | None:
        parsed = parse_start_code_command(text, self.get_config())
        if parsed is None:
            return None
        if parsed.get("ok") is not True:
            return parsed
        try:
            job = self.create_job(parsed["request"])
        except CodingExecutionError as exc:
            return {"ok": False, "error": str(exc), "needs_config": False}
        return {"ok": True, "job_id": job["job_id"], "job": job}

    def create_job(self, request: dict[str, Any]) -> dict[str, Any]:
        user_request = str(request.get("user_request") or "").strip()
        raw_repo_path = str(request.get("repo_path") or "").strip()
        if not user_request:
            raise CodingExecutionError("user_request 不能为空")
        if not raw_repo_path:
            raise CodingExecutionError("repo_path 不能为空")
        repo_path = Path(raw_repo_path).expanduser()

        job_id = uuid4().hex[:12]
        task_type = str(request.get("task_type") or "custom").strip() or "custom"
        writable_scopes = _normalize_scopes(request.get("writable_scopes") or ["."])
        readonly_scopes = _normalize_scopes(request.get("readonly_scopes") or [])
        preferred_provider = str(request.get("preferred_provider") or "local_claude_code").strip() or "local_claude_code"
        review_strategy = str(request.get("review_strategy") or "codex_if_available").strip() or "codex_if_available"
        design_mode = str(request.get("design_mode") or "none").strip() or "none"
        branch_name = f"ai/coding/{job_id}"
        created_at = _now()

        artifact_dir = self.artifact_dir(job_id)
        run_dir = self.run_dir(job_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)

        provider_status = self.health_check_provider(preferred_provider)
        review_provider = self._select_review_provider(review_strategy)
        repo_info = self._inspect_repo(repo_path)
        blockers: list[dict[str, Any]] = []
        warnings: list[str] = []

        if not repo_info["valid"]:
            blockers.append(self._blocker("repo", "misconfigured", repo_info["error"], ["cancel"]))
        if design_mode in {"opendesign_required", "opendesign_daemon_required"}:
            opendesign_status = self.health_check_provider("opendesign")
            if opendesign_status["availability"] != "available":
                blockers.append(
                    self._blocker(
                        "opendesign",
                        str(opendesign_status["availability"]),
                        opendesign_status.get("blocking_reason")
                        or "OpenDesign daemon_required 需要先连接本地 OpenDesign daemon。",
                        ["start_provider", "switch_design_mode", "cancel"],
                    )
                )
        if design_mode in {"import_existing_artifact", "manual_artifact_import"}:
            config = self._read_config_private()
            artifact_dir = str(config.get("opendesign_artifact_dir") or "").strip()
            if not artifact_dir or not Path(artifact_dir).expanduser().exists():
                blockers.append(
                    self._blocker(
                        "opendesign",
                        "user_action_required",
                        "manual_artifact_import 需要先配置可读的 OpenDesign artifact 目录。",
                        ["configure_provider", "switch_design_mode", "cancel"],
                    )
                )
        if preferred_provider != "mock" and provider_status["availability"] != "available":
            blockers.append(
                self._blocker(
                    preferred_provider,
                    str(provider_status["availability"]),
                    provider_status.get("blocking_reason") or f"{preferred_provider} 不可用",
                    ["open_install_docs", "switch_provider", "cancel"],
                )
            )

        dirty_summary = repo_info.get("dirty_summary", {})
        dirty_files = dirty_summary.get("files") or []
        if dirty_files:
            warnings.append("目标仓库已有未提交改动；审批前请确认这些改动可以保留在新分支上。")
        risk_level = self._risk_level(task_type, writable_scopes, bool(dirty_files))
        if risk_level == "high" and dirty_files and task_type in _HIGH_RISK_TASK_TYPES:
            blockers.append(
                self._blocker(
                    "git",
                    "user_action_required",
                    "高风险 job 遇到已有 dirty changes；请先 stash 或 commit 后再继续。",
                    ["cancel"],
                )
            )

        selected_provider = preferred_provider if provider_status["availability"] == "available" else ""
        status = "blocked" if blockers else "awaiting_approval"
        plan_summary = self._build_plan_summary(
            user_request=user_request,
            repo_path=repo_path,
            task_type=task_type,
            writable_scopes=writable_scopes,
            provider=selected_provider or preferred_provider,
            review_provider=review_provider["id"],
            branch_name=branch_name,
            warnings=warnings,
        )
        fallback_options = self._fallback_options(preferred_provider, review_strategy)

        row = {
            "job_id": job_id,
            "status": status,
            "user_request": user_request,
            "repo_path": str(repo_path),
            "task_type": task_type,
            "preferred_provider": preferred_provider,
            "selected_provider": selected_provider,
            "review_strategy": review_strategy,
            "selected_review_provider": review_provider["id"],
            "design_mode": design_mode,
            "writable_scopes_json": _json(writable_scopes),
            "readonly_scopes_json": _json(readonly_scopes),
            "branch_name": branch_name,
            "original_branch": repo_info.get("branch", ""),
            "risk_level": risk_level,
            "requires_approval": 1,
            "plan_summary": plan_summary,
            "blockers_json": _json(blockers),
            "fallback_options_json": _json(fallback_options),
            "dirty_summary_json": _json(dirty_summary),
            "changed_files_json": "[]",
            "artifacts_json": "[]",
            "error": "",
            "created_at": created_at,
            "updated_at": created_at,
            "approved_at": None,
            "completed_at": None,
        }
        self._insert_job(row)
        self._write_planning_artifacts(job_id, row, provider_status, review_provider, warnings)
        self._refresh_artifact_list(job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._get_job_row(job_id)
        if row is None:
            raise KeyError(job_id)
        return self._row_to_job(row)

    def list_jobs(self, limit: int = 50) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM coding_jobs ORDER BY updated_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return {"ok": True, "jobs": [self._row_to_job(row) for row in rows]}

    def approve_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._get_job_row(job_id)
            if row is None:
                raise KeyError(job_id)
            job = self._row_to_job(row)
            if job["status"] == "blocked":
                return {**job, "ok": False, "error": "job 当前处于 blocked，不能审批执行"}
            if job["status"] in _TERMINAL_STATUSES:
                return {**job, "ok": False, "error": f"job 已处于终态 {job['status']}"}
            if job["status"] not in {"awaiting_approval"}:
                return {**job, "ok": False, "error": f"job 当前状态不能审批：{job['status']}"}
            now = _now()
            self._update_job_fields(job_id, status="running", approved_at=now, updated_at=now, error="")
            self._cancel_flags.discard(job_id)

            thread = threading.Thread(target=self._run_job_guarded, args=(job_id,), daemon=True, name=f"coding-job-{job_id}")
            self._threads[job_id] = thread
            thread.start()
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._get_job_row(job_id)
            if row is None:
                raise KeyError(job_id)
            job = self._row_to_job(row)
            if job["status"] in _TERMINAL_STATUSES:
                return {**job, "ok": False, "error": f"job 已处于终态 {job['status']}"}
            self._cancel_flags.add(job_id)
            proc = self._processes.get(job_id)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    logger.debug("终止 coding provider 进程失败: %s", job_id, exc_info=True)
            self._write_artifact(job_id, "rollback.md", self._rollback_text(self._row_to_job(row), "用户已取消任务。"))
            self._update_job_fields(job_id, status="cancelled", updated_at=_now(), completed_at=_now(), error="用户取消任务")
            self._refresh_artifact_list(job_id)
        return self.get_job(job_id)

    def list_artifacts(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        root = self.artifact_dir(job_id)
        artifacts: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                rel = _safe_relpath(path, root)
                stat = path.stat()
                item: dict[str, Any] = {
                    "path": rel,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
                if path.suffix.lower() in _TEXT_ARTIFACT_SUFFIXES and stat.st_size <= _ARTIFACT_MAX_INLINE_BYTES:
                    try:
                        item["content"] = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        item["content"] = ""
                artifacts.append(item)
        return {"ok": True, "job_id": job_id, "status": job["status"], "artifacts": artifacts}

    # Persistence -------------------------------------------------------

    def _insert_job(self, row: dict[str, Any]) -> None:
        with self._lock:
            conn = self._get_conn()
            columns = list(row.keys())
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO coding_jobs ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
            conn.commit()

    def _get_job_row(self, job_id: str) -> sqlite3.Row | None:
        with self._lock:
            conn = self._get_conn()
            return conn.execute("SELECT * FROM coding_jobs WHERE job_id = ?", (job_id,)).fetchone()

    def _update_job_fields(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "status" in fields and fields["status"] not in _VALID_JOB_STATUSES:
            raise ValueError(f"invalid job status: {fields['status']}")
        with self._lock:
            conn = self._get_conn()
            assignments = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE coding_jobs SET {assignments} WHERE job_id = ?",
                tuple(fields.values()) + (job_id,),
            )
            conn.commit()

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        job["requires_approval"] = bool(job.get("requires_approval"))
        job["writable_scopes"] = _loads(job.pop("writable_scopes_json", "[]"), [])
        job["readonly_scopes"] = _loads(job.pop("readonly_scopes_json", "[]"), [])
        job["blockers"] = _loads(job.pop("blockers_json", "[]"), [])
        job["fallback_options"] = _loads(job.pop("fallback_options_json", "[]"), [])
        job["dirty_summary"] = _loads(job.pop("dirty_summary_json", "{}"), {})
        job["changed_files"] = _loads(job.pop("changed_files_json", "[]"), [])
        job["artifacts"] = _loads(job.pop("artifacts_json", "[]"), [])
        return {"ok": True, **job}

    # Paths/artifacts ---------------------------------------------------

    def artifact_dir(self, job_id: str) -> Path:
        return self._workspace / "artifacts" / "coding" / job_id

    def run_dir(self, job_id: str) -> Path:
        return self._workspace / "runs" / "coding" / job_id

    def _write_artifact(self, job_id: str, relative_path: str, content: str) -> Path:
        root = self.artifact_dir(job_id)
        target = (root / relative_path).resolve()
        root_resolved = root.resolve()
        if root_resolved != target and root_resolved not in target.parents:
            raise CodingExecutionError("artifact 路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def _write_run_file(self, job_id: str, relative_path: str, content: str) -> Path:
        root = self.run_dir(job_id)
        target = (root / relative_path).resolve()
        root_resolved = root.resolve()
        if root_resolved != target and root_resolved not in target.parents:
            raise CodingExecutionError("run 路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_redact_text(content), encoding="utf-8")
        return target

    def _refresh_artifact_list(self, job_id: str) -> None:
        root = self.artifact_dir(job_id)
        artifacts: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                artifacts.append({"path": _safe_relpath(path, root), "size": path.stat().st_size})
        self._update_job_fields(job_id, artifacts_json=_json(artifacts), updated_at=_now())

    def _write_planning_artifacts(
        self,
        job_id: str,
        row: dict[str, Any],
        provider_status: dict[str, Any],
        review_provider_status: dict[str, Any],
        warnings: list[str],
    ) -> None:
        brief = (
            "# Coding Brief\n\n"
            f"## User Request\n\n{row['user_request']}\n\n"
            f"## Task Type\n\n{row['task_type']}\n\n"
            f"## Repo\n\n{row['repo_path']}\n"
        )
        plan = (
            "# Execution Plan\n\n"
            f"{row['plan_summary']}\n\n"
            "## Writable Scopes\n\n"
            + "\n".join(f"- `{scope}`" for scope in _loads(row["writable_scopes_json"], []))
            + "\n\n## Branch\n\n"
            f"`{row['branch_name']}`\n\n"
        )
        if warnings:
            plan += "## Warnings\n\n" + "\n".join(f"- {warning}" for warning in warnings) + "\n"
        self._write_artifact(job_id, "brief.md", brief)
        self._write_artifact(job_id, "plan.md", plan)
        self._write_artifact(job_id, "provider-status.json", _json(provider_status))
        self._write_artifact(job_id, "review-provider-status.json", _json(review_provider_status))
        self._write_artifact(job_id, "manual-review-checklist.md", self._manual_review_text(self._row_to_job_dict(row), "Job 尚未执行。"))

    def _row_to_job_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        fake = dict(row)
        return {
            "job_id": fake["job_id"],
            "status": fake["status"],
            "user_request": fake["user_request"],
            "repo_path": fake["repo_path"],
            "task_type": fake["task_type"],
            "selected_provider": fake.get("selected_provider", ""),
            "selected_review_provider": fake.get("selected_review_provider", ""),
            "review_strategy": fake.get("review_strategy", ""),
            "writable_scopes": _loads(fake.get("writable_scopes_json"), []),
            "branch_name": fake.get("branch_name", ""),
            "changed_files": _loads(fake.get("changed_files_json"), []),
            "error": fake.get("error", ""),
        }

    # Planning ----------------------------------------------------------

    def _inspect_repo(self, repo_path: Path) -> dict[str, Any]:
        if not repo_path.exists() or not repo_path.is_dir():
            return {"valid": False, "error": "repo_path 不存在或不是目录", "dirty_summary": {"files": []}}
        git_dir = self._git(repo_path, "rev-parse", "--show-toplevel")
        if not git_dir.ok:
            return {"valid": False, "error": "目标路径不是 git 仓库", "dirty_summary": {"files": []}}
        branch = self._git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        status = self._git_status_map(repo_path)
        return {
            "valid": True,
            "branch": (branch.stdout or "").strip(),
            "git_root": (git_dir.stdout or "").strip(),
            "dirty_summary": {
                "dirty": bool(status),
                "count": len(status),
                "files": sorted(status.keys()),
                "status": status,
            },
        }

    def _risk_level(self, task_type: str, writable_scopes: list[str], has_dirty_changes: bool) -> str:
        if task_type in _HIGH_RISK_TASK_TYPES:
            return "high"
        if any(scope in {".", "*"} for scope in writable_scopes) and has_dirty_changes:
            return "high"
        if any(scope in {".", "*"} for scope in writable_scopes):
            return "medium"
        return "medium"

    def _select_review_provider(self, strategy: str) -> dict[str, Any]:
        if strategy == "none":
            return _provider_status(
                provider_id="none",
                display_name="No Review",
                role="review",
                availability="available",
                risk_level="low",
            )
        if strategy in {"manual_only", "same_provider", "any_available_agent"}:
            return self.health_check_provider("manual_review")
        codex = self.health_check_provider("codex_review")
        if codex["availability"] == "available":
            return codex
        return self.health_check_provider("manual_review")

    def _build_plan_summary(
        self,
        *,
        user_request: str,
        repo_path: Path,
        task_type: str,
        writable_scopes: list[str],
        provider: str,
        review_provider: str,
        branch_name: str,
        warnings: list[str],
    ) -> str:
        lines = [
            f"将在 `{repo_path}` 中创建独立分支 `{branch_name}`。",
            f"任务类型：{task_type}。",
            f"执行 provider：{provider or '待选择'}；review provider：{review_provider or 'manual_review'}。",
            "允许写入范围：" + ", ".join(f"`{scope}`" for scope in writable_scopes) + "。",
            "用户审批前不会启动本地 CLI。",
        ]
        if warnings:
            lines.extend(warnings)
        lines.append("请求摘要：" + _compact(user_request, limit=240))
        return "\n".join(lines)

    def _fallback_options(self, provider: str, strategy: str) -> list[dict[str, str]]:
        options = [
            {
                "id": "manual_review",
                "label": "使用 Manual Review",
                "consequence": "不调用 Agent review，只生成 diff checklist。",
            },
            {
                "id": "mock",
                "label": "使用 Mock Provider",
                "consequence": "只验证状态机与 UI，不修改目标仓库。",
            },
        ]
        if provider != "local_claude_code":
            options.append(
                {
                    "id": "local_claude_code",
                    "label": "切换到 Claude Code",
                    "consequence": "需要本机安装并登录 claude CLI。",
                }
            )
        if strategy != "none":
            options.append({"id": "skip_review", "label": "跳过 Review", "consequence": "只展示 diff、测试结果和回滚建议。"})
        return options

    def _blocker(self, provider_id: str, reason: str, message: str, actions: list[str]) -> dict[str, Any]:
        labels = {
            "open_install_docs": "查看安装说明",
            "open_auth_guide": "查看登录说明",
            "switch_provider": "切换 provider",
            "skip_review": "跳过 review",
            "manual_review": "使用 manual review",
            "import_artifact": "导入 artifact",
            "cancel": "取消",
        }
        return {
            "provider_id": provider_id,
            "reason": reason,
            "message": message,
            "suggested_actions": [{"type": action, "label": labels.get(action, action)} for action in actions],
        }

    # Execution ---------------------------------------------------------

    def _run_job_guarded(self, job_id: str) -> None:
        try:
            self._run_job(job_id)
        except Exception as exc:
            logger.exception("coding job 执行失败: %s", job_id)
            self._write_artifact(job_id, "rollback.md", self._rollback_text(self.get_job(job_id), str(exc)))
            self._update_job_fields(job_id, status="failed", error=str(exc), updated_at=_now(), completed_at=_now())
            self._refresh_artifact_list(job_id)
        finally:
            self._processes.pop(job_id, None)
            self._threads.pop(job_id, None)

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        repo_path = Path(job["repo_path"])
        provider_id = job["selected_provider"] or job["preferred_provider"]
        if self._is_cancelled(job_id):
            return

        baseline_snapshot = self._git_change_snapshot(repo_path)
        branch = self._git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        original_branch = (branch.stdout or "").strip()
        self._update_job_fields(job_id, original_branch=original_branch, updated_at=_now())
        self._write_run_file(job_id, "provider.json", _json({"provider": provider_id, "started_at": _now()}))
        self._write_run_file(job_id, "redacted-env.json", _json(self._redacted_env_snapshot()))

        switch = self._git(repo_path, "switch", "-c", job["branch_name"])
        if not switch.ok:
            raise CodingExecutionError(f"无法创建执行分支：{switch.stderr or switch.stdout}")

        provider_result = self._run_provider(job_id, job, provider_id)
        self._write_run_file(job_id, "stdout.log", provider_result.stdout)
        self._write_run_file(job_id, "stderr.log", provider_result.stderr)
        self._write_run_file(
            job_id,
            "exit.json",
            _json(
                {
                    "returncode": provider_result.returncode,
                    "timed_out": provider_result.timed_out,
                    "cancelled": provider_result.cancelled,
                    "finished_at": _now(),
                }
            ),
        )
        if provider_result.cancelled or self._is_cancelled(job_id):
            self._update_job_fields(job_id, status="cancelled", error="用户取消任务", updated_at=_now(), completed_at=_now())
            return
        if not provider_result.ok:
            raise CodingExecutionError(provider_result.stderr or provider_result.stdout or f"{provider_id} 执行失败")

        changed_snapshot = self._git_change_snapshot(repo_path)
        changed_files = self._changed_files_since_baseline(baseline_snapshot, changed_snapshot)
        self._update_job_fields(job_id, changed_files_json=_json(changed_files), updated_at=_now())
        patch = self._git(repo_path, "diff", "--binary", "HEAD")
        self._write_artifact(job_id, "patch.diff", patch.stdout or "")

        out_of_scope = [path for path in changed_files if not _file_in_scopes(path, job["writable_scopes"])]
        if out_of_scope:
            message = "检测到越界文件变更：" + ", ".join(out_of_scope)
            self._write_artifact(job_id, "rollback.md", self._rollback_text({**job, "changed_files": changed_files}, message))
            self._update_job_fields(job_id, status="failed", error=message, updated_at=_now(), completed_at=_now())
            self._refresh_artifact_list(job_id)
            return

        self._update_job_fields(job_id, status="reviewing", updated_at=_now())
        review_text = self._run_review(job_id, {**self.get_job(job_id), "changed_files": changed_files})
        self._write_artifact(job_id, "review.md", review_text)
        self._write_artifact(job_id, "manual-review-checklist.md", self._manual_review_text({**job, "changed_files": changed_files}, "Review fallback/checklist."))
        self._write_artifact(job_id, "rollback.md", self._rollback_text({**job, "changed_files": changed_files}, "如需回滚，请先检查当前分支和 diff。"))
        self._update_job_fields(job_id, status="completed", updated_at=_now(), completed_at=_now(), error="")
        self._refresh_artifact_list(job_id)

    def _run_provider(self, job_id: str, job: dict[str, Any], provider_id: str) -> CommandResult:
        if provider_id == "mock":
            self._write_artifact(job_id, "mock-provider.md", "# Mock Provider\n\nMock provider completed without editing the repository.\n")
            return CommandResult(returncode=0, stdout="mock provider completed")
        if provider_id != "local_claude_code":
            return CommandResult(returncode=1, stderr=f"Unsupported coding provider: {provider_id}")
        status = self.health_check_provider("local_claude_code")
        if status["availability"] != "available":
            return CommandResult(returncode=1, stderr=status.get("blocking_reason") or "Claude Code provider unavailable")
        executable = status.get("executable_path") or "claude"
        headless_flag = status.get("capabilities", {}).get("headless_flag") or "-p"
        prompt = self._provider_prompt(job)
        cmd = [str(executable), str(headless_flag)]
        if status.get("capabilities", {}).get("credential_mode") == "api_env" and status.get("capabilities", {}).get("bare"):
            cmd.append("--bare")
        if status.get("capabilities", {}).get("output_format"):
            cmd.extend(["--output-format", "text"])
        config = self._read_config_private()
        model = str(config.get("anthropic_model") or "").strip()
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        self._write_run_file(
            job_id,
            "command.json",
            _json(
                {
                    "argv": self._public_argv(cmd),
                    "cwd": job["repo_path"],
                    "credential_mode": status.get("capabilities", {}).get("credential_mode"),
                    "isolated_auth": status.get("capabilities", {}).get("isolated_auth"),
                    "env_keys": ["ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"]
                    if status.get("capabilities", {}).get("credential_mode") == "api_env"
                    else [],
                    "model": model,
                }
            ),
        )
        return self._run_command(
            job_id,
            cmd,
            cwd=Path(job["repo_path"]),
            timeout_seconds=_CLI_TIMEOUT_SECONDS,
            env=self._provider_env("local_claude_code", job_id=job_id),
        )

    def _run_review(self, job_id: str, job: dict[str, Any]) -> str:
        strategy = job.get("review_strategy") or "codex_if_available"
        if strategy == "none":
            return "# Review\n\nReview skipped by strategy.\n"
        codex = self.health_check_provider("codex_review")
        if (
            strategy == "codex_if_available"
            and codex["availability"] == "available"
            and codex.get("capabilities", {}).get("review_uncommitted")
        ):
            executable = codex.get("executable_path") or "codex"
            prompt = (
                "Review the uncommitted changes for this Hermes-Yachiyo coding job. "
                "Focus on correctness, regressions, maintainability, tests, and security. "
                "Return concise findings first."
            )
            config = self._read_config_private()
            cmd = [str(executable), *self._codex_cli_config_args(config), "review", "--uncommitted"]
            self._write_run_file(
                job_id,
                "review-command.json",
                _json(
                    {
                        "argv": self._public_argv(cmd),
                        "cwd": job["repo_path"],
                        "credential_mode": codex.get("capabilities", {}).get("credential_mode"),
                        "isolated_auth": codex.get("capabilities", {}).get("isolated_auth"),
                        "env_keys": ["OPENAI_BASE_URL", "OPENAI_API_KEY"]
                        if codex.get("capabilities", {}).get("credential_mode") == "api_env"
                        else [],
                        "instructions": prompt,
                    }
                ),
            )
            result = self._run_command(
                job_id,
                cmd,
                cwd=Path(job["repo_path"]),
                timeout_seconds=_REVIEW_TIMEOUT_SECONDS,
                env=self._provider_env("codex_review", job_id=job_id),
            )
            self._write_run_file(job_id, "review-stdout.log", result.stdout)
            self._write_run_file(job_id, "review-stderr.log", result.stderr)
            if result.ok and result.stdout.strip():
                return "# Codex CLI Review\n\n" + _redact_text(result.stdout)
            fallback_reason = result.stderr or result.stdout or "Codex review unavailable, fallback required."
            return self._manual_review_text(job, f"Codex review fallback: {_compact(fallback_reason, limit=500)}")
        return self._manual_review_text(job, "Manual review selected or no agent review provider available.")

    def _codex_cli_config_args(self, config: dict[str, Any] | None = None) -> list[str]:
        config = config or self._read_config_private()
        args: list[str] = []
        base_url = str(config.get("codex_base_url") or "").strip()
        if config.get("codex_credential_mode") == "api_env" and base_url:
            args.extend(["-c", f"openai_base_url={_toml_string(base_url)}"])
        model = str(config.get("codex_model") or "").strip()
        if model:
            args.extend(["-m", model])
        return args

    def _provider_prompt(self, job: dict[str, Any]) -> str:
        return (
            "You are running under Hermes-Yachiyo CodingExecutionService.\n"
            "Follow the approved plan only. Do not push, do not install dependencies, do not use sudo, "
            "and do not modify files outside writable scopes.\n\n"
            f"User request:\n{job['user_request']}\n\n"
            f"Task type: {job['task_type']}\n"
            f"Writable scopes: {', '.join(job['writable_scopes'])}\n"
            f"Branch: {job['branch_name']}\n\n"
            "Make the minimal implementation needed. Leave a concise final summary with files changed and tests run."
        )

    def _run_command(
        self,
        job_id: str,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except OSError as exc:
            return CommandResult(returncode=-1, stderr=str(exc))
        self._processes[job_id] = proc
        while proc.poll() is None:
            if self._is_cancelled(job_id):
                try:
                    proc.terminate()
                except OSError:
                    pass
                stdout, stderr = self._collect_after_terminate(proc)
                return CommandResult(proc.returncode or -1, _redact_text(stdout), _redact_text(stderr), cancelled=True)
            if time.monotonic() - started > timeout_seconds:
                try:
                    proc.terminate()
                except OSError:
                    pass
                stdout, stderr = self._collect_after_terminate(proc)
                return CommandResult(proc.returncode or -1, _redact_text(stdout), _redact_text(stderr), timed_out=True)
            time.sleep(0.2)
        stdout, stderr = proc.communicate()
        return CommandResult(proc.returncode or 0, _redact_text(stdout), _redact_text(stderr))

    def _provider_env(self, provider_id: str, job_id: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        config = self._read_config_private()
        if provider_id == "local_claude_code":
            env.pop("ANTHROPIC_BASE_URL", None)
            env.pop("ANTHROPIC_API_KEY", None)
            if config.get("claude_credential_mode") != "api_env":
                return env
            if not config.get("anthropic_api_key"):
                raise CodingExecutionError("Claude Code API Env 模式需要先配置 ANTHROPIC_API_KEY")
            if config.get("anthropic_base_url"):
                env["ANTHROPIC_BASE_URL"] = str(config["anthropic_base_url"])
            env["ANTHROPIC_API_KEY"] = str(config["anthropic_api_key"])
            if job_id:
                self._apply_isolated_auth_home(env, job_id, provider_id)
        elif provider_id == "codex_review":
            env.pop("OPENAI_BASE_URL", None)
            env.pop("OPENAI_API_KEY", None)
            if config.get("codex_credential_mode") != "api_env":
                return env
            if not config.get("codex_api_key"):
                raise CodingExecutionError("Codex CLI API Env 模式需要先配置 OPENAI_API_KEY")
            if config.get("codex_base_url"):
                env["OPENAI_BASE_URL"] = str(config["codex_base_url"])
            env["OPENAI_API_KEY"] = str(config["codex_api_key"])
            if job_id:
                self._apply_isolated_auth_home(env, job_id, provider_id)
        return env

    def _apply_isolated_auth_home(self, env: dict[str, str], job_id: str, provider_id: str) -> None:
        root = self.run_dir(job_id) / "provider-auth" / provider_id
        home = root / "home"
        xdg_config = root / "xdg-config"
        xdg_cache = root / "xdg-cache"
        xdg_state = root / "xdg-state"
        for path in (home, xdg_config, xdg_cache, xdg_state):
            path.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(xdg_config)
        env["XDG_CACHE_HOME"] = str(xdg_cache)
        env["XDG_STATE_HOME"] = str(xdg_state)
        if provider_id == "codex_review":
            codex_home = root / "codex-home"
            codex_home.mkdir(parents=True, exist_ok=True)
            env["CODEX_HOME"] = str(codex_home)
        elif provider_id == "local_claude_code":
            claude_config = root / "claude-config"
            claude_config.mkdir(parents=True, exist_ok=True)
            env["CLAUDE_CONFIG_DIR"] = str(claude_config)

    def _collect_after_terminate(self, proc: subprocess.Popen[str]) -> tuple[str, str]:
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            return proc.communicate()

    def _is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancel_flags

    # Git ---------------------------------------------------------------

    def _git(self, repo_path: Path, *args: str) -> CommandResult:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(returncode=-1, stderr=str(exc))
        return CommandResult(result.returncode, _redact_text(result.stdout), _redact_text(result.stderr))

    def _git_status_map(self, repo_path: Path) -> dict[str, str]:
        result = self._git(repo_path, "status", "--porcelain=v1", "--untracked-files=all")
        if not result.ok:
            return {}
        status: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line.strip() or len(line) < 4:
                continue
            code = line[:2]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            status[path] = code
        return status

    def _git_change_snapshot(self, repo_path: Path) -> dict[str, str]:
        status = self._git_status_map(repo_path)
        return {path: f"{code}:{self._file_fingerprint(repo_path / path)}" for path, code in status.items()}

    def _file_fingerprint(self, path: Path) -> str:
        try:
            if not path.exists():
                return "missing"
            if path.is_symlink():
                return "symlink:" + os.readlink(path)
            if path.is_dir():
                return "directory"
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError as exc:
            return f"error:{exc}"

    def _changed_files_since_baseline(self, before: dict[str, str], after: dict[str, str]) -> list[str]:
        files: list[str] = []
        for path, fingerprint in after.items():
            if before.get(path) != fingerprint:
                files.append(path)
        return sorted(files)

    # Review/checklist text -------------------------------------------

    def _manual_review_text(self, job: dict[str, Any], reason: str) -> str:
        files = job.get("changed_files") or []
        file_lines = "\n".join(f"- `{path}`" for path in files) if files else "- No changed files recorded yet."
        return (
            "# Manual Review Checklist\n\n"
            f"{reason}\n\n"
            "## Changed Files\n\n"
            f"{file_lines}\n\n"
            "## Checklist\n\n"
            "- Confirm changed files are within approved writable scopes.\n"
            "- Review diff for correctness and unintended behavior changes.\n"
            "- Run focused tests or build commands before merging.\n"
            "- Check that no secrets or local-only paths were committed.\n"
        )

    def _rollback_text(self, job: dict[str, Any], reason: str) -> str:
        branch = job.get("branch_name") or "current branch"
        return (
            "# Rollback Notes\n\n"
            f"Reason: {reason}\n\n"
            f"Job branch: `{branch}`\n\n"
            "Suggested manual rollback:\n\n"
            "```bash\n"
            "git status\n"
            "# inspect changes, then restore only files that belong to this job\n"
            "```\n\n"
            "Yachiyo does not run destructive rollback commands automatically in Phase 4 MVP.\n"
        )

    def _redacted_env_snapshot(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in os.environ.items():
            if re.search(r"(?i)(key|token|password|secret|authorization)", key):
                result[key] = "[redacted]"
            elif key in {"PATH", "HOME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE"}:
                result[key] = value
        return result

    def _public_argv(self, argv: list[str]) -> list[str]:
        return [_redact_text(part, limit=260) for part in argv]


_global_coding_service: CodingExecutionService | None = None
_global_lock = threading.Lock()


def get_coding_execution_service() -> CodingExecutionService:
    global _global_coding_service
    with _global_lock:
        if _global_coding_service is None:
            _global_coding_service = CodingExecutionService()
        return _global_coding_service


def close_coding_execution_service() -> None:
    global _global_coding_service
    with _global_lock:
        if _global_coding_service is not None:
            _global_coding_service.close()
            _global_coding_service = None
