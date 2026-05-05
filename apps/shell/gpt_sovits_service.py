"""GPT-SoVITS local service helpers for proactive TTS."""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin
from urllib.error import HTTPError
from urllib.request import Request, urlopen


LAUNCH_AGENT_LABEL = "com.hermes-yachiyo.gpt-sovits"


def get_gpt_sovits_service_status(config: Any) -> dict[str, Any]:
    """Return a side-effect-free status snapshot for the configured GPT-SoVITS service."""
    tts = getattr(config, "tts", config)
    base_url = str(getattr(tts, "gsv_base_url", "") or "").rstrip("/")
    workdir = _expand_path(str(getattr(tts, "gsv_service_workdir", "") or ""))
    command = str(getattr(tts, "gsv_service_command", "") or "").strip()
    plist_path = _launch_agent_path()
    reachable = _service_reachable(base_url)
    return {
        "provider": "gpt-sovits",
        "base_url": base_url,
        "reachable": reachable["ok"],
        "reachable_error": reachable.get("error", ""),
        "workdir": str(workdir) if workdir else "",
        "workdir_display": _display_path(workdir) if workdir else "",
        "workdir_exists": bool(workdir and workdir.exists() and workdir.is_dir()),
        "command": command,
        "command_configured": bool(command),
        "plist_path": str(plist_path),
        "plist_path_display": _display_path(plist_path),
        "launch_agent_installed": plist_path.exists(),
        "launch_agent_running": _launch_agent_running(),
        "platform_supported": platform.system() == "Darwin",
        "tools": {
            "python": _tool_exists("python3.11", "python3", "python"),
            "python311": _tool_exists("python3.11"),
            "git": _tool_exists("git"),
            "uv": _tool_exists("uv"),
            "ffmpeg": _tool_exists("ffmpeg"),
            "mecab_config": _tool_exists("mecab-config"),
        },
        "logs": {
            "stdout": _display_path(_log_path("out")),
            "stderr": _display_path(_log_path("err")),
        },
    }


def get_gpt_sovits_service_status_for_values(
    *,
    base_url: str = "",
    workdir: str = "",
    command: str = "",
) -> dict[str, Any]:
    """Return status for unsaved UI draft values."""
    config = SimpleNamespace(
        tts=SimpleNamespace(
            gsv_base_url=base_url,
            gsv_service_workdir=workdir,
            gsv_service_command=command,
        )
    )
    return get_gpt_sovits_service_status(config)


def install_gpt_sovits_launch_agent(config: Any) -> dict[str, Any]:
    """Install and start a user LaunchAgent for the configured GPT-SoVITS service."""
    if platform.system() != "Darwin":
        return {"ok": False, "error": "GPT-SoVITS 后台/开机自启目前仅支持 macOS LaunchAgent"}
    tts = getattr(config, "tts", config)
    workdir = _expand_path(str(getattr(tts, "gsv_service_workdir", "") or ""))
    command = str(getattr(tts, "gsv_service_command", "") or "").strip()
    if not workdir or not workdir.exists() or not workdir.is_dir():
        return {"ok": False, "error": "请先填写存在的 GPT-SoVITS 服务目录"}
    if not command:
        return {"ok": False, "error": "请先填写 GPT-SoVITS 服务启动命令"}

    plist_path = _launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    _log_path("out").parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/bin/zsh", "-lc", _service_shell_command(command)],
        "WorkingDirectory": str(workdir),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(_log_path("out")),
        "StandardErrorPath": str(_log_path("err")),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }
    plist_path.write_bytes(plistlib.dumps(payload, sort_keys=False))
    _launchctl(["bootout", _launchctl_domain(), str(plist_path)], check=False)
    bootstrap = _launchctl(["bootstrap", _launchctl_domain(), str(plist_path)], check=False)
    if bootstrap.returncode != 0:
        return {
            "ok": False,
            "error": _command_error("launchctl bootstrap", bootstrap),
            "status": get_gpt_sovits_service_status(config),
        }
    _launchctl(["kickstart", "-k", f"{_launchctl_domain()}/{LAUNCH_AGENT_LABEL}"], check=False)
    return {
        "ok": True,
        "message": "已启动 GPT-SoVITS 后台服务，并安装为登录后自动运行",
        "status": get_gpt_sovits_service_status(config),
    }


def uninstall_gpt_sovits_launch_agent(config: Any | None = None) -> dict[str, Any]:
    """Stop and remove the GPT-SoVITS LaunchAgent if present."""
    if platform.system() != "Darwin":
        return {"ok": False, "error": "GPT-SoVITS 后台/开机自启目前仅支持 macOS LaunchAgent"}
    plist_path = _launch_agent_path()
    _launchctl(["bootout", _launchctl_domain(), str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)
    result = {
        "ok": True,
        "message": "已停止 GPT-SoVITS 后台服务，并移除开机自启",
    }
    if config is not None:
        result["status"] = get_gpt_sovits_service_status(config)
    return result


def _service_shell_command(command: str) -> str:
    return "\n".join(
        [
            'if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi',
            'if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi',
            "if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi",
            "if [ -f venv/bin/activate ]; then source venv/bin/activate; fi",
            command,
        ]
    )


def _service_reachable(base_url: str) -> dict[str, Any]:
    if not base_url:
        return {"ok": False, "error": "API Base URL 未配置"}
    health_url = urljoin(base_url.rstrip("/") + "/", "docs")
    try:
        with urlopen(Request(health_url), timeout=2):
            return {"ok": True}
    except HTTPError:
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def _launch_agent_running() -> bool:
    if platform.system() != "Darwin":
        return False
    result = _launchctl(["print", f"{_launchctl_domain()}/{LAUNCH_AGENT_LABEL}"], check=False)
    return result.returncode == 0


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        timeout=12,
        check=check,
    )


def _command_error(command: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part and part.strip())
    return f"{command} 失败，退出码 {result.returncode}{f'：{detail}' if detail else ''}"


def _log_path(kind: str) -> Path:
    suffix = "out.log" if kind == "out" else "err.log"
    return Path.home() / ".hermes" / "yachiyo" / "logs" / f"gpt-sovits-{suffix}"


def _expand_path(value: str) -> Path | None:
    text = value.strip()
    return Path(os.path.expandvars(text)).expanduser() if text else None


def _tool_path(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
        for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
            candidate = Path(prefix) / name
            if candidate.exists():
                return str(candidate)
    return None


def _tool_exists(*names: str) -> bool:
    return _tool_path(*names) is not None


def _display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return f"~/{path.expanduser().resolve().relative_to(Path.home().resolve())}"
    except Exception:
        return str(path)
