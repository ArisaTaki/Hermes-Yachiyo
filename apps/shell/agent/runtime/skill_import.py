"""Skill import source resolution helpers."""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from apps.shell.agent.runtime.errors import AgentRuntimeError


@dataclass(frozen=True)
class ResolvedSkillImportSource:
    source: Path
    source_root: Path
    source_path: str
    source_type: str
    source_ref: str
    origin_path: str
    temp_dir: Path | None = None


class SkillImportSourceResolver:
    """Resolves user supplied Skill paths without importing records."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        id_factory: Callable[[], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._id_factory = id_factory
        self._error_type = error_type

    def resolve(self, source_path: str) -> ResolvedSkillImportSource:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise self._error_type("Skill 路径不存在")

        source_type = "local_dir"
        source_ref = source.name
        origin_path = str(source.resolve())
        source_root = source
        temp_dir: Path | None = None
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise self._error_type("Skill 文件只支持 ZIP")
            source_type = "local_zip"
            temp_dir = self._workspace_dir / "skill-import-tmp" / self._id_factory()
            temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._extract_zip(source, temp_dir)
                roots = [child for child in temp_dir.iterdir() if child.is_dir()]
                source_root = temp_dir
                if not (source_root / "SKILL.md").exists() and len(roots) == 1:
                    source_root = roots[0]
            except Exception:
                self.cleanup_temp_dir(temp_dir)
                raise

        return ResolvedSkillImportSource(
            source=source,
            source_root=source_root,
            source_path=f"local:{source.name}",
            source_type=source_type,
            source_ref=source_ref,
            origin_path=origin_path,
            temp_dir=temp_dir,
        )

    @staticmethod
    def cleanup(resolved: ResolvedSkillImportSource) -> None:
        if resolved.temp_dir is not None:
            SkillImportSourceResolver.cleanup_temp_dir(resolved.temp_dir)

    @staticmethod
    def cleanup_temp_dir(temp_dir: Path) -> None:
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _extract_zip(self, source: Path, temp_dir: Path) -> None:
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise self._error_type("ZIP 包含路径穿越项，已拒绝导入")
            archive.extractall(temp_dir)
