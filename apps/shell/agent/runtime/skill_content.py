"""Skill content inspection helpers for import and sync flows."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class SkillContentInspector:
    """Extracts metadata, summaries, hashes, and assets from Skill roots."""

    @staticmethod
    def read_text(path: Path, limit: int = 200_000) -> str:
        data = path.read_bytes()[:limit]
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def content_hash(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            try:
                rel = path.relative_to(root).as_posix()
                digest.update(rel.encode("utf-8", errors="replace"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
            except OSError:
                continue
        return digest.hexdigest()

    @staticmethod
    def parse_frontmatter(markdown: str) -> dict[str, Any]:
        lines = markdown.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        data: dict[str, Any] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip().strip("\"'")
            if key and value:
                data[key] = value
        return data

    @staticmethod
    def metadata_source_ref(metadata: dict[str, Any], fallback: str) -> str:
        for key in ("source", "repository", "repo", "homepage", "url", "origin"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

    @staticmethod
    def name(markdown: str, fallback: str) -> str:
        for line in markdown.splitlines():
            if line.startswith("# "):
                return line[2:].strip()[:120] or fallback
        return fallback or "Imported Skill"

    @staticmethod
    def description(markdown: str) -> str:
        for line in markdown.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                return clean[:240]
        return ""

    @staticmethod
    def summary(markdown: str) -> str:
        lines = [line.strip() for line in markdown.splitlines() if line.strip() and not line.startswith("#")]
        return " ".join(lines)[:500]

    @staticmethod
    def asset_paths(root: Path) -> list[str]:
        paths: list[str] = []
        for folder in ("assets", "templates", "examples"):
            base = root / folder
            if not base.exists():
                continue
            for child in base.rglob("*"):
                if child.is_file():
                    paths.append(child.relative_to(root).as_posix())
        return sorted(paths)
