"""System terminal helpers."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path


def open_terminal_command(command: str) -> tuple[bool, str | None]:
    """Open a system terminal and run an interactive command."""
    system = platform.system()
    if system == "Darwin":
        return _open_macos_terminal_command(command)
    if system == "Linux":
        return _open_linux_terminal_command(command)
    return False, f"当前平台（{system}）不支持自动打开终端，请手动运行：{command}"


def _open_macos_terminal_command(command: str) -> tuple[bool, str | None]:
    script_path = _write_macos_command_file(command)
    try:
        result = subprocess.run(
            ["open", "-a", "Terminal", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "Terminal 打开失败"
    return True, None


def _write_macos_command_file(command: str) -> Path:
    script_dir = Path(tempfile.gettempdir()) / "hermes-yachiyo-terminal"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f"hermes-yachiyo-{int(time.time() * 1000)}.command"
    script_path.write_text(
        "\n".join([
            "#!/bin/zsh",
            "clear",
            command,
            "status=$?",
            "echo",
            'if [ "$status" -eq 0 ]; then',
            '  echo "Hermes-Yachiyo：命令已完成。"',
            "else",
            '  echo "Hermes-Yachiyo：命令退出码 $status。"',
            "fi",
            'echo "完成后可以关闭此窗口。"',
            "exit $status",
            "",
        ]),
        encoding="utf-8",
    )
    os.chmod(script_path, 0o700)
    return script_path


def _open_linux_terminal_command(command: str) -> tuple[bool, str | None]:
    for terminal_cmd in [
        ["gnome-terminal", "--", "bash", "-c", command],
        ["xfce4-terminal", "-e", command],
        ["konsole", "-e", command],
        ["x-terminal-emulator", "-e", command],
        ["xterm", "-e", command],
    ]:
        try:
            subprocess.Popen(
                terminal_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, None
        except FileNotFoundError:
            continue
        except Exception as exc:
            return False, str(exc)
    return False, "未找到可用的终端模拟器，请手动打开终端"
