"""Skill sync planning helpers for native and installed Skill libraries."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillSyncCandidate:
    source_root: Path
    source_type: str
    library: str
    source_ref: str


@dataclass(frozen=True)
class SkillSyncEntry:
    skipped_result: dict[str, Any] | None = None
    candidate: SkillSyncCandidate | None = None


class SkillSyncPlanner:
    """Plans filesystem sync work without importing or mutating Skill records."""

    def __init__(
        self,
        *,
        skill_source_types: set[str],
        count_skill_files: Callable[[Path], int],
    ) -> None:
        self._skill_source_types = skill_source_types
        self._count_skill_files = count_skill_files

    def plan_entries(self, root_specs: list[dict[str, Any]], *, library: str) -> list[SkillSyncEntry]:
        entries: list[SkillSyncEntry] = []
        for root_spec in root_specs:
            root = root_spec["path"]
            source_type = self.normalize_source_type(root_spec.get("source_type"))
            if not root.exists():
                entries.append(self.skipped_entry(root, source_type, library, "Skills root 不存在"))
                continue

            skill_files = sorted(root.rglob("SKILL.md"))
            if not skill_files:
                entries.append(self.skipped_entry(root, source_type, library, "未发现 SKILL.md"))
                continue

            skill_ancestors = {path.parent for path in skill_files}
            for child in sorted(item for item in root.iterdir() if item.is_dir()):
                if not any(child == parent or child in parent.parents for parent in skill_ancestors):
                    entries.append(self.skipped_entry(child, source_type, library, "目录中未发现 SKILL.md"))

            for skill_md in skill_files:
                source_root = skill_md.parent
                entries.append(SkillSyncEntry(candidate=SkillSyncCandidate(
                    source_root=source_root,
                    source_type=source_type,
                    library=library,
                    source_ref=self.source_ref_for(root_spec, root=root, source_root=source_root),
                )))
        return entries

    def roots_info(self, root_specs: Iterable[dict[str, Any]], *, library: str) -> list[dict[str, Any]]:
        return [
            {
                "path": str(root["path"]),
                "source_type": root["source_type"],
                "library": library,
                "exists": root["path"].exists(),
                "skill_count": self._count_skill_files(root["path"]),
            }
            for root in root_specs
        ]

    @staticmethod
    def summarize_results(results: Iterable[dict[str, Any]]) -> dict[str, int]:
        items = list(results)
        return {
            "imported": sum(1 for item in items if item.get("status") == "imported"),
            "updated": sum(1 for item in items if item.get("status") == "updated"),
            "skipped": sum(1 for item in items if item.get("status") == "skipped"),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
        }

    def normalize_source_type(self, value: Any) -> str:
        source_type = str(value)
        if source_type not in self._skill_source_types:
            return "local_dir"
        return source_type

    @staticmethod
    def skipped_entry(source: Path, source_type: str, library: str, message: str) -> SkillSyncEntry:
        return SkillSyncEntry(skipped_result={
            "source": str(source),
            "source_type": source_type,
            "library": library,
            "status": "skipped",
            "message": message,
        })

    @staticmethod
    def source_ref_for(root_spec: dict[str, Any], *, root: Path, source_root: Path) -> str:
        try:
            source_ref = source_root.relative_to(root).as_posix()
        except ValueError:
            source_ref = source_root.name
        source_map = root_spec.get("source_map") if isinstance(root_spec.get("source_map"), dict) else {}
        return str(
            source_map.get(source_root.name)
            or source_map.get(source_ref)
            or root_spec.get("source_ref_override")
            or source_ref
        )
