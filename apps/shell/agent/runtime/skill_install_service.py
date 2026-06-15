"""Skill install command execution for Agent Studio Skill imports."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from packages.security import scrubbed_subprocess_env


class RuntimeSkillInstallService:
    """Runs validated Skill install commands without owning Skill persistence."""

    def __init__(
        self,
        *,
        validator: SkillInstallCommandValidator,
        skill_installs_dir: Path,
        skill_installs_native_home: Path,
        normalize_skill_folder_id: Callable[[str | None], str],
        sync_installed_skills: Callable[..., dict[str, Any]],
        run_command: Callable[..., Any],
        now: Callable[[], str],
        redact_secrets: Callable[[Any], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._validator = validator
        self._skill_installs_dir = skill_installs_dir
        self._skill_installs_native_home = skill_installs_native_home
        self._normalize_skill_folder_id = normalize_skill_folder_id
        self._sync_installed_skills = sync_installed_skills
        self._run_command = run_command
        self._now = now
        self._redact_secrets = redact_secrets
        self._error_type = error_type

    def install(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        argv, installer = self._validator.validate(command)
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        source_ref = self._validator.source_ref(argv, installer)
        started_at = self._now()
        env = scrubbed_subprocess_env({"OHA_YACHIYO_HOME": str(self._skill_installs_native_home)})
        try:
            completed = self._run_command(
                argv,
                cwd=self._skill_installs_dir,
                env=env,
                text=True,
                capture_output=True,
                timeout=600,
                check=False,
            )
        except FileNotFoundError as exc:
            raise self._error_type(f"找不到安装命令：{argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise self._error_type("Skill 安装命令超时") from exc
        stdout = self._redact_secrets(getattr(completed, "stdout", ""))[-12000:]
        stderr = self._redact_secrets(getattr(completed, "stderr", ""))[-12000:]
        sync_result = (
            self._sync_installed_skills(
                record_source_type=installer,
                folder_id=target_folder_id,
                source_ref_override=source_ref,
                restore_deleted=True,
            )
            if completed.returncode == 0
            else None
        )
        return {
            "ok": completed.returncode == 0,
            "installer": installer,
            "command": argv,
            "started_at": started_at,
            "finished_at": self._now(),
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "sync": sync_result,
        }
