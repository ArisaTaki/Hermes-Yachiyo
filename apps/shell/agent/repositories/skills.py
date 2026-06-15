"""Skill record persistence for Agent Studio skill library entries."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any


class SkillRepository:
    """Stores Skill records while import/sync orchestration remains in the runtime."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_skill: Callable[[Any], dict[str, Any]],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        json_load: Callable[[str | None, Any], Any],
        normalize_skill_folder_id: Callable[[str | None], str],
        installed_skill_source_map: Callable[[], dict[str, str]],
        remove_managed_copy_if_safe: Callable[[Path, str], None],
        skill_path_owned_by_runtime: Callable[[Path], bool],
        record_studio_deletion: Callable[[str, str], Any],
        skill_deletion_key: Callable[[str, str], str],
        is_native_library_source_type: Callable[[Any], bool],
        skills_dir: Path,
        delete_tree: Callable[..., Any] = shutil.rmtree,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_skill = row_to_skill
        self._now = now
        self._json_dump = json_dump
        self._json_load = json_load
        self._normalize_skill_folder_id = normalize_skill_folder_id
        self._installed_skill_source_map = installed_skill_source_map
        self._remove_managed_copy_if_safe = remove_managed_copy_if_safe
        self._skill_path_owned_by_runtime = skill_path_owned_by_runtime
        self._record_studio_deletion = record_studio_deletion
        self._skill_deletion_key = skill_deletion_key
        self._is_native_library_source_type = is_native_library_source_type
        self._skills_dir = skills_dir
        self._delete_tree = delete_tree

    def list(self) -> dict[str, Any]:
        self._ensure_row_factory()
        self.repair_native_references()
        self.repair_installed_provenance()
        rows = self._conn.execute(
            """
            SELECT s.*, f.name AS folder_name
              FROM skills s
              LEFT JOIN skill_folders f ON f.folder_id = s.folder_id
             ORDER BY s.updated_at DESC
            """
        ).fetchall()
        return {"ok": True, "skills": [self._row_to_skill(row) for row in rows]}

    def get(self, skill_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        self.repair_native_references()
        self.repair_installed_provenance()
        row = self._conn.execute(
            """
            SELECT s.*, f.name AS folder_name
              FROM skills s
              LEFT JOIN skill_folders f ON f.folder_id = s.folder_id
             WHERE s.skill_id=?
            """,
            (skill_id,),
        ).fetchone()
        if row is None:
            raise KeyError(skill_id)
        return self._row_to_skill(row)

    def update(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get(skill_id)
        if "enabled" not in payload and "folder_id" not in payload:
            return current
        enabled = payload.get("enabled") if "enabled" in payload else current.get("enabled", True)
        folder_id = (
            self._normalize_skill_folder_id(payload.get("folder_id"))
            if "folder_id" in payload
            else current.get("folder_id", "")
        )
        self._conn.execute(
            """
            UPDATE skills
               SET enabled=?, folder_id=?, updated_at=?
             WHERE skill_id=?
            """,
            (1 if enabled is not False else 0, folder_id, self._now(), skill_id),
        )
        self._conn.commit()
        return self.get(skill_id)

    def delete(self, skill_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        skill_row = self._conn.execute(
            "SELECT local_path, source_type, origin_path FROM skills WHERE skill_id=?",
            (skill_id,),
        ).fetchone()
        if skill_row is not None:
            self._record_studio_deletion(
                "skill_source",
                self._skill_deletion_key(str(skill_row["source_type"]), str(skill_row["origin_path"])),
            )
        self._conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
        rows = self._conn.execute("SELECT agent_id, skill_ids_json FROM agents").fetchall()
        for row in rows:
            skill_ids = [item for item in self._json_load(row["skill_ids_json"], []) if item != skill_id]
            self._conn.execute(
                "UPDATE agents SET skill_ids_json=?, updated_at=? WHERE agent_id=?",
                (self._json_dump(skill_ids), self._now(), row["agent_id"]),
            )
        self._conn.commit()
        source_type = str(skill_row["source_type"] if skill_row is not None else "")
        if not self._is_native_library_source_type(source_type):
            local_path = (
                Path(str(skill_row["local_path"]))
                if skill_row is not None and skill_row["local_path"]
                else self._skills_dir / skill_id
            )
            if self._skill_path_owned_by_runtime(local_path):
                self._delete_tree(local_path, ignore_errors=True)
        return {"ok": True}

    def repair_native_references(self) -> None:
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path
              FROM skills
             WHERE source_type IN ('native_global', 'native_project')
               AND origin_path != ''
               AND local_path != origin_path
            """
        ).fetchall()
        if not rows:
            return
        for row in rows:
            old_local_path = Path(str(row["local_path"] or ""))
            origin_path = str(row["origin_path"])
            self._remove_managed_copy_if_safe(old_local_path, origin_path)
            self._conn.execute(
                """
                UPDATE skills
                   SET local_path=?, updated_at=?
                 WHERE skill_id=?
                """,
                (origin_path, self._now(), row["skill_id"]),
            )
        self._conn.commit()

    def repair_installed_provenance(self) -> None:
        source_map = self._installed_skill_source_map()
        if not source_map:
            return
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT skill_id, local_path, origin_path, source_ref, source_type
             FROM skills
             WHERE source_type='npx_skills'
            """
        ).fetchall()
        changed = False
        for row in rows:
            keys = []
            for raw_path in (row["local_path"], row["origin_path"]):
                if raw_path:
                    keys.append(Path(str(raw_path)).name)
            if row["source_ref"]:
                keys.append(str(row["source_ref"]))
            next_ref = next((source_map[key] for key in keys if key in source_map), "")
            if next_ref and next_ref != row["source_ref"]:
                self._conn.execute(
                    """
                    UPDATE skills
                       SET source_ref=?, source_path=?, updated_at=?
                     WHERE skill_id=?
                    """,
                    (next_ref, f"{row['source_type']}:{next_ref}", self._now(), row["skill_id"]),
                )
                changed = True
        if changed:
            self._conn.commit()
