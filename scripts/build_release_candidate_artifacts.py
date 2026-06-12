#!/usr/bin/env python3
"""Build local release-candidate artifacts without leaving tracked metadata dirty."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_METADATA_FILE = ROOT / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
BACKEND_ARTIFACT = ROOT / "dist" / "backend" / (
    "oha-yachiyo-backend.exe" if sys.platform.startswith("win") else "oha-yachiyo-backend"
)
ELECTRON_DIST_DIR = ROOT / "dist" / "electron"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _restore_metadata(original: bytes | None) -> None:
    if original is None:
        try:
            BUILD_METADATA_FILE.unlink()
        except FileNotFoundError:
            pass
        return
    BUILD_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUILD_METADATA_FILE.write_bytes(original)


def _latest_dmg_artifact() -> Path:
    candidates = sorted(
        ELECTRON_DIST_DIR.glob("Oha-Yachiyo-*-*.dmg"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return ELECTRON_DIST_DIR / "Oha-Yachiyo-0.4.0-arm64.dmg"


def build_release_candidate_artifacts(
    *,
    channel: str,
    repository: str | None = None,
    clean_backend: bool = True,
    built_at: str | None = None,
) -> dict[str, Path]:
    original_metadata = (
        BUILD_METADATA_FILE.read_bytes() if BUILD_METADATA_FILE.exists() else None
    )
    try:
        metadata_command = [
            sys.executable,
            "scripts/prepare_app_build_metadata.py",
            "--channel",
            channel,
        ]
        if repository:
            metadata_command.extend(["--repository", repository])
        if built_at:
            metadata_command.extend(["--built-at", built_at])
        _run(metadata_command)

        backend_command = [sys.executable, "scripts/build_backend.py"]
        if clean_backend:
            backend_command.append("--clean")
        _run(backend_command)

        _run(["npm", "--prefix", "apps/frontend", "run", "dist:mac"])
    finally:
        _restore_metadata(original_metadata)

    return {
        "backend": BACKEND_ARTIFACT,
        "dmg": _latest_dmg_artifact(),
        "metadata": BUILD_METADATA_FILE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel",
        default="experimental",
        choices=("stable", "alpha", "experimental"),
        help="Release channel metadata to embed in the packaged app.",
    )
    parser.add_argument(
        "--repository",
        help="GitHub owner/repo used for latest JSON URLs.",
    )
    parser.add_argument(
        "--built-at",
        help="Optional ISO timestamp for reproducible metadata tests.",
    )
    parser.add_argument(
        "--no-clean-backend",
        action="store_true",
        help="Do not pass --clean to scripts/build_backend.py.",
    )
    args = parser.parse_args(argv)
    artifacts = build_release_candidate_artifacts(
        channel=args.channel,
        repository=args.repository,
        clean_backend=not args.no_clean_backend,
        built_at=args.built_at,
    )
    print(f"packaged backend: {artifacts['backend']}")
    print(f"Electron DMG: {artifacts['dmg']}")
    print(f"restored tracked build metadata: {artifacts['metadata']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
