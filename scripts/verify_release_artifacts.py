"""Verify release-facing files do not point at the legacy product identity."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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
PACKAGING_CONFIG_FILE = Path("apps/frontend/electron-builder.yml")
TRACKED_GENERATED_PATHS: tuple[str, ...] = (
    "apps/frontend/.vite",
    "apps/frontend/dist",
    "apps/frontend/dist-electron",
)
PACKAGING_CONFIG_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "npmRebuild: false",
        "macOS release packaging must disable local native dependency rebuilds",
    ),
    (
        "- '!node_modules/node-pty/build/**'",
        "macOS release packaging must exclude rebuilt node-pty native artifacts",
    ),
    (
        "- '!**/.vite/**'",
        "macOS release packaging must exclude Vite cache artifacts",
    ),
    (
        "hardenedRuntime: true",
        "macOS release packaging must enable hardened runtime for the app bundle",
    ),
    (
        "entitlements: ../../packaging/entitlements.mac.plist",
        "macOS release packaging must use the checked-in app entitlements",
    ),
    (
        "entitlementsInherit: ../../packaging/entitlements.mac.plist",
        "macOS release packaging must use the checked-in inherited entitlements",
    ),
    (
        "NSAppleEventsUsageDescription",
        "macOS release packaging must include Apple Events permission copy",
    ),
    (
        "NSDocumentsFolderUsageDescription",
        "macOS release packaging must include Documents folder permission copy",
    ),
    (
        "NSDownloadsFolderUsageDescription",
        "macOS release packaging must include Downloads folder permission copy",
    ),
    (
        "NSMicrophoneUsageDescription",
        "macOS release packaging must include microphone permission copy",
    ),
)
RELEASE_WORKFLOW_FILE = Path(".github/workflows/release-macos.yml")
MACOS_SIGNING_SCRIPT_FILE = Path("scripts/build_macos_self_signed_dmg.sh")
MACOS_ENTITLEMENTS_FILE = Path("packaging/entitlements.mac.plist")
MACOS_SIGNING_SCRIPT_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --config electron-builder.yml --mac dir",
        "macOS signing script must build an unsigned app directory before signing",
    ),
    (
        "--options runtime",
        "macOS signing script must sign the app with hardened runtime options",
    ),
    (
        '--entitlements "${ENTITLEMENTS}"',
        "macOS signing script must apply the checked-in entitlements",
    ),
    (
        'codesign --verify --deep --strict --verbose=2 "${APP_PATH}"',
        "macOS signing script must verify the signed app bundle",
    ),
    (
        "hdiutil create",
        "macOS signing script must create the unsigned DMG from the signed app bundle",
    ),
)
MACOS_ENTITLEMENTS_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "com.apple.security.cs.allow-jit",
        "macOS entitlements must allow JIT for the Electron runtime",
    ),
    (
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "macOS entitlements must allow unsigned executable memory for Electron",
    ),
    (
        "com.apple.security.cs.disable-library-validation",
        "macOS entitlements must disable library validation for packaged native modules",
    ),
)
RELEASE_WORKFLOW_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "Verify release-facing product identity and security guards",
        "macOS release workflow must run the release verifier before dependency installation",
    ),
    (
        "Import macOS self-signing certificate",
        "macOS release workflow must import the signing certificate before building the DMG",
    ),
    (
        "MACOS_SIGNING_ENABLED",
        "macOS release workflow must pass signing state into the Electron DMG build",
    ),
    (
        "scripts/build_macos_self_signed_dmg.sh",
        "macOS release workflow must use the signed app build path when signing is configured",
    ),
    (
        "首次启动应用时仍会显示未知开发者 / Gatekeeper 提示",
        "macOS release workflow must document Gatekeeper first-launch handling",
    ),
    (
        "未使用 Apple Developer ID 签名或 notarization",
        "macOS release workflow must document current notarization status",
    ),
    (
        "屏幕录制权限",
        "macOS release workflow must document screen recording permission setup",
    ),
    (
        "package_scan_paths=(dist/backend)",
        "macOS release workflow must scan the packaged backend binary",
    ),
    (
        "find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'",
        "macOS release workflow must discover packaged app resource directories",
    ),
    (
        'python scripts/verify_release_artifacts.py --allow-binary "${package_scan_paths[@]}"',
        "macOS release workflow must binary-scan packaged app resources",
    ),
    (
        "python scripts/verify_release_artifacts.py --allow-binary release",
        "macOS release workflow must binary-scan final release artifacts",
    ),
    (
        'cp "${dmg_files[0]}" "release/${VERSIONED_DMG}"',
        "macOS release workflow must stage the versioned DMG for final artifact scanning",
    ),
    (
        'cp "${dmg_files[0]}" "release/${LATEST_DMG}"',
        "macOS release workflow must stage the latest DMG for final artifact scanning",
    ),
    (
        'VERSIONED_SHA256="$(shasum -a 256 "release/${VERSIONED_DMG}"',
        "macOS release workflow must compute a SHA256 checksum for the versioned DMG",
    ),
    (
        "release/*.json",
        "macOS release workflow must upload release metadata JSON artifacts",
    ),
    (
        "release/*.dmg",
        "macOS release workflow must upload release DMG artifacts",
    ),
    (
        "release/*.sha256",
        "macOS release workflow must upload release checksum artifacts",
    ),
    (
        '"release/${LATEST_JSON}"',
        "macOS release workflow must publish latest channel JSON metadata",
    ),
)
RELEASE_WORKFLOW_METADATA_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        'LATEST_SHA256="$(shasum -a 256 "release/${LATEST_DMG}"',
        "macOS release workflow must compute a SHA256 checksum for the latest DMG",
    ),
    (
        '"version": "${RELEASE_VERSION}"',
        "macOS release workflow latest JSON must include the release version",
    ),
    (
        '"commit": "${GITHUB_SHA}"',
        "macOS release workflow latest JSON must include the source commit",
    ),
    (
        '"build_number": ${BUILD_NUMBER}',
        "macOS release workflow latest JSON must include the build number",
    ),
    (
        '"dmg_name": "${LATEST_DMG}"',
        "macOS release workflow latest JSON must include the DMG filename",
    ),
    (
        '"sha256": "${LATEST_SHA256}"',
        "macOS release workflow latest JSON must include the latest DMG SHA256",
    ),
    (
        '"download_url": "https://github.com/${GITHUB_REPOSITORY}/releases/download/${LATEST_TAG}/${LATEST_DMG}"',
        "macOS release workflow latest JSON must include the DMG download URL",
    ),
)
RELEASE_WORKFLOW_SMOKE_TEST_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "Run smoke tests",
        "macOS release workflow must run smoke tests before packaging",
    ),
    (
        "tests/test_screenshot.py",
        "macOS release workflow smoke tests must cover screenshot behavior",
    ),
    (
        "tests/test_proactive.py",
        "macOS release workflow smoke tests must cover proactive care",
    ),
    (
        "tests/test_chat_session.py",
        "macOS release workflow smoke tests must cover ChatSession persistence",
    ),
    (
        "tests/test_chat_api.py",
        "macOS release workflow smoke tests must cover Chat API flows",
    ),
    (
        "tests/test_ui_bridge_routes.py",
        "macOS release workflow smoke tests must cover mature UI bridge routes",
    ),
    (
        "tests/test_frontend_feature_preservation.py",
        "macOS release workflow smoke tests must cover mature frontend feature preservation",
    ),
    (
        "tests/test_ui_mature_flow_contract.py",
        "macOS release workflow smoke tests must cover mature UI flow contracts",
    ),
    (
        "tests/test_bridge_server.py::test_chat_message_image_attachment_http_roundtrip_maps_idempotency_and_file_response",
        "macOS release workflow smoke tests must cover Chat image HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_agent_run_http_routes_roundtrip_approval_detail_and_replay",
        "macOS release workflow smoke tests must cover Agent approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_approval_node_http_roundtrip_approve_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_run_http_routes_roundtrip_child_approval_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow child approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_rerun_http_roundtrip_detail_artifact_and_replay",
        "macOS release workflow smoke tests must cover Workflow rerun artifact replay HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_chat_group_dispatch_bridge_route_runs_native_summary",
        "macOS release workflow smoke tests must cover group chat Native summary flow",
    ),
    (
        "tests/test_bridge_server.py::test_chat_delegated_summary_bridge_route_runs_native_followup",
        "macOS release workflow smoke tests must cover auto delegation Native summary flow",
    ),
    (
        "tests/test_tts.py",
        "macOS release workflow smoke tests must cover manual TTS",
    ),
    (
        "tests/test_mode_settings.py",
        "macOS release workflow smoke tests must cover Live2D and mode settings",
    ),
)
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
        findings.extend(_verify_tracked_generated_artifacts(root_path))
        findings.extend(_verify_release_packaging_guards(root_path))
        findings.extend(_verify_macos_signing_guards(root_path))
        findings.extend(_verify_release_workflow_guards(root_path))

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


def _verify_tracked_generated_artifacts(root: Path) -> list[Finding]:
    if not (root / ".git").exists():
        return []
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", *TRACKED_GENERATED_PATHS],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return [Finding(root / ".git", f"could not inspect tracked generated artifacts: {exc}")]
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited with {completed.returncode}"
        return [Finding(root / ".git", f"could not inspect tracked generated artifacts: {detail}")]
    tracked_paths = [path.strip() for path in completed.stdout.splitlines() if path.strip()]
    return [
        Finding(root / path, "generated frontend build artifacts must not be tracked")
        for path in tracked_paths
    ]


def _verify_release_packaging_guards(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    config_path = _resolve(root, PACKAGING_CONFIG_FILE)
    try:
        config = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(config_path, f"could not read macOS release packaging config: {exc}")]

    for required_text, message in PACKAGING_CONFIG_REQUIRED_TEXT:
        if required_text not in config:
            findings.append(Finding(config_path, message))
    return findings


def _verify_macos_signing_guards(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    script_path = _resolve(root, MACOS_SIGNING_SCRIPT_FILE)
    try:
        script = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        findings.append(Finding(script_path, f"could not read macOS signing script: {exc}"))
    else:
        for required_text, message in MACOS_SIGNING_SCRIPT_REQUIRED_TEXT:
            if required_text not in script:
                findings.append(Finding(script_path, message))

    entitlements_path = _resolve(root, MACOS_ENTITLEMENTS_FILE)
    try:
        entitlements = entitlements_path.read_text(encoding="utf-8")
    except OSError as exc:
        findings.append(Finding(entitlements_path, f"could not read macOS entitlements: {exc}"))
    else:
        for required_text, message in MACOS_ENTITLEMENTS_REQUIRED_TEXT:
            if required_text not in entitlements:
                findings.append(Finding(entitlements_path, message))
    return findings


def _verify_release_workflow_guards(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    workflow_path = _resolve(root, RELEASE_WORKFLOW_FILE)
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(workflow_path, f"could not read macOS release workflow: {exc}")]

    for required_text, message in RELEASE_WORKFLOW_REQUIRED_TEXT:
        if required_text not in workflow:
            findings.append(Finding(workflow_path, message))
    for required_text, message in RELEASE_WORKFLOW_METADATA_REQUIRED_TEXT:
        if required_text not in workflow:
            findings.append(Finding(workflow_path, message))
    for required_text, message in RELEASE_WORKFLOW_SMOKE_TEST_REQUIRED_TEXT:
        if required_text not in workflow:
            findings.append(Finding(workflow_path, message))

    preinstall_guard = workflow.find("Verify release-facing product identity and security guards")
    install_deps = workflow.find("Install Python dependencies")
    if preinstall_guard < 0:
        return findings
    if install_deps < 0 or preinstall_guard > install_deps:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must verify release guards before installing dependencies",
            )
        )
    signing_import = workflow.find("Import macOS self-signing certificate")
    smoke_tests = workflow.find("Run smoke tests")
    build_backend = workflow.find("Build packaged backend")
    build_dmg = workflow.find("Build Electron DMG")
    if (
        smoke_tests < 0
        or build_backend < 0
        or build_dmg < 0
        or smoke_tests > build_backend
        or smoke_tests > build_dmg
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must run smoke tests before packaged backend and DMG builds",
            )
        )
    if signing_import >= 0 and build_dmg >= 0 and signing_import > build_dmg:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must import signing material before building the DMG",
            )
        )
    prepare_release = workflow.find("Prepare release metadata")
    verify_release = workflow.find("Verify packaged release artifacts")
    if prepare_release < 0 or verify_release < 0 or verify_release < prepare_release:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must verify release artifacts after preparing release metadata",
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
