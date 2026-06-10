#!/usr/bin/env python3
"""Manage the Oha-Yachiyo product version across Python and Electron files."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_product_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        raise SystemExit("pyproject.toml does not contain [project]")
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("pyproject.toml project.version is missing")
    return version.strip()


def replace_text(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"expected one version match in {path}")
    path.write_text(next_text, encoding="utf-8")


def replace_text_all(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    next_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count < 1:
        raise SystemExit(f"expected at least one version match in {path}")
    path.write_text(next_text, encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_product_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"version must be X.Y.Z, got {version!r}")

    replace_text(
        ROOT / "pyproject.toml",
        r'(^version\s*=\s*)"[^"]+"',
        rf'\g<1>"{version}"',
    )
    replace_text(
        ROOT / "apps/core/version.py",
        r'(_FALLBACK_VERSION\s*=\s*)"[^"]+"',
        rf'\g<1>"{version}"',
    )
    replace_text(
        ROOT / "packages/protocol/schemas.py",
        r'(version:\s*str\s*=\s*)"[^"]+"',
        rf'\g<1>"{version}"',
    )
    replace_text_all(
        ROOT / "apps/shell/main_api.py",
        r'status\.get\("version", "[^"]+"\)',
        f'status.get("version", "{version}")',
    )
    replace_text_all(
        ROOT / "apps/shell/main_api.py",
        r'get_status\(\)\.get\("version"\) or "[^"]+"',
        f'get_status().get("version") or "{version}"',
    )
    replace_text_all(
        ROOT / "apps/frontend/src/views/ModeSettingsView.tsx",
        r"payload\?\.app\?\.version \|\| '[^']+'",
        f"payload?.app?.version || '{version}'",
    )

    package_path = ROOT / "apps/frontend/package.json"
    package = read_json(package_path)
    package["version"] = version
    write_json(package_path, package)

    lock_path = ROOT / "apps/frontend/package-lock.json"
    lock = read_json(lock_path)
    lock["version"] = version
    root_package = lock.get("packages", {}).get("")
    if isinstance(root_package, dict):
        root_package["version"] = version
    write_json(lock_path, lock)

    build_path = ROOT / "apps/frontend/public/oha-yachiyo-build.json"
    if build_path.exists():
        build = read_json(build_path)
        build["version"] = f"{version}-dev"
        build["base_version"] = version
        write_json(build_path, build)


def check_product_version() -> None:
    version = read_product_version()
    expected = {
        "apps/frontend/package.json": read_json(ROOT / "apps/frontend/package.json").get("version"),
        "apps/frontend/package-lock.json": read_json(ROOT / "apps/frontend/package-lock.json").get("version"),
        "apps/frontend/package-lock.json packages.\"\"": read_json(ROOT / "apps/frontend/package-lock.json").get("packages", {}).get("", {}).get("version"),
    }
    failures = [
        f"{label}={value!r}, expected {version!r}"
        for label, value in expected.items()
        if value != version
    ]
    fallback_text = (ROOT / "apps/core/version.py").read_text(encoding="utf-8")
    if f'_FALLBACK_VERSION = "{version}"' not in fallback_text:
        failures.append("apps/core/version.py fallback version is out of sync")
    protocol_text = (ROOT / "packages/protocol/schemas.py").read_text(encoding="utf-8")
    if f'version: str = "{version}"' not in protocol_text:
        failures.append("packages/protocol/schemas.py status response version is out of sync")
    main_api_text = (ROOT / "apps/shell/main_api.py").read_text(encoding="utf-8")
    bad_main_api_status_fallbacks = [
        value
        for value in re.findall(r'status\.get\("version", "([^"]+)"\)', main_api_text)
        if value != version
    ]
    if bad_main_api_status_fallbacks:
        failures.append("apps/shell/main_api.py status fallback version is out of sync")
    bad_main_api_update_fallbacks = [
        value
        for value in re.findall(r'get_status\(\)\.get\("version"\) or "([^"]+)"', main_api_text)
        if value != version
    ]
    if bad_main_api_update_fallbacks:
        failures.append("apps/shell/main_api.py update fallback version is out of sync")
    mode_settings_text = (ROOT / "apps/frontend/src/views/ModeSettingsView.tsx").read_text(encoding="utf-8")
    if f"payload?.app?.version || '{version}'" not in mode_settings_text:
        failures.append("apps/frontend/src/views/ModeSettingsView.tsx fallback version is out of sync")
    build_path = ROOT / "apps/frontend/public/oha-yachiyo-build.json"
    if build_path.exists():
        build = read_json(build_path)
        if build.get("base_version") != version:
            failures.append("apps/frontend/public/oha-yachiyo-build.json base_version is out of sync")
    if failures:
        raise SystemExit("\n".join(failures))
    print(version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("current", help="Print the product version from pyproject.toml.")
    subparsers.add_parser("check", help="Validate that mirrored version files match pyproject.toml.")
    set_parser = subparsers.add_parser("set", help="Set and sync the product version.")
    set_parser.add_argument("version", help="Product version in X.Y.Z format.")

    args = parser.parse_args()
    if args.command == "current":
        print(read_product_version())
        return 0
    if args.command == "check":
        check_product_version()
        return 0
    if args.command == "set":
        set_product_version(args.version)
        check_product_version()
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
