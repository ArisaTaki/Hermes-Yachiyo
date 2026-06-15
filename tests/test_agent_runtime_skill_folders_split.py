"""Tests for SkillFolderRepository split out of the legacy runtime."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _connect_skill_folder_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE skill_folders (
            folder_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source_scope TEXT NOT NULL DEFAULT 'all',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY,
            folder_id TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'local_dir',
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def _row_to_skill_folder(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "folder_id": str(row["folder_id"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "source_scope": str(row["source_scope"]),
        "sort_order": int(row["sort_order"]),
        "skill_count": int(row["skill_count"] or 0),
        "installed_count": int(row["installed_count"] or 0),
        "native_count": int(row["native_count"] or 0),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _slug(value: str, fallback: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return clean or fallback


def test_skill_folder_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillFolderRepository is SkillFolderRepository


def test_skill_folder_repository_lifecycle_counts_and_deletes() -> None:
    conn = _connect_skill_folder_db()
    now_values = iter(
        [
            "2026-06-15T10:00:00Z",
            "2026-06-15T10:01:00Z",
            "2026-06-15T10:02:00Z",
            "2026-06-15T10:03:00Z",
            "2026-06-15T10:04:00Z",
        ]
    )
    suffix_values = iter(["abc123", "def456"])
    deleted_skills: list[str] = []

    def delete_skill(skill_id: str) -> dict[str, Any]:
        deleted_skills.append(skill_id)
        conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
        conn.commit()
        return {"ok": True}

    repo = SkillFolderRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_skill_folder=_row_to_skill_folder,
        now=lambda: next(now_values),
        slug=_slug,
        id_suffix_factory=lambda: next(suffix_values),
        delete_skill=delete_skill,
        error_type=AgentRuntimeError,
    )
    conn.execute(
        "INSERT INTO skills (skill_id, folder_id, source_type, updated_at) VALUES (?, '', ?, ?)",
        ("uncategorized-native", "native_global", "2026-06-15T09:00:00Z"),
    )
    conn.execute(
        "INSERT INTO skills (skill_id, folder_id, source_type, updated_at) VALUES (?, '', ?, ?)",
        ("uncategorized-installed", "local_dir", "2026-06-15T09:00:01Z"),
    )

    folder = repo.create({"name": "Research Tools", "source_scope": "unexpected"})
    assert folder["folder_id"] == "folder_research_tools_abc123"
    assert folder["source_scope"] == "all"
    assert repo.normalize_id(f" {folder['folder_id']} ") == folder["folder_id"]

    conn.execute(
        "INSERT INTO skills (skill_id, folder_id, source_type, updated_at) VALUES (?, ?, ?, ?)",
        ("folder-installed", folder["folder_id"], "local_dir", "2026-06-15T09:01:00Z"),
    )
    conn.execute(
        "INSERT INTO skills (skill_id, folder_id, source_type, updated_at) VALUES (?, ?, ?, ?)",
        ("folder-native", folder["folder_id"], "native_project", "2026-06-15T09:01:01Z"),
    )
    listed = repo.list()
    assert listed["folders"][0]["skill_count"] == 2
    assert listed["folders"][0]["installed_count"] == 1
    assert listed["folders"][0]["native_count"] == 1
    assert listed["uncategorized"]["skill_count"] == 2

    updated = repo.update(folder["folder_id"], {"name": "Research", "source_scope": "native", "sort_order": 5})
    assert updated["name"] == "Research"
    assert updated["source_scope"] == "native"
    assert updated["sort_order"] == 5

    with pytest.raises(AgentRuntimeError, match="Skill 文件夹已存在"):
        repo.create({"name": "research"})
    with pytest.raises(AgentRuntimeError, match="Skill 文件夹不存在"):
        repo.normalize_id("folder_missing")

    deleted = repo.delete(folder["folder_id"])
    assert deleted == {"ok": True, "deleted_skill_count": 0}
    assert conn.execute("SELECT DISTINCT folder_id FROM skills WHERE skill_id LIKE 'folder-%'").fetchone()["folder_id"] == ""

    destructive = repo.create({"name": "Temporary"})
    conn.execute(
        "INSERT INTO skills (skill_id, folder_id, source_type, updated_at) VALUES (?, ?, ?, ?)",
        ("temporary-skill", destructive["folder_id"], "local_dir", "2026-06-15T09:02:00Z"),
    )
    assert repo.delete(destructive["folder_id"], delete_skills=True) == {"ok": True, "deleted_skill_count": 1}
    assert deleted_skills == ["temporary-skill"]


def test_native_runtime_uses_split_skill_folder_repository(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        folder = service.create_skill_folder({"name": "Runtime Folder"})

        assert isinstance(service.skill_folders, SkillFolderRepository)
        assert service.get_skill_folder(folder["folder_id"])["name"] == "Runtime Folder"
        assert service._normalize_skill_folder_id(folder["folder_id"]) == folder["folder_id"]
        service.delete_skill_folder(folder["folder_id"])
    finally:
        service.close()
