"""Build the packaged oha-yachiyo backend executable with PyInstaller."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "packaging" / "backend_entry.py"
DIST_DIR = ROOT / "dist" / "backend"
BUILD_DIR = ROOT / "build" / "pyinstaller"
ASSETS_DIR = ROOT / "apps" / "shell" / "assets"
BUILD_METADATA_FILE = ROOT / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
PYINSTALLER_HOOKS_DIR = ROOT / "packaging" / "pyinstaller_hooks"
PYINSTALLER_EXCLUDED_MODULES = [
    "gunicorn",
    "httptools",
    "uvicorn.loops.auto",
    "uvicorn.loops.uvloop",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.websockets_sansio_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.workers",
    "uvloop",
    "watchfiles",
    "websockets",
    "wsproto",
]


def _data_separator() -> str:
    return ";" if os.name == "nt" else ":"


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path, ignore_errors=True)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _publish_staged_bundle(staging_bundle_dir: Path) -> None:
    """Publish the executable and its runtime sidecars as one recoverable unit."""

    pending_bundle_dir = DIST_DIR.parent / f".{DIST_DIR.name}-staging"
    backup_bundle_dir = DIST_DIR.parent / f".{DIST_DIR.name}-backup"

    # Recover from an interruption between moving the previous bundle aside and
    # publishing its replacement. If the replacement already won, the backup is
    # stale and can be removed.
    if not _path_exists(DIST_DIR) and _path_exists(backup_bundle_dir):
        backup_bundle_dir.replace(DIST_DIR)
    elif _path_exists(DIST_DIR):
        _remove_path(backup_bundle_dir)

    _remove_path(pending_bundle_dir)
    shutil.copytree(staging_bundle_dir, pending_bundle_dir, symlinks=True)

    had_previous_bundle = _path_exists(DIST_DIR)
    if had_previous_bundle:
        DIST_DIR.replace(backup_bundle_dir)
    try:
        pending_bundle_dir.replace(DIST_DIR)
    except BaseException:
        if (
            had_previous_bundle
            and not _path_exists(DIST_DIR)
            and _path_exists(backup_bundle_dir)
        ):
            backup_bundle_dir.replace(DIST_DIR)
        _remove_path(pending_bundle_dir)
        raise
    else:
        _remove_path(backup_bundle_dir)


def build_backend(clean: bool = False) -> Path:
    DIST_DIR.parent.mkdir(parents=True, exist_ok=True)
    if clean:
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    output_name = "oha-yachiyo-backend.exe" if os.name == "nt" else "oha-yachiyo-backend"
    output_path = DIST_DIR / output_name
    staging_dist_dir = BUILD_DIR / "dist"
    staging_bundle_dir = staging_dist_dir / "oha-yachiyo-backend"
    staging_output_path = staging_bundle_dir / output_name
    staging_runtime_dir = staging_bundle_dir / "runtime"
    data_args = [
        f"{ASSETS_DIR}{_data_separator()}apps/shell/assets",
    ]
    if BUILD_METADATA_FILE.exists():
        data_args.append(
            f"{BUILD_METADATA_FILE}{_data_separator()}apps/frontend/public"
        )

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--contents-directory",
        "runtime",
        "--name",
        "oha-yachiyo-backend",
        "--distpath",
        str(staging_dist_dir),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--additional-hooks-dir",
        str(PYINSTALLER_HOOKS_DIR),
        "--collect-data",
        "certifi",
    ]
    for data_arg in data_args:
        command.extend(["--add-data", data_arg])
    for module_name in PYINSTALLER_EXCLUDED_MODULES:
        command.extend(["--exclude-module", module_name])
    command.extend([
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ENTRYPOINT),
    ])
    subprocess.run(command, cwd=ROOT, check=True)
    if not staging_output_path.exists():
        raise FileNotFoundError(f"PyInstaller did not create {staging_output_path}")
    if not staging_runtime_dir.is_dir():
        raise FileNotFoundError(f"PyInstaller did not create {staging_runtime_dir}")

    _publish_staged_bundle(staging_bundle_dir)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Oha-Yachiyo packaged backend.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove old backend build intermediates before rebuilding.",
    )
    args = parser.parse_args()
    output_path = build_backend(clean=args.clean)
    print(output_path)


if __name__ == "__main__":
    main()
