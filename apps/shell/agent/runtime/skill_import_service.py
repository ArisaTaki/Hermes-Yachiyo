"""Skill import orchestration for Agent Studio Skill records."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver


class RuntimeSkillImportService:
    """Coordinates Skill source resolution, import persistence, and deletion restore."""

    def __init__(
        self,
        *,
        conn: Any,
        source_resolver: SkillImportSourceResolver,
        preparer: SkillImportPreparer,
        skill_records: Any,
        normalize_skill_folder_id: Callable[[str | None], str],
        skill_deletion_key: Callable[[str, str], str],
        clear_studio_deletion: Callable[[str, str], None],
        get_skill: Callable[[str], dict[str, Any]],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._source_resolver = source_resolver
        self._preparer = preparer
        self._skill_records = skill_records
        self._normalize_skill_folder_id = normalize_skill_folder_id
        self._skill_deletion_key = skill_deletion_key
        self._clear_studio_deletion = clear_studio_deletion
        self._get_skill = get_skill
        self._error_type = error_type

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise self._error_type("Skill 路径不存在")
        target_folder_id = self._normalize_skill_folder_id(folder_id)
        resolved = self._source_resolver.resolve(str(source))
        try:
            imported = self.import_root(
                resolved.source_root,
                source_path=resolved.source_path,
                source_type=resolved.source_type,
                origin_path=resolved.origin_path,
                source_ref=resolved.source_ref,
                sync_status="imported",
                folder_id=target_folder_id,
            )
            self._clear_studio_deletion(
                "skill_source",
                self._skill_deletion_key(resolved.source_type, resolved.origin_path),
            )
            self._conn.commit()
            return imported
        finally:
            self._source_resolver.cleanup(resolved)

    def import_root(
        self,
        source_root: Path,
        *,
        source_path: str,
        source_type: str,
        origin_path: str,
        source_ref: str,
        sync_status: str,
        synced_at: str = "",
        copy_to_managed: bool = True,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        prepared = self._preparer.prepare(
            source_root,
            source_type=source_type,
            source_ref=source_ref,
            synced_at=synced_at,
        )
        target_folder_id = self._normalize_skill_folder_id(folder_id) if folder_id is not None else ""
        saved = self._skill_records.save_import(
            source_root=source_root,
            source_path=source_path,
            source_type=source_type,
            origin_path=origin_path,
            source_ref=prepared.source_ref,
            name=prepared.name,
            description=prepared.description,
            content_hash=prepared.content_hash,
            last_synced_at=prepared.last_synced_at,
            sync_status=sync_status,
            summary=prepared.summary,
            markdown=prepared.markdown,
            now=prepared.now,
            existing=self.find_existing(origin_path, prepared.content_hash, source_type),
            copy_to_managed=copy_to_managed,
            folder_id_was_provided=folder_id is not None,
            target_folder_id=target_folder_id,
        )
        skill = self._get_skill(saved["skill_id"])
        skill["sync_status"] = saved["sync_status"]
        return skill

    def find_existing(self, origin_path: str, content_hash: str, source_type: str) -> Any | None:
        return self._skill_records.find_existing_import(
            origin_path=origin_path,
            content_hash=content_hash,
            source_type=source_type,
        )
