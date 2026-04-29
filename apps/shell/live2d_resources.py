"""Live2D resource preparation helpers for the desktop bridge."""

from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
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


def _pick_import_target_dir(root: Path, preferred_name: str) -> Path:
    base_name = Path(preferred_name).name.strip() or "live2d-model"
    candidate = root / base_name
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        candidate = root / f"{base_name}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def copy_live2d_model_dir(source_dir: Path, assets_root: Path | None = None) -> Path:
    """Copy a selected Live2D model directory into the default user asset root."""
    source_model_dir = find_importable_live2d_dir(source_dir)
    if source_model_dir is None:
        raise ValueError("所选目录内未检测到有效的 Live2D 模型资源")

    target_root = (assets_root or get_user_live2d_assets_dir()).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    if _is_relative_to(source_model_dir, target_root):
        return source_model_dir

    target_dir = _pick_import_target_dir(target_root, source_model_dir.name)
    shutil.copytree(source_model_dir, target_dir)
    return target_dir.resolve()


def import_live2d_archive(archive_path: Path, assets_root: Path | None = None) -> Path:
    """Extract an archive and return the imported model directory path."""
    resolved_archive = archive_path.expanduser().resolve()
    if not resolved_archive.exists() or not resolved_archive.is_file():
        raise FileNotFoundError("未找到要导入的资源包文件")

    with tempfile.TemporaryDirectory(prefix="hermes-live2d-import-") as tmp_dir:
        try:
            shutil.unpack_archive(str(resolved_archive), tmp_dir)
        except (shutil.ReadError, ValueError) as exc:
            raise ValueError("所选文件不是可导入的压缩包") from exc

        source_dir = find_importable_live2d_dir(Path(tmp_dir))
        if source_dir is None:
            raise ValueError("压缩包内未检测到有效的 Live2D 模型资源")

        return copy_live2d_model_dir(source_dir, assets_root=assets_root)


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