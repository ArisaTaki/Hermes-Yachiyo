"""Tests for Skill import source resolution split out of the legacy runtime."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.skill_content import SkillContentInspector
from apps.shell.agent.runtime.skill_import import (
    PreparedSkillImport,
    ResolvedSkillImportSource,
    SkillImportPreparer,
    SkillImportSourceResolver,
)
from apps.shell.agent.runtime.skill_import_service import RuntimeSkillImportService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _resolver(workspace_dir: Path, ids: list[str] | None = None) -> SkillImportSourceResolver:
    pending_ids = list(ids or ["tmp"])
    return SkillImportSourceResolver(
        workspace_dir=workspace_dir,
        id_factory=lambda: pending_ids.pop(0),
        error_type=AgentRuntimeError,
    )


def test_skill_import_source_resolver_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillImportSourceResolver is SkillImportSourceResolver
    assert agent_runtime.SkillImportPreparer is SkillImportPreparer
    assert agent_runtime.RuntimeSkillImportService is RuntimeSkillImportService


def test_skill_import_source_resolver_accepts_directory_and_nested_zip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_dir = tmp_path / "demo-skill"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text("# Demo Skill", encoding="utf-8")
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested-skill/SKILL.md", "# Nested Skill")

    resolver = _resolver(workspace, ["zip-root"])

    directory = resolver.resolve(str(source_dir))
    zipped = resolver.resolve(str(archive))

    assert directory == ResolvedSkillImportSource(
        source=source_dir,
        source_root=source_dir,
        source_path="local:demo-skill",
        source_type="local_dir",
        source_ref="demo-skill",
        origin_path=str(source_dir.resolve()),
        temp_dir=None,
    )
    assert zipped.source == archive
    assert zipped.source_root == workspace / "skill-import-tmp" / "zip-root" / "nested-skill"
    assert zipped.source_path == "local:nested.zip"
    assert zipped.source_type == "local_zip"
    assert zipped.source_ref == "nested.zip"
    assert zipped.origin_path == str(archive.resolve())
    assert zipped.temp_dir == workspace / "skill-import-tmp" / "zip-root"
    assert zipped.source_root.joinpath("SKILL.md").is_file()

    resolver.cleanup(zipped)
    assert not zipped.temp_dir.exists()


def test_skill_import_source_resolver_rejects_invalid_sources_and_cleans_temp(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    text_file = tmp_path / "not-a-skill.txt"
    text_file.write_text("plain text", encoding="utf-8")
    bad_archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_archive, "w") as zf:
        zf.writestr("../SKILL.md", "# Bad")
    resolver = _resolver(workspace, ["bad-zip"])

    with pytest.raises(AgentRuntimeError, match="Skill 路径不存在"):
        resolver.resolve(str(tmp_path / "missing"))
    with pytest.raises(AgentRuntimeError, match="Skill 文件只支持 ZIP"):
        resolver.resolve(str(text_file))
    with pytest.raises(AgentRuntimeError, match="路径穿越"):
        resolver.resolve(str(bad_archive))

    assert not (workspace / "skill-import-tmp" / "bad-zip").exists()


def test_native_runtime_uses_split_skill_import_source_resolver(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("runtime-skill/SKILL.md", "# Runtime Zip Skill\n\nDemo.")

    try:
        assert isinstance(service.skill_import_sources, SkillImportSourceResolver)
        assert isinstance(service.skill_import_preparer, SkillImportPreparer)
        assert isinstance(service.skill_import_service, RuntimeSkillImportService)
        skill = service.import_skill(str(archive))

        assert skill["name"] == "Runtime Zip Skill"
        assert skill["source_path"] == "local:runtime.zip"
        assert skill["source_type"] == "local_zip"
        assert skill["local_path"].startswith(str(service.skills_dir))
        assert not any((service.workspace_dir / "skill-import-tmp").glob("*"))
    finally:
        service.close()


def test_native_runtime_keeps_missing_skill_path_error_before_folder_validation(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        with pytest.raises(AgentRuntimeError, match="Skill 路径不存在"):
            service.import_skill(str(tmp_path / "missing"), "folder_missing")
    finally:
        service.close()


def test_skill_import_preparer_extracts_metadata_and_sync_timestamps(tmp_path: Path) -> None:
    root = tmp_path / "prepared-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\n"
        "name: Frontmatter Prepared Skill\n"
        "description: Frontmatter description.\n"
        "repository: https://example.test/prepared\n"
        "---\n\n"
        "# Markdown Heading\n\nUse the prepared skill.",
        encoding="utf-8",
    )
    preparer = SkillImportPreparer(
        content=SkillContentInspector(),
        skill_source_types={"local_dir", "native_global"},
        now=lambda: "2026-01-02T03:04:05Z",
        error_type=AgentRuntimeError,
    )

    local = preparer.prepare(root, source_type="local_dir", source_ref="fallback")
    synced = preparer.prepare(root, source_type="native_global", source_ref="fallback", synced_at="")

    assert local == PreparedSkillImport(
        source_ref="https://example.test/prepared",
        markdown=(root / "SKILL.md").read_text(encoding="utf-8"),
        metadata={
            "name": "Frontmatter Prepared Skill",
            "description": "Frontmatter description.",
            "repository": "https://example.test/prepared",
        },
        name="Frontmatter Prepared Skill",
        description="Frontmatter description.",
        content_hash=SkillContentInspector.content_hash(root),
        summary=SkillContentInspector.summary((root / "SKILL.md").read_text(encoding="utf-8")),
        now="2026-01-02T03:04:05Z",
        last_synced_at="",
    )
    assert synced.last_synced_at == "2026-01-02T03:04:05Z"


def test_skill_import_preparer_rejects_unknown_type_and_missing_skill_md(tmp_path: Path) -> None:
    root = tmp_path / "missing-md"
    root.mkdir()
    preparer = SkillImportPreparer(
        content=SkillContentInspector(),
        skill_source_types={"local_dir"},
        now=lambda: "now",
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="未知 Skill 来源类型"):
        preparer.prepare(root, source_type="unknown", source_ref="fallback")
    with pytest.raises(AgentRuntimeError, match="SKILL.md"):
        preparer.prepare(root, source_type="local_dir", source_ref="fallback")


def test_runtime_skill_import_service_imports_source_and_cleans_up(tmp_path: Path) -> None:
    source = tmp_path / "source-skill"
    source.mkdir()
    source_root = tmp_path / "resolved-skill"
    source_root.mkdir()
    resolved = ResolvedSkillImportSource(
        source=source,
        source_root=source_root,
        source_path="local:source-skill",
        source_type="local_dir",
        source_ref="source-skill",
        origin_path=str(source.resolve()),
        temp_dir=None,
    )
    prepared = PreparedSkillImport(
        source_ref="https://example.test/source-skill",
        markdown="# Source Skill",
        metadata={},
        name="Source Skill",
        description="Demo",
        content_hash="hash-1",
        summary="summary",
        now="now",
        last_synced_at="",
    )
    cleanup_calls: list[ResolvedSkillImportSource] = []
    clear_calls: list[tuple[str, str]] = []
    commits: list[str] = []
    save_calls: list[dict[str, object]] = []

    class FakeResolver:
        def resolve(self, source_path: str) -> ResolvedSkillImportSource:
            assert source_path == str(source)
            return resolved

        def cleanup(self, value: ResolvedSkillImportSource) -> None:
            cleanup_calls.append(value)

    class FakePreparer:
        def prepare(self, root: Path, **kwargs) -> PreparedSkillImport:
            assert root == source_root
            assert kwargs == {"source_type": "local_dir", "source_ref": "source-skill", "synced_at": ""}
            return prepared

    class FakeSkillRecords:
        def find_existing_import(self, **kwargs):
            assert kwargs == {
                "origin_path": str(source.resolve()),
                "content_hash": "hash-1",
                "source_type": "local_dir",
            }
            return None

        def save_import(self, **kwargs):
            save_calls.append(kwargs)
            return {"skill_id": "skill-1", "sync_status": "imported"}

    class FakeConn:
        def commit(self) -> None:
            commits.append("commit")

    service = RuntimeSkillImportService(
        conn=FakeConn(),
        source_resolver=FakeResolver(),
        preparer=FakePreparer(),
        skill_records=FakeSkillRecords(),
        normalize_skill_folder_id=lambda folder_id: folder_id or "",
        skill_deletion_key=lambda source_type, origin_path: f"{source_type}:{origin_path}",
        clear_studio_deletion=lambda item_type, item_key: clear_calls.append((item_type, item_key)),
        get_skill=lambda skill_id: {"skill_id": skill_id, "name": "Source Skill"},
        error_type=AgentRuntimeError,
    )

    imported = service.import_skill(str(source), folder_id="folder-1")

    assert imported == {"skill_id": "skill-1", "name": "Source Skill", "sync_status": "imported"}
    assert cleanup_calls == [resolved]
    assert clear_calls == [("skill_source", f"local_dir:{source.resolve()}")]
    assert commits == ["commit"]
    assert save_calls[0]["source_root"] == source_root
    assert save_calls[0]["source_ref"] == "https://example.test/source-skill"
    assert save_calls[0]["folder_id_was_provided"] is True
    assert save_calls[0]["target_folder_id"] == "folder-1"


def test_runtime_skill_import_service_keeps_missing_path_error_before_folder_validation(tmp_path: Path) -> None:
    class Unused:
        def __getattr__(self, name: str):
            raise AssertionError(name)

    service = RuntimeSkillImportService(
        conn=Unused(),
        source_resolver=Unused(),
        preparer=Unused(),
        skill_records=Unused(),
        normalize_skill_folder_id=lambda _folder_id: (_ for _ in ()).throw(AssertionError("folder validated")),
        skill_deletion_key=lambda _source_type, _origin_path: "",
        clear_studio_deletion=lambda _item_type, _item_key: None,
        get_skill=lambda _skill_id: {},
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="Skill 路径不存在"):
        service.import_skill(str(tmp_path / "missing"), folder_id="missing-folder")
