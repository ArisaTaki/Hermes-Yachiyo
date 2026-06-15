"""Skill install command validation for Agent Studio skill imports."""

from __future__ import annotations

import re
import shlex

from apps.shell.agent.runtime.errors import AgentRuntimeError


_SHELL_METACHARS = {"&&", "||", "&", ";", "|", ">", ">>", "<", "$(", "`", "\n", "\r"}


class SkillInstallCommandValidator:
    """Normalizes allowed Skill install commands and rejects shell execution."""

    def __init__(self, *, error_type: type[Exception] = AgentRuntimeError) -> None:
        self._error_type = error_type

    def validate(self, command: str) -> tuple[list[str], str]:
        if not command.strip():
            raise self._error_type("请输入 Skill 来源或安装命令")
        if any(token in command for token in _SHELL_METACHARS):
            raise self._error_type("Skill 安装命令不能包含 shell 管道、重定向或串联操作")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise self._error_type("Skill 安装命令格式无效") from exc
        if not argv:
            raise self._error_type("请输入 Skill 来源或安装命令")
        if re.fullmatch(r"skills(@[A-Za-z0-9._~-]+)?", argv[0]):
            argv = ["npx", *argv]
        if argv[0] == "npx":
            return self.validate_npx_skills_argv(argv), "npx_skills"
        if argv[0] in {"npm", "pnpm", "yarn", "bun", "curl", "bash", "sh", "zsh"}:
            raise self._error_type("只允许 skills 来源或 npx skills add")
        return self.validate_npx_skills_argv(["npx", "skills@latest", "add", *argv]), "npx_skills"

    @staticmethod
    def source_ref(argv: list[str], installer: str) -> str:
        if installer != "npx_skills":
            return ""
        index = 1
        while index < len(argv) and argv[index] in {"-y", "--yes"}:
            index += 1
        if index + 1 >= len(argv):
            return ""
        install_args = argv[index + 2:]
        clean_args: list[str] = []
        skip_next = False
        for arg in install_args:
            if skip_next:
                skip_next = False
                continue
            if arg in {"-a", "--agent"}:
                skip_next = True
                continue
            if arg.startswith("--agent=") or arg in {"--copy", "-y", "--yes"}:
                continue
            clean_args.append(arg)
        if not clean_args:
            return ""
        if re.fullmatch(r"[^/\s]+/[^/\s]+", clean_args[0]):
            clean_args[0] = f"https://github.com/{clean_args[0]}"
        return " ".join(clean_args)

    def validate_npx_skills_argv(self, argv: list[str]) -> list[str]:
        normalized = list(argv)
        index = 1
        while index < len(normalized) and normalized[index] in {"-y", "--yes"}:
            index += 1
        if index + 1 >= len(normalized) or not re.fullmatch(r"skills(@[A-Za-z0-9._~-]+)?", normalized[index]):
            raise self._error_type("只允许 Skill 来源、npx skills add 或 npx skills@latest add")
        if normalized[index + 1] not in {"add", "install"}:
            raise self._error_type("只允许 Skill 来源、npx skills add 或 npx skills@latest add")
        install_args = normalized[index + 2:]
        if not install_args:
            raise self._error_type("请提供要安装的 Skill 来源")
        self.validate_agent_target(install_args)
        if not self.has_agent_target(install_args):
            normalized.extend(["-a", "oha-yachiyo"])
        if "--copy" not in install_args:
            normalized.append("--copy")
        if "-y" not in normalized and "--yes" not in normalized:
            normalized.append("-y")
        return normalized

    @staticmethod
    def has_agent_target(args: list[str]) -> bool:
        return any(arg in {"-a", "--agent"} or arg.startswith("--agent=") for arg in args)

    def validate_agent_target(self, args: list[str]) -> None:
        for index, arg in enumerate(args):
            if arg == "-a" or arg == "--agent":
                value = args[index + 1] if index + 1 < len(args) else ""
                if value != "oha-yachiyo":
                    raise self._error_type("Yachiyo 安装入口固定使用 oha-yachiyo 目标")
            elif arg.startswith("--agent=") and arg != "--agent=oha-yachiyo":
                raise self._error_type("Yachiyo 安装入口固定使用 oha-yachiyo 目标")
