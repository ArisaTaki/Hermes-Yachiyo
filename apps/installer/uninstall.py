"""Oha-Yachiyo uninstall planning and execution."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from apps.installer import backup as backup_mod
from apps.shell import config as config_mod
from apps.shell import gpt_sovits_service
from apps.shell.assets import project_display_path

logger = logging.getLogger(__name__)

UNINSTALL_CONFIRM_PHRASE = "UNINSTALL"


class UninstallScope(StrEnum):
    """卸载范围。"""

    OHA_ONLY = "oha_only"


@dataclass(frozen=True)
class UninstallTarget:
    """单个卸载目标。"""

    id: str
    label: str
    path: str
    display_path: str
    kind: str
    exists: bool
    removable: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackupPlan:
    """卸载前资料备份计划。"""

    enabled: bool
    backup_root: str
    backup_root_display: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UninstallPlan:
    """完整卸载计划。"""

    scope: UninstallScope
    keep_config_snapshot: bool
    confirm_phrase: str
    app_config_dir: str
    native_home: str
    oha_workspace: str
    targets: list[UninstallTarget]
    backup: BackupPlan
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["targets"] = [target.to_dict() for target in self.targets]
        data["backup"] = self.backup.to_dict()
        data["existing_count"] = sum(1 for target in self.targets if target.exists)
        data["removable_count"] = sum(
            1 for target in self.targets if target.exists and target.removable
        )
        return data


@dataclass(frozen=True)
class UninstallResult:
    """卸载执行结果。"""

    ok: bool
    plan: UninstallPlan
    backup_path: str = ""
    backup_path_display: str = ""
    removed: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "plan": self.plan.to_dict(),
            "backup_path": self.backup_path,
            "backup_path_display": self.backup_path_display,
            "removed": self.removed,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
        }


def _parse_scope(scope: str | UninstallScope) -> UninstallScope:
    if isinstance(scope, UninstallScope):
        return scope
    try:
        return UninstallScope(str(scope))
    except ValueError as exc:
        raise ValueError("未知卸载范围") from exc


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _display_path(path: Path) -> str:
    try:
        return project_display_path(path)
    except Exception:
        return str(path.expanduser())


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _normalize_confirm_text(value: Any) -> str:
    return str(value or "").strip()


def _is_safe_native_home(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    if backup_mod.is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if not _is_relative_to(resolved, Path.home().expanduser()):
        return False, "Oha-Yachiyo runtime 不在当前用户目录下，已跳过"
    if resolved.name != ".oha-yachiyo":
        return False, "路径不像 Oha-Yachiyo runtime，已跳过"
    if _path_exists(resolved):
        safe, reason = backup_mod.is_safe_oha_workspace(resolved)
        if not safe:
            return False, reason
    return True, ""


def _is_safe_gpt_sovits_workdir(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    if backup_mod.is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if not _is_relative_to(resolved, Path.home().expanduser()):
        return False, "GPT-SoVITS 服务目录不在当前用户目录下，已跳过"
    if resolved.name != "GPT-SoVITS":
        return False, "路径不像 GPT-SoVITS 服务目录，已跳过"
    if not ((resolved / "api_v2.py").exists() or (resolved / "GPT_SoVITS").exists()):
        return False, "路径不像 GPT-SoVITS 服务目录，已跳过"
    return True, ""


def _is_safe_gpt_sovits_launch_agent(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    expected = (
        Path.home().expanduser()
        / "Library"
        / "LaunchAgents"
        / f"{gpt_sovits_service.LAUNCH_AGENT_LABEL}.plist"
    ).resolve()
    if resolved != expected:
        return False, "LaunchAgent 路径不符合预期，已跳过"
    return True, ""


def _make_target(
    *,
    target_id: str,
    label: str,
    path: Path,
    kind: str,
    safe_check: Any,
) -> UninstallTarget:
    expanded = path.expanduser()
    exists = _path_exists(expanded)
    removable, reason = safe_check(expanded)
    if not exists:
        removable = False
        reason = "路径不存在"
    return UninstallTarget(
        id=target_id,
        label=label,
        path=str(expanded),
        display_path=_display_path(expanded),
        kind=kind,
        exists=exists,
        removable=removable,
        reason=reason,
    )


def _app_config_dir() -> Path:
    return Path(getattr(config_mod, "_CONFIG_DIR")).expanduser()


def _oha_yachiyo_home_dir() -> Path:
    return Path(os.getenv("OHA_YACHIYO_HOME", "~/.oha-yachiyo")).expanduser()


def _backup_root(backup_root: str | Path | None = None) -> Path:
    return backup_mod.default_backup_root(backup_root)


def _load_current_config() -> config_mod.AppConfig:
    try:
        return config_mod.load_config()
    except Exception:
        return config_mod.AppConfig()


def _discover_gpt_sovits_workdir_paths(app_config: config_mod.AppConfig) -> list[Path]:
    candidates: list[Path] = []
    configured = str(getattr(app_config.tts, "gsv_service_workdir", "") or "").strip()
    if configured:
        candidates.append(Path(os.path.expandvars(configured)).expanduser())
    candidates.append(Path.home().expanduser() / "AI" / "GPT-SoVITS")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        expanded = candidate.expanduser()
        key = str(expanded)
        if key in seen or not _path_exists(expanded):
            continue
        seen.add(key)
        unique.append(expanded)
    return unique


def _gpt_sovits_installed(app_config: config_mod.AppConfig) -> bool:
    return bool(
        _path_exists(Path(gpt_sovits_service._launch_agent_path()).expanduser())
        or _discover_gpt_sovits_workdir_paths(app_config)
    )


def build_uninstall_plan(
    scope: str | UninstallScope = UninstallScope.OHA_ONLY,
    *,
    keep_config_snapshot: bool = True,
    include_gpt_sovits: bool = False,
    backup_root: str | Path | None = None,
) -> UninstallPlan:
    """生成卸载计划，不修改文件系统。"""
    parsed_scope = _parse_scope(scope)
    app_config = _app_config_dir()
    native_home = _oha_yachiyo_home_dir()
    oha_workspace = native_home
    app_config_data = _load_current_config()
    targets = [
        _make_target(
            target_id="app_config_dir",
            label="Oha-Yachiyo 应用配置",
            path=app_config,
            kind="directory",
            safe_check=backup_mod.is_safe_app_config_dir,
        ),
        _make_target(
            target_id="oha_workspace",
            label="Oha-Yachiyo 工作空间",
            path=oha_workspace,
            kind="directory",
            safe_check=_is_safe_native_home,
        ),
    ]

    if include_gpt_sovits:
        targets.append(
            _make_target(
                target_id="gpt_sovits_launch_agent",
                label="GPT-SoVITS 后台服务与开机自启",
                path=Path(gpt_sovits_service._launch_agent_path()),
                kind="launch_agent",
                safe_check=_is_safe_gpt_sovits_launch_agent,
            )
        )
        for index, workdir in enumerate(
            _discover_gpt_sovits_workdir_paths(app_config_data),
            start=1,
        ):
            targets.append(
                _make_target(
                    target_id=f"gpt_sovits_workdir_{index}",
                    label="GPT-SoVITS 服务目录（含基础模型）",
                    path=workdir,
                    kind="directory",
                    safe_check=_is_safe_gpt_sovits_workdir,
                )
            )

    warnings = []
    if keep_config_snapshot:
        warnings.append(
            "卸载前备份将保存 Oha-Yachiyo 配置、工作空间、"
            "聊天数据库、缓存、日志与导入资源。"
        )
    for target in targets:
        if target.exists and not target.removable:
            warnings.append(f"{target.label} 将跳过：{target.reason}")
    if not include_gpt_sovits and _gpt_sovits_installed(app_config_data):
        warnings.append(
            "检测到 GPT-SoVITS 本地服务；当前未选择卸载，将保留服务目录与开机自启配置。"
        )
    if include_gpt_sovits:
        warnings.append("将删除 GPT-SoVITS 服务目录，包括已下载的基础预训练模型和运行环境。")

    backup_root_path = _backup_root(backup_root)
    return UninstallPlan(
        scope=parsed_scope,
        keep_config_snapshot=keep_config_snapshot,
        confirm_phrase=UNINSTALL_CONFIRM_PHRASE,
        app_config_dir=str(app_config),
        native_home=str(native_home),
        oha_workspace=str(oha_workspace),
        targets=targets,
        backup=BackupPlan(
            enabled=keep_config_snapshot,
            backup_root=str(backup_root_path),
            backup_root_display=_display_path(backup_root_path),
            note="卸载前生成可随时导入的 Oha-Yachiyo ZIP 备份",
        ),
        warnings=warnings,
    )


def create_uninstall_backup(
    plan: UninstallPlan,
    *,
    backup_root: str | Path | None = None,
) -> Path:
    """创建卸载前备份。"""
    effective_backup_root: str | Path | None = (
        backup_root if backup_root is not None else plan.backup.backup_root
    )
    backup = backup_mod.create_backup(
        backup_root=effective_backup_root,
        source_context=f"uninstall:{plan.scope.value}",
    )
    return Path(backup.path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def execute_uninstall(
    scope: str | UninstallScope = UninstallScope.OHA_ONLY,
    *,
    keep_config_snapshot: bool = True,
    include_gpt_sovits: bool = False,
    confirm_text: str = "",
    backup_root: str | Path | None = None,
) -> UninstallResult:
    """执行卸载。调用方必须传入确认短语。"""
    plan = build_uninstall_plan(
        scope,
        keep_config_snapshot=keep_config_snapshot,
        include_gpt_sovits=include_gpt_sovits,
        backup_root=backup_root,
    )
    if _normalize_confirm_text(confirm_text) != _normalize_confirm_text(
        UNINSTALL_CONFIRM_PHRASE
    ):
        return UninstallResult(
            ok=False,
            plan=plan,
            errors=[f"请输入确认短语 {UNINSTALL_CONFIRM_PHRASE}"],
        )

    backup_path = Path("")
    if keep_config_snapshot:
        try:
            backup_path = create_uninstall_backup(plan, backup_root=backup_root)
        except Exception as exc:
            logger.error("创建卸载前备份失败: %s", exc)
            return UninstallResult(
                ok=False,
                plan=plan,
                errors=[f"创建备份失败，已取消卸载：{exc}"],
            )

    removed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for target in plan.targets:
        path = Path(target.path).expanduser()
        if not target.exists:
            skipped.append({"label": target.label, "path": target.path, "reason": "路径不存在"})
            continue
        if not _path_exists(path):
            skipped.append({
                "label": target.label,
                "path": target.path,
                "reason": "已随上级目录删除",
            })
            continue
        if not target.removable:
            skipped.append({"label": target.label, "path": target.path, "reason": target.reason})
            continue
        try:
            if target.id == "gpt_sovits_launch_agent":
                service_result = gpt_sovits_service.uninstall_gpt_sovits_launch_agent()
                if service_result.get("ok") is False:
                    raise RuntimeError(
                        str(service_result.get("error") or "停止 GPT-SoVITS 后台服务失败")
                    )
            elif target.id.startswith("gpt_sovits_workdir_"):
                gpt_sovits_service.uninstall_gpt_sovits_launch_agent()
                _remove_path(path)
            else:
                _remove_path(path)
            removed.append({"label": target.label, "path": target.path})
        except Exception as exc:
            logger.error("卸载目标删除失败: %s (%s)", path, exc)
            failed.append({"label": target.label, "path": target.path, "reason": str(exc)})

    errors = [f"{item['label']} 删除失败：{item['reason']}" for item in failed]
    return UninstallResult(
        ok=not failed,
        plan=plan,
        backup_path=str(backup_path) if str(backup_path) != "." else "",
        backup_path_display=_display_path(backup_path) if str(backup_path) != "." else "",
        removed=removed,
        skipped=skipped,
        failed=failed,
        errors=errors,
    )
