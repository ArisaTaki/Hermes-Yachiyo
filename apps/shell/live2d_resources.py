"""Live2D resource preparation helpers for the desktop bridge."""

from __future__ import annotations

import copy
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from apps.shell.assets import find_default_live2d_model_dir
from apps.shell.assets import get_user_live2d_assets_dir
from apps.shell.assets import project_display_path
from apps.shell.config import check_live2d_model_dir
from apps.shell.config import scan_live2d_model_dir
from apps.shell.mode_settings import apply_settings_changes
from apps.shell.mode_settings import serialize_mode_window_data

if TYPE_CHECKING:
    from apps.shell.config import AppConfig


def find_importable_live2d_dir(root: Path) -> Path | None:
    """Return a valid Live2D model directory from a selected folder or extracted archive."""
    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return None
    if check_live2d_model_dir(resolved_root):
        summary = scan_live2d_model_dir(resolved_root)
        if summary.found_in_subdir and summary.subdir_name:
            return (resolved_root / summary.subdir_name).resolve()
        return resolved_root
    discovered = find_default_live2d_model_dir(check_live2d_model_dir, resolved_root)
    if discovered is None:
        return None
    summary = scan_live2d_model_dir(discovered)
    if summary.found_in_subdir and summary.subdir_name:
        return (discovered / summary.subdir_name).resolve()
    return discovered.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


_MOJIBAKE_MARKERS = frozenset("│─┌┐└┘├┤┬┴┼�□■")


def _looks_like_mojibake(text: str) -> bool:
    value = str(text or "")
    if not value:
        return True
    marker_count = sum(1 for char in value if char in _MOJIBAKE_MARKERS)
    control_count = sum(1 for char in value if ord(char) < 32)
    return control_count > 0 or marker_count >= 2


def _safe_import_dir_name(preferred_name: str, *, fallback: str = "yachiyo-live2d") -> str:
    raw_name = Path(str(preferred_name or "")).name.strip()
    if not raw_name or _looks_like_mojibake(raw_name):
        raw_name = fallback
    safe_name = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in raw_name
    )
    safe_name = re.sub(r"-{2,}", "-", safe_name).strip(".-")
    return safe_name or fallback


def _pick_import_target_dir(root: Path, preferred_name: str) -> Path:
    base_name = _safe_import_dir_name(preferred_name)
    candidate = root / base_name
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        candidate = root / f"{base_name}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def copy_live2d_model_dir(
    source_dir: Path,
    assets_root: Path | None = None,
    *,
    preferred_name: str | None = None,
) -> Path:
    """Copy a selected Live2D model directory into the default user asset root."""
    source_model_dir = find_importable_live2d_dir(source_dir)
    if source_model_dir is None:
        raise ValueError("所选目录内未检测到有效的 Live2D 模型资源")

    target_root = (assets_root or get_user_live2d_assets_dir()).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    if _is_relative_to(source_model_dir, target_root):
        return source_model_dir

    target_dir = _pick_import_target_dir(target_root, preferred_name or source_model_dir.name)
    shutil.copytree(source_model_dir, target_dir)
    return target_dir.resolve()


def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """Recover common UTF-8/GBK encoded ZIP names when the UTF-8 flag is missing."""
    name = str(info.filename or "").replace("\\", "/")
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "gb18030", "cp932", "shift_jis", "cp949"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        decoded = decoded.replace("\\", "/")
        if decoded and not _looks_like_mojibake(decoded):
            return decoded
    return name


def _archive_member_target(root: Path, member_name: str) -> Path:
    parts = [part for part in PurePosixPath(member_name).parts if part not in {"", "/"}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("压缩包内包含不安全的路径")
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("压缩包内包含不安全的路径") from exc
    return target


def _unpack_live2d_archive(archive_path: Path, tmp_dir: str) -> None:
    if archive_path.suffix.lower() != ".zip":
        shutil.unpack_archive(str(archive_path), tmp_dir)
        return
    root = Path(tmp_dir).resolve()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member_name = _decode_zip_member_name(info)
                if not member_name:
                    continue
                if member_name.endswith("/"):
                    _archive_member_target(root, member_name).mkdir(parents=True, exist_ok=True)
                    continue
                target = _archive_member_target(root, member_name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    except zipfile.BadZipFile as exc:
        raise shutil.ReadError(str(exc)) from exc


def import_live2d_archive(archive_path: Path, assets_root: Path | None = None) -> Path:
    """Extract an archive and return the imported model directory path."""
    resolved_archive = archive_path.expanduser().resolve()
    if not resolved_archive.exists() or not resolved_archive.is_file():
        raise FileNotFoundError("未找到要导入的资源包文件")

    with tempfile.TemporaryDirectory(prefix="hermes-live2d-import-") as tmp_dir:
        try:
            _unpack_live2d_archive(resolved_archive, tmp_dir)
        except (shutil.ReadError, ValueError) as exc:
            raise ValueError("所选文件不是可导入的压缩包") from exc

        source_dir = find_importable_live2d_dir(Path(tmp_dir))
        if source_dir is None:
            raise ValueError("压缩包内未检测到有效的 Live2D 模型资源")

        return copy_live2d_model_dir(
            source_dir,
            assets_root=assets_root,
            preferred_name=source_dir.name or resolved_archive.stem,
        )


def prepare_live2d_model_path_draft(
    config: "AppConfig",
    model_path: Path,
    *,
    message: str = "已选择 Live2D 模型路径，等待保存更改",
) -> dict[str, Any]:
    """Validate a model directory and return a draft config change without persisting it."""
    model_dir = find_importable_live2d_dir(model_path)
    if model_dir is None:
        return {"ok": False, "error": "所选目录内未检测到有效的 Live2D 模型资源"}
    return _build_live2d_model_path_draft(config, model_dir, message=message)


def import_live2d_archive_draft(config: "AppConfig", archive_path: Path) -> dict[str, Any]:
    """Import an archive and return a draft config change without persisting it."""
    try:
        imported_path = import_live2d_archive(archive_path)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return _build_live2d_model_path_draft(
        config,
        imported_path,
        message="已导入 Live2D 资源包，等待保存更改",
    )


def _build_live2d_model_path_draft(
    config: "AppConfig",
    model_path: Path,
    *,
    message: str,
) -> dict[str, Any]:
    resolved_path = str(model_path.expanduser().resolve())
    preview_config = copy.deepcopy(config)
    result = apply_settings_changes(
        preview_config,
        {"live2d_mode.model_path": resolved_path},
        persist=False,
    )
    if not result.get("ok"):
        return result
    result["message"] = message
    result["draft_changes"] = {"live2d_mode.model_path": resolved_path}
    result["model_path_display"] = project_display_path(model_path)
    result["preview"] = serialize_mode_window_data(preview_config, "live2d")
    return result
