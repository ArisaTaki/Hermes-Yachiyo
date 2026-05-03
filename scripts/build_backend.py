"""Build the packaged Hermes-Yachiyo backend executable with PyInstaller."""

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


def _data_separator() -> str:
    return ";" if os.name == "nt" else ":"


def build_backend(clean: bool = False) -> Path:
    if clean:
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    output_name = "hermes-yachiyo-backend.exe" if os.name == "nt" else "hermes-yachiyo-backend"
    output_path = DIST_DIR / output_name
    data_arg = f"{ASSETS_DIR}{_data_separator()}apps/shell/assets"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "hermes-yachiyo-backend",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--add-data",
        data_arg,
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ENTRYPOINT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if not output_path.exists():
        raise FileNotFoundError(f"PyInstaller did not create {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Hermes-Yachiyo packaged backend.")
    parser.add_argument("--clean", action="store_true", help="Remove old backend build output first.")
    args = parser.parse_args()
    output_path = build_backend(clean=args.clean)
    print(output_path)


if __name__ == "__main__":
    main()
