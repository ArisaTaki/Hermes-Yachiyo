"""Tests for SkillRepository split out of the legacy runtime."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _connect_skills_db() -> sqlite3.Connection:
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
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL,
            local_path TEXT NOT NULL DEFAULT '',
            folder_id TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'local_dir',
            origin_path TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            last_synced_at TEXT NOT NULL DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'imported',
            content_summary TEXT NOT NULL DEFAULT '',
            skill_markdown TEXT NOT NULL,
            asset_paths_json TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            skill_ids_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def _row_to_skill(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "skill_id": str(row["skill_id"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "source_path": str(row["source_path"]),
        "local_path": str(row["local_path"]),
        "folder_id": str(row["folder_id"]),
        "folder_name": str(row["folder_name"] if "folder_name" in keys and row["folder_name"] else ""),
        "source_type": str(row["source_type"]),
        "origin_path": str(row["origin_path"]),
        "source_ref": str(row["source_ref"]),
        "asset_paths": _json_load(row["asset_paths_json"], []),
        "enabled": bool(row["enabled"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _insert_skill(conn: sqlite3.Connection, *, skill_id: str, name: str, **overrides: Any) -> None:
    values = {
        "skill_id": skill_id,
        "name": name,
        "description": "",
        "source_path": f"local:{name}",
        "local_path": "",
        "folder_id": "",
        "source_type": "local_dir",
        "origin_path": "",
        "source_ref": "",
        "content_hash": skill_id,
        "last_synced_at": "",
        "sync_status": "imported",
        "content_summary": "",
        "skill_markdown": f"# {name}\n",
        "asset_paths_json": "[]",
        "enabled": 1,
        "created_at": "2026-06-15T09:00:00Z",
        "updated_at": "2026-06-15T09:00:00Z",
    }
    values.update(overrides)
    conn.execute(
        """
        INSERT INTO skills (
            skill_id, name, description, source_path, local_path, folder_id, source_type, origin_path,
            source_ref, content_hash, last_synced_at, sync_status, content_summary, skill_markdown,
            asset_paths_json, enabled, created_at, updated_at
        ) VALUES (
            :skill_id, :name, :description, :source_path, :local_path, :folder_id, :source_type, :origin_path,
            :source_ref, :content_hash, :last_synced_at, :sync_status, :content_summary, :skill_markdown,
            :asset_paths_json, :enabled, :created_at, :updated_at
        )
        """,
        values,
    )


def test_skill_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillRepository is SkillRepository


def test_skill_repository_lifecycle_repairs_updates_and_deletes(tmp_path: Path) -> None:
    conn = _connect_skills_db()
    now_values = iter(
        [
            "2026-06-15T10:00:00Z",
            "2026-06-15T10:01:00Z",
            "2026-06-15T10:02:00Z",
            "2026-06-15T10:03:00Z",
            "2026-06-15T10:04:00Z",
        ]
    )
    deletion_events: list[tuple[str, str]] = []
    removed_managed_copies: list[tuple[str, str]] = []
    deleted_trees: list[str] = []
    folder_id = "folder-research"
    conn.execute(
        """
        INSERT INTO skill_folders (folder_id, name, description, source_scope, sort_order, created_at, updated_at)
        VALUES (?, 'Research', '', 'all', 0, '2026-06-15T09:00:00Z', '2026-06-15T09:00:00Z')
        """,
        (folder_id,),
    )
    native_root = tmp_path / "native" / "demo"
    managed_copy = tmp_path / "managed" / "skill-native"
    local_skill = tmp_path / "managed" / "skill-local"
    installed_root = tmp_path / "skill-installs" / ".skills" / "skills" / "dev" / "installed-skill"
    for path in (native_root, managed_copy, local_skill, installed_root):
        path.mkdir(parents=True)
    _insert_skill(
        conn,
        skill_id="skill-native",
        name="Native Skill",
        source_type="native_global",
        local_path=str(managed_copy),
        origin_path=str(native_root),
    )
    _insert_skill(
        conn,
        skill_id="skill-installed",
        name="Installed Skill",
        source_type="npx_skills",
        source_path="npx_skills:installed-skill",
        local_path=str(installed_root),
        origin_path=str(installed_root),
        source_ref="",
    )
    _insert_skill(
        conn,
        skill_id="skill-local",
        name="Local Skill",
        local_path=str(local_skill),
        folder_id=folder_id,
    )
    conn.execute(
        "INSERT INTO agents (agent_id, skill_ids_json, updated_at) VALUES (?, ?, ?)",
        ("agent-1", _json_dump(["skill-local", "skill-other"]), "2026-06-15T09:00:00Z"),
    )
    conn.commit()

    def normalize_folder_id(value: str | None) -> str:
        clean = str(value or "").strip()
        if clean and conn.execute("SELECT 1 FROM skill_folders WHERE folder_id=?", (clean,)).fetchone() is None:
            raise AssertionError("missing folder")
        return clean

    repo = SkillRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_skill=_row_to_skill,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        json_load=_json_load,
        normalize_skill_folder_id=normalize_folder_id,
        installed_skill_source_map=lambda: {"installed-skill": "https://github.com/owner/repo/blob/main/SKILL.md"},
        remove_managed_copy_if_safe=lambda path, origin: removed_managed_copies.append((str(path), origin)),
        skill_path_owned_by_runtime=lambda path: str(path).startswith(str(tmp_path / "managed")),
        record_studio_deletion=lambda kind, key: deletion_events.append((kind, key)),
        skill_deletion_key=lambda source_type, origin_path: f"{source_type}:{origin_path}",
        is_native_library_source_type=lambda value: str(value) in {"native_global", "native_project"},
        skills_dir=tmp_path / "managed",
        delete_tree=lambda path, ignore_errors=False: deleted_trees.append(str(path)),
    )

    listed = repo.list()["skills"]
    native = next(skill for skill in listed if skill["skill_id"] == "skill-native")
    installed = next(skill for skill in listed if skill["skill_id"] == "skill-installed")
    assert native["local_path"] == str(native_root)
    assert installed["source_ref"] == "https://github.com/owner/repo/blob/main/SKILL.md"
    assert removed_managed_copies == [(str(managed_copy), str(native_root))]

    updated = repo.update("skill-local", {"enabled": False, "folder_id": ""})
    assert updated["enabled"] is False
    assert updated["folder_id"] == ""
    assert repo.update("skill-local", {"description": "ignored"}) == updated

    assert repo.delete("skill-local") == {"ok": True}
    assert deletion_events == [("skill_source", "local_dir:")]
    assert deleted_trees == [str(local_skill)]
    agent_row = conn.execute("SELECT skill_ids_json FROM agents WHERE agent_id='agent-1'").fetchone()
    assert _json_load(agent_row["skill_ids_json"], []) == ["skill-other"]


def test_skill_repository_finds_existing_import_by_origin_or_hash_with_library_scope(tmp_path: Path) -> None:
    conn = _connect_skills_db()
    native_root = tmp_path / "native-skill"
    local_root = tmp_path / "local-skill"
    _insert_skill(
        conn,
        skill_id="skill-native",
        name="Native Skill",
        source_type="native_global",
        origin_path=str(native_root),
        content_hash="shared-hash",
    )
    _insert_skill(
        conn,
        skill_id="skill-local",
        name="Local Skill",
        source_type="local_dir",
        origin_path=str(local_root),
        content_hash="shared-hash",
    )
    _insert_skill(
        conn,
        skill_id="skill-local-by-origin",
        name="Local By Origin",
        source_type="local_dir",
        origin_path=str(tmp_path / "origin-first"),
        content_hash="other-hash",
    )
    conn.commit()
    repo = SkillRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_skill=_row_to_skill,
        now=lambda: "2026-06-15T10:00:00Z",
        json_dump=_json_dump,
        json_load=_json_load,
        normalize_skill_folder_id=lambda value: str(value or ""),
        installed_skill_source_map=lambda: {},
        remove_managed_copy_if_safe=lambda _path, _origin: None,
        skill_path_owned_by_runtime=lambda _path: False,
        record_studio_deletion=lambda _kind, _key: None,
        skill_deletion_key=lambda source_type, origin_path: f"{source_type}:{origin_path}",
        is_native_library_source_type=lambda value: str(value) in {"native_global", "native_project"},
        skills_dir=tmp_path / "managed",
    )

    assert repo.find_existing_import(
        origin_path=str(tmp_path / "origin-first"),
        content_hash="shared-hash",
        source_type="local_dir",
    )["skill_id"] == "skill-local-by-origin"
    assert repo.find_existing_import(
        origin_path="",
        content_hash="shared-hash",
        source_type="native_global",
    )["skill_id"] == "skill-native"
    assert repo.find_existing_import(
        origin_path="",
        content_hash="shared-hash",
        source_type="local_zip",
    )["skill_id"] == "skill-local"
    assert repo.find_existing_import(origin_path="", content_hash="", source_type="local_dir") is None


def test_native_runtime_uses_split_skill_repository(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    source = tmp_path / "runtime-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Runtime Skill\n\nDemo.", encoding="utf-8")
    try:
        skill = service.import_skill(str(source))

        assert isinstance(service.skill_records, SkillRepository)
        assert service.get_skill(skill["skill_id"])["name"] == "Runtime Skill"
        assert service.update_skill(skill["skill_id"], {"enabled": False})["enabled"] is False
        assert service.delete_skill(skill["skill_id"]) == {"ok": True}
    finally:
        service.close()
