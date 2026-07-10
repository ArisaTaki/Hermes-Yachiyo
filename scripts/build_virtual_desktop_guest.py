"""Build standalone macOS virtual desktop components with PyInstaller."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "packaging" / "virtual_desktop_guest_entry.py"
BRIDGE_ENTRYPOINT = ROOT / "packaging" / "virtual_desktop_ssh_bridge_entry.py"
DIST_DIR = ROOT / "dist" / "desktop-provider"
BUILD_DIR = ROOT / "build" / "pyinstaller-desktop-provider"
BRIDGE_BUILD_DIR = ROOT / "build" / "pyinstaller-desktop-provider-bridge"
OUTPUT_NAME = (
    "oha-yachiyo-desktop-provider.exe"
    if os.name == "nt"
    else "oha-yachiyo-desktop-provider"
)
BRIDGE_OUTPUT_NAME = (
    "oha-yachiyo-virtual-desktop-bridge.exe"
    if os.name == "nt"
    else "oha-yachiyo-virtual-desktop-bridge"
)


def build_virtual_desktop_guest(clean: bool = False) -> Path:
    if clean:
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DIST_DIR / OUTPUT_NAME
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "oha-yachiyo-desktop-provider",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--exclude-module",
        "fastapi",
        "--exclude-module",
        "uvicorn",
        "--exclude-module",
        "pytest",
        str(ENTRYPOINT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if not output_path.exists():
        raise FileNotFoundError(f"PyInstaller did not create {output_path}")
    return output_path


def build_virtual_desktop_ssh_bridge(clean: bool = False) -> Path:
    if clean:
        shutil.rmtree(BRIDGE_BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DIST_DIR / BRIDGE_OUTPUT_NAME
    if clean:
        output_path.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "oha-yachiyo-virtual-desktop-bridge",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BRIDGE_BUILD_DIR),
        "--specpath",
        str(BRIDGE_BUILD_DIR),
        "--exclude-module",
        "fastapi",
        "--exclude-module",
        "uvicorn",
        "--exclude-module",
        "pytest",
        str(BRIDGE_ENTRYPOINT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if not output_path.exists():
        raise FileNotFoundError(f"PyInstaller did not create {output_path}")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)
    print(build_virtual_desktop_guest(clean=args.clean))
    print(build_virtual_desktop_ssh_bridge(clean=args.clean))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
