"""GPT-SoVITS local service helpers for proactive TTS."""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
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
    model_status = _gpt_sovits_model_status(workdir)
    api_process = _service_process_status(base_url)
    related_launch_agents = _related_launch_agents(workdir)
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
        "api_process": api_process,
        "related_launch_agents": related_launch_agents,
        "platform_supported": platform.system() == "Darwin",
        "tools": {
            "python": _tool_exists("python3.11", "python3", "python"),
            "python311": _tool_exists("python3.11"),
            "git": _tool_exists("git"),
            "uv": _tool_exists("uv"),
            "ffmpeg": _tool_exists("ffmpeg"),
            "mecab_config": _tool_exists("mecab-config"),
            "torchcodec": _python_package_available(workdir, "torchcodec"),
        },
        "models": model_status["models"],
        "missing_model_files": model_status["missing"],
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


def adopt_gpt_sovits_launch_agent(config: Any) -> dict[str, Any]:
    """Disable user-level third-party GPT-SoVITS agents and install the Hermes agent."""
    if platform.system() != "Darwin":
        return {"ok": False, "error": "GPT-SoVITS 后台/开机自启目前仅支持 macOS LaunchAgent"}

    tts = getattr(config, "tts", config)
    base_url = str(getattr(tts, "gsv_base_url", "") or "").rstrip("/")
    workdir = _expand_path(str(getattr(tts, "gsv_service_workdir", "") or ""))
    command = str(getattr(tts, "gsv_service_command", "") or "").strip()
    if not workdir or not workdir.exists() or not workdir.is_dir():
        return {"ok": False, "error": "请先填写存在的 GPT-SoVITS 服务目录"}
    if not command:
        return {"ok": False, "error": "请先填写 GPT-SoVITS 服务启动命令"}

    external_agents = [
        agent for agent in _related_launch_agents(workdir) if not agent["managed_by_hermes"]
    ]
    if not external_agents:
        return {
            "ok": False,
            "error": "未检测到可接管的外部 GPT-SoVITS 用户级 LaunchAgent",
            "status": get_gpt_sovits_service_status(config),
        }

    unsafe_agents = []
    for agent in external_agents:
        if not _is_user_launch_agent_path(Path(str(agent.get("path") or ""))):
            unsafe_agents.append(agent)
    if unsafe_agents:
        labels = "、".join(
            str(agent.get("label") or agent.get("path_display") or "未知服务")
            for agent in unsafe_agents
        )
        return {
            "ok": False,
            "error": f"检测到系统级或不可写的 GPT-SoVITS 自启项，无法自动接管：{labels}",
            "status": get_gpt_sovits_service_status(config),
        }

    current_process = _service_process_status(base_url)
    disabled_agents: list[dict[str, str]] = []
    try:
        for agent in external_agents:
            disabled_agents.append(_disable_user_launch_agent(agent))
    except OSError as exc:
        return {
            "ok": False,
            "error": f"停用外部 GPT-SoVITS 自启项失败：{exc}",
            "disabled_launch_agents": disabled_agents,
            "status": get_gpt_sovits_service_status(config),
        }

    if not _wait_for_service_process_stop(base_url, current_process.get("pid")):
        return {
            "ok": False,
            "error": (
                "外部 GPT-SoVITS 服务仍占用 API 端口，已停用自启项；"
                "请停止该进程后再启动 Hermes-Yachiyo 后台服务"
            ),
            "disabled_launch_agents": disabled_agents,
            "status": get_gpt_sovits_service_status(config),
        }

    install_result = install_gpt_sovits_launch_agent(config)
    install_result["disabled_launch_agents"] = disabled_agents
    if install_result.get("ok") is True:
        install_result["message"] = "已停用外部 GPT-SoVITS 自启项，并交由 Hermes-Yachiyo 管理"
    return install_result


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
    return _launch_agent_label_running(LAUNCH_AGENT_LABEL)


