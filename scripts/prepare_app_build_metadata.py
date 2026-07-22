#!/usr/bin/env python3
"""Write app build metadata for local and CI release-candidate builds."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.app_version import read_product_version
from scripts.release_integrity import (
    SOURCE_TREE_FINGERPRINT_RE,
    capture_source_tree_provenance,
)

DEFAULT_OUTPUT = ROOT / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
CHANNEL_CHOICES = ("stable", "alpha", "experimental")


def _git_output(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def default_source_branch() -> str:
    env_branch = os.getenv("GITHUB_REF_NAME", "").strip()
    if env_branch:
        return env_branch
    branch = _git_output(["rev-parse", "--abbrev-ref", "HEAD"])
    return branch if branch and branch != "HEAD" else "local"


def default_commit() -> str:
    return os.getenv("GITHUB_SHA", "").strip() or _git_output(["rev-parse", "HEAD"]) or "dev"


def default_channel(source_branch: str) -> str:
    if source_branch == "main":
        return "stable"
    if source_branch == "alpha":
        return "alpha"
    return "experimental"


def latest_branch_for_channel(channel: str) -> str:
    if channel == "stable":
        return "main"
    if channel == "alpha":
        return "alpha"
    return "oha-develop"


def build_metadata(
    *,
    channel: str,
    source_branch: str,
    version: str,
    commit: str,
    build_number: int,
    run_number: int,
    repository: str,
    built_at: str,
    dirty: bool,
    source_tree_fingerprint: str,
) -> dict[str, Any]:
    latest_branch = latest_branch_for_channel(channel)
    short_commit = commit[:7] if commit and commit != "dev" else "dev"
    return {
        "name": "Oha-Yachiyo",
        "channel": channel,
        "branch": latest_branch,
        "source_branch": source_branch,
        "version": version,
        "base_version": version,
        "commit": commit,
        "short_commit": short_commit,
        "build_number": build_number,
        "run_number": run_number,
        "repository": repository,
        "latest_json_url": (
            f"https://github.com/{repository}/releases/download/"
            f"{latest_branch}-latest/Oha-Yachiyo-{latest_branch}-latest.json"
        ),
        "built_at": built_at,
        "dirty": dirty,
        "source_tree_fingerprint": source_tree_fingerprint,
        "release_publishable": not dirty,
    }


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--channel", choices=CHANNEL_CHOICES)
    parser.add_argument("--source-branch")
    parser.add_argument("--commit")
    parser.add_argument("--build-number", type=int)
    parser.add_argument("--run-number", type=int)
    parser.add_argument("--repository")
    parser.add_argument("--built-at")
    parser.add_argument("--source-tree-fingerprint")
    source_state = parser.add_mutually_exclusive_group()
    source_state.add_argument("--source-dirty", dest="source_dirty", action="store_true")
    source_state.add_argument("--source-clean", dest="source_dirty", action="store_false")
    parser.set_defaults(source_dirty=None)
    args = parser.parse_args(argv)

    source_branch = args.source_branch or default_source_branch()
    channel = args.channel or default_channel(source_branch)
    commit = args.commit or default_commit()
    version = read_product_version()
    build_number = args.build_number
    if build_number is None:
        build_number = _env_int("GITHUB_RUN_NUMBER", 0)
    run_number = args.run_number
    if run_number is None:
        run_number = _env_int("GITHUB_RUN_NUMBER", build_number)
    repository = args.repository or os.getenv("GITHUB_REPOSITORY", "").strip() or "local/oha-yachiyo"
    built_at = args.built_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if (args.source_tree_fingerprint is None) != (args.source_dirty is None):
        parser.error(
            "--source-tree-fingerprint must be paired with --source-clean or --source-dirty"
        )
    if args.source_tree_fingerprint is None:
        provenance = capture_source_tree_provenance(ROOT)
        if commit.lower() != provenance.commit:
            parser.error(
                "build metadata commit must match the captured source provenance HEAD"
            )
        source_tree_fingerprint = provenance.source_tree_fingerprint
        source_dirty = provenance.dirty
    else:
        source_tree_fingerprint = args.source_tree_fingerprint.strip().lower()
        source_dirty = bool(args.source_dirty)
    if not SOURCE_TREE_FINGERPRINT_RE.fullmatch(source_tree_fingerprint):
        parser.error("--source-tree-fingerprint must be sha256 followed by 64 lowercase hex digits")

    metadata = build_metadata(
        channel=channel,
        source_branch=source_branch,
        version=version,
        commit=commit,
        build_number=build_number,
        run_number=run_number,
        repository=repository,
        built_at=built_at,
        dirty=source_dirty,
        source_tree_fingerprint=source_tree_fingerprint,
    )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    write_metadata(output, metadata)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
