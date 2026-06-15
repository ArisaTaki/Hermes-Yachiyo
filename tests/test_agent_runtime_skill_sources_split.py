"""Tests for Skill source discovery split out of the legacy runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_sources import SkillSourceDiscovery
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def test_skill_source_discovery_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillSourceDiscovery is SkillSourceDiscovery


def test_skill_source_discovery_roots_counts_and_installed_source_map(tmp_path: Path, monkeypatch) -> None:
    native_home = tmp_path / "native-home"
    installs_dir = tmp_path / "skill-installs"
    native_project_root = tmp_path / "project" / ".oha-yachiyo" / "skills"
    native_global_root = native_home / "skills"
    native_project_root.mkdir(parents=True)
    (native_project_root / "project-skill").mkdir()
    (native_project_root / "project-skill" / "SKILL.md").write_text("# Project Skill", encoding="utf-8")
    native_global_root.mkdir(parents=True)
    (native_global_root / "global-skill").mkdir()
    (native_global_root / "global-skill" / "SKILL.md").write_text("# Global Skill", encoding="utf-8")
    installs_dir.mkdir(parents=True)
    (installs_dir / "skills-lock.json").write_text(
        json.dumps(
            {
                "skills": {
                    "installed-skill": {
                        "source": "owner/repo",
                        "sourceType": "github",
                        "skillPath": "skills/dev/installed-skill/SKILL.md",
                    },
                    "manual-skill": {
                        "source": "https://example.test/manual",
                        "skillPath": "skills/manual/SKILL.md",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path / "project")
    discovery = SkillSourceDiscovery(
        native_skill_home=lambda: native_home,
        skill_installs_dir=installs_dir,
        skill_installs_native_home=installs_dir / "native-home",
        json_load=_json_load,
        normalize_source_type=lambda value: str(value or "").strip(),
        native_library_source_types={"native_global", "native_project"},
    )

    default_specs = discovery.native_root_specs()
    assert default_specs == [{"path": native_global_root, "source_type": "native_global"}]
    specs = discovery.native_root_specs([
        native_project_root,
        {"path": str(native_project_root), "source_type": "unexpected"},
        {"path": str(native_global_root), "source_type": "native_global"},
    ])
    assert specs == [
        {"path": native_project_root, "source_type": "native_project"},
        {"path": native_global_root, "source_type": "native_global"},
    ]
    assert discovery.count_skill_files(native_project_root) == 1
    assert discovery.count_skill_files(tmp_path / "missing") == 0
    native_sources = discovery.list_native_sources([native_project_root])
    assert native_sources == {
        "ok": True,
        "roots": [
            {
                "path": str(native_project_root),
                "source_type": "native_project",
                "library": "native",
                "exists": True,
                "skill_count": 1,
            }
        ],
    }

    source_map = discovery.installed_source_map()
    assert source_map["installed-skill"] == "https://github.com/owner/repo/blob/main/skills/dev/installed-skill/SKILL.md"
    assert source_map["manual"] == "https://example.test/manual · skills/manual/SKILL.md"
    roots = discovery.installed_root_specs(source_type="npx_skills", source_ref_override="https://override")
    assert roots[0]["path"] == installs_dir / ".skills" / "skills"
    assert roots[0]["source_map"] == source_map
    assert roots[0]["source_ref_override"] == "https://override"


def test_native_runtime_uses_split_skill_source_discovery(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        assert isinstance(service.skill_sources, SkillSourceDiscovery)
        assert service._count_skill_files(tmp_path / "missing") == 0
        native_sources = service.list_native_skill_sources()
        assert native_sources["ok"] is True
        assert native_sources["roots"][0]["library"] == "native"
        assert "skill_count" in native_sources["roots"][0]
        roots = service._installed_skill_root_specs(source_type="npx_skills", source_ref_override="override")
        assert roots[0]["path"] == service.skill_installs_dir / ".skills" / "skills"
        assert roots[1]["path"] == service.skill_installs_native_home / "skills"
        assert roots[0]["source_ref_override"] == "override"
    finally:
        service.close()
