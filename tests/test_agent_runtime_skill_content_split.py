"""Tests for Skill content inspection split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_content import SkillContentInspector, content_hash, parse_frontmatter
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_skill_content_inspector_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillContentInspector is SkillContentInspector
    assert agent_runtime._skill_content_hash is content_hash
    assert agent_runtime._parse_skill_frontmatter is parse_frontmatter


def test_skill_content_inspector_extracts_metadata_hash_and_assets(tmp_path: Path) -> None:
    root = tmp_path / "skill-root"
    assets = root / "assets"
    templates = root / "templates" / "nested"
    examples = root / "examples"
    assets.mkdir(parents=True)
    templates.mkdir(parents=True)
    examples.mkdir(parents=True)
    skill_md = root / "SKILL.md"
    skill_md.write_text(
        "---\nname: Frontmatter Skill\nrepository: https://example.test/repo\n---\n\n# Heading Skill\n\nUse the skill.\n",
        encoding="utf-8",
    )
    (assets / "sample.txt").write_text("asset", encoding="utf-8")
    (templates / "template.md").write_text("template", encoding="utf-8")
    (examples / "demo.md").write_text("demo", encoding="utf-8")

    markdown = SkillContentInspector.read_text(skill_md)
    metadata = SkillContentInspector.parse_frontmatter(markdown)

    assert metadata == {"name": "Frontmatter Skill", "repository": "https://example.test/repo"}
    assert SkillContentInspector.metadata_source_ref(metadata, "fallback") == "https://example.test/repo"
    assert SkillContentInspector.name(markdown, "fallback") == "Heading Skill"
    assert SkillContentInspector.description(markdown) == "---"
    assert "Use the skill." in SkillContentInspector.summary(markdown)
    assert SkillContentInspector.asset_paths(root) == [
        "assets/sample.txt",
        "examples/demo.md",
        "templates/nested/template.md",
    ]
    assert content_hash(root) == SkillContentInspector.content_hash(root)
    assert content_hash(root) == agent_runtime._skill_content_hash(root)
    assert parse_frontmatter(markdown) == agent_runtime._parse_skill_frontmatter(markdown)


def test_native_runtime_uses_split_skill_content_inspector(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    source = tmp_path / "runtime-skill"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: Runtime Content Skill\nsource: https://example.test/source\n---\n\n# Runtime Heading\n\nDemo.",
        encoding="utf-8",
    )
    (source / "assets" / "sample.txt").write_text("asset", encoding="utf-8")
    try:
        skill = service.import_skill(str(source))

        assert isinstance(service.skill_content, SkillContentInspector)
        assert skill["name"] == "Runtime Content Skill"
        assert skill["source_ref"] == "https://example.test/source"
        assert skill["asset_paths"] == ["assets/sample.txt"]
    finally:
        service.close()