def _launch_agent_label_running(label: str) -> bool:
    if platform.system() != "Darwin":
        return False
    result = _launchctl(["print", f"{_launchctl_domain()}/{label}"], check=False)
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
    detail = "\n".join(
        part.strip() for part in (result.stderr, result.stdout) if part and part.strip()
    )
    return f"{command} 失败，退出码 {result.returncode}{f'：{detail}' if detail else ''}"


def _service_process_status(base_url: str) -> dict[str, Any]:
    port = _base_url_port(base_url)
    if not port or platform.system() not in {"Darwin", "Linux"}:
        return {"running": False}

    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return {"running": False, "port": port}
    if result.returncode != 0:
        return {"running": False, "port": port}

    pid = _first_lsof_pid(result.stdout)
    if not pid:
        return {"running": False, "port": port}

    process = {"running": True, "port": port, "pid": pid}
    process.update(_process_snapshot(pid))
    return process


def _base_url_port(base_url: str) -> int | None:
    if not base_url:
        return None
    parsed = urlparse(base_url)
    if parsed.port:
        return parsed.port
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def _first_lsof_pid(output: str) -> int | None:
    for line in output.splitlines():
        if not line.startswith("p"):
            continue
        try:
            return int(line[1:])
        except ValueError:
            continue
    return None


