"""Skill folder persistence for Agent Studio skill library organization."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class SkillFolderRepository:
    """Stores Studio skill folders without owning skill import or file deletion."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_skill_folder: Callable[[Any], dict[str, Any]],
        now: Callable[[], str],
        slug: Callable[[str, str], str],
        id_suffix_factory: Callable[[], str],
        delete_skill: Callable[[str], dict[str, Any]],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_skill_folder = row_to_skill_folder
        self._now = now
        self._slug = slug
        self._id_suffix_factory = id_suffix_factory
        self._delete_skill = delete_skill
        self._error_type = error_type

    def list(self) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT f.*,
                   COUNT(s.skill_id) AS skill_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skill_folders f
              LEFT JOIN skills s ON s.folder_id = f.folder_id
             GROUP BY f.folder_id
             ORDER BY f.sort_order ASC, LOWER(f.name) ASC
            """
        ).fetchall()
        uncategorized = self._conn.execute(
            """
            SELECT COUNT(*) AS skill_count,
                   SUM(CASE WHEN source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skills
             WHERE folder_id = ''
            """
        ).fetchone()
        return {
            "ok": True,
            "folders": [self._row_to_skill_folder(row) for row in rows],
            "uncategorized": {
                "folder_id": "",
                "name": "Uncategorized",
                "description": "",
                "source_scope": "all",
                "sort_order": -1,
                "skill_count": int(uncategorized["skill_count"] or 0),
                "installed_count": int(uncategorized["installed_count"] or 0),
                "native_count": int(uncategorized["native_count"] or 0),
            },
        }

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise self._error_type("文件夹名称不能为空")
        self.validate_name(name)
        folder_id = str(
            payload.get("folder_id")
            or f"folder_{self._slug(name, 'folder')}_{self._id_suffix_factory()}"
        ).strip()
        folder_id = self._slug(folder_id, "folder")
        if not folder_id.startswith("folder_"):
            folder_id = f"folder_{folder_id}"
        description = str(payload.get("description") or "").strip()[:1000]
        source_scope = str(payload.get("source_scope") or "all")
        if source_scope not in {"all", "installed", "native"}:
            source_scope = "all"
        sort_order = int(payload.get("sort_order") or 0)
        now = self._now()
        try:
            self._conn.execute(
                """
                INSERT INTO skill_folders (
                    folder_id, name, description, source_scope, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (folder_id, name, description, source_scope, sort_order, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise self._error_type("Skill 文件夹已存在") from exc
        self._conn.commit()
        return self.get(folder_id)

    def get(self, folder_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT f.*,
                   COUNT(s.skill_id) AS skill_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 0 ELSE 1 END) AS installed_count,
                   SUM(CASE WHEN s.source_type IN ('native_global', 'native_project') THEN 1 ELSE 0 END) AS native_count
              FROM skill_folders f
              LEFT JOIN skills s ON s.folder_id = f.folder_id
             WHERE f.folder_id=?
             GROUP BY f.folder_id
            """,
            (folder_id,),
        ).fetchone()
        if row is None:
            raise KeyError(folder_id)
        return self._row_to_skill_folder(row)

    def update(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get(folder_id)
        name = str(payload.get("name") if "name" in payload else current["name"]).strip()
        if not name:
            raise self._error_type("文件夹名称不能为空")
        self.validate_name(name, current_folder_id=folder_id)
        description = str(
            payload.get("description") if "description" in payload else current["description"]
        ).strip()[:1000]
        source_scope = str(payload.get("source_scope") if "source_scope" in payload else current["source_scope"])
        if source_scope not in {"all", "installed", "native"}:
            source_scope = "all"
        sort_order = int(payload.get("sort_order") if "sort_order" in payload else current["sort_order"])
        self._conn.execute(
            """
            UPDATE skill_folders
               SET name=?, description=?, source_scope=?, sort_order=?, updated_at=?
             WHERE folder_id=?
            """,
            (name, description, source_scope, sort_order, self._now(), folder_id),
        )
        self._conn.commit()
        return self.get(folder_id)

    def delete(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        self.get(folder_id)
        deleted_skill_count = 0
        if delete_skills:
            self._ensure_row_factory()
            rows = self._conn.execute("SELECT skill_id FROM skills WHERE folder_id=?", (folder_id,)).fetchall()
            for row in rows:
                self._delete_skill(str(row["skill_id"]))
                deleted_skill_count += 1
            self._conn.execute("DELETE FROM skill_folders WHERE folder_id=?", (folder_id,))
            self._conn.commit()
            return {"ok": True, "deleted_skill_count": deleted_skill_count}
        now = self._now()
        self._conn.execute("UPDATE skills SET folder_id='', updated_at=? WHERE folder_id=?", (now, folder_id))
        self._conn.execute("DELETE FROM skill_folders WHERE folder_id=?", (folder_id,))
        self._conn.commit()
        return {"ok": True, "deleted_skill_count": 0}

    def normalize_id(self, folder_id: str | None) -> str:
        clean = str(folder_id or "").strip()
        if not clean:
            return ""
        row = self._conn.execute("SELECT folder_id FROM skill_folders WHERE folder_id=?", (clean,)).fetchone()
        if row is None:
            raise self._error_type("Skill 文件夹不存在")
        return clean

    def validate_name(self, name: str, *, current_folder_id: str = "") -> None:
        if len(name) > 120:
            raise self._error_type("Skill 文件夹名称不能超过 120 个字符")
        row = self._conn.execute(
            """
            SELECT folder_id
              FROM skill_folders
             WHERE LOWER(name)=LOWER(?)
               AND folder_id != ?
             LIMIT 1
            """,
            (name, current_folder_id),
        ).fetchone()
        if row is not None:
            raise self._error_type("Skill 文件夹已存在")
