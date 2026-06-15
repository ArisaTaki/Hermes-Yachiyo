"""Skill source discovery for native and installed Skill libraries."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any


class SkillSourceDiscovery:
    """Finds Skill roots and provenance metadata without importing records."""

    def __init__(
        self,
        *,
        native_skill_home: Callable[[], Path],
        skill_installs_dir: Path,
        skill_installs_native_home: Path,
        json_load: Callable[[str | None, Any], Any],
        normalize_source_type: Callable[[Any], str],
        native_library_source_types: set[str],
    ) -> None:
        self._native_skill_home = native_skill_home
        self._skill_installs_dir = skill_installs_dir
        self._skill_installs_native_home = skill_installs_native_home
        self._json_load = json_load
        self._normalize_source_type = normalize_source_type
        self._native_library_source_types = native_library_source_types

    def native_root_specs(self, roots: list[Any] | None = None) -> list[dict[str, Any]]:
        if roots is None:
            raw_roots: list[Any] = [
                {"path": self._native_skill_home() / "skills", "source_type": "native_global"},
            ]
        else:
            raw_roots = roots
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_roots:
            if isinstance(item, dict):
                path = Path(str(item.get("path") or "")).expanduser()
                source_type = self._normalize_source_type(item.get("source_type") or self.infer_native_source_type(path))
            else:
                path = Path(str(item)).expanduser()
                source_type = self.infer_native_source_type(path)
            if source_type not in self._native_library_source_types:
                source_type = "native_global"
            key = str(path.resolve()) if path.exists() else str(path)
            if not key or key in seen:
                continue
            seen.add(key)
            specs.append({"path": path, "source_type": source_type})
        return specs

    def list_native_sources(self, roots: list[Any] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "roots": [
                {
                    "path": str(root["path"]),
                    "source_type": root["source_type"],
                    "library": "native",
                    "exists": root["path"].exists(),
                    "skill_count": self.count_skill_files(root["path"]),
                }
                for root in self.native_root_specs(roots)
            ],
        }

    def installed_root_specs(self, *, source_type: str, source_ref_override: str = "") -> list[dict[str, Any]]:
        roots = [
            self._skill_installs_dir / ".skills" / "skills",
            self._skill_installs_native_home / "skills",
        ]
        source_map = self.installed_source_map()
        return [
            {
                "path": root,
                "source_type": source_type,
                "source_map": source_map,
                "source_ref_override": source_ref_override,
            }
            for root in roots
        ]

    def installed_source_map(self) -> dict[str, str]:
        lock_path = self._skill_installs_dir / "skills-lock.json"
        if not lock_path.is_file():
            return {}
        try:
            data = self._json_load(lock_path.read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        raw_skills = data.get("skills") if isinstance(data, dict) else {}
        if not isinstance(raw_skills, dict):
            return {}
        source_map: dict[str, str] = {}
        for skill_name, raw_entry in raw_skills.items():
            if not isinstance(raw_entry, dict):
                continue
            source_ref = self.skill_lock_source_ref(raw_entry)
            if not source_ref:
                continue
            source_map[str(skill_name)] = source_ref
            skill_path = str(raw_entry.get("skillPath") or "")
            if skill_path:
                source_map[Path(skill_path).parent.name] = source_ref
        return source_map

    @staticmethod
    def skill_lock_source_ref(entry: dict[str, Any]) -> str:
        source = str(entry.get("source") or "").strip()
        source_type = str(entry.get("sourceType") or "").strip().lower()
        skill_path = str(entry.get("skillPath") or "").strip()
        if source_type == "github" and re.fullmatch(r"[^/\s]+/[^/\s]+", source):
            if skill_path:
                return f"https://github.com/{source}/blob/main/{skill_path}"
            return f"https://github.com/{source}"
        return " · ".join(part for part in [source, skill_path] if part)

    @staticmethod
    def infer_native_source_type(path: Path) -> str:
        project_root = Path.cwd() / ".oha-yachiyo" / "skills"
        try:
            if path.resolve() == project_root.resolve():
                return "native_project"
        except OSError:
            pass
        return "native_global"

    @staticmethod
    def count_skill_files(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(1 for _ in root.rglob("SKILL.md"))
