"""Skill import source resolution helpers."""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.skill_content import SkillContentInspector


@dataclass(frozen=True)
class ResolvedSkillImportSource:
    source: Path
    source_root: Path
    source_path: str
    source_type: str
    source_ref: str
    origin_path: str
    temp_dir: Path | None = None


@dataclass(frozen=True)
class PreparedSkillImport:
    source_ref: str
    markdown: str
    metadata: dict[str, Any]
    name: str
    description: str
    content_hash: str
    summary: str
    now: str
    last_synced_at: str


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


class SkillImportPreparer:
    """Prepares Skill metadata before the runtime writes records."""

    def __init__(
        self,
        *,
        content: SkillContentInspector,
        skill_source_types: set[str],
        now: Callable[[], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._content = content
        self._skill_source_types = skill_source_types
        self._now = now
        self._error_type = error_type

    def prepare(
        self,
        source_root: Path,
        *,
        source_type: str,
        source_ref: str,
        synced_at: str = "",
    ) -> PreparedSkillImport:
        if source_type not in self._skill_source_types:
            raise self._error_type("未知 Skill 来源类型")
        skill_md = source_root / "SKILL.md"
        if not skill_md.is_file():
            raise self._error_type("Skill 根目录必须包含 SKILL.md")

        markdown = self._content.read_text(skill_md)
        metadata = self._content.parse_frontmatter(markdown)
        resolved_source_ref = self._content.metadata_source_ref(metadata, source_ref)
        name = self._content.name(markdown, source_root.name)
        name = str(metadata.get("name") or name)[:120] or source_root.name
        description = self._content.description(markdown)
        description = str(metadata.get("description") or description)[:240]
        now = self._now()
        return PreparedSkillImport(
            source_ref=resolved_source_ref,
            markdown=markdown,
            metadata=metadata,
            name=name,
            description=description,
            content_hash=self._content.content_hash(source_root),
            summary=self._content.summary(markdown),
            now=now,
            last_synced_at=synced_at or (now if source_type not in {"local_dir", "local_zip"} else ""),
        )
