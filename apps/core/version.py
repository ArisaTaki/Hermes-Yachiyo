"""Hermes-Yachiyo application version helpers."""

from __future__ import annotations

import subprocess
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_PACKAGE_NAME = "hermes-yachiyo"
_FALLBACK_VERSION = "0.1.0"


def project_root() -> Path:
    """Return the repository root for source checkouts."""
    return Path(__file__).resolve().parents[2]


def get_base_version() -> str:
    """Read the package version from installed metadata or pyproject.toml."""
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        pass

    pyproject = project_root() / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return _FALLBACK_VERSION
    project = data.get("project")
    if not isinstance(project, dict):
        return _FALLBACK_VERSION
    value = project.get("version")
    return str(value or _FALLBACK_VERSION)


def get_git_revision() -> str:
    """Return the current git short sha when running from a checkout."""
    root = project_root()
    if not (root / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_app_version(*, include_git: bool = True) -> str:
    """Return the visible Hermes-Yachiyo version.

    Source checkouts expose ``<package-version>+<git-sha>`` so users can tell
    exactly which local build is running. Packaged releases still work without
    a git checkout and fall back to the package version.
    """
    base = get_base_version()
    if not include_git:
        return base
    revision = get_git_revision()
    return f"{base}+{revision}" if revision else base
