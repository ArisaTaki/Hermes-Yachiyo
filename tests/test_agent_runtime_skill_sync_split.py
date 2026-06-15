"""Tests for Skill sync planning split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_sync import SkillSyncCandidate, SkillSyncPlanner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _planner() -> SkillSyncPlanner:
    return SkillSyncPlanner(
        skill_source_types={"native_global", "native_project", "npx_skills", "local_zip", "local_dir"},
        count_skill_files=lambda root: sum(1 for _ in root.rglob("SKILL.md")) if root.exists() else 0,
    )


def test_skill_sync_planner_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillSyncPlanner is SkillSyncPlanner


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
