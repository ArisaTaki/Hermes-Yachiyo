"""Build-channel helpers shared by backend runtime guards."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

APP_BUILD_METADATA_FILE = "oha-yachiyo-build.json"
RELEASE_LIKE_CHANNELS = {"release", "alpha", "stable"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_packaged_build() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", ""))


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def build_metadata_search_paths() -> list[Path]:
    paths: list[Path] = []
    meipass = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if meipass:
        root = Path(meipass)
        paths.extend(
            [
                root / "apps" / "frontend" / "public" / APP_BUILD_METADATA_FILE,
                root / APP_BUILD_METADATA_FILE,
            ]
        )
    if is_packaged_build():
        exe_dir = Path(sys.executable).resolve().parent
        paths.extend(
            [
                exe_dir / APP_BUILD_METADATA_FILE,
                exe_dir / "resources" / APP_BUILD_METADATA_FILE,
                exe_dir / "resources" / "app" / "dist" / APP_BUILD_METADATA_FILE,
            ]
        )
    override = os.getenv("OHA_YACHIYO_BUILD_METADATA", "").strip()
    if override:
        paths.append(Path(override).expanduser())
    root = project_root()
    paths.extend(
        [
            root / "apps" / "frontend" / "public" / APP_BUILD_METADATA_FILE,
            root / "dist" / APP_BUILD_METADATA_FILE,
        ]
    )
    return _dedupe(paths)


def load_build_metadata() -> dict[str, Any]:
    for path in build_metadata_search_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def build_channel() -> str:
    metadata = load_build_metadata()
    channel = str(metadata.get("channel") or "").strip().lower()
    return channel or os.getenv("OHA_YACHIYO_BUILD_CHANNEL", "").strip().lower()


def is_release_like_build() -> bool:
    channels = {
        build_channel(),
        os.getenv("OHA_YACHIYO_BUILD_CHANNEL", "").strip().lower(),
    }
    if channels & RELEASE_LIKE_CHANNELS:
        return True
    if os.getenv("OHA_YACHIYO_RELEASE_BUILD", "").strip() == "1":
        return True
    if os.getenv("OHA_YACHIYO_ALPHA_BUILD", "").strip() == "1":
        return True
    return False


def development_features_enabled() -> bool:
    if os.getenv("OHA_YACHIYO_DEV", "").strip() != "1":
        return False
    if is_release_like_build() or is_packaged_build():
        return False
    if os.getenv("OHA_YACHIYO_PACKAGED_BUILD", "").strip() == "1":
        return False
    return True
