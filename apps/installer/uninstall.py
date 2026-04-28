"""Hermes-Yachiyo 卸载计划与执行。"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from apps.installer import backup as backup_mod
from apps.installer.hermes_setup import HermesEnvironmentSetup
from apps.shell import config as config_mod
from apps.shell.assets import project_display_path

logger = logging.getLogger(__name__)

UNINSTALL_CONFIRM_PHRASE = "UNINSTALL"
BACKUP_DIR_NAME = backup_mod.BACKUP_DIR_NAME


class UninstallScope(StrEnum):
    """卸载范围。"""

    YACHIYO_ONLY = "yachiyo_only"
    INCLUDE_HERMES = "include_hermes"


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
    """配置快照计划。"""

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
    hermes_home: str
    yachiyo_workspace: str
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


def _protected_paths() -> set[Path]:
    home = Path.home().expanduser().resolve()
    candidates = {
        Path("/"),
        home,
        home.parent,
        Path("/Applications"),
        Path("/Library"),
        Path("/System"),
        Path("/bin"),
        Path("/etc"),
        Path("/opt"),
        Path("/sbin"),
        Path("/usr"),
        Path("/var"),
    }
    return {path.resolve() for path in candidates if path.exists()}


def _is_protected_path(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return True
    return resolved in _protected_paths()


def _is_safe_app_config_dir(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    if _is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if resolved.name != ".hermes-yachiyo":
        return False, "配置目录名称不符合预期，已跳过"
    if not _is_relative_to(resolved, Path.home().expanduser()):
        return False, "配置目录不在当前用户目录下，已跳过"
    return True, ""


def _is_safe_yachiyo_workspace(path: Path) -> tuple[bool, str]:
    return backup_mod.is_safe_yachiyo_workspace(path)


def _looks_like_hermes_home(path: Path) -> bool:
    if path.name in {".hermes", "hermes"}:
        return True
    markers = (
        "bin/hermes",
        "config.yaml",
        "config.yml",
        "config.json",
        "yachiyo",
    )
    return any((path / marker).exists() for marker in markers)


def _is_safe_hermes_home(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    if _is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if not _is_relative_to(resolved, Path.home().expanduser()):
        return False, "Hermes Home 不在当前用户目录下，已跳过"
    if not _looks_like_hermes_home(resolved):
        return False, "路径不像 Hermes Home，已跳过"
    return True, ""


def _is_safe_hermes_binary(path: Path) -> tuple[bool, str]:
    resolved = path.expanduser().resolve()
    if resolved.name != "hermes":
        return False, "可执行文件名称不符合预期，已跳过"
    if not _is_relative_to(resolved, Path.home().expanduser()):
        return False, "Hermes 命令位于系统或共享路径，第一版不自动删除"
    if _is_protected_path(resolved.parent):
        return False, "Hermes 命令位于受保护路径，已跳过"
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


def _hermes_home_dir() -> Path:
    return Path(HermesEnvironmentSetup.get_effective_hermes_home()).expanduser()


def _backup_root(backup_root: str | Path | None = None) -> Path:
    return backup_mod.default_backup_root(backup_root)


def _discover_hermes_binary_paths() -> list[Path]:
    import shutil as _shutil

    candidates: list[Path] = []
    found = _shutil.which("hermes")
    if found:
        candidates.append(Path(found))

    try:
        from apps.installer.hermes_check import HERMES_COMMON_INSTALL_PATHS

        candidates.extend(Path(os.path.expanduser(item)) for item in HERMES_COMMON_INSTALL_PATHS)
    except Exception:
        pass

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


def build_uninstall_plan(
    scope: str | UninstallScope = UninstallScope.YACHIYO_ONLY,
    *,
    keep_config_snapshot: bool = True,
    backup_root: str | Path | None = None,
) -> UninstallPlan:
    """生成卸载计划，不修改文件系统。"""
    parsed_scope = _parse_scope(scope)
    app_config = _app_config_dir()
    hermes_home = _hermes_home_dir()
    yachiyo_workspace = hermes_home / "yachiyo"
    targets = [
        _make_target(
            target_id="app_config_dir",
            label="Hermes-Yachiyo 应用配置",
            path=app_config,
            kind="directory",
            safe_check=_is_safe_app_config_dir,
        )
    ]

    if parsed_scope == UninstallScope.YACHIYO_ONLY:
        targets.append(
            _make_target(
                target_id="yachiyo_workspace",
                label="Hermes-Yachiyo 工作空间",
                path=yachiyo_workspace,
                kind="directory",
                safe_check=_is_safe_yachiyo_workspace,
            )
        )
    else:
        targets.append(
            _make_target(
                target_id="hermes_home",
                label="Hermes Agent Home 与 Yachiyo 工作空间",
                path=hermes_home,
                kind="directory",
                safe_check=_is_safe_hermes_home,
            )
        )
        for index, binary_path in enumerate(_discover_hermes_binary_paths(), start=1):
            targets.append(
                _make_target(
                    target_id=f"hermes_binary_{index}",
                    label="Hermes Agent 命令",
                    path=binary_path,
                    kind="file",
                    safe_check=_is_safe_hermes_binary,
                )
            )

    warnings = []
    if keep_config_snapshot:
        warnings.append(
            "卸载前备份将保存 Hermes-Yachiyo 配置、工作空间、"
            "聊天数据库、缓存、日志与导入资源。"
        )
    for target in targets:
        if target.exists and not target.removable:
            warnings.append(f"{target.label} 将跳过：{target.reason}")

    backup_root_path = _backup_root(backup_root)
    return UninstallPlan(
        scope=parsed_scope,
        keep_config_snapshot=keep_config_snapshot,
        confirm_phrase=UNINSTALL_CONFIRM_PHRASE,
        app_config_dir=str(app_config),
        hermes_home=str(hermes_home),
        yachiyo_workspace=str(yachiyo_workspace),
        targets=targets,
        backup=BackupPlan(
            enabled=keep_config_snapshot,
            backup_root=str(backup_root_path),
            backup_root_display=_display_path(backup_root_path),
            note="卸载前生成可随时导入的 Hermes-Yachiyo ZIP 备份",
        ),
        warnings=warnings,
    )


def create_uninstall_backup(
    plan: UninstallPlan,
    *,
    backup_root: str | Path | None = None,
) -> Path:
    """创建卸载前备份。"""
    backup = backup_mod.create_backup(
        backup_root=backup_root,
        source_context=f"uninstall:{plan.scope.value}",
    )
    return Path(backup.path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def execute_uninstall(
    scope: str | UninstallScope = UninstallScope.YACHIYO_ONLY,
    *,
    keep_config_snapshot: bool = True,
    confirm_text: str = "",
    backup_root: str | Path | None = None,
) -> UninstallResult:
    """执行卸载。调用方必须传入确认短语。"""
    plan = build_uninstall_plan(
        scope,
        keep_config_snapshot=keep_config_snapshot,
        backup_root=backup_root,
    )
    if confirm_text != UNINSTALL_CONFIRM_PHRASE:
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
