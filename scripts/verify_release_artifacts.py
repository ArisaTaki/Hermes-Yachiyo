"""Verify release-facing files do not point at the legacy product identity."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_OLD_CAPITALIZED = "Her" "mes-Yachiyo"
_OLD_LOWER = "her" "mes-yachiyo"
_OLD_ENV = "HER" "MES_YACHIYO"
_OLD_MODULE = "her" "mes_yachiyo"

FORBIDDEN_TOKENS: tuple[str, ...] = (
    _OLD_CAPITALIZED,
    _OLD_LOWER,
    _OLD_ENV,
    _OLD_MODULE,
    f"{_OLD_LOWER}-build.json",
)

DEFAULT_SCAN_PATHS: tuple[Path, ...] = (
    Path(".github/workflows/release-macos.yml"),
    Path(".github/workflows/release-tts-assets.yml"),
    Path("docs/release-packaging.md"),
    Path("apps/frontend/electron-builder.yml"),
    Path("scripts/build_backend.py"),
    Path("apps/frontend/public/oha-yachiyo-build.json"),
)

REQUIRED_FILES: tuple[Path, ...] = (
    Path("apps/frontend/public/oha-yachiyo-build.json"),
)

FORBIDDEN_FILES: tuple[Path, ...] = (
    Path(f"apps/frontend/public/{_OLD_LOWER}-build.json"),
)

RELEASE_SECURITY_CHANNELS: tuple[str, ...] = ("release", "alpha", "stable")
_BUILD_GUARD_ENV_KEYS: tuple[str, ...] = (
    "OHA_YACHIYO_DEV",
    "OHA_YACHIYO_BUILD_METADATA",
    "OHA_YACHIYO_BUILD_CHANNEL",
    "OHA_YACHIYO_RELEASE_BUILD",
    "OHA_YACHIYO_ALPHA_BUILD",
    "OHA_YACHIYO_PACKAGED_BUILD",
)


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str

    def format(self, root: Path = ROOT) -> str:
        try:
            path = self.path.resolve().relative_to(root.resolve())
        except ValueError:
            path = self.path
        return f"{path}: {self.message}"


def _resolve(root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _iter_files(root: Path, paths: Iterable[Path | str]) -> Iterable[Path]:
    for path in paths:
        resolved = _resolve(root, path)
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if child.is_file():
                    yield child
        else:
            yield resolved


def verify_release_artifacts(
    *,
    root: Path | str = ROOT,
    paths: Sequence[Path | str] | None = None,
    check_required_files: bool = True,
    check_release_security_guards: bool = True,
    allow_binary_targets: bool = False,
) -> list[Finding]:
    root_path = Path(root)
    findings: list[Finding] = []

    if check_required_files:
        for required in REQUIRED_FILES:
            path = _resolve(root_path, required)
            if not path.is_file():
                findings.append(Finding(path, "required release metadata file is missing"))
        for forbidden in FORBIDDEN_FILES:
            path = _resolve(root_path, forbidden)
            if path.exists():
                findings.append(Finding(path, "legacy release metadata filename must not exist"))

    scan_paths = paths if paths is not None else DEFAULT_SCAN_PATHS
    for path in _iter_files(root_path, scan_paths):
        if not path.exists():
            findings.append(Finding(path, "release verification target is missing"))
            continue
        try:
            content_bytes = path.read_bytes()
        except OSError as exc:
            findings.append(Finding(path, f"release verification target could not be read: {exc}"))
            continue
        for token in FORBIDDEN_TOKENS:
            if token.encode("utf-8") in content_bytes:
                findings.append(Finding(path, f"contains legacy product token {token!r}"))
        if not allow_binary_targets:
            try:
                content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                findings.append(Finding(path, "release verification target is not UTF-8 text"))

    if check_release_security_guards:
        findings.extend(_verify_release_security_guards(root_path))

    return findings


@contextmanager
def _release_guard_env(metadata_path: Path):
    saved = {key: os.environ.get(key) for key in _BUILD_GUARD_ENV_KEYS}
    try:
        for key in _BUILD_GUARD_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["OHA_YACHIYO_DEV"] = "1"
        os.environ["OHA_YACHIYO_BUILD_METADATA"] = str(metadata_path)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _verify_release_security_guards(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        from apps.bridge import server as bridge_server
        from apps.core import build_metadata
        from apps.shell import credential_store
    except Exception as exc:  # pragma: no cover - exercised only when import environment is broken.
        return [
            Finding(
                root / "apps" / "core" / "build_metadata.py",
                f"could not import release security guards: {exc.__class__.__name__}",
            )
        ]

    if tuple(getattr(bridge_server, "_DEBUG_ROUTE_MODULES", ())) != ():
        findings.append(
            Finding(
                root / "apps" / "bridge" / "server.py",
                "release builds must not register debug route modules",
            )
        )

    with tempfile.TemporaryDirectory(prefix="oha-release-guards-") as temp_dir:
        temp_root = Path(temp_dir)
        for channel in RELEASE_SECURITY_CHANNELS:
            metadata_path = temp_root / f"{channel}.json"
            metadata_path.write_text(json.dumps({"channel": channel}), encoding="utf-8")
            with _release_guard_env(metadata_path):
                if not build_metadata.is_release_like_build():
                    findings.append(
                        Finding(
                            root / "apps" / "core" / "build_metadata.py",
                            f"{channel} metadata must be treated as release-like",
                        )
                    )
                if build_metadata.development_features_enabled():
                    findings.append(
                        Finding(
                            root / "apps" / "core" / "build_metadata.py",
                            f"{channel} metadata must disable development features even when OHA_YACHIYO_DEV=1",
                        )
                    )
                if bridge_server.debug_routes_enabled():
                    findings.append(
                        Finding(
                            root / "apps" / "bridge" / "server.py",
                            f"{channel} metadata must disable debug routes even when OHA_YACHIYO_DEV=1",
                        )
                    )
                if credential_store.development_credential_fallback_enabled():
                    findings.append(
                        Finding(
                            root / "apps" / "shell" / "credential_store.py",
                            f"{channel} metadata must disable development credential fallback",
                        )
                    )
                try:
                    store = credential_store.DevFileCredentialStore(temp_root / channel / "credentials.dev.json")
                except credential_store.CredentialStoreError:
                    continue
                else:
                    store.close()
                    findings.append(
                        Finding(
                            root / "apps" / "shell" / "credential_store.py",
                            f"{channel} metadata must not allow DevFileCredentialStore",
                        )
                    )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Oha-Yachiyo release-facing files are not using legacy product identifiers "
            "and release-like builds keep development-only guards disabled."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to scan. Defaults to release-facing project files.",
    )
    parser.add_argument(
        "--allow-binary",
        action="store_true",
        help="Allow binary artifact targets and scan their raw bytes for legacy product tokens.",
    )
    args = parser.parse_args(argv)

    findings = verify_release_artifacts(paths=args.paths or None, allow_binary_targets=args.allow_binary)
    if not findings:
        print("release artifact verification passed")
        return 0

    print("release artifact verification failed:")
    for finding in findings:
        print(f"- {finding.format()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
