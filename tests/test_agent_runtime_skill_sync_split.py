"""Tests for Skill sync planning split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_sync import SkillSyncCandidate, SkillSyncPlanner
from apps.shell.agent.runtime.skill_sync_service import RuntimeSkillSyncService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _planner() -> SkillSyncPlanner:
    return SkillSyncPlanner(
        skill_source_types={"native_global", "native_project", "npx_skills", "local_zip", "local_dir"},
        count_skill_files=lambda root: sum(1 for _ in root.rglob("SKILL.md")) if root.exists() else 0,
    )


def test_skill_sync_planner_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillSyncPlanner is SkillSyncPlanner
    assert agent_runtime.RuntimeSkillSyncService is RuntimeSkillSyncService


def test_skill_sync_planner_scans_roots_skips_and_source_refs(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    empty_root = tmp_path / "empty"
    skills_root = tmp_path / "skills"
    empty_root.mkdir()
    (skills_root / "not-a-skill").mkdir(parents=True)
    nested_skill = skills_root / "research" / "demo-skill"
    nested_skill.mkdir(parents=True)
    (nested_skill / "SKILL.md").write_text("# Demo Skill", encoding="utf-8")
    mapped_skill = skills_root / "mapped-skill"
    mapped_skill.mkdir()
    (mapped_skill / "SKILL.md").write_text("# Mapped Skill", encoding="utf-8")

    planner = _planner()
    entries = planner.plan_entries(
        [
            {"path": missing_root, "source_type": "native_global"},
            {"path": empty_root, "source_type": "native_global"},
            {
                "path": skills_root,
                "source_type": "unknown",
                "source_map": {"mapped-skill": "https://example.test/mapped"},
                "source_ref_override": "https://example.test/override",
            },
        ],
        library="native",
    )

    skipped = [entry.skipped_result for entry in entries if entry.skipped_result is not None]
    candidates = [entry.candidate for entry in entries if entry.candidate is not None]

    assert skipped == [
        {
            "source": str(missing_root),
            "source_type": "native_global",
            "library": "native",
            "status": "skipped",
            "message": "Skills root 不存在",
        },
        {
            "source": str(empty_root),
            "source_type": "native_global",
            "library": "native",
            "status": "skipped",
            "message": "未发现 SKILL.md",
        },
        {
            "source": str(skills_root / "not-a-skill"),
            "source_type": "local_dir",
            "library": "native",
            "status": "skipped",
            "message": "目录中未发现 SKILL.md",
        },
    ]
    assert candidates == [
        SkillSyncCandidate(
            source_root=mapped_skill,
            source_type="local_dir",
            library="native",
            source_ref="https://example.test/mapped",
        ),
        SkillSyncCandidate(
            source_root=nested_skill,
            source_type="local_dir",
            library="native",
            source_ref="https://example.test/override",
        ),
    ]

    roots_info = planner.roots_info([
        {"path": missing_root, "source_type": "native_global"},
        {"path": skills_root, "source_type": "unknown"},
    ], library="native")
    assert roots_info == [
        {
            "path": str(missing_root),
            "source_type": "native_global",
            "library": "native",
            "exists": False,
            "skill_count": 0,
        },
        {
            "path": str(skills_root),
            "source_type": "unknown",
            "library": "native",
            "exists": True,
            "skill_count": 2,
        },
    ]

    assert planner.summarize_results([
        {"status": "imported"},
        {"status": "updated"},
        {"status": "skipped"},
        {"status": "failed"},
        {"status": "ignored"},
    ]) == {"imported": 1, "updated": 1, "skipped": 1, "failed": 1}


def test_native_runtime_uses_split_skill_sync_planner(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        assert isinstance(service.skill_sync, SkillSyncPlanner)
        assert isinstance(service.skill_sync_service, RuntimeSkillSyncService)
        synced = service.sync_native_skills(roots=[{"path": str(tmp_path / "missing"), "source_type": "native_global"}])
        assert synced["results"] == [
            {
                "source": str(tmp_path / "missing"),
                "source_type": "native_global",
                "library": "native",
                "status": "skipped",
                "message": "Skills root 不存在",
            }
        ]
        assert synced["summary"] == {"imported": 0, "updated": 0, "skipped": 1, "failed": 0}
    finally:
        service.close()


def test_skill_sync_service_skips_and_restores_deleted_sources(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    source_root = skills_root / "demo"
    source_root.mkdir(parents=True)
    (source_root / "SKILL.md").write_text("# Demo", encoding="utf-8")
    deletion_key = f"native_global:{source_root.resolve()}"
    deleted = {("skill_source", deletion_key)}
    cleared: list[tuple[str, str]] = []
    imported: list[dict[str, object]] = []
    conn = _FakeConn()
    service = RuntimeSkillSyncService(
        conn=conn,
        skill_sync=_planner(),
        normalize_skill_folder_id=lambda folder_id: str(folder_id or ""),
        skill_deletion_key=lambda source_type, path: f"{source_type}:{path}",
        has_studio_deletion=lambda item_type, item_key: (item_type, item_key) in deleted,
        clear_studio_deletion=lambda item_type, item_key: cleared.append((item_type, item_key)),
        import_skill_root=lambda source_root, **kwargs: imported.append({"source_root": source_root, **kwargs})
        or {"sync_status": "imported", "skill_id": "skill-1", "name": "Demo"},
        now=lambda: "now",
        redact_error=str,
        error_type=agent_runtime.AgentRuntimeError,
    )
    root_specs = [{"path": skills_root, "source_type": "native_global"}]

    skipped = service.sync_roots(root_specs, library="native")
    restored = service.sync_roots(root_specs, library="native", folder_id="folder-1", restore_deleted=True)

    assert skipped["results"][0]["status"] == "skipped"
    assert "用户已删除" in skipped["results"][0]["message"]
    assert imported[0]["folder_id"] == "folder-1"
    assert imported[0]["copy_to_managed"] is False
    assert imported[0]["sync_status"] == "synced"
    assert restored["summary"] == {"imported": 1, "updated": 0, "skipped": 0, "failed": 0}
    assert cleared == [("skill_source", deletion_key)]
    assert conn.commits == 1


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1