def _process_snapshot(pid: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=", "-o", "ppid=", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return {}
    if result.returncode != 0:
        return {}
    line = result.stdout.strip()
    if not line:
        return {}
    parts = line.split(None, 2)
    snapshot: dict[str, Any] = {}
    if len(parts) >= 2:
        try:
            snapshot["ppid"] = int(parts[1])
        except ValueError:
            pass
    if len(parts) >= 3:
        snapshot["command"] = parts[2]
    return snapshot


def _related_launch_agents(workdir: Path | None) -> list[dict[str, Any]]:
    if platform.system() != "Darwin":
        return []
    roots = [Path.home() / "Library" / "LaunchAgents", Path("/Library/LaunchAgents")]
    workdir_text = str(workdir.expanduser()) if workdir else ""
    agents: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for plist_path in sorted(root.glob("*.plist")):
            info = _launch_agent_info(plist_path, workdir_text)
            if info is not None:
                agents.append(info)
    return agents


def _launch_agent_info(plist_path: Path, workdir_text: str) -> dict[str, Any] | None:
    try:
        payload = plistlib.loads(plist_path.read_bytes())
    except Exception:
        return None
    label = str(payload.get("Label") or plist_path.stem)
    args = payload.get("ProgramArguments")
    if isinstance(args, list):
        arg_text = " ".join(str(item) for item in args)
    else:
        arg_text = str(args or "")
    working_directory = str(payload.get("WorkingDirectory") or "")
    haystack = " ".join([label, arg_text, working_directory])
    if not _looks_like_related_gpt_sovits_agent(haystack, workdir_text):
        return None
    return {
        "label": label,
        "path": str(plist_path),
        "path_display": _display_path(plist_path),
        "working_directory": working_directory,
        "managed_by_hermes": label == LAUNCH_AGENT_LABEL,
        "running": _launch_agent_label_running(label),
    }


def _disable_user_launch_agent(agent: dict[str, Any]) -> dict[str, str]:
    label = str(agent.get("label") or "")
    plist_path = Path(str(agent.get("path") or "")).expanduser()
    if not _is_user_launch_agent_path(plist_path):
        raise OSError(f"不是用户级 LaunchAgent：{agent.get('path_display') or plist_path}")

    domain = _launchctl_domain()
    if label:
        _launchctl(["bootout", f"{domain}/{label}"], check=False)
    if plist_path.exists():
        _launchctl(["bootout", domain, str(plist_path)], check=False)
        disabled_path = _disabled_launch_agent_path(plist_path)
        plist_path.rename(disabled_path)
    else:
        disabled_path = plist_path

    return {
        "label": label,
        "path": str(plist_path),
        "path_display": _display_path(plist_path),
        "disabled_path": str(disabled_path),
        "disabled_path_display": _display_path(disabled_path),
    }


def _wait_for_service_process_stop(
    base_url: str,
    previous_pid: int | None,
    *,
    timeout_seconds: float = 8,
) -> bool:
    if not _base_url_port(base_url):
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        process = _service_process_status(base_url)
        if not process.get("running"):
            return True
        if previous_pid and process.get("pid") != previous_pid:
            return False
        time.sleep(0.35)
    return not _service_process_status(base_url).get("running")


def _is_user_launch_agent_path(path: Path) -> bool:
    if not str(path):
        return False
    try:
        path.expanduser().resolve().relative_to(
            (Path.home() / "Library" / "LaunchAgents").resolve()
        )
    except Exception:
        return False
    return path.suffix == ".plist"


def _disabled_launch_agent_path(plist_path: Path) -> Path:
    base = plist_path.with_name(f"{plist_path.name}.hermes-yachiyo-disabled")
    if not base.exists():
        return base
    for index in range(2, 100):
        candidate = plist_path.with_name(f"{plist_path.name}.hermes-yachiyo-disabled-{index}")
        if not candidate.exists():
            return candidate
    return plist_path.with_name(f"{plist_path.name}.hermes-yachiyo-disabled-{int(time.time())}")


def _looks_like_related_gpt_sovits_agent(haystack: str, workdir_text: str) -> bool:
    if LAUNCH_AGENT_LABEL in haystack:
        return True
    if workdir_text and workdir_text in haystack:
        return True
    lowered = haystack.lower()
    return "gpt-sovits" in lowered and ("api_v2.py" in lowered or "gsv" in lowered)


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


def _python_package_available(workdir: Path | None, package: str) -> bool:
    venv_candidates: list[Path] = []
    if workdir:
        venv_candidates.extend(
            [workdir / ".venv" / "bin" / "python", workdir / "venv" / "bin" / "python"]
        )
    candidates = [python for python in venv_candidates if python.exists()]
    if not candidates:
        for tool in (_tool_path("python3.11"), _tool_path("python3"), _tool_path("python")):
            if tool:
                candidates.append(Path(tool))

    seen: set[str] = set()
    for python in candidates:
        key = str(python)
        if key in seen:
            continue
        seen.add(key)
        if not python.exists():
            continue
        try:
            result = subprocess.run(
                [str(python), "-c", f"import {package}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            continue
        if result.returncode == 0:
            return True
    return False


def _gpt_sovits_model_status(workdir: Path | None) -> dict[str, Any]:
    if not workdir:
        return {"models": {}, "missing": []}

    pretrained = workdir / "GPT_SoVITS" / "pretrained_models"
    models = {
        "s1v3": _nonempty_file(pretrained / "s1v3.ckpt"),
        "s2Gv4": _nonempty_file(pretrained / "gsv-v4-pretrained" / "s2Gv4.pth"),
        "vocoder": _nonempty_file(pretrained / "gsv-v4-pretrained" / "vocoder.pth"),
        "g2pw": _nonempty_file(workdir / "GPT_SoVITS" / "text" / "G2PWModel" / "g2pW.onnx"),
        "bert": _has_model_weight(pretrained / "chinese-roberta-wwm-ext-large"),
        "cnhubert": _has_model_weight(pretrained / "chinese-hubert-base"),
    }
    return {
        "models": models,
        "missing": [name for name, ok in models.items() if not ok],
    }


def _has_model_weight(path: Path) -> bool:
    return any(_nonempty_file(path / name) for name in ("pytorch_model.bin", "model.safetensors"))


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return f"~/{path.expanduser().resolve().relative_to(Path.home().resolve())}"
    except Exception:
        return str(path)
