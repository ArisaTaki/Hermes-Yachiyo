"""Oha-Yachiyo workspace initialization."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oha_yachiyo_home(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser()
    return Path(os.getenv("OHA_YACHIYO_HOME", "~/.oha-yachiyo")).expanduser()


def _workspace_dirs(root: Path) -> dict[str, str]:
    return {
        "projects": str(root / "projects"),
        "configs": str(root / "configs"),
        "logs": str(root / "logs"),
        "cache": str(root / "cache"),
        "templates": str(root / "templates"),
        "assets": str(root / "assets"),
        "workspaces": str(root / "workspaces"),
        "skills": str(root / "skills"),
    }


class OhaWorkspaceInitializer:
    """Initialize the local Oha-Yachiyo runtime workspace."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = _oha_yachiyo_home(workspace_root)

    @property
    def init_marker(self) -> Path:
        return self.workspace_root / ".oha_yachiyo_init"

    def check_prerequisites(self) -> tuple[bool, str]:
        try:
            self.workspace_root.parent.mkdir(parents=True, exist_ok=True)
            if self.workspace_root.exists() and not self.workspace_root.is_dir():
                return False, f"工作空间路径不是目录: {self.workspace_root}"
            return True, ""
        except PermissionError:
            return False, f"无法创建或访问工作空间: {self.workspace_root}"
        except Exception as exc:
            logger.error("工作空间前提检查失败: %s", exc)
            return False, f"检查失败: {exc}"

    def create_workspace_structure(self) -> tuple[bool, str]:
        try:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            for path in _workspace_dirs(self.workspace_root).values():
                Path(path).mkdir(parents=True, exist_ok=True)
            return True, ""
        except Exception as exc:
            logger.error("创建工作空间目录失败: %s", exc)
            return False, f"创建失败: {exc}"

    def create_default_configs(self) -> tuple[bool, str]:
        try:
            configs_dir = self.workspace_root / "configs"
            configs_dir.mkdir(parents=True, exist_ok=True)
            config_file = configs_dir / "oha-yachiyo.json"
            if not config_file.exists():
                config_file.write_text(
                    json.dumps(
                        {
                            "version": "1.0.0",
                            "workspace_path": str(self.workspace_root),
                            "created_at": _now_iso(),
                            "settings": {
                                "auto_start": False,
                                "log_level": "INFO",
                                "max_log_files": 10,
                            },
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            template_file = self.workspace_root / "templates" / "default.json"
            if not template_file.exists():
                template_file.write_text(
                    json.dumps(
                        {
                            "name": "default",
                            "description": "Default project template for Oha-Yachiyo",
                            "structure": {"commands": [], "integrations": []},
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            return True, ""
        except Exception as exc:
            logger.error("创建工作空间配置失败: %s", exc)
            return False, f"配置创建失败: {exc}"

    def create_init_marker(self) -> tuple[bool, str]:
        try:
            self.init_marker.write_text(
                json.dumps(
                    {
                        "initialized_at": _now_iso(),
                        "version": "1.0.0",
                        "workspace_path": str(self.workspace_root),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return True, ""
        except Exception as exc:
            logger.error("创建工作空间初始化标记失败: %s", exc)
            return False, f"标记文件创建失败: {exc}"

    def initialize_workspace(self) -> tuple[bool, str, list[str]]:
        created_items: list[str] = []
        prereq_ok, prereq_error = self.check_prerequisites()
        if not prereq_ok:
            return False, prereq_error, created_items
        dirs_ok, dirs_error = self.create_workspace_structure()
        if not dirs_ok:
            return False, dirs_error, created_items
        created_items.append(f"工作空间目录: {self.workspace_root}")
        config_ok, config_error = self.create_default_configs()
        if not config_ok:
            return False, config_error, created_items
        created_items.extend(["configs/oha-yachiyo.json", "templates/default.json"])
        marker_ok, marker_error = self.create_init_marker()
        if not marker_ok:
            return False, marker_error, created_items
        created_items.append(".oha_yachiyo_init")
        logger.info("Oha-Yachiyo 工作空间初始化完成: %s", self.workspace_root)
        return True, "", created_items


def initialize_oha_workspace(workspace_root: str | Path | None = None) -> tuple[bool, str, list[str]]:
    initializer = OhaWorkspaceInitializer(workspace_root)
    return initializer.initialize_workspace()


def get_workspace_status(workspace_root: str | Path | None = None) -> dict[str, Any]:
    root = _oha_yachiyo_home(workspace_root)
    marker = root / ".oha_yachiyo_init"
    config_file = root / "configs" / "oha-yachiyo.json"
    initialized = marker.exists() and config_file.exists()
    created_at = ""
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            created_at = str(data.get("initialized_at") or data.get("created_at") or "")
        except Exception:
            created_at = ""
    return {
        "workspace_root": str(root),
        "workspace_path": str(root),
        "initialized": initialized,
        "created_at": created_at or None,
        "dirs": _workspace_dirs(root),
    }
