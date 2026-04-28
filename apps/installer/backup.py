"""Hermes-Yachiyo 本地资料备份与恢复。"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from apps.installer.hermes_setup import HermesEnvironmentSetup
from apps.shell import config as config_mod
from apps.shell.assets import project_display_path

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "Hermes-Yachiyo-backups"
BACKUP_FILE_PREFIX = "hermes-yachiyo-backup-"
BACKUP_SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.json"
DEFAULT_RETENTION_COUNT = 10


@dataclass(frozen=True)
class BackupInfo:
    """备份文件信息。"""

    path: str
    display_path: str
    created_at: str = ""
    scope: str = ""
    schema_version: int = 0
    format: str = ""
    included: list[str] = field(default_factory=list)
    size_bytes: int = 0
    size_display: str = ""
    valid: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackupImportResult:
    """备份导入结果。"""

    ok: bool
    backup: BackupInfo | None = None
    restored: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    restart_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        backup = self.backup.to_dict() if self.backup else None
        return {
            "ok": self.ok,
            "backup": backup,
            "restored": self.restored,
            "skipped": self.skipped,
            "errors": self.errors,
            "restart_required": self.restart_required,
        }


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


def _has_yachiyo_workspace_marker(path: Path) -> bool:
    init_marker = path / ".yachiyo_init"
    if init_marker.is_file() and not init_marker.is_symlink():
        return True
    config_marker = path / "configs" / "yachiyo.json"
    return (
        config_marker.is_file()
        and not config_marker.is_symlink()
        and not config_marker.parent.is_symlink()
    )


def _is_safe_yachiyo_workspace(path: Path) -> tuple[bool, str]:
    original = path.expanduser()
    resolved = original.resolve()
    if _is_protected_path(resolved):
        return False, "受保护路径，已跳过"
    if resolved.name != "yachiyo":
        return False, "工作空间目录名称不符合预期，已跳过"
    home = Path.home().expanduser().resolve()
    if not _is_relative_to(resolved, home):
        return False, "工作空间不在当前用户目录下，已跳过"
    if resolved.parent == home:
        return False, "工作空间不能直接指向用户主目录下的通用目录，已跳过"
    if _path_exists(original) and not _has_yachiyo_workspace_marker(resolved):
        return False, "工作空间缺少 Yachiyo 初始化标识，已跳过"
    return True, ""


def _app_config_dir() -> Path:
    return Path(getattr(config_mod, "_CONFIG_DIR")).expanduser()


def _hermes_home_dir() -> Path:
    return Path(HermesEnvironmentSetup.get_effective_hermes_home()).expanduser()


def _yachiyo_workspace_dir() -> Path:
    return _hermes_home_dir() / "yachiyo"


def default_backup_root(backup_root: str | Path | None = None) -> Path:
    """返回默认备份目录。"""
    if backup_root is not None:
        return Path(backup_root).expanduser()
    return Path.home().expanduser() / BACKUP_DIR_NAME


def _unique_backup_archive(root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = root / f"{BACKUP_FILE_PREFIX}{timestamp}.zip"
    existing_orders = [
        _filename_order(path)
        for path in root.glob(f"{BACKUP_FILE_PREFIX}{timestamp}*.zip")
        if path.is_file()
    ]
    if not existing_orders and not base.exists():
        return base
    suffix = max(existing_orders, default=1) + 1
    while True:
        candidate = root / f"{BACKUP_FILE_PREFIX}{timestamp}-{suffix}.zip"
        if not candidate.exists():
            return candidate
        suffix += 1


def _copy_sqlite_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as source_conn:
            with sqlite3.connect(target) as target_conn:
                source_conn.backup(target_conn)
        shutil.copystat(source, target, follow_symlinks=False)
    except sqlite3.Error:
        shutil.copy2(source, target, follow_symlinks=False)


def _copy_file(source: str, target: str) -> str:
    source_path = Path(source)
    target_path = Path(target)
    if source_path.is_symlink():
        logger.warning("跳过符号链接备份项: %s", source_path)
        return target
    if source_path.name == "chat.db":
        _copy_sqlite_database(source_path, target_path)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path, follow_symlinks=False)
    return target


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in {"chat.db-wal", "chat.db-shm"}}
    directory = Path(_directory)
    for name in names:
        if name in ignored:
            continue
        path = directory / name
        if path.is_symlink():
            logger.warning("跳过符号链接备份项: %s", path)
            ignored.add(name)
    return ignored


def _copy_path(source: Path, target: Path) -> bool:
    if not _path_exists(source):
        return False
    if source.is_symlink():
        logger.warning("跳过符号链接备份源: %s", source)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target, copy_function=_copy_file, ignore=_copy_ignore)
    else:
        _copy_file(str(source), str(target))
    return True


def _write_zip_from_dir(source_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_symlink():
                logger.warning("跳过符号链接压缩项: %s", path)
                continue
            relative = path.relative_to(source_dir).as_posix()
            if path.is_dir():
                archive.write(path, relative + "/")
            else:
                archive.write(path, relative)


def create_backup(
    *,
    backup_root: str | Path | None = None,
    source_context: str = "manual",
    auto_cleanup: bool = True,
    retention_count: int = DEFAULT_RETENTION_COUNT,
    overwrite_latest: bool = False,
) -> BackupInfo:
    """生成可独立触发的 Hermes-Yachiyo 本地资料备份。"""
    root = default_backup_root(backup_root)
    root.mkdir(parents=True, exist_ok=True)
    previous_latest = find_latest_backup(root) if overwrite_latest else None
    archive_path = _unique_backup_archive(root)
    staging_root = Path(tempfile.mkdtemp(prefix=".hermes-yachiyo-backup-", dir=str(root)))
    staging_dir = staging_root / "payload"
    staging_dir.mkdir(parents=True, exist_ok=False)

    try:
        sources: list[tuple[str, str, Path, str]] = [
            (
                "app_config",
                "Hermes-Yachiyo 应用配置",
                _app_config_dir(),
                "app-config",
            ),
            (
                "yachiyo_workspace",
                "Yachiyo 工作空间",
                _yachiyo_workspace_dir(),
                "yachiyo-workspace",
            ),
        ]
        copied: list[dict[str, str]] = []
        for source_id, label, source_path, target_name in sources:
            if _copy_path(source_path, staging_dir / target_name):
                copied.append({
                    "id": source_id,
                    "label": label,
                    "source": str(source_path),
                    "target": target_name,
                })

        if not copied:
            raise ValueError("未找到可备份的 Hermes-Yachiyo 本地资料")

        manifest = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "kind": "hermes-yachiyo-backup",
            "format": "zip",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": source_context,
            "source_app_config_dir": str(_app_config_dir()),
            "source_hermes_home": str(_hermes_home_dir()),
            "source_yachiyo_workspace": str(_yachiyo_workspace_dir()),
            "entries": copied,
            "copied": copied,
            "note": (
                "此备份包含 Hermes-Yachiyo 应用配置与 Yachiyo 工作空间，"
                "包括聊天数据库、项目资料、缓存、日志与导入资源。"
            ),
        }
        (staging_dir / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_zip_from_dir(staging_dir, archive_path)
        backup = _backup_info(archive_path)
        if previous_latest and previous_latest.path != backup.path:
            delete_backup(previous_latest.path, backup_root=root)
        if auto_cleanup:
            cleanup_old_backups(backup_root=root, keep_count=retention_count)
        return backup
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _read_manifest_from_directory(snapshot_dir: Path) -> dict[str, Any]:
    manifest_path = snapshot_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError("缺少 manifest.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest.json 格式无效")
    return data


def _read_manifest_from_zip(archive_path: Path) -> dict[str, Any]:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError("备份文件不是有效 ZIP")
    with zipfile.ZipFile(archive_path, "r") as archive:
        try:
            raw = archive.read(MANIFEST_NAME)
        except KeyError as exc:
            raise ValueError("缺少 manifest.json") from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest.json 格式无效")
    return data


def _read_backup_manifest(path: Path) -> dict[str, Any]:
    if path.is_file():
        data = _read_manifest_from_zip(path)
        data.setdefault("format", "zip")
    elif path.is_dir():
        data = _read_manifest_from_directory(path)
        data.setdefault("format", "directory")
    else:
        raise ValueError("备份路径不存在")

    schema_version = int(data.get("schema_version") or 0)
    if schema_version != BACKUP_SCHEMA_VERSION:
        raise ValueError("不支持的备份版本")
    return data


def _included_ids(path: Path, data: dict[str, Any]) -> list[str]:
    entries = data.get("entries") or data.get("copied")
    if isinstance(entries, list):
        return [
            str(item.get("id"))
            for item in entries
            if isinstance(item, dict) and item.get("id")
        ]

    included: list[str] = []
    if path.is_dir():
        if (path / "app-config").exists():
            included.append("app_config")
        if (path / "yachiyo-workspace").exists():
            included.append("yachiyo_workspace")
    elif path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
        if any(name.startswith("app-config/") for name in names):
            included.append("app_config")
        if any(name.startswith("yachiyo-workspace/") for name in names):
            included.append("yachiyo_workspace")
    return included


def _backup_info(path: Path) -> BackupInfo:
    resolved = path.expanduser().resolve()
    try:
        data = _read_backup_manifest(resolved)
        included = _included_ids(resolved, data)
        if not included:
            raise ValueError("备份内没有可导入内容")
        return BackupInfo(
            path=str(resolved),
            display_path=_display_path(resolved),
            created_at=str(data.get("created_at") or ""),
            scope=str(data.get("scope") or ""),
            schema_version=int(data.get("schema_version") or 0),
            format=str(data.get("format") or ""),
            included=included,
            size_bytes=_backup_size(resolved),
            size_display=_format_bytes(_backup_size(resolved)),
        )
    except Exception as exc:
        return BackupInfo(
            path=str(resolved),
            display_path=_display_path(resolved),
            size_bytes=_backup_size(resolved),
            size_display=_format_bytes(_backup_size(resolved)),
            valid=False,
            error=str(exc),
        )


def _looks_like_backup(path: Path) -> bool:
    return path.is_file() and path.name.startswith(BACKUP_FILE_PREFIX) and path.suffix == ".zip"


def _backup_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _format_bytes(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size_bytes} B"


def _filename_order(path: Path) -> int:
    stem = path.stem
    if not stem.startswith(BACKUP_FILE_PREFIX):
        return 0
    suffix = stem.removeprefix(BACKUP_FILE_PREFIX)
    parts = suffix.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 1


def find_backups(backup_root: str | Path | None = None) -> list[BackupInfo]:
    """列出可导入备份，最新在前。"""
    backups: list[BackupInfo] = []
    root = default_backup_root(backup_root)
    if not root.exists() or not root.is_dir():
        return backups
    for path in root.iterdir():
        if _looks_like_backup(path):
            backups.append(_backup_info(path))

    def sort_key(item: BackupInfo) -> tuple[str, int, int, str]:
        path = Path(item.path)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except Exception:
            mtime_ns = 0
        if item.created_at:
            return (item.created_at, mtime_ns, _filename_order(path), path.name)
        try:
            created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except Exception:
            created_at = ""
        return (created_at, mtime_ns, _filename_order(path), path.name)

    backups.sort(key=sort_key, reverse=True)
    return backups


def find_latest_backup(backup_root: str | Path | None = None) -> BackupInfo | None:
    """返回最近一个有效备份。"""
    for backup in find_backups(backup_root):
        if backup.valid:
            return backup
    return None


def get_backup_status(backup_root: str | Path | None = None) -> dict[str, Any]:
    """获取备份目录状态，供主界面与安装引导展示。"""
    root = default_backup_root(backup_root)
    backups = find_backups(backup_root)
    latest = next((item for item in backups if item.valid), None)
    latest_dict = latest.to_dict() if latest else None
    total_size = sum(item.size_bytes for item in backups)
    return {
        "backup_root": str(root),
        "backup_root_display": _display_path(root),
        "backups": [item.to_dict() for item in backups],
        "latest": latest_dict,
        "has_backup": latest is not None,
        "count": len(backups),
        "total_size_bytes": total_size,
        "total_size_display": _format_bytes(total_size),
    }


def cleanup_old_backups(
    *,
    backup_root: str | Path | None = None,
    keep_count: int = DEFAULT_RETENTION_COUNT,
) -> list[BackupInfo]:
    """删除超过保留数量的旧备份，返回被删除的备份信息。"""
    keep_count = max(1, int(keep_count))
    backups = [item for item in find_backups(backup_root) if item.valid]
    deleted: list[BackupInfo] = []
    for backup in backups[keep_count:]:
        delete_backup(backup.path, backup_root=backup_root)
        deleted.append(backup)
    return deleted


def resolve_managed_backup_path(
    backup_path: str | Path,
    *,
    backup_root: str | Path | None = None,
) -> Path:
    """解析并校验默认备份目录内的托管备份 ZIP 文件。"""
    root = default_backup_root(backup_root).expanduser().resolve()
    path = Path(backup_path).expanduser().resolve()
    if path.parent != root:
        raise ValueError("只能管理默认备份目录中的备份文件")
    if not path.name.startswith(BACKUP_FILE_PREFIX) or path.suffix != ".zip":
        raise ValueError("备份文件名称不符合预期")
    if not path.is_file():
        raise ValueError("备份文件不存在")
    return path


def _resolve_managed_backup_path(
    backup_path: str | Path,
    *,
    backup_root: str | Path | None = None,
) -> Path:
    return resolve_managed_backup_path(backup_path, backup_root=backup_root)


def delete_backup(
    backup_path: str | Path,
    *,
    backup_root: str | Path | None = None,
) -> BackupInfo:
    """删除指定备份。"""
    path = resolve_managed_backup_path(backup_path, backup_root=backup_root)
    info = _backup_info(path)
    path.unlink()
    return info


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _replace_path(source: Path, target: Path) -> bool:
    if not _path_exists(source):
        return False
    if _path_exists(target):
        _remove_path(target)
    return _copy_path(source, target)


def _extract_zip_safely(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("备份文件包含不安全路径")
            output_path = target_dir.joinpath(*member_path.parts)
            if member.is_dir():
                output_path.mkdir(parents=True, exist_ok=True)
                continue
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source_file:
                with output_path.open("wb") as target_file:
                    shutil.copyfileobj(source_file, target_file)


@contextmanager
def _materialized_backup(path: Path) -> Iterator[Path]:
    if path.is_dir():
        yield path
        return

    with tempfile.TemporaryDirectory(prefix="hermes-yachiyo-import-") as temp_dir:
        target_dir = Path(temp_dir) / "payload"
        target_dir.mkdir(parents=True, exist_ok=True)
        _extract_zip_safely(path, target_dir)
        yield target_dir


def import_backup(
    backup_path: str | Path | None = None,
    *,
    backup_root: str | Path | None = None,
) -> BackupImportResult:
    """导入 Hermes-Yachiyo 备份。"""
    if backup_path:
        backup_source = Path(backup_path).expanduser()
        if not _looks_like_backup(backup_source):
            info = BackupInfo(
                path=str(backup_source),
                display_path=_display_path(backup_source),
                valid=False,
                error="只支持导入新版 ZIP 备份文件",
            )
            return BackupImportResult(ok=False, backup=info, errors=[info.error])
        backup = _backup_info(backup_source)
    else:
        backup = None
    if backup is None:
        backup = find_latest_backup(backup_root)
    if backup is None:
        return BackupImportResult(ok=False, errors=["未找到可导入的备份"])
    if not backup.valid:
        return BackupImportResult(ok=False, backup=backup, errors=[backup.error])

    backup_source = Path(backup.path).expanduser().resolve()
    restored: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    errors: list[str] = []

    with _materialized_backup(backup_source) as snapshot_dir:
        _read_backup_manifest(snapshot_dir)

        app_config_source = snapshot_dir / "app-config"
        app_config_target = _app_config_dir()
        app_config_safe, app_config_reason = _is_safe_app_config_dir(app_config_target)
        if app_config_source.exists() and app_config_safe:
            try:
                _replace_path(app_config_source, app_config_target)
                restored.append({
                    "label": "Hermes-Yachiyo 应用配置",
                    "path": str(app_config_target),
                })
            except Exception as exc:
                errors.append(f"应用配置导入失败：{exc}")
        elif app_config_source.exists():
            skipped.append({"label": "Hermes-Yachiyo 应用配置", "reason": app_config_reason})
        else:
            skipped.append({"label": "Hermes-Yachiyo 应用配置", "reason": "备份中不存在"})

        workspace_source = snapshot_dir / "yachiyo-workspace"
        workspace_target = _yachiyo_workspace_dir()
        workspace_safe, workspace_reason = _is_safe_yachiyo_workspace(workspace_target)
        if workspace_source.exists() and not _has_yachiyo_workspace_marker(workspace_source):
            skipped.append({
                "label": "Hermes-Yachiyo 工作空间",
                "reason": "备份中的工作空间缺少初始化标识",
            })
        elif workspace_source.exists() and workspace_safe:
            try:
                _replace_path(workspace_source, workspace_target)
                restored.append({
                    "label": "Yachiyo 工作空间",
                    "path": str(workspace_target),
                })
            except Exception as exc:
                errors.append(f"Yachiyo 工作空间导入失败：{exc}")
        elif workspace_source.exists():
            skipped.append({"label": "Hermes-Yachiyo 工作空间", "reason": workspace_reason})
        else:
            skipped.append({"label": "Hermes-Yachiyo 工作空间", "reason": "备份中不存在"})

    return BackupImportResult(
        ok=not errors,
        backup=backup,
        restored=restored,
        skipped=skipped,
        errors=errors,
    )
