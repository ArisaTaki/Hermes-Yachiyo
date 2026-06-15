"""Skill sync orchestration for native and installed Skill libraries."""

from __future__ import annotations

from typing import Any, Callable


class RuntimeSkillSyncService:
    """Executes planned Skill sync entries without owning import persistence."""

    def __init__(
        self,
        *,
        conn: Any,
        skill_sync: Any,
        normalize_skill_folder_id: Callable[[str | None], str],
        skill_deletion_key: Callable[[str, str], str],
        has_studio_deletion: Callable[[str, str], bool],
        clear_studio_deletion: Callable[[str, str], None],
        import_skill_root: Callable[..., dict[str, Any]],
        now: Callable[[], str],
        redact_error: Callable[[Any], str],
        error_type: type[Exception],
    ) -> None:
        self._conn = conn
        self._skill_sync = skill_sync
        self._normalize_skill_folder_id = normalize_skill_folder_id
        self._skill_deletion_key = skill_deletion_key
        self._has_studio_deletion = has_studio_deletion
        self._clear_studio_deletion = clear_studio_deletion
        self._import_skill_root = import_skill_root
        self._now = now
        self._redact_error = redact_error
        self._error_type = error_type

    def sync_roots(
        self,
        root_specs: list[dict[str, Any]],
        *,
        library: str,
        folder_id: str | None = None,
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        now = self._now()
        target_folder_id = self._normalize_skill_folder_id(folder_id) if folder_id is not None else None
        for entry in self._skill_sync.plan_entries(root_specs, library=library):
            if entry.skipped_result is not None:
                results.append(entry.skipped_result)
                continue
            if entry.candidate is None:
                continue
            candidate = entry.candidate
            source_root = candidate.source_root
            source_type = candidate.source_type
            source_ref = candidate.source_ref
            library_name = candidate.library
            deletion_key = self._skill_deletion_key(source_type, str(source_root.resolve()))
            has_deletion = self._has_studio_deletion("skill_source", deletion_key)
            restore_deletion = restore_deleted and has_deletion
            if has_deletion and not restore_deletion:
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": "skipped",
                    "message": "用户已删除，跳过同步；可通过显式导入或重新安装恢复",
                })
                continue
            try:
                result = self._import_skill_root(
                    source_root,
                    source_path=f"{source_type}:{source_ref}",
                    source_type=source_type,
                    origin_path=str(source_root.resolve()),
                    source_ref=source_ref,
                    sync_status="synced",
                    synced_at=now,
                    copy_to_managed=False,
                    folder_id=target_folder_id,
                )
                if restore_deletion:
                    self._clear_studio_deletion("skill_source", deletion_key)
                    self._conn.commit()
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": result["sync_status"],
                    "skill_id": result["skill_id"],
                    "name": result["name"],
                })
            except self._error_type as exc:
                results.append({
                    "source": str(source_root),
                    "source_type": source_type,
                    "library": library_name,
                    "source_ref": source_ref,
                    "status": "failed",
                    "message": self._redact_error(exc),
                })
        summary = self._skill_sync.summarize_results(results)
        roots_info = self._skill_sync.roots_info(root_specs, library=library)
        return {"ok": summary["failed"] == 0, "roots": roots_info, "summary": summary, "results": results}
