"""Hermes-Yachiyo 卸载计划与执行。"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from apps.installer.hermes_setup import HermesEnvironmentSetup
from apps.shell import config as config_mod
from apps.shell.assets import project_display_path

logger = logging.getLogger(__name__)

UNINSTALL_CONFIRM_PHRASE = "UNINSTALL"
BACKUP_DIR_NAME = "Hermes-Yachiyo-uninstall-backups"


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


@dataclass(frozen=True)
class ConfigSnapshotInfo:
    """卸载配置快照信息。"""

    path: str
    display_path: str
    created_at: str = ""
    scope: str = ""
    schema_version: int = 0
    valid: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfigSnapshotImportResult:
    """配置快照导入结果。"""

    ok: bool
    snapshot: ConfigSnapshotInfo | None = None
    restored: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    restart_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "restored": self.restored,
            "skipped": self.skipped,
            "errors": self.errors,
            "restart_required": self.restart_required,
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
    resolved = path.expanduser().resolve()
    if _is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if resolved.name != "yachiyo":
        return False, "工作空间目录名称不符合预期，已跳过"
    if resolved.parent == Path.home().expanduser().resolve():
        return False, "工作空间不能直接指向用户主目录下的通用目录，已跳过"
    return True, ""


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
    if backup_root is not None:
        return Path(backup_root).expanduser()
    return Path.home().expanduser() / BACKUP_DIR_NAME


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
        warnings.append("配置快照只保存配置与初始化信息，不包含聊天数据库和大型资源包。")
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
            note="保留下次导入用的 Hermes-Yachiyo 配置快照",
        ),
        warnings=warnings,
    )


def _unique_backup_dir(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = root / f"hermes-yachiyo-config-{timestamp}"
    if not base.exists():
        return base
    suffix = 2
    while True:
        candidate = root / f"hermes-yachiyo-config-{timestamp}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def _copy_path(source: Path, target: Path) -> bool:
    if not _path_exists(source):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target, follow_symlinks=False)
    return True


def _replace_path(source: Path, target: Path) -> bool:
    if not _path_exists(source):
        return False
    if _path_exists(target):
        _remove_path(target)
    return _copy_path(source, target)


def create_config_snapshot(
    plan: UninstallPlan,
    *,
    backup_root: str | Path | None = None,
) -> Path:
    """创建仅包含配置的卸载前快照。"""
    root = _backup_root(backup_root)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_dir = _unique_backup_dir(root)
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    copied: list[dict[str, str]] = []
    app_config = Path(plan.app_config_dir).expanduser()
    if _copy_path(app_config, snapshot_dir / "app-config"):
        copied.append({"source": str(app_config), "target": "app-config"})

    workspace = Path(plan.yachiyo_workspace).expanduser()
    workspace_backup = snapshot_dir / "yachiyo-workspace"
    for relative in (".yachiyo_init", "configs", "config", "templates"):
        source = workspace / relative
        if _copy_path(source, workspace_backup / relative):
            copied.append({"source": str(source), "target": f"yachiyo-workspace/{relative}"})

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": plan.scope.value,
        "source_app_config_dir": plan.app_config_dir,
        "source_hermes_home": plan.hermes_home,
        "source_yachiyo_workspace": plan.yachiyo_workspace,
        "copied": copied,
        "note": "此快照仅用于重新导入 Hermes-Yachiyo 配置，不包含聊天数据库和资源包。",
    }
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot_dir


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _read_snapshot_manifest(snapshot_dir: Path) -> dict[str, Any]:
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("缺少 manifest.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest.json 格式无效")
    if int(data.get("schema_version") or 0) != 1:
        raise ValueError("不支持的配置快照版本")
    has_app_config = (snapshot_dir / "app-config").exists()
    has_workspace = (snapshot_dir / "yachiyo-workspace").exists()
    if not has_app_config and not has_workspace:
        raise ValueError("快照内没有可导入内容")
    return data


def _snapshot_info(snapshot_dir: Path) -> ConfigSnapshotInfo:
    resolved = snapshot_dir.expanduser().resolve()
    try:
        data = _read_snapshot_manifest(resolved)
        return ConfigSnapshotInfo(
            path=str(resolved),
            display_path=_display_path(resolved),
            created_at=str(data.get("created_at") or ""),
            scope=str(data.get("scope") or ""),
            schema_version=int(data.get("schema_version") or 0),
        )
    except Exception as exc:
        return ConfigSnapshotInfo(
            path=str(resolved),
            display_path=_display_path(resolved),
            valid=False,
            error=str(exc),
        )


def find_config_snapshots(backup_root: str | Path | None = None) -> list[ConfigSnapshotInfo]:
    """列出默认备份目录中的配置快照，最新在前。"""
    root = _backup_root(backup_root)
    if not root.exists() or not root.is_dir():
        return []
    snapshots = [
        _snapshot_info(path)
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("hermes-yachiyo-config-")
    ]
    snapshots.sort(
        key=lambda item: item.created_at or str(Path(item.path).stat().st_mtime),
        reverse=True,
    )
    return snapshots


def find_latest_config_snapshot(
    backup_root: str | Path | None = None,
) -> ConfigSnapshotInfo | None:
    """返回最近一个有效配置快照。"""
    for snapshot in find_config_snapshots(backup_root):
        if snapshot.valid:
            return snapshot
    return None


def get_config_snapshot_status(backup_root: str | Path | None = None) -> dict[str, Any]:
    """获取默认配置快照目录状态，供安装/初始化向导展示。"""
    root = _backup_root(backup_root)
    snapshots = find_config_snapshots(backup_root)
    latest = next((item for item in snapshots if item.valid), None)
    return {
        "backup_root": str(root),
        "backup_root_display": _display_path(root),
        "snapshots": [item.to_dict() for item in snapshots],
        "latest": latest.to_dict() if latest else None,
        "has_snapshot": latest is not None,
    }


def import_config_snapshot(
    snapshot_path: str | Path | None = None,
    *,
    backup_root: str | Path | None = None,
) -> ConfigSnapshotImportResult:
    """导入卸载前保存的 Hermes-Yachiyo 配置快照。"""
    snapshot = _snapshot_info(Path(snapshot_path).expanduser()) if snapshot_path else None
    if snapshot is None:
        snapshot = find_latest_config_snapshot(backup_root)
    if snapshot is None:
        return ConfigSnapshotImportResult(ok=False, errors=["未找到可导入的配置快照"])
    if not snapshot.valid:
        return ConfigSnapshotImportResult(ok=False, snapshot=snapshot, errors=[snapshot.error])

    snapshot_dir = Path(snapshot.path).expanduser().resolve()
    restored: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[str] = []

    app_config_source = snapshot_dir / "app-config"
    app_config_target = _app_config_dir()
    app_config_safe, app_config_reason = _is_safe_app_config_dir(app_config_target)
    if app_config_source.exists() and app_config_safe:
        try:
            _replace_path(app_config_source, app_config_target)
            restored.append({"label": "Hermes-Yachiyo 应用配置", "path": str(app_config_target)})
        except Exception as exc:
            errors.append(f"应用配置导入失败：{exc}")
    elif app_config_source.exists():
        skipped.append({"label": "Hermes-Yachiyo 应用配置", "reason": app_config_reason})
    else:
        skipped.append({"label": "Hermes-Yachiyo 应用配置", "reason": "快照中不存在"})

    workspace_source = snapshot_dir / "yachiyo-workspace"
    workspace_target = _hermes_home_dir() / "yachiyo"
    workspace_safe, workspace_reason = _is_safe_yachiyo_workspace(workspace_target)
    if workspace_source.exists() and workspace_safe:
        try:
            workspace_target.mkdir(parents=True, exist_ok=True)
            for relative in (".yachiyo_init", "configs", "config", "templates"):
                source = workspace_source / relative
                if not _path_exists(source):
                    skipped.append({"label": relative, "reason": "快照中不存在"})
                    continue
                target = workspace_target / relative
                _replace_path(source, target)
                restored.append({"label": f"Yachiyo {relative}", "path": str(target)})
        except Exception as exc:
            errors.append(f"Yachiyo 工作空间导入失败：{exc}")
    elif workspace_source.exists():
        skipped.append({"label": "Hermes-Yachiyo 工作空间", "reason": workspace_reason})
    else:
        skipped.append({"label": "Hermes-Yachiyo 工作空间", "reason": "快照中不存在"})

    return ConfigSnapshotImportResult(
        ok=not errors,
        snapshot=snapshot,
        restored=restored,
        skipped=skipped,
        errors=errors,
    )


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
            backup_path = create_config_snapshot(plan, backup_root=backup_root)
        except Exception as exc:
            logger.error("创建卸载配置快照失败: %s", exc)
            return UninstallResult(
                ok=False,
                plan=plan,
                errors=[f"创建配置快照失败，已取消卸载：{exc}"],
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
