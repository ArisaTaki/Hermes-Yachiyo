"""Verify release-facing files do not point at the legacy product identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
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
_OLD_KERNEL_NAME = "Her" "mes"
_OLD_KERNEL_LOWER = "her" "mes"
_OLD_PROTOCOL_PRODUCT = "yachi" "yo"
_OLD_PROTOCOL_TITLE = "Yachi" "yo"
_LEGACY_KERNEL_TOKENS: tuple[str, ...] = (
    f"{_OLD_KERNEL_NAME}Runtime",
    f"{_OLD_KERNEL_LOWER}_runtime",
    f"{_OLD_KERNEL_NAME}Executor",
    f"{_OLD_KERNEL_NAME}UnavailableExecutor",
    f"{_OLD_KERNEL_NAME} CLI",
    f"{_OLD_KERNEL_NAME} stream",
    f"{_OLD_KERNEL_NAME} installer",
    f"{_OLD_KERNEL_NAME} setup",
    f"{_OLD_KERNEL_NAME} doctor",
    f"{_OLD_KERNEL_NAME} readiness",
    f"{_OLD_KERNEL_NAME} Agent",
    f"{_OLD_KERNEL_NAME} bridge",
    f"{_OLD_KERNEL_NAME} Bridge",
    f"{_OLD_KERNEL_NAME}Bridge",
    f"{_OLD_KERNEL_NAME}Capability",
    f"{_OLD_KERNEL_NAME} capability",
    f"{_OLD_KERNEL_LOWER}_setup",
    f"{_OLD_KERNEL_LOWER}_doctor",
    f"{_OLD_KERNEL_LOWER}_agent",
    f"{_OLD_KERNEL_LOWER}_capability",
    f"/ui/{_OLD_KERNEL_LOWER}",
    f"{_OLD_KERNEL_LOWER}/install",
    f"{_OLD_KERNEL_LOWER}/status",
    f"{_OLD_KERNEL_LOWER}/config",
    f"{_OLD_KERNEL_LOWER}_profile",
    f"{_OLD_KERNEL_LOWER}_provider",
    f"{_OLD_KERNEL_LOWER}_toolsets",
    f"{_OLD_KERNEL_LOWER} bridge",
    f"{_OLD_KERNEL_LOWER}_bridge",
    f"can_use_as_{_OLD_KERNEL_LOWER}",
    f"sync{_OLD_KERNEL_NAME}",
    f"include_{_OLD_KERNEL_LOWER}",
    f"INCLUDE_{_OLD_KERNEL_LOWER.upper()}",
    f"{_OLD_KERNEL_LOWER}_home",
    f"{_OLD_KERNEL_LOWER.upper()}_HOME",
    f"{_OLD_KERNEL_LOWER.upper()}_CONFIG",
    f"{_OLD_KERNEL_LOWER.upper()}_PROFILE",
    f"{_OLD_KERNEL_LOWER}_stream_bridge",
    f"{_OLD_KERNEL_LOWER}-bridge",
    f"{_OLD_KERNEL_LOWER}-setup",
    f"{_OLD_KERNEL_LOWER}-doctor",
    f"{_OLD_KERNEL_LOWER}-agent",
    f"{_OLD_KERNEL_LOWER}_cli",
    f"{_OLD_KERNEL_LOWER}-cli",
)
_LEGACY_PROTOCOL_TOKENS: tuple[str, ...] = (
    f"run_{_OLD_PROTOCOL_PRODUCT}",
    f"{_OLD_PROTOCOL_PRODUCT}_delegation",
    f"{_OLD_PROTOCOL_PRODUCT}_group_dispatch",
    f"{_OLD_PROTOCOL_PRODUCT}_only",
    f"{_OLD_PROTOCOL_PRODUCT.upper()}_ONLY",
    f"get_{_OLD_PROTOCOL_PRODUCT}_workspace_dir",
    f"{_OLD_PROTOCOL_PRODUCT}_workspace",
    f"{_OLD_PROTOCOL_PRODUCT}-workspace",
    f"{_OLD_PROTOCOL_PRODUCT}_agent",
    f"Runtime: {_OLD_PROTOCOL_TITLE} Agent Runtime",
    f".{_OLD_PROTOCOL_PRODUCT}_init",
    f"configs/{_OLD_PROTOCOL_PRODUCT}.json",
)

FORBIDDEN_TOKENS: tuple[str, ...] = (
    _OLD_CAPITALIZED,
    _OLD_LOWER,
    _OLD_ENV,
    _OLD_MODULE,
    f"{_OLD_LOWER}-build.json",
    *_LEGACY_KERNEL_TOKENS,
    *_LEGACY_PROTOCOL_TOKENS,
)

DEFAULT_SCAN_PATHS: tuple[Path, ...] = (
    Path(".github/workflows/release-macos.yml"),
    Path(".github/workflows/release-tts-assets.yml"),
    Path("docs/release-packaging.md"),
    Path("apps/frontend/electron-builder.yml"),
    Path("scripts/build_backend.py"),
    Path("scripts/prepare_app_build_metadata.py"),
    Path("scripts/verify_release_candidate.py"),
    Path("apps/frontend/public/oha-yachiyo-build.json"),
)

REQUIRED_FILES: tuple[Path, ...] = (
    Path("apps/frontend/public/oha-yachiyo-build.json"),
)

FORBIDDEN_FILES: tuple[Path, ...] = (
    Path(f"apps/frontend/public/{_OLD_LOWER}-build.json"),
)

RELEASE_SECURITY_CHANNELS: tuple[str, ...] = ("release", "alpha", "stable")
RELEASE_PACKAGING_DOC_FILE = Path("docs/release-packaging.md")
USER_FACING_RELEASE_DOC_REQUIRED_TEXT: tuple[tuple[Path, str, str], ...] = (
    (
        Path("README.md"),
        "未知开发者 / Gatekeeper",
        "README must document Gatekeeper first-launch handling",
    ),
    (
        Path("README.md"),
        "屏幕录制",
        "README must document macOS Screen Recording permission",
    ),
    (
        Path("docs/user-manual.md"),
        "未知开发者 / Gatekeeper",
        "user manual must document Gatekeeper first-launch handling",
    ),
    (
        Path("docs/user-manual.md"),
        "屏幕录制权限",
        "user manual must document macOS Screen Recording permission",
    ),
)
PACKAGING_CONFIG_FILE = Path("apps/frontend/electron-builder.yml")
PACKAGED_APP_OUTPUT_DIR = Path("dist/electron")
PACKAGED_APP_NAME = "Oha-Yachiyo.app"
PACKAGED_APP_IDENTIFIER = "io.github.arisataki.oha-yachiyo"
PACKAGED_BACKEND_RELATIVE_PATH = Path("Contents/Resources/backend/oha-yachiyo-backend")
PACKAGED_BACKEND_BUILD_METADATA_MARKER = b"apps/frontend/public/oha-yachiyo-build.json"
PACKAGED_ASAR_RELATIVE_PATH = Path("Contents/Resources/app.asar")
CHAT_IMAGE_ATTACHMENT_SMOKE_SCRIPT = Path("scripts/smoke_chat_image_attachment_ui.mjs")
PACKAGED_UI_SAMPLING_SMOKE_SCRIPT = Path("scripts/smoke_packaged_ui_sampling.mjs")
PACKAGED_CHAT_NATIVE_FILE_SMOKE_SCRIPT = Path("scripts/smoke_packaged_chat_native_file_upload.mjs")
CHAT_IMAGE_ATTACHMENT_SMOKE_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "DOM.setFileInputFiles",
        "Chat image Electron UI smoke must drive the hidden file input through CDP DOM.setFileInputFiles",
    ),
    (
        "selector: '[data-testid=\"chat-image-file-input\"]'",
        "Chat image Electron UI smoke must target the Chat image file input through CDP",
    ),
    (
        "files: filePaths",
        "Chat image Electron UI smoke must pass real filesystem image paths to the file input",
    ),
    (
        "smoke-image-cdp-fourth.svg",
        "Chat image Electron UI smoke must keep multi-image file input coverage",
    ),
    (
        "chooseChatImages: async ()",
        "Chat image Electron UI smoke must cover the desktop native image picker API path",
    ),
    (
        "chat desktop image picker should not click hidden file input",
        "Chat image Electron UI smoke must prove desktop image picker bypasses the hidden input",
    ),
)
PACKAGED_UI_SAMPLING_SMOKE_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "ROUTE_SAMPLES",
        "packaged UI sampling smoke must define route samples",
    ),
    (
        "--debug-port",
        "packaged UI sampling smoke must connect to the packaged app DevTools port",
    ),
    (
        "WebSocket",
        "packaged UI sampling smoke must use the DevTools websocket protocol",
    ),
    (
        '#/agents/workflows',
        "packaged UI sampling smoke must cover Workflow Studio",
    ),
    (
        '[data-testid="chat-composer-input"]',
        "packaged UI sampling smoke must cover Chat composer selectors",
    ),
    (
        '[data-testid="live2d-resource-settings"]',
        "packaged UI sampling smoke must cover Live2D settings selectors",
    ),
)
PACKAGED_CHAT_NATIVE_FILE_SMOKE_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "--app-executable",
        "packaged Chat native file smoke must launch the packaged app executable",
    ),
    (
        "OHA_YACHIYO_CHAT_IMAGE_PICKER_SMOKE_PATHS",
        "packaged Chat native file smoke must drive the desktop picker IPC with smoke file paths",
    ),
    (
        "chat-composer-image-attach-button",
        "packaged Chat native file smoke must click the Chat attach button",
    ),
    (
        "chat-message-attachment-item",
        "packaged Chat native file smoke must verify sent message attachments",
    ),
    (
        "chat-image-viewer-modal",
        "packaged Chat native file smoke must verify the image viewer",
    ),
    (
        "agent-run-detail",
        "packaged Chat native file smoke must verify Run Detail handoff",
    ),
)
ELECTRON_MAIN_CHAT_NATIVE_FILE_SMOKE_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "OHA_YACHIYO_DESKTOP_SMOKE_MODE",
        "Electron main must gate Chat native file smoke override behind explicit smoke mode",
    ),
    (
        "OHA_YACHIYO_CHAT_IMAGE_PICKER_SMOKE_PATHS",
        "Electron main must expose smoke-selected Chat image picker paths",
    ),
    (
        "chatImagePickerSmokePaths",
        "Electron main must isolate Chat image picker smoke path parsing",
    ),
)
ELECTRON_UI_SMOKE_RUNNER_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "def electron_ui_smoke_scripts",
        "Electron UI smoke runner must expose dynamic smoke script discovery",
    ),
    (
        "def run_electron_ui_smoke_report",
        "Electron UI smoke runner must expose reusable report generation",
    ),
    (
        'glob("smoke_*_ui.mjs")',
        "Electron UI smoke runner must discover every scripts/smoke_*_ui.mjs file",
    ),
    (
        'subprocess.run(["node", str(relative_script)]',
        "Electron UI smoke runner must execute discovered smoke scripts with node",
    ),
    (
        '"script_count"',
        "Electron UI smoke runner report must include script_count",
    ),
    (
        '"scripts"',
        "Electron UI smoke runner report must include per-script results",
    ),
    (
        '"--report-json"',
        "Electron UI smoke runner CLI must accept a report JSON output path",
    ),
)
RELEASE_LATEST_BRANCH_CHANNELS: dict[str, str] = {
    "main": "stable",
    "alpha": "alpha",
    "develop": "experimental",
}
RELEASE_LATEST_JSON_RE = re.compile(r"^Oha-Yachiyo-(?P<branch>main|alpha|develop)-latest\.json$")
RELEASE_LATEST_SIGNING_MODES = {"unsigned", "self-signed-app-unsigned-dmg"}
RELEASE_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
RELEASE_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
RELEASE_SHORT_SHA_RE = re.compile(r"^[0-9a-f]{7}$", re.IGNORECASE)
RELEASE_PUBLISHED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RELEASE_SOURCE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
PACKAGED_UI_E2E_REQUIRED_SELECTORS: tuple[str, ...] = (
    "chat-image-file-input",
    "chat-header-image-attach-button",
    "chat-composer-image-attach-button",
    "chat-composer-attachment-preview",
    "chat-composer-attachment-remove",
    "chat-message-attachment-item",
    "chat-image-viewer-backdrop",
    "chat-image-viewer-modal",
    "chat-image-viewer-stage",
    "chat-image-viewer-close",
    "chat-session-tab-groups",
    "chat-session-tab-create",
    "chat-group-settings",
    "chat-group-dialog",
    "chat-group-name-input",
    "chat-group-avatar-preview",
    "chat-group-avatar-select",
    "chat-group-avatar-file-input",
    "chat-group-avatar-clear",
    "chat-group-avatar-clear-secondary",
    "chat-group-agent-member-checkbox",
    "chat-group-dialog-submit",
    "chat-composer-input",
    "chat-composer-send",
    "chat-header-stop-button",
    "chat-composer-stop-button",
    "chat-message-copy",
    "chat-code-copy",
    "chat-message-summary-status",
    "chat-message-followup-status",
    "chat-message-activity-row",
    "chat-message-activity-open-run-detail",
    "activity-feed",
    "activity-search-input",
    "activity-list",
    "activity-row",
    "activity-row-open",
    "activity-detail-page",
    "activity-detail-summary",
    "activity-detail-body",
    "activity-detail-open-run",
    "activity-trace",
    "activity-trace-row",
    "activity-trace-expand",
    "activity-detail-delete",
    "confirm-dialog",
    "confirm-action",
    "diagnostics-status",
    "diagnostics-run-command",
    "diagnostics-output",
    "diagnostics-copy-output",
    "diagnostics-screen-probe",
    "diagnostics-screen-probe-card",
    "diagnostics-screen-probe-summary",
    "diagnostics-screen-probe-image",
    "mode-settings-status",
    "mode-settings-save",
    "live2d-resource-settings",
    "live2d-model-path-prepare",
    "live2d-archive-import",
    "live2d-open-assets-dir",
    "live2d-open-releases",
    "live2d-manual-model-path",
    "live2d-manual-archive-path",
    "live2d-model-state",
    "live2d-configured-path",
    "live2d-effective-path",
    "bubble-launcher-shell",
    "bubble-launcher-button",
    "bubble-launcher-summary",
    "bubble-launcher-status-label",
    "bubble-launcher-session-summary-probe",
    "bubble-launcher-recent-session",
    "live2d-launcher-shell",
    "live2d-launcher-stage",
    "live2d-launcher-preview-fallback",
    "live2d-launcher-reply-text",
    "live2d-launcher-latest-reply",
    "live2d-launcher-session-summary-probe",
    "live2d-launcher-recent-session",
    "live2d-launcher-quick-input",
    "live2d-launcher-quick-input-field",
    "live2d-launcher-quick-input-submit",
    "proactive-tts-settings",
    "proactive-tts-provider",
    "proactive-tts-status",
    "proactive-tts-runtime-status",
    "proactive-screen-permission-check",
    "proactive-test-run",
    "proactive-test-result",
    "tts-gsv-service-panel",
    "tts-gsv-service-status",
    "tts-gsv-service-refresh",
    "tts-gsv-service-install",
    "tts-gsv-service-uninstall",
    "tts-gsv-service-meta",
    "tts-voice-import",
    "tts-voice-archive-path",
    "tts-save-and-test",
    "tts-test-result",
    "tts-test-text-page",
    "chat-message-approval-card",
    "chat-message-approval-actions",
    "chat-message-approval-approve",
    "chat-message-approval-reject",
    "chat-message-approval-open-run-detail",
    "chat-message-open-run-detail",
    "chat-agent-run-progress-card",
    "chat-agent-run-progress-open-run-detail",
    "chat-composer-approval-notice",
    "chat-composer-approval-approve",
    "chat-composer-approval-reject",
    "chat-composer-approval-open-run-detail",
    "chat-composer-approval-reveal",
    "chat-composer-approval-previous",
    "chat-composer-approval-next",
    "agent-studio-agents",
    "agent-new",
    "agent-list",
    "agent-list-item",
    "agent-list-open",
    "agent-editor",
    "agent-name-input",
    "agent-nickname-input",
    "agent-avatar-select",
    "agent-avatar-clear",
    "agent-description-input",
    "agent-category-input",
    "agent-output-contract-select",
    "agent-instructions-input",
    "agent-persona-input",
    "agent-save",
    "agent-delete",
    "skill-library",
    "skill-import-folder-select",
    "skill-install-command-input",
    "skill-install-command-submit",
    "skill-native-sync",
    "skill-source-root",
    "skill-import-results",
    "skill-import-result",
    "skill-source-picker",
    "skill-library-folder-filter",
    "skill-list",
    "skill-card",
    "skill-card-enabled-toggle",
    "skill-card-folder-select",
    "skill-card-open-location",
    "skill-card-delete",
    "agent-skill-mounts",
    "agent-skill-mount-summary",
    "agent-skill-mount-filter-installed",
    "agent-skill-mount-filter-native",
    "agent-skill-mount-folder-filter",
    "agent-skill-mount-search",
    "agent-skill-mount-visible-count",
    "agent-skill-mount-all-visible",
    "agent-skill-unmount-all-visible",
    "agent-skill-mount-grid",
    "agent-skill-mount-item",
    "skill-folder-page",
    "skill-folder-name-input",
    "skill-folder-create",
    "skill-folder-list",
    "skill-folder-row",
    "skill-folder-edit-name-input",
    "skill-folder-save-rename",
    "skill-folder-rename",
    "skill-folder-open",
    "skill-folder-delete",
    "agent-run-detail",
    "agent-run-detail-approval",
    "agent-run-detail-approval-approve",
    "agent-run-detail-approval-reject",
    "agent-run-approval-request",
    "agent-run-detail-workflow-child-approval",
    "agent-run-detail-workflow-child-approve",
    "agent-run-detail-workflow-child-reject",
    "agent-run-detail-workflow-child-cancel",
    "agent-run-detail-workflow-child-open-run",
    "agent-run-detail-workflow-step-open-run",
    "agent-run-detail-execution-open-child-run",
    "agent-run-detail-execution-event",
    "agent-run-detail-task",
    "agent-run-detail-result",
    "agent-run-detail-workflow-step",
    "agent-run-detail-open-parent-run",
    "agent-run-detail-load-more-events",
    "agent-run-detail-artifact",
    "agent-run-detail-artifact-preview",
    "agent-run-detail-rerun",
    "agent-run-history-manage",
    "agent-run-history-bulk-actions",
    "agent-run-history-select-all",
    "agent-run-history-clear-selection",
    "agent-run-history-row",
    "agent-run-history-select-run",
    "agent-run-history-delete-selected",
    "agent-run-history-finish-management",
    "workflow-studio",
    "workflow-list",
    "workflow-list-item",
    "workflow-list-manage",
    "workflow-bulk-actions",
    "workflow-select-all",
    "workflow-clear-selection",
    "workflow-list-checkbox",
    "workflow-delete-selected",
    "workflow-finish-management",
    "workflow-list-open",
    "workflow-editor",
    "workflow-new",
    "workflow-name-input",
    "workflow-description-input",
    "workflow-delete",
    "workflow-add-approval-node",
    "workflow-add-artifact-node",
    "workflow-agent-palette-item",
    "workflow-node-setting-row",
    "workflow-node-approval-criteria-input",
    "workflow-node-artifact-path-input",
    "workflow-run-preview-step",
    "workflow-run-goal-input",
    "workflow-save-and-run",
)
PACKAGED_UI_E2E_REQUIRED_DATA_ATTRIBUTES: tuple[str, ...] = (
    "data-run-id",
    "data-run-status",
)
PACKAGED_UI_E2E_FORBIDDEN_TEXT: tuple[str, ...] = (
    "oha-chat-e2e-add-image",
)
DATA_TESTID_SELECTOR_RE = re.compile(
    r"""data-testid=(?:\\)?(?P<quote>["'])(?P<selector>[^"'\\]+)(?:\\)?(?P=quote)"""
)
DATA_ATTRIBUTE_RE = re.compile(r"\bdata-[a-z][a-z0-9-]*\b")
PACKAGED_INFO_REQUIRED_VALUES: tuple[tuple[str, str, str], ...] = (
    (
        "LSApplicationCategoryType",
        "public.app-category.productivity",
        "packaged app Info.plist must keep the productivity app category",
    ),
)
PACKAGED_INFO_REQUIRED_PERMISSION_KEYS: tuple[tuple[str, str], ...] = (
    ("NSAppleEventsUsageDescription", "packaged app Info.plist must include Apple Events permission copy"),
    ("NSDocumentsFolderUsageDescription", "packaged app Info.plist must include Documents folder permission copy"),
    ("NSDownloadsFolderUsageDescription", "packaged app Info.plist must include Downloads folder permission copy"),
    ("NSMicrophoneUsageDescription", "packaged app Info.plist must include microphone permission copy"),
)
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
RELEASE_PACKAGING_DOC_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "release-facing product identity and security guards",
        "release packaging docs must document the pre-dependency release guard",
    ),
    (
        "debug route",
        "release packaging docs must document debug route guard coverage",
    ),
    (
        "CredentialStore fallback",
        "release packaging docs must document release CredentialStore fallback guard coverage",
    ),
    (
        "codesign --verify --deep --strict --verbose=2",
        "release packaging docs must document final packaged app signature verification",
    ),
    (
        "binary-safe release artifact scan",
        "release packaging docs must document final release artifact binary scanning",
    ),
    (
        "latest JSON 的 `dmg_name` / `sha256`",
        "release packaging docs must document latest JSON checksum consistency checks",
    ),
    (
        "latest JSON 的 `name` / `channel` / `branch` / `source_branch` / `version` / `commit` / `short_commit` / `build_number` / `run_number` / `run_id` / `tag` / `signing` / `published_at` / `changelog`",
        "release packaging docs must document latest JSON metadata format validation",
    ),
    (
        "python scripts/prepare_app_build_metadata.py",
        "release packaging docs must document reusable app build metadata preparation",
    ),
    (
        "每个 DMG 的 `.sha256` 文件",
        "release packaging docs must document per-DMG checksum file validation",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts",
        "release packaging docs must document the local RC verification entrypoint",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount",
        "release packaging docs must document the local RC DMG mount gate",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --run-dmg-app-smoke",
        "release packaging docs must document the local RC packaged app startup smoke",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --run-dmg-screen-smoke",
        "release packaging docs must document the local RC packaged screen recording smoke",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --run-provider-smoke",
        "release packaging docs must document the local RC real provider smoke gate",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --run-ui-smoke",
        "release packaging docs must document the local RC Electron UI smoke gate",
    ),
    (
        "python scripts/run_electron_ui_smokes.py --report-json release/electron-ui-smoke.json",
        "release packaging docs must document the archived Electron UI smoke runner report",
    ),
    (
        "release/electron-ui-smoke.json",
        "release packaging docs must document the archived Electron UI smoke report",
    ),
    (
        "release/electron-ui-smoke.json` 作为额外 `--manual-checks-json`",
        "release packaging docs must document standalone Electron UI smoke signoff evidence merging",
    ),
    (
        "python scripts/verify_release_candidate.py --source-only --report-json tmp/source-only-rc.json",
        "release packaging docs must document the source-only RC dry run",
    ),
    (
        "上传 DMG 前运行 `python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --run-dmg-app-smoke --report-json release/rc-verification.json`",
        "release packaging docs must document the CI release-candidate gate and packaged app startup smoke before upload",
    ),
    (
        "release/rc-verification.json",
        "release packaging docs must document the archived RC verification report",
    ),
    (
        "release/manual-rc-checks.template.json",
        "release packaging docs must document the archived manual RC check template",
    ),
    (
        "release/manual-rc-checks.draft.json",
        "release packaging docs must document the archived manual RC check draft",
    ),
    (
        "release/manual-rc-checks.md",
        "release packaging docs must document the archived manual RC check Markdown checklist",
    ),
    (
        "manual_release_candidate_check_statuses",
        "release packaging docs must document structured manual RC check statuses",
    ),
    (
        "--manual-checks-json",
        "release packaging docs must document manual RC check evidence input",
    ),
    (
        "--manual-checks-markdown",
        "release packaging docs must document manual RC check Markdown evidence input",
    ),
    (
        "--write-manual-checks-template",
        "release packaging docs must document manual RC check template generation",
    ),
    (
        "--write-manual-checks-draft",
        "release packaging docs must document manual RC check draft generation",
    ),
    (
        "--write-manual-checks-markdown",
        "release packaging docs must document manual RC check Markdown generation",
    ),
    (
        "--print-manual-checks-status",
        "release packaging docs must document read-only manual RC check status printing",
    ),
    (
        "自动收证命令",
        "release packaging docs must document recommended automation commands for remaining manual checks",
    ),
    (
        "生成 draft 或 Markdown 时，CLI 会立即打印同一套 progress",
        "release packaging docs must document fast signoff summary output for generated drafts",
    ),
    (
        "不写显式 `status` 会按 `passed` 解析",
        "release packaging docs must document checked Markdown items default to passed",
    ),
    (
        "``- [x] `check_id` - not_applicable``",
        "release packaging docs must document explicit Markdown not_applicable status",
    ),
    (
        "非空 `Evidence:`",
        "release packaging docs must document Markdown signoff evidence requirements",
    ),
    (
        "--write-manual-checks-markdown tmp/final-rc-signoff.md --mark-provider-smoke-not-applicable-if-missing",
        "release packaging docs must document direct no-provider Markdown signoff draft generation",
    ),
    (
        "草稿会把通过的脚本列表预填到 `packaged_ui_sampling` 的 `Notes:`",
        "release packaging docs must document UI smoke supporting evidence notes",
    ),
    (
        "这两项仍保持 `manual_required`",
        "release packaging docs must document UI smoke does not auto-pass manual checks",
    ),
    (
        "--run-dmg-ui-sampling-smoke",
        "release packaging docs must document packaged UI sampling smoke",
    ),
    (
        "--mark-provider-smoke-not-applicable-if-missing",
        "release packaging docs must document explicit provider-smoke not_applicable draft evidence",
    ),
    (
        "workflow 会向 RC report、draft 和 Markdown 传入 `--mark-provider-smoke-not-applicable-if-missing`",
        "release packaging docs must document workflow provider-smoke not_applicable evidence propagation",
    ),
    (
        "--require-manual-checks-complete",
        "release packaging docs must document final manual RC signoff enforcement",
    ),
    (
        "manual_release_candidate_check_source_revision_findings",
        "release packaging docs must document stale manual evidence source revision rejection",
    ),
    (
        "final signoff requires manual release-candidate evidence source revisions",
        "release packaging docs must document missing manual evidence source revision rejection",
    ),
    (
        "gatekeeper_first_launch",
        "release packaging docs must document the Gatekeeper manual RC check id",
    ),
    (
        "screen_recording_permission",
        "release packaging docs must document the screen recording manual RC check id",
    ),
    (
        "chat_native_file_upload",
        "release packaging docs must document the native Chat file upload manual RC check id",
    ),
    (
        "packaged_ui_sampling",
        "release packaging docs must document the packaged UI sampling manual RC check id",
    ),
)
RELEASE_WORKFLOW_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "Verify release-facing product identity and security guards",
        "macOS release workflow must run the release verifier before dependency installation",
    ),
    (
        "          - alpha",
        "macOS release workflow must expose an alpha release channel",
    ),
    (
        'CHANNEL_LABEL="Alpha 版"',
        "macOS release workflow must label alpha releases separately",
    ),
    (
        'LATEST_BRANCH="alpha"',
        "macOS release workflow must publish alpha builds to alpha-latest metadata",
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
        'python scripts/verify_release_artifacts.py --allow-binary --check-packaged-app "${package_scan_paths[@]}"',
        "macOS release workflow must binary-scan packaged app resources",
    ),
    (
        "--check-packaged-app",
        "macOS release workflow must validate packaged app bundle structure",
    ),
    (
        'codesign --verify --deep --strict --verbose=2 "${app_path}"',
        "macOS release workflow must verify the final packaged app code signature when signing is enabled",
    ),
    (
        "python scripts/verify_release_artifacts.py --allow-binary release",
        "macOS release workflow must binary-scan final release artifacts",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts",
        "macOS release workflow must run the local RC verification gate",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount",
        "macOS release workflow must mount-check DMG contents during local RC verification",
    ),
    (
        "python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --run-dmg-app-smoke",
        "macOS release workflow must launch the app inside DMG artifacts during RC verification",
    ),
    (
        "provider_smoke_status_args+=(--mark-provider-smoke-not-applicable-if-missing)",
        "macOS release workflow must mark provider smoke not_applicable in archived signoff artifacts when secrets are missing",
    ),
    (
        "--report-json release/rc-verification.json",
        "macOS release workflow must upload a release-candidate verification report",
    ),
    (
        "--write-manual-checks-template release/manual-rc-checks.template.json",
        "macOS release workflow must archive a manual RC check evidence template",
    ),
    (
        "--manual-checks-json release/rc-verification.json --manual-checks-json release/electron-ui-smoke.json --write-manual-checks-draft release/manual-rc-checks.draft.json",
        "macOS release workflow must archive a manual RC check draft seeded from the RC report and Electron UI smoke report",
    ),
    (
        "--manual-checks-json release/manual-rc-checks.draft.json --write-manual-checks-markdown release/manual-rc-checks.md",
        "macOS release workflow must archive a manual RC check Markdown checklist seeded from the draft",
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
        "Multiple DMG artifacts found; refusing to choose implicitly.",
        "macOS release workflow must fail instead of choosing implicitly when multiple DMGs exist",
    ),
    (
        "release/*.sha256",
        "macOS release workflow must upload release checksum artifacts",
    ),
    (
        '"release/${LATEST_JSON}"',
        "macOS release workflow must publish latest channel JSON metadata",
    ),
    (
        "provider_smoke_args+=(--run-provider-smoke)",
        "macOS release workflow must expose opt-in real provider smoke through the RC gate",
    ),
    (
        "OHA_YACHIYO_SMOKE_BASE_URL",
        "macOS release workflow must wire opt-in provider smoke base URL secret",
    ),
    (
        "OHA_YACHIYO_SMOKE_MODEL",
        "macOS release workflow must wire opt-in provider smoke model secret",
    ),
    (
        "OHA_YACHIYO_SMOKE_API_KEY",
        "macOS release workflow must wire opt-in provider smoke API key secret",
    ),
    (
        'if [[ -z "${OHA_YACHIYO_SMOKE_BASE_URL}" || -z "${OHA_YACHIYO_SMOKE_MODEL}" || -z "${OHA_YACHIYO_SMOKE_API_KEY}" ]]; then',
        "macOS release workflow provider smoke must skip unless all opt-in secrets are configured",
    ),
    (
        "Skipping opt-in real provider streaming smoke; OHA_YACHIYO_SMOKE_* secrets are not fully configured.",
        "macOS release workflow provider smoke must report an explicit opt-in secret skip",
    ),
    (
        '"${provider_smoke_args[@]}"',
        "macOS release workflow must pass opt-in provider smoke args to the RC verifier",
    ),
)
RELEASE_CANDIDATE_PROVIDER_SMOKE_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "PROVIDER_SMOKE_ENV_VARS",
        "release candidate verifier must define opt-in provider smoke environment variables",
    ),
    (
        "PROVIDER_SMOKE_COMMANDS",
        "release candidate verifier must define provider smoke command contracts",
    ),
    (
        "scripts/smoke_openai_compatible_stream.py",
        "release candidate verifier must run the real provider streaming smoke helper",
    ),
    (
        '"text_stream"',
        "release candidate verifier must run real provider text stream smoke",
    ),
    (
        '"--require-content"',
        "release candidate verifier text smoke must require streamed content",
    ),
    (
        '"--expect-finish-reason"',
        "release candidate verifier provider smoke must assert finish_reason values",
    ),
    (
        '"stop"',
        "release candidate verifier provider smoke must assert stop finish_reason",
    ),
    (
        '"tool_call_stream"',
        "release candidate verifier must run real provider tool-call stream smoke",
    ),
    (
        '"--require-tool-call"',
        "release candidate verifier tool-call smoke must require streamed tool calls",
    ),
    (
        '"--require-tool-result-content"',
        "release candidate verifier tool-call smoke must verify streamed content after a tool result",
    ),
    (
        '"--expect-tool-name"',
        "release candidate verifier tool-call smoke must assert an expected tool name",
    ),
    (
        '"workspace_read"',
        "release candidate verifier tool-call smoke must assert the workspace_read tool call",
    ),
    (
        '"--expect-tool-argument-substring"',
        "release candidate verifier tool-call smoke must assert an expected argument substring",
    ),
    (
        '"README.md"',
        "release candidate verifier tool-call smoke must assert the README argument",
    ),
    (
        '"--expect-tool-argument-json-field"',
        "release candidate verifier tool-call smoke must assert an expected JSON argument field",
    ),
    (
        '"path=README.md"',
        "release candidate verifier tool-call smoke must assert the README path JSON field",
    ),
    (
        '"tool_calls"',
        "release candidate verifier tool-call smoke must assert tool_calls finish_reason",
    ),
    (
        '"--expect-tool-result-finish-reason"',
        "release candidate verifier tool-call smoke must assert tool-result follow-up finish_reason",
    ),
    (
        "missing environment variables",
        "release candidate verifier provider smoke must fail explicitly when credentials are missing",
    ),
    (
        "verify_provider_smoke",
        "release candidate verifier must expose provider smoke verification",
    ),
    (
        "run_provider_smoke",
        "release candidate verifier must report whether provider smoke was requested",
    ),
    (
        "run_electron_ui_smoke_report",
        "release candidate verifier must reuse the shared Electron UI smoke runner",
    ),
)
RELEASE_CANDIDATE_VERIFIER_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS",
        "release candidate verifier must define structured manual release checks",
    ),
    (
        "MANUAL_RELEASE_CANDIDATE_CHECK_STATUS_VALUES",
        "release candidate verifier must define allowed manual check statuses",
    ),
    (
        '"passed"',
        "release candidate verifier manual checks must support passed status",
    ),
    (
        '"failed"',
        "release candidate verifier manual checks must support failed status",
    ),
    (
        '"not_applicable"',
        "release candidate verifier manual checks must support not_applicable status",
    ),
    (
        '"gatekeeper_first_launch"',
        "release candidate verifier must track Gatekeeper first-launch manual status",
    ),
    (
        '"packaged_bridge_isolation"',
        "release candidate verifier must track packaged bridge isolation manual status",
    ),
    (
        '"screen_recording_permission"',
        "release candidate verifier must track screen recording permission manual status",
    ),
    (
        '"chat_native_file_upload"',
        "release candidate verifier must track native Chat file upload manual status",
    ),
    (
        '"packaged_ui_sampling"',
        "release candidate verifier must track packaged UI sampling manual status",
    ),
    (
        '"real_provider_smoke"',
        "release candidate verifier must track real provider smoke manual status",
    ),
    (
        '"manual_required"',
        "release candidate verifier manual checks must default to manual_required",
    ),
    (
        '"public_release_signoff"',
        "release candidate verifier manual checks must declare the release signoff gate",
    ),
    (
        '"evidence"',
        "release candidate verifier manual checks must describe required evidence",
    ),
    (
        '"manual_release_candidate_check_statuses"',
        "release candidate verifier must write structured manual check statuses to the RC report",
    ),
    (
        '"source_revision"',
        "release candidate verifier must write source revision metadata to the RC report",
    ),
    (
        '"bridge_statuses"',
        "release candidate verifier must archive packaged Bridge status metadata from DMG smokes",
    ),
    (
        "build_metadata.commit",
        "release candidate verifier must compare packaged Bridge build metadata with source revision",
    ),
    (
        '"app_build_metadata"',
        "release candidate verifier must archive packaged Electron app build metadata from Chat native file smoke",
    ),
    (
        '"source_revision_final_signoff_findings"',
        "release candidate verifier final signoff must reject dirty source revisions",
    ),
    (
        '"manual_release_candidate_check_source_revision_findings"',
        "release candidate verifier final signoff must reject stale manual evidence source revisions",
    ),
    (
        "requires manual release-candidate evidence source revisions",
        "release candidate verifier final signoff must reject manual evidence without source revisions",
    ),
    (
        "manual evidence source revision guard",
        "release candidate verifier must print stale manual evidence source revision findings",
    ),
    (
        '"manual_release_candidate_check_source_revisions"',
        "release candidate verifier manual reports, drafts, and Markdown must preserve source revision metadata",
    ),
    (
        '"manual_release_candidate_check_summary"',
        "release candidate verifier must write manual check progress summary to the RC report",
    ),
    (
        "_manual_release_candidate_check_summary",
        "release candidate verifier must calculate manual check progress summary",
    ),
    (
        "_print_manual_release_candidate_check_summary",
        "release candidate verifier must print manual check progress for both gates and generated drafts",
    ),
    (
        "print_manual_release_candidate_checks_status",
        "release candidate verifier must expose read-only manual check status printing",
    ),
    (
        "manual release-candidate check progress:",
        "release candidate verifier must print compact manual check progress",
    ),
    (
        '"remaining_check_ids"',
        "release candidate verifier manual summary must list remaining check ids",
    ),
    (
        '"remaining_next_actions"',
        "release candidate verifier manual summary must list remaining next actions",
    ),
    (
        '"remaining_commands"',
        "release candidate verifier manual summary must list recommended automation commands",
    ),
    (
        "manual release-candidate recommended commands:",
        "release candidate verifier must print recommended automation commands for remaining checks",
    ),
    (
        "## Remaining Automation Commands",
        "release candidate verifier Markdown checklist must include recommended automation commands",
    ),
    (
        '"remaining_notes"',
        "release candidate verifier manual summary must list supporting notes for remaining checks",
    ),
    (
        '"automated_evidence_check_ids"',
        "release candidate verifier manual summary must list automated evidence check ids",
    ),
    (
        "_manual_release_candidate_check_report()",
        "release candidate verifier must copy manual check details into reports",
    ),
    (
        "_manual_release_candidate_check_template()",
        "release candidate verifier must generate manual check templates",
    ),
    (
        "write_manual_release_candidate_checks_template",
        "release candidate verifier must expose manual check template writing",
    ),
    (
        "_manual_release_candidate_check_draft",
        "release candidate verifier must generate editable manual check drafts",
    ),
    (
        "write_manual_release_candidate_checks_draft",
        "release candidate verifier must expose manual check draft writing",
    ),
    (
        "_manual_release_candidate_checks_markdown",
        "release candidate verifier must generate manual check Markdown checklists",
    ),
    (
        "## How To Fill",
        "release candidate verifier Markdown checklist must include fill instructions",
    ),
    (
        "omitted status defaults to `passed`",
        "release candidate verifier Markdown checklist must explain checked items default to passed",
    ),
    (
        "Every `passed`, `failed`, or `not_applicable` item needs non-empty `Evidence:`",
        "release candidate verifier Markdown checklist must explain evidence requirements",
    ),
    (
        "## Final Gate",
        "release candidate verifier Markdown checklist must include the final gate command",
    ),
    (
        "tmp/rc-with-manual-checks.json",
        "release candidate verifier Markdown checklist must name the final signoff report path",
    ),
    (
        "write_manual_release_candidate_checks_markdown",
        "release candidate verifier must expose manual check Markdown writing",
    ),
    (
        "--print-manual-checks-status",
        "release candidate verifier CLI must print manual check status without running artifact gates",
    ),
    (
        '"evidence_prompt"',
        "release candidate verifier manual check templates must preserve evidence prompts",
    ),
    (
        '"next_action"',
        "release candidate verifier manual check templates must include next actions",
    ),
    (
        "_load_manual_release_candidate_checks",
        "release candidate verifier must load manual check evidence JSON",
    ),
    (
        "_manual_release_candidate_checks_from_markdown",
        "release candidate verifier must parse manual check Markdown evidence",
    ),
    (
        "_manual_release_candidate_checks_from_payload",
        "release candidate verifier must accept previous RC reports as manual evidence input",
    ),
    (
        "_standalone_electron_ui_smoke_report",
        "release candidate verifier must accept standalone Electron UI smoke reports as supporting evidence",
    ),
    (
        "_manual_release_candidate_checks_with_supporting_evidence",
        "release candidate verifier must preserve supporting evidence from previous RC reports",
    ),
    (
        "_append_electron_ui_smoke_supporting_evidence",
        "release candidate verifier must attach UI smoke supporting evidence to current RC reports",
    ),
    (
        "the packaged OS file picker still ",
        "release candidate verifier must not auto-pass native file picker from UI smoke",
    ),
    (
        "_auto_apply_release_candidate_check_evidence",
        "release candidate verifier must auto-fill manual evidence from passed RC gates",
    ),
    (
        "_auto_apply_packaged_bridge_ready_evidence",
        "release candidate verifier must preserve packaged bridge evidence from partial DMG probes",
    ),
    (
        '"bridge_ready_dmg_paths"',
        "release candidate verifier must report packaged bridge readiness from DMG probes",
    ),
    (
        '"dmg_screen_probe"',
        "release candidate verifier must report packaged screen probe results",
    ),
    (
        '"dmg_ui_sampling_smoke"',
        "release candidate verifier must report packaged UI sampling smoke results",
    ),
    (
        '"dmg_chat_native_file_smoke"',
        "release candidate verifier must report packaged Chat native file smoke results",
    ),
    (
        "DMG_UI_SAMPLING_SMOKE_SCRIPT",
        "release candidate verifier must name the packaged UI sampling smoke helper",
    ),
    (
        "DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT",
        "release candidate verifier must name the packaged Chat native file smoke helper",
    ),
    (
        "verify_dmg_ui_sampling_smoke",
        "release candidate verifier must expose packaged UI sampling verification",
    ),
    (
        "verify_dmg_chat_native_file_upload_smoke",
        "release candidate verifier must expose packaged Chat native file verification",
    ),
    (
        '"--run-dmg-screen-smoke"',
        "release candidate verifier CLI must expose packaged screen recording smoke",
    ),
    (
        '"--run-dmg-ui-sampling-smoke"',
        "release candidate verifier CLI must expose packaged UI sampling smoke",
    ),
    (
        '"--run-dmg-chat-native-file-smoke"',
        "release candidate verifier CLI must expose packaged Chat native file smoke",
    ),
    (
        "Screenshot image bytes were not archived",
        "release candidate verifier screen probe evidence must avoid archiving screenshot bytes",
    ),
    (
        '"automated_rc_gate"',
        "release candidate verifier must label automatically supplied manual evidence",
    ),
    (
        "_refresh_manual_release_candidate_check_report",
        "release candidate verifier must refresh manual check status after automated gates",
    ),
    (
        "manual_checks_json",
        "release candidate verifier must expose manual check evidence input",
    ),
    (
        "require_manual_checks_complete",
        "release candidate verifier must expose final manual signoff enforcement",
    ),
    (
        '"--manual-checks-json"',
        "release candidate verifier CLI must accept manual check evidence JSON",
    ),
    (
        'action="append"',
        "release candidate verifier CLI must allow repeated manual check evidence JSON inputs",
    ),
    (
        '"--manual-checks-markdown"',
        "release candidate verifier CLI must accept manual check evidence Markdown",
    ),
    (
        '"--require-manual-checks-complete"',
        "release candidate verifier CLI must require complete manual checks for final signoff",
    ),
    (
        '"--write-manual-checks-template"',
        "release candidate verifier CLI must write manual check templates",
    ),
    (
        '"--write-manual-checks-draft"',
        "release candidate verifier CLI must write editable manual check drafts",
    ),
    (
        '"--write-manual-checks-markdown"',
        "release candidate verifier CLI must write manual check Markdown checklists",
    ),
    (
        '"--mark-provider-smoke-not-applicable-if-missing"',
        "release candidate verifier CLI must explicitly mark provider smoke not_applicable only when requested",
    ),
    (
        "mark_provider_smoke_not_applicable_if_missing=(",
        "release candidate verifier CLI must pass provider not_applicable evidence into RC reports",
    ),
    (
        "_mark_provider_smoke_not_applicable_if_missing",
        "release candidate verifier must isolate provider smoke not_applicable draft handling",
    ),
)
STREAMING_PROVIDER_SMOKE_SCRIPT_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "require_tool_result_followup = require_tool_result_content or bool(expected_tool_result_finish_reasons)",
        "real provider smoke helper must enable tool-result follow-up when finish_reason is asserted",
    ),
    (
        "_tool_result_followup_messages(prompt, tool_calls[0])",
        "real provider smoke helper must send a streamed tool-result follow-up request",
    ),
    (
        'call.pop("arguments", None)',
        "real provider smoke helper must strip tool-call arguments before printing summaries",
    ),
    (
        'redact_api_error_text(str(exc), fallback="stream smoke failed")',
        "real provider smoke helper must redact provider errors before printing stderr",
    ),
    (
        "_finish_reasons_from_value(choice)",
        "real provider smoke helper must parse choice-level stop_reason values",
    ),
    (
        "_responses_stream_reasoning_done(chunk)",
        "real provider smoke helper must parse Responses reasoning summary done snapshots",
    ),
    (
        "response.reasoning_summary_part.done",
        "real provider smoke helper must parse Responses reasoning summary part snapshots",
    ),
    (
        "_first_present(_field(chunk, \"output_index\")",
        "real provider smoke helper must preserve zero-valued Responses indexes before fallback indexes",
    ),
)
STREAMING_PROVIDER_SMOKE_TEST_REQUIRED_TEXT: tuple[tuple[str, str], ...] = (
    (
        "def test_stream_smoke_requires_tool_result_followup_content_without_leaking",
        "provider smoke tests must cover tool-result follow-up without leaking arguments",
    ),
    (
        'assert "synthetic workspace_read result" not in summary_json',
        "provider smoke tests must prove synthetic tool-result content stays out of printed summaries",
    ),
    (
        "def test_stream_smoke_uses_responses_call_id_for_tool_result_followup",
        "provider smoke tests must cover Responses call_id tool-result follow-up",
    ),
    (
        "def test_stream_smoke_main_expect_tool_name_requests_tool_call",
        "provider smoke tests must cover CLI tool-call expectation wiring",
    ),
    (
        'assert calls[0]["expect_tool_result_finish_reasons"] == ["stop"]',
        "provider smoke tests must cover CLI tool-result finish_reason wiring",
    ),
    (
        "def test_stream_smoke_main_redacts_provider_errors",
        "provider smoke tests must cover provider error redaction",
    ),
    (
        "def test_stream_smoke_accepts_choice_level_stop_reason",
        "provider smoke tests must cover choice-level stop_reason provider chunks",
    ),
    (
        "def test_stream_smoke_accepts_responses_completed_top_level_finish_reason",
        "provider smoke tests must cover Responses completed top-level finish_reason",
    ),
    (
        "def test_stream_smoke_accepts_responses_completed_top_level_stop_reason",
        "provider smoke tests must cover Responses completed top-level stop_reason",
    ),
    (
        "def test_stream_smoke_uses_responses_reasoning_summary_done_snapshot",
        "provider smoke tests must cover Responses reasoning summary done snapshots",
    ),
    (
        "def test_stream_smoke_uses_responses_reasoning_output_item_done_snapshot",
        "provider smoke tests must cover Responses reasoning output item snapshots",
    ),
    (
        "def test_stream_smoke_uses_responses_output_text_done_list_snapshot",
        "provider smoke tests must cover Responses output_text.done list snapshots",
    ),
    (
        "def test_stream_smoke_preserves_zero_responses_indexes_before_fallback_indexes",
        "provider smoke tests must cover zero-valued Responses indexes before fallback indexes",
    ),
    (
        "def test_stream_smoke_uses_responses_content_part_done_snapshot",
        "provider smoke tests must cover Responses content part done snapshots",
    ),
    (
        "def test_stream_smoke_uses_responses_refusal_done_snapshot",
        "provider smoke tests must cover Responses refusal done snapshots",
    ),
    (
        "def test_stream_smoke_accepts_sse_delta_tool_call_object_arguments_without_leaking",
        "provider smoke tests must cover object-shaped streaming tool arguments without leaks",
    ),
    (
        "def test_stream_smoke_coalesces_indexless_interleaved_tool_call_deltas_by_id",
        "provider smoke tests must cover indexless interleaved streaming tool-call deltas without leaks",
    ),
    (
        "def test_stream_smoke_handles_sse_event_split_across_response_chunks_without_leaking",
        "provider smoke tests must cover SSE events split across response chunks",
    ),
    (
        "assert leaked_secret not in captured.err",
        "provider smoke tests must prove provider errors do not print API keys",
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
        "tests/test_protocol.py",
        "macOS release workflow smoke tests must cover Task API protocol schemas",
    ),
    (
        "tests/test_state.py",
        "macOS release workflow smoke tests must cover AppState task lifecycle",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_main_chat_native_tool_approval_roundtrip",
        "macOS release workflow smoke tests must cover TaskRunner native approval roundtrip",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_main_chat_approval_timeout_clears_chat_and_activity_projection",
        "macOS release workflow smoke tests must cover TaskRunner approval timeout projection",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_main_chat_image_attachment_reaches_native_model",
        "macOS release workflow smoke tests must cover TaskRunner image attachment Native runtime flow",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_main_chat_auto_delegation_uses_native_runtime",
        "macOS release workflow smoke tests must cover TaskRunner auto delegation Native runtime flow",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_group_dispatch_summary_uses_native_runtime",
        "macOS release workflow smoke tests must cover TaskRunner group dispatch summary Native runtime flow",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_direct_group_agent_summary_uses_native_runtime",
        "macOS release workflow smoke tests must cover TaskRunner direct group summary Native runtime flow",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_direct_group_agent_rejected_summary_uses_native_runtime",
        "macOS release workflow smoke tests must cover TaskRunner rejected direct group summary Native runtime flow",
    ),
    (
        "tests/test_task_runner.py::test_task_runner_proactive_screenshot_task_uses_native_runtime",
        "macOS release workflow smoke tests must cover TaskRunner proactive screenshot Native runtime flow",
    ),
    (
        "tests/test_agent_runtime.py::test_run_projection_coordinator_syncs_run_projections",
        "macOS release workflow smoke tests must cover RunProjectionCoordinator snapshot boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_approval_timeout_records_replayable_fact_and_is_idempotent",
        "macOS release workflow smoke tests must cover Native approval timeout replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_records_failed_run_event_when_approved_tool_fails",
        "macOS release workflow smoke tests must cover main chat approved tool failure replay",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_fails_when_approved_terminal_returns_nonzero",
        "macOS release workflow smoke tests must cover Agent approved tool failure projection",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice",
        "macOS release workflow smoke tests must cover main chat repeated approval idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_approval_uses_resume_coordinator_claim_boundary",
        "macOS release workflow smoke tests must cover main chat approval resume claim boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_consecutive_tool_approvals_use_resume_required_projection",
        "macOS release workflow smoke tests must cover main chat approval resume wait projection",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_coordinator_snapshots_input_previews",
        "macOS release workflow smoke tests must cover ApprovalCoordinator input preview snapshot boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_transitions_use_shared_context_boundary",
        "macOS release workflow smoke tests must cover tool approval shared context boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution",
        "macOS release workflow smoke tests must cover durable approval claim across runtime instances",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_claims_and_projects_approved_tool_once",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator claim projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_claim_projection_builds_running_payload",
        "macOS release workflow smoke tests must cover ToolApprovalClaimProjection running payload boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_orchestrates_resume_projection_states",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator resume orchestration states",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_continuation_outcome_projects_resume_states",
        "macOS release workflow smoke tests must cover ToolApprovalContinuationOutcome resume state projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_approval_uses_resume_coordinator_claim_boundary",
        "macOS release workflow smoke tests must cover NativeRunEngine approval resume claim boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consecutive_terminal_approvals_update_pending_request",
        "macOS release workflow smoke tests must cover Agent approval resume wait projection",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_executes_approved_tool_and_remaining_requests",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator approved tool resume flow",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_execution_request_calls_approved_tool_with_context_payload",
        "macOS release workflow smoke tests must cover ToolApprovalExecutionRequest approved call boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_execution_followup_appends_result_and_runs_remaining_requests",
        "macOS release workflow smoke tests must cover ToolApprovalExecutionFollowup remaining-tool boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_execution_failure_projection_builds_timeline_event",
        "macOS release workflow smoke tests must cover ToolApprovalExecutionFailureProjection timeline boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_stops_on_fatal_tool_failure",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator fatal tool failure boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_custom_api_continuation_request_calls_model_with_handoff_payload",
        "macOS release workflow smoke tests must cover ToolApprovalCustomApiContinuationRequest handoff boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_continues_custom_api_agent_after_approved_tool",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator custom API resume flow",
    ),
    (
        "tests/test_agent_runtime.py::test_custom_api_agent_normalizes_invalid_start_iteration",
        "macOS release workflow smoke tests must cover custom API Agent start iteration normalization",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_projection_coordinator_projects_resume_states",
        "macOS release workflow smoke tests must cover ApprovalResumeProjectionCoordinator resume state projections",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_approval_resume_context_parses_pending_payload",
        "macOS release workflow smoke tests must cover ToolApprovalResumeContext pending payload parsing",
    ),
    (
        "tests/test_agent_runtime.py::test_pending_approval_snapshot_is_isolated_before_resume",
        "macOS release workflow smoke tests must cover pending approval snapshot isolation",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_child_outcome_coordinator_projects_child_artifacts_and_timeline",
        "macOS release workflow smoke tests must cover WorkflowChildOutcomeCoordinator projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_child_run_projection_builds_replay_payloads",
        "macOS release workflow smoke tests must cover Workflow child run replay payload projection",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_run_locator_finds_waiting_parents_and_root_groups",
        "macOS release workflow smoke tests must cover WorkflowParentRunLocator parent lookup boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_resume_planner_uses_snapshot_and_child_agent_ordinal",
        "macOS release workflow smoke tests must cover WorkflowResumePlanner child resume boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_path_planner_builds_path_snapshot_and_artifact_paths",
        "macOS release workflow smoke tests must cover WorkflowPathPlanner path snapshot boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_run_start_projector_builds_timeline_and_replay_payload",
        "macOS release workflow smoke tests must cover WorkflowRunStartProjector replay boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_child_status_projection_builds_projected_and_fallback_payloads",
        "macOS release workflow smoke tests must cover Workflow child status projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_failure_projection_redacts_and_builds_update_fields",
        "macOS release workflow smoke tests must cover Workflow parent resume failure projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_coordinator_continues_completed_child",
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator completed child handoff",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_coordinator_does_not_resume_completed_child_twice",
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator completed child replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_coordinator_does_not_project_child_approval_twice",
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child approval replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_coordinator_does_not_project_child_cancel_twice",
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child cancellation replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_parent_resume_coordinator_does_not_project_child_failure_twice",
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child failure replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_cancellation_target_builds_event_payloads",
        "macOS release workflow smoke tests must cover Workflow cancellation target projection",
    ),
    (
        "tests/test_agent_runtime.py::test_run_cancellation_projection_builds_update_fields",
        "macOS release workflow smoke tests must cover Run cancellation update projection",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_cancellation_projection_coordinator_cancels_waiting_child_run",
        "macOS release workflow smoke tests must cover WorkflowCancellationProjectionCoordinator child cancellation projection",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_agent_node_handoff_builds_child_run_payload",
        "macOS release workflow smoke tests must cover Workflow agent-node child run handoff",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_agent_node_execution_runs_child_and_builds_replay_payloads",
        "macOS release workflow smoke tests must cover Workflow agent-node child run execution handoff",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_approval_pause_projection_builds_private_and_public_payloads",
        "macOS release workflow smoke tests must cover Workflow approval pause projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_start_node_projection_builds_timeline_and_replay_payloads",
        "macOS release workflow smoke tests must cover Workflow start node projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_run_completion_projection_builds_update_and_replay_payloads",
        "macOS release workflow smoke tests must cover Workflow run completion projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_failure_projection_redacts_and_builds_update_fields",
        "macOS release workflow smoke tests must cover Workflow continuation failure projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_coordinator_pauses_for_approval_node",
        "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator approval pause projection",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_coordinator_resumes_after_approval_node",
        "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator approval resume handoff",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_coordinator_projects_background_failure_without_secret_leak",
        "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator background failure projection",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_coordinator_fails_unknown_node_without_secret_leak",
        "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator failure redaction boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_artifact_node_write_builds_record_and_replay_payload",
        "macOS release workflow smoke tests must cover Workflow artifact node write boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_continuation_coordinator_writes_artifact_node",
        "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator artifact node handoff",
    ),
    (
        "tests/test_agent_runtime.py::test_run_approval_routes_return_404_and_are_idempotent",
        "macOS release workflow smoke tests must cover approval approve route idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_run_approval_reject_route_is_idempotent",
        "macOS release workflow smoke tests must cover approval reject route idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_concurrent_cancel_run_is_idempotent",
        "macOS release workflow smoke tests must cover concurrent Run cancellation idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_run_transition_projection_coordinator_projects_child_and_workflow_group",
        "macOS release workflow smoke tests must cover RunTransitionProjectionCoordinator child and workflow group projection",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_rejects_sensitive_client_run_id_before_persistence",
        "macOS release workflow smoke tests must cover sensitive client_run_id rejection",
    ),
    (
        "tests/test_bridge_server.py::test_agent_and_workflow_run_http_routes_redact_sensitive_idempotency_key_errors",
        "macOS release workflow smoke tests must cover sensitive Agent/Workflow Idempotency-Key error redaction",
    ),
    (
        "tests/test_bridge_server.py::test_agent_run_http_route_rejects_sensitive_idempotency_key_before_persistence",
        "macOS release workflow smoke tests must cover sensitive Agent Idempotency-Key persistence rejection",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_run_http_route_rejects_sensitive_idempotency_key_before_persistence",
        "macOS release workflow smoke tests must cover sensitive Workflow Idempotency-Key persistence rejection",
    ),
    (
        "tests/test_bridge_server.py::test_run_cancel_route_handler_is_idempotent",
        "macOS release workflow smoke tests must cover UI Run cancel route idempotency",
    ),
    (
        "tests/test_bridge_server.py::test_chat_cancel_bridge_route_cancels_native_run_and_ignores_late_output",
        "macOS release workflow smoke tests must cover Chat cancel late-output HTTP roundtrip",
    ),
    (
        "tests/test_executor.py::TestNativeAgentUnavailableExecutor::test_run_fails_without_simulated_result",
        "macOS release workflow smoke tests must cover missing-model executor structured failure",
    ),
    (
        "tests/test_executor.py::TestNativeAgentUnavailableExecutor::test_select_executor_returns_native_unavailable_when_runtime_not_ready",
        "macOS release workflow smoke tests must cover missing-model executor selection",
    ),
    (
        "tests/test_executor.py::TestNativeAgentExecutor::test_run_uses_native_run_and_returns_task_result",
        "macOS release workflow smoke tests must cover NativeAgentExecutor Task-to-Run boundary",
    ),
    (
        "tests/test_executor.py::TestNativeAgentExecutor::test_run_passes_recent_chat_history_and_excludes_current_task",
        "macOS release workflow smoke tests must cover NativeAgentExecutor multi-turn context filtering",
    ),
    (
        "tests/test_executor.py::TestNativeAgentExecutor::test_run_limits_chat_history_by_context_chars",
        "macOS release workflow smoke tests must cover NativeAgentExecutor context size limit",
    ),
    (
        "tests/test_executor.py::TestNativeAgentExecutor::test_run_passes_image_attachments_as_limited_data_urls",
        "macOS release workflow smoke tests must cover NativeAgentExecutor image attachment payloads",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_run_links_task_and_records_replayable_events",
        "macOS release workflow smoke tests must cover TaskRunLink replay projection",
    ),
    (
        "tests/test_agent_runtime.py::test_task_run_link_repository_tracks_run_projection",
        "macOS release workflow smoke tests must cover TaskRunLink repository projection boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_run_artifact_repository_redacts_projection_and_reads_files",
        "macOS release workflow smoke tests must cover RunArtifactRepository redaction and file reads",
    ),
    (
        "tests/test_agent_runtime.py::test_run_group_repository_redacts_summary_projection",
        "macOS release workflow smoke tests must cover RunGroupRepository summary redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_run_group_repository_redacts_insert_projection",
        "macOS release workflow smoke tests must cover RunGroupRepository insert redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_legacy_run_group_secret_projection_migration_vacuums_plaintext_secret",
        "macOS release workflow smoke tests must cover legacy RunGroupRepository secret scrub",
    ),
    (
        "tests/test_agent_runtime.py::test_run_repository_rejects_sensitive_client_request_id_before_persistence",
        "macOS release workflow smoke tests must cover RunRepository sensitive client_request_id rejection",
    ),
    (
        "tests/test_agent_runtime.py::test_run_repository_deletes_rows_and_artifacts",
        "macOS release workflow smoke tests must cover RunRepository artifact cleanup callback",
    ),
    (
        "tests/test_agent_runtime.py::test_run_event_repository_allocates_sequences_under_concurrent_writers",
        "macOS release workflow smoke tests must cover RunEvent concurrent replay cursor projection",
    ),
    (
        "tests/test_agent_runtime.py::test_run_event_repository_snapshots_payload_before_persistence",
        "macOS release workflow smoke tests must cover RunEvent payload snapshot boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_runtime_sqlite_enables_required_database_guards",
        "macOS release workflow smoke tests must cover runtime SQLite database guards",
    ),
    (
        "tests/test_agent_runtime.py::test_runtime_shutdown_cancels_active_runs_rejects_new_runs_and_records_fact",
        "macOS release workflow smoke tests must cover Native runtime shutdown cancellation facts",
    ),
    (
        "tests/test_agent_runtime.py::test_runtime_shutdown_close_db_closes_runtime_resources",
        "macOS release workflow smoke tests must cover Native runtime shutdown resource closure",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_validates_write_patch_workspace_boundary_before_approval",
        "macOS release workflow smoke tests must cover write_patch boundary validation before approval",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_broker_rejects_symlink_workspace_escape",
        "macOS release workflow smoke tests must cover ToolBroker symlink workspace escape guard",
    ),
    (
        "tests/test_agent_runtime.py::test_tool_descriptor_schema_and_validation_share_patch_contract",
        "macOS release workflow smoke tests must cover workspace.write_patch schema validation contract",
    ),
    (
        "tests/test_agent_runtime.py::test_workspace_write_patch_applies_single_file_unified_diff_with_hash",
        "macOS release workflow smoke tests must cover workspace.write_patch single-file hash application",
    ),
    (
        "tests/test_agent_runtime.py::test_workspace_write_patch_rejects_hash_or_context_mismatch_without_writing",
        "macOS release workflow smoke tests must cover workspace.write_patch hash and context mismatch refusal",
    ),
    (
        "tests/test_agent_runtime.py::test_workspace_write_patch_rejects_multifile_or_binary_patch",
        "macOS release workflow smoke tests must cover workspace.write_patch multifile and binary patch refusal",
    ),
    (
        "tests/test_agent_runtime.py::test_terminal_run_uses_workspace_argv_and_scrubbed_environment",
        "macOS release workflow smoke tests must cover terminal workspace argv and env scrub",
    ),
    (
        "tests/test_agent_runtime.py::test_skill_install_command_runs_whitelisted_npx_and_syncs",
        "macOS release workflow smoke tests must cover skill install env scrub",
    ),
    (
        "tests/test_agent_runtime.py::test_terminal_run_startup_failure_returns_structured_sanitized_error",
        "macOS release workflow smoke tests must cover terminal startup structured sanitized errors",
    ),
    (
        "tests/test_agent_runtime.py::test_terminal_run_truncates_and_sanitizes_outputs",
        "macOS release workflow smoke tests must cover terminal output redaction and truncation",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_redacts_approved_terminal_failure_output_from_projection_and_storage",
        "macOS release workflow smoke tests must cover approved terminal failure output redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_terminal_run_timeout_kills_process_group",
        "macOS release workflow smoke tests must cover terminal timeout process-group kill",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_stream_chunks_before_persisting",
        "macOS release workflow smoke tests must cover streaming output completed-event persistence",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_preserves_stream_stop_reason_as_finish_reason_in_completed_event",
        "macOS release workflow smoke tests must cover NativeRunEngine stop_reason stream metadata normalization",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_openai_sdk_object_stream_before_persisting",
        "macOS release workflow smoke tests must cover OpenAI SDK object stream completed-event persistence",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_consumes_openai_compatible_sse_stream",
        "macOS release workflow smoke tests must cover NativeRunEngine canonical SSE content stream",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_consumes_coalesced_openai_compatible_sse_frames",
        "macOS release workflow smoke tests must cover NativeRunEngine coalesced SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_consumes_split_openai_compatible_sse_frame_chunks",
        "macOS release workflow smoke tests must cover NativeRunEngine split SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_consumes_split_utf8_openai_compatible_sse_frame_chunks",
        "macOS release workflow smoke tests must cover NativeRunEngine split UTF-8 SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_consumes_multiline_openai_compatible_sse_data_event",
        "macOS release workflow smoke tests must cover NativeRunEngine multiline SSE content data",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_rejects_non_stream_reasoning_only_output",
        "macOS release workflow smoke tests must cover provider reasoning privacy for direct chat calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_rejects_non_stream_reasoning_only_output",
        "macOS release workflow smoke tests must cover provider reasoning privacy for main chat loop",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_provider_exception_is_redacted_from_run_events_and_storage",
        "macOS release workflow smoke tests must cover provider exception redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_child_agent_provider_exception_is_redacted_from_parent_events_and_storage",
        "macOS release workflow smoke tests must cover Workflow child provider exception redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_tool_exception_is_redacted_from_tool_messages_events_and_storage",
        "macOS release workflow smoke tests must cover tool exception redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_openai_compatible_sse_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine canonical SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_singular_sse_tool_call_frames",
        "macOS release workflow smoke tests must cover NativeRunEngine singular SSE tool-call frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_sse_delta_tool_call_object_arguments",
        "macOS release workflow smoke tests must cover NativeRunEngine SSE object tool-call arguments",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_message_level_openai_compatible_sse_tool_call",
        "macOS release workflow smoke tests must cover NativeRunEngine message-level SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_multiline_openai_compatible_sse_tool_call",
        "macOS release workflow smoke tests must cover NativeRunEngine multiline SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_split_openai_compatible_sse_tool_call_frames",
        "macOS release workflow smoke tests must cover NativeRunEngine split-frame SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_interleaved_streaming_tool_call_deltas",
        "macOS release workflow smoke tests must cover NativeRunEngine interleaved SSE tool-call deltas",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_keeps_multi_choice_same_index_streaming_tool_calls_separate",
        "macOS release workflow smoke tests must cover NativeRunEngine multi-choice same-index SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_indexless_streaming_tool_call_deltas",
        "macOS release workflow smoke tests must cover NativeRunEngine indexless SSE tool-call deltas",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_indexless_interleaved_tool_call_deltas_by_id",
        "macOS release workflow smoke tests must cover NativeRunEngine indexless interleaved SSE tool-call deltas",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_legacy_streaming_function_call",
        "macOS release workflow smoke tests must cover NativeRunEngine legacy streaming function_call frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_top_level_delta_message_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine top-level delta/message tool-call frames",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_provider_message_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine provider message tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_openai_sdk_object_message_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine OpenAI SDK object message tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_responses_style_streaming_tool_call",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses-style streaming tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_multiple_responses_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses-style multiple tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_uses_responses_call_id_without_item_id",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id main chat history",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_provider_message_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run provider message tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_openai_sdk_object_message_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run OpenAI SDK object message tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_streaming_tool_call_and_continues",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_top_level_delta_message_streaming_tool_call",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run top-level delta/message tool-call frames",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consumes_split_utf8_http_sse_content_chunks",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split UTF-8 SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consumes_split_http_sse_content_frame_chunks",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split HTTP SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consumes_coalesced_http_sse_content_frames",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run coalesced HTTP SSE content frames",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consumes_multiline_http_sse_content_data_event",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run multiline HTTP SSE content data",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_consumes_http_sse_content_parts",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE content parts",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_persists_streaming_refusal_delta",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming refusal deltas",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_accepts_refusal_message_field",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run refusal message fields",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_preserves_stream_stop_reason_as_finish_reason_in_run_events",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run stop_reason metadata replay",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_uses_responses_refusal_done_snapshot",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses refusal.done snapshots",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_hides_streaming_reasoning_delta",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming reasoning privacy",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_rejects_reasoning_only_output_without_leaking",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run reasoning privacy",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_redacts_http_sse_provider_error",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE provider error redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_redacts_multiline_http_sse_provider_error",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run multiline HTTP SSE provider error redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_http_sse_tool_call_and_continues",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_split_http_sse_tool_call_chunks_and_continues",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split HTTP SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_singular_http_sse_tool_call_and_continues",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run singular HTTP SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_coalesces_indexless_interleaved_http_sse_tool_call_deltas_by_id",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run indexless interleaved HTTP SSE tool-call deltas",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_http_sse_object_tool_call_arguments",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE object tool-call arguments",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_message_level_http_sse_tool_call",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run message-level HTTP SSE tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_legacy_streaming_function_call",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run legacy streaming function_call frames",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_uses_responses_call_id_without_item_id",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id Agent Run history",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_prefers_responses_call_id_over_item_id",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id over item id Agent Run history",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_executes_multiple_responses_tool_calls",
        "macOS release workflow smoke tests must cover NativeRunEngine Responses-style multiple Agent Run tool calls",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_uses_responses_output_text_done_snapshot",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses output_text.done snapshots",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_uses_responses_output_item_message_snapshot",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses output_item.done message snapshots",
    ),
    (
        "tests/test_agent_runtime.py::test_agent_run_uses_responses_content_part_snapshot",
        "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses content_part.done snapshots",
    ),
    (
        "tests/test_streaming_provider_smoke.py",
        "macOS release workflow smoke tests must cover OpenAI-compatible streaming provider contracts",
    ),
    (
        "tests/test_legacy_kernel_removal.py",
        "macOS release workflow smoke tests must cover legacy Hermes kernel removal",
    ),
    (
        "tests/test_runtime_injection_boundary.py",
        "macOS release workflow smoke tests must cover Native runtime injection boundary",
    ),
    (
        "tests/test_runtime.py",
        "macOS release workflow smoke tests must cover AppRuntime Native service aggregation",
    ),
    (
        "tests/test_desktop_backend_app.py",
        "macOS release workflow smoke tests must cover desktop backend Native startup",
    ),
    (
        "tests/test_desktop_launcher.py",
        "macOS release workflow smoke tests must cover desktop launcher startup wiring",
    ),
    (
        "tests/test_shell_app_entrypoint.py",
        "macOS release workflow smoke tests must cover shell app Electron entrypoint",
    ),
    (
        "tests/test_main_api_modes.py::test_native_connection_missing_default_returns_structured_error",
        "macOS release workflow smoke tests must cover missing-model MainWindow readiness",
    ),
    (
        "tests/test_main_api_modes.py",
        "macOS release workflow smoke tests must cover desktop MainWindow API modes",
    ),
    (
        "tests/test_model_capabilities.py",
        "macOS release workflow smoke tests must cover model capability and image input guards",
    ),
    (
        "tests/test_model_profiles.py",
        "macOS release workflow smoke tests must cover model profile credentials and provider contracts",
    ),
    (
        "tests/test_provider_catalog_sync.py",
        "macOS release workflow smoke tests must cover provider catalog metadata and cache redaction",
    ),
    (
        "tests/test_build_backend.py",
        "macOS release workflow smoke tests must cover packaged backend build command guards",
    ),
    (
        "tests/test_build_metadata.py",
        "macOS release workflow smoke tests must cover release-like build metadata guards",
    ),
    (
        "tests/test_prepare_app_build_metadata.py",
        "macOS release workflow smoke tests must cover app build metadata preparation",
    ),
    (
        "tests/test_release_candidate_verifier.py",
        "macOS release workflow smoke tests must cover local RC verification gate",
    ),
    (
        "tests/test_electron_ui_smoke_runner.py",
        "macOS release workflow smoke tests must cover the shared Electron UI smoke runner",
    ),
    (
        "tests/test_credential_store.py",
        "macOS release workflow smoke tests must cover release-like CredentialStore guards",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_debug_routes_are_disabled_for_release_metadata",
        "macOS release workflow smoke tests must cover Bridge debug routes release metadata guard",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_debug_routes_are_disabled_for_release_channel_env",
        "macOS release workflow smoke tests must cover Bridge debug routes release channel env guard",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_debug_routes_are_disabled_for_release_flag_env",
        "macOS release workflow smoke tests must cover Bridge debug routes release flag env guard",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_debug_routes_are_disabled_for_packaged_build_env",
        "macOS release workflow smoke tests must cover Bridge debug routes packaged build guard",
    ),
    (
        "tests/test_secret_redaction_verifier.py",
        "macOS release workflow smoke tests must cover runtime secret redaction verifier",
    ),
    (
        "tests/test_security_logging.py",
        "macOS release workflow smoke tests must cover security logging redaction",
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
        "tests/test_launcher_notifications.py",
        "macOS release workflow smoke tests must cover launcher notifications and proactive attention",
    ),
    (
        "tests/test_chat_session.py",
        "macOS release workflow smoke tests must cover ChatSession persistence",
    ),
    (
        "tests/test_chat_store.py",
        "macOS release workflow smoke tests must cover ChatStore persistence and redaction",
    ),
    (
        "tests/test_chat_bridge.py",
        "macOS release workflow smoke tests must cover ChatBridge session summary",
    ),
    (
        "tests/test_chat_api.py::test_send_message_rejects_when_native_agent_unavailable",
        "macOS release workflow smoke tests must cover missing-model Chat API readiness",
    ),
    (
        "tests/test_chat_api.py",
        "macOS release workflow smoke tests must cover Chat API flows",
    ),
    (
        "tests/test_activity_store.py",
        "macOS release workflow smoke tests must cover ActivityStore feed and redaction",
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
        "python scripts/run_electron_ui_smokes.py --report-json release/electron-ui-smoke.json",
        "macOS release workflow smoke tests must run dynamic Electron UI smoke runner and archive its report",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_http_middleware_enforces_host_origin_and_session_token",
        "macOS release workflow smoke tests must cover Bridge Host Origin and session token guard",
    ),
    (
        "tests/test_bridge_server.py::test_bridge_start_and_restart_reject_non_loopback_host_before_binding",
        "macOS release workflow smoke tests must cover Bridge loopback bind guard",
    ),
    (
        "tests/test_bridge_server.py::test_all_registered_mutating_routes_require_bridge_token",
        "macOS release workflow smoke tests must cover mutating Bridge token guard",
    ),
    (
        "tests/test_bridge_server.py::test_post_runs_http_route_rejects_sensitive_idempotency_key_before_persistence",
        "macOS release workflow smoke tests must cover sensitive generic Run Idempotency-Key persistence rejection",
    ),
    (
        "tests/test_bridge_server.py::test_run_events_http_route_paginates_and_hides_non_user_events",
        "macOS release workflow smoke tests must cover RunEvent HTTP replay pagination and filtering",
    ),
    (
        "tests/test_bridge_server.py::test_chat_message_http_route_rejects_sensitive_idempotency_key_header",
        "macOS release workflow smoke tests must cover sensitive Chat Idempotency-Key rejection",
    ),
    (
        "tests/test_bridge_server.py::test_chat_message_image_attachment_http_roundtrip_maps_idempotency_and_file_response",
        "macOS release workflow smoke tests must cover Chat image HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_chat_image_bridge_route_reaches_native_run_events",
        "macOS release workflow smoke tests must cover Chat image NativeRunEngine replay roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_chat_approval_bridge_route_projects_failed_approved_tool",
        "macOS release workflow smoke tests must cover Chat approval failed tool HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_agent_run_http_routes_roundtrip_approval_detail_and_replay",
        "macOS release workflow smoke tests must cover Agent approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_agent_run_http_routes_roundtrip_reject_detail_and_replay",
        "macOS release workflow smoke tests must cover Agent approval reject Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_agent_run_http_routes_roundtrip_cancel_detail_and_replay",
        "macOS release workflow smoke tests must cover Agent approval cancel Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_routes_save_and_run_latest_canvas_with_step_approval_and_artifact",
        "macOS release workflow smoke tests must cover Workflow save-and-run latest canvas route contract",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_approval_transitions_use_shared_context_boundary",
        "macOS release workflow smoke tests must cover Workflow approval shared context boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_approval_resume_context_parses_pending_payload",
        "macOS release workflow smoke tests must cover Workflow approval resume context boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_approval_resume_rejects_out_of_range_next_index",
        "macOS release workflow smoke tests must cover Workflow approval resume index validation",
    ),
    (
        "tests/test_agent_runtime.py::test_workflow_approval_resume_coordinator_claims_and_handoffs",
        "macOS release workflow smoke tests must cover Workflow approval resume coordinator boundary",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_approval_node_http_roundtrip_approve_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_approval_node_http_roundtrip_reject_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow approval reject Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_approval_node_http_roundtrip_cancel_detail_group_and_replay",
        "macOS release workflow smoke tests must cover Workflow approval cancel Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_run_http_routes_roundtrip_child_approval_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow child approval Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_run_http_routes_roundtrip_child_reject_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow child approval reject Run Detail HTTP roundtrip",
    ),
    (
        "tests/test_bridge_server.py::test_workflow_run_http_routes_roundtrip_child_cancel_detail_and_replay",
        "macOS release workflow smoke tests must cover Workflow child approval cancel Run Detail HTTP roundtrip",
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
        "tests/test_bridge_server.py::test_chat_direct_group_agent_bridge_route_runs_native_summary",
        "macOS release workflow smoke tests must cover direct group Agent Native summary flow",
    ),
    (
        "tests/test_bridge_server.py::test_chat_direct_group_agent_bridge_route_runs_rejected_summary",
        "macOS release workflow smoke tests must cover rejected direct group Agent Native summary flow",
    ),
    (
        "tests/test_bridge_server.py::test_chat_direct_group_agent_bridge_route_runs_approved_summary",
        "macOS release workflow smoke tests must cover approved direct group Agent Native summary flow",
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
        "tests/test_tts.py::test_tts_command_invocation_uses_text_voice_and_timeout",
        "macOS release workflow smoke tests must cover TTS command env scrub",
    ),
    (
        "tests/test_display_modes.py",
        "macOS release workflow smoke tests must cover desktop display mode normalization",
    ),
    (
        "tests/test_effect_policy.py",
        "macOS release workflow smoke tests must cover settings effect policy",
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


def _release_electron_ui_smoke_scripts(root: Path) -> tuple[str, ...]:
    scripts_dir = _resolve(root, "scripts")
    if not scripts_dir.is_dir():
        return ()
    scripts: list[str] = []
    for script in sorted(scripts_dir.glob("smoke_*_ui.mjs")):
        if not script.is_file():
            continue
        try:
            scripts.append(script.relative_to(root).as_posix())
        except ValueError:
            continue
    return tuple(scripts)


def _verify_chat_image_attachment_smoke_guard(root: Path) -> list[Finding]:
    script_path = _resolve(root, CHAT_IMAGE_ATTACHMENT_SMOKE_SCRIPT)
    try:
        script = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(script_path, f"could not read Chat image Electron UI smoke script: {exc}")]
    findings: list[Finding] = []
    for required_text, message in CHAT_IMAGE_ATTACHMENT_SMOKE_REQUIRED_TEXT:
        if required_text not in script:
            findings.append(Finding(script_path, message))
    return findings


AGENT_RUN_PROVIDER_CONTRACT_TEST_RE = re.compile(
    r"^def (?P<name>test_agent_run_[A-Za-z0-9_]*(?:http_sse|streaming|responses|function_call|provider_message|sdk|reasoning|refusal)[A-Za-z0-9_]*)\(",
    re.MULTILINE,
)
MAIN_CHAT_PROVIDER_CONTRACT_TEST_RE = re.compile(
    r"^def (?P<name>test_main_chat_model(?:_loop)?_[A-Za-z0-9_]*(?:openai_compatible_sse|sse|stream|streaming|responses|function_call|provider_message|sdk|reasoning|refusal)[A-Za-z0-9_]*)\(",
    re.MULTILINE,
)


def _release_main_chat_provider_contract_tests(root: Path) -> tuple[str, ...]:
    test_file = _resolve(root, "tests/test_agent_runtime.py")
    try:
        text = test_file.read_text(encoding="utf-8")
    except OSError:
        return ()
    tests = [
        f"tests/test_agent_runtime.py::{match.group('name')}"
        for match in MAIN_CHAT_PROVIDER_CONTRACT_TEST_RE.finditer(text)
    ]
    return tuple(dict.fromkeys(tests))


def _release_agent_run_provider_contract_tests(root: Path) -> tuple[str, ...]:
    test_file = _resolve(root, "tests/test_agent_runtime.py")
    try:
        text = test_file.read_text(encoding="utf-8")
    except OSError:
        return ()
    tests = [
        f"tests/test_agent_runtime.py::{match.group('name')}"
        for match in AGENT_RUN_PROVIDER_CONTRACT_TEST_RE.finditer(text)
    ]
    return tuple(dict.fromkeys(tests))


def _release_electron_ui_smoke_selectors(root: Path) -> tuple[str, ...]:
    selectors: set[str] = set()
    for script in _release_electron_ui_smoke_scripts(root):
        script_path = _resolve(root, script)
        try:
            text = script_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in DATA_TESTID_SELECTOR_RE.finditer(text):
            selector = match.group("selector")
            if "$" in selector or "{" in selector:
                continue
            selectors.add(selector)
    return tuple(sorted(selectors))


def _release_electron_ui_smoke_data_attributes(root: Path) -> tuple[str, ...]:
    attributes: set[str] = set()
    for script in _release_electron_ui_smoke_scripts(root):
        script_path = _resolve(root, script)
        try:
            text = script_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in DATA_ATTRIBUTE_RE.finditer(text):
            attribute = match.group(0)
            if attribute == "data-testid":
                continue
            attributes.add(attribute)
    return tuple(sorted(attributes))


def _packaged_ui_e2e_required_selectors(root: Path) -> tuple[str, ...]:
    selectors: list[str] = []
    seen: set[str] = set()
    for selector in (
        *PACKAGED_UI_E2E_REQUIRED_SELECTORS,
        *_release_electron_ui_smoke_selectors(root),
    ):
        if selector in seen:
            continue
        seen.add(selector)
        selectors.append(selector)
    return tuple(selectors)


def _packaged_ui_e2e_required_data_attributes(root: Path) -> tuple[str, ...]:
    attributes: list[str] = []
    seen: set[str] = set()
    for attribute in (
        *PACKAGED_UI_E2E_REQUIRED_DATA_ATTRIBUTES,
        *_release_electron_ui_smoke_data_attributes(root),
    ):
        if attribute in seen:
            continue
        seen.add(attribute)
        attributes.append(attribute)
    return tuple(attributes)


def verify_release_artifacts(
    *,
    root: Path | str = ROOT,
    paths: Sequence[Path | str] | None = None,
    check_required_files: bool = True,
    check_release_security_guards: bool = True,
    check_packaged_app_bundle: bool = False,
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
            relative_path = str(path.resolve().relative_to(root_path.resolve()))
        except ValueError:
            relative_path = str(path)
        for token in FORBIDDEN_TOKENS:
            if token in relative_path:
                findings.append(Finding(path, f"path contains legacy product token {token!r}"))
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

    findings.extend(_verify_release_directory_artifacts(root_path, scan_paths))

    if check_release_security_guards:
        findings.extend(_verify_release_security_guards(root_path))
        findings.extend(_verify_user_facing_release_docs(root_path))
        findings.extend(_verify_release_packaging_documentation(root_path))
        findings.extend(_verify_streaming_provider_smoke_contract_guards(root_path))
        findings.extend(_verify_tracked_generated_artifacts(root_path))
        findings.extend(_verify_release_packaging_guards(root_path))
        findings.extend(_verify_macos_signing_guards(root_path))
        findings.extend(_verify_release_workflow_guards(root_path))

    if check_packaged_app_bundle:
        findings.extend(_verify_packaged_app_bundle(root_path, scan_paths))

    return findings


def _verify_release_directory_artifacts(root: Path, scan_paths: Sequence[Path | str]) -> list[Finding]:
    findings: list[Finding] = []
    release_dirs: set[Path] = set()
    for path in scan_paths:
        resolved = _resolve(root, path)
        if resolved.is_dir() and resolved.name == "release":
            release_dirs.add(resolved)
        elif resolved.is_file() and resolved.parent.name == "release":
            release_dirs.add(resolved.parent)

    for release_dir in sorted(release_dirs):
        findings.extend(_verify_release_dmg_checksum_files(release_dir))
        latest_json_files = sorted(release_dir.glob("Oha-Yachiyo-*-latest.json"))
        if not latest_json_files:
            findings.append(Finding(release_dir, "release directory must include latest channel JSON metadata"))
            continue
        for metadata_path in latest_json_files:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(Finding(metadata_path, f"release latest JSON could not be parsed: {exc.__class__.__name__}"))
                continue
            if not isinstance(metadata, dict):
                findings.append(Finding(metadata_path, "release latest JSON must be an object"))
                continue
            findings.extend(_verify_release_latest_json_metadata(metadata_path, metadata))
            dmg_name = str(metadata.get("dmg_name") or "").strip()
            if not dmg_name:
                findings.append(Finding(metadata_path, "release latest JSON must include dmg_name"))
                continue
            if Path(dmg_name).name != dmg_name:
                findings.append(Finding(metadata_path, "release latest JSON dmg_name must be a filename"))
                continue
            expected_sha = str(metadata.get("sha256") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                findings.append(Finding(metadata_path, "release latest JSON must include a 64-character sha256"))
                continue
            download_url = str(metadata.get("download_url") or "")
            if dmg_name not in download_url:
                findings.append(Finding(metadata_path, "release latest JSON download_url must reference dmg_name"))
            latest_json_url = str(metadata.get("latest_json_url") or "")
            if latest_json_url and metadata_path.name not in latest_json_url:
                findings.append(Finding(metadata_path, "release latest JSON latest_json_url must reference its metadata filename"))

            dmg_path = release_dir / dmg_name
            sha_path = release_dir / f"{dmg_name}.sha256"
            if not dmg_path.is_file():
                findings.append(Finding(dmg_path, "release latest JSON dmg_name does not exist"))
                continue
            if not sha_path.is_file():
                findings.append(Finding(sha_path, "release latest DMG checksum file is missing"))
                continue
            try:
                sha_file_value = sha_path.read_text(encoding="utf-8").split()[0].strip().lower()
            except (OSError, IndexError) as exc:
                findings.append(Finding(sha_path, f"release latest DMG checksum could not be read: {exc.__class__.__name__}"))
                continue
            if sha_file_value != expected_sha:
                findings.append(Finding(sha_path, "release latest DMG checksum does not match latest JSON sha256"))
                continue
            try:
                actual_sha = _sha256_file(dmg_path)
            except OSError as exc:
                findings.append(Finding(dmg_path, f"release latest DMG could not be hashed: {exc}"))
                continue
            if actual_sha != expected_sha:
                findings.append(Finding(dmg_path, "release latest DMG content does not match latest JSON sha256"))
    return findings


def _is_safe_release_source_branch(value: str) -> bool:
    if not RELEASE_SOURCE_BRANCH_RE.fullmatch(value):
        return False
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value:
        return False
    return True


def _verify_release_latest_json_metadata(metadata_path: Path, metadata: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    required_fields = (
        "name",
        "channel",
        "branch",
        "source_branch",
        "version",
        "base_version",
        "commit",
        "short_commit",
        "build_number",
        "run_number",
        "run_id",
        "tag",
        "signing",
        "dmg_name",
        "sha256",
        "download_url",
        "latest_json_url",
        "published_at",
        "changelog",
    )
    for field_name in required_fields:
        value = metadata.get(field_name)
        if value in (None, ""):
            findings.append(Finding(metadata_path, f"release latest JSON must include {field_name}"))
    if metadata.get("name") != "Oha-Yachiyo":
        findings.append(Finding(metadata_path, "release latest JSON name must be Oha-Yachiyo"))

    match = RELEASE_LATEST_JSON_RE.fullmatch(metadata_path.name)
    if not match:
        findings.append(Finding(metadata_path, "release latest JSON filename must identify a known latest branch"))
        return findings
    expected_branch = match.group("branch")
    expected_channel = RELEASE_LATEST_BRANCH_CHANNELS[expected_branch]
    expected_latest_tag = f"{expected_branch}-latest"
    if metadata.get("branch") != expected_branch:
        findings.append(Finding(metadata_path, "release latest JSON branch must match its filename"))
    if metadata.get("channel") != expected_channel:
        findings.append(Finding(metadata_path, "release latest JSON channel must match its filename branch"))
    source_branch = str(metadata.get("source_branch") or "")
    if not _is_safe_release_source_branch(source_branch):
        findings.append(Finding(metadata_path, "release latest JSON source_branch must be a safe branch name"))
    expected_dmg = f"Oha-Yachiyo-{expected_branch}-latest.dmg"
    if metadata.get("dmg_name") != expected_dmg:
        findings.append(Finding(metadata_path, "release latest JSON dmg_name must match its filename branch"))
    download_url = str(metadata.get("download_url") or "")
    if f"/releases/download/{expected_latest_tag}/" not in download_url:
        findings.append(Finding(metadata_path, "release latest JSON download_url must reference its latest channel tag"))
    latest_json_url = str(metadata.get("latest_json_url") or "")
    if f"/releases/download/{expected_latest_tag}/" not in latest_json_url:
        findings.append(Finding(metadata_path, "release latest JSON latest_json_url must reference its latest channel tag"))
    version = str(metadata.get("version") or "")
    base_version = str(metadata.get("base_version") or "")
    if not RELEASE_SEMVER_RE.fullmatch(version):
        findings.append(Finding(metadata_path, "release latest JSON version must be semver"))
    if not RELEASE_SEMVER_RE.fullmatch(base_version):
        findings.append(Finding(metadata_path, "release latest JSON base_version must be semver"))
    commit = str(metadata.get("commit") or "")
    short_commit = str(metadata.get("short_commit") or "")
    if not RELEASE_SHA_RE.fullmatch(commit):
        findings.append(Finding(metadata_path, "release latest JSON commit must be a 40-character git SHA"))
    if not RELEASE_SHORT_SHA_RE.fullmatch(short_commit):
        findings.append(Finding(metadata_path, "release latest JSON short_commit must be a 7-character git SHA prefix"))
    if commit and short_commit and not commit.lower().startswith(short_commit.lower()):
        findings.append(Finding(metadata_path, "release latest JSON short_commit must prefix commit"))
    if not isinstance(metadata.get("build_number"), int):
        findings.append(Finding(metadata_path, "release latest JSON build_number must be an integer"))
    if not isinstance(metadata.get("run_number"), int):
        findings.append(Finding(metadata_path, "release latest JSON run_number must be an integer"))
    if not str(metadata.get("run_id") or "").isdigit():
        findings.append(Finding(metadata_path, "release latest JSON run_id must be numeric"))
    signing = str(metadata.get("signing") or "")
    if signing not in RELEASE_LATEST_SIGNING_MODES:
        findings.append(Finding(metadata_path, "release latest JSON signing must be a known signing mode"))
    published_at = str(metadata.get("published_at") or "")
    if not RELEASE_PUBLISHED_AT_RE.fullmatch(published_at):
        findings.append(Finding(metadata_path, "release latest JSON published_at must be UTC ISO-8601"))
    tag = str(metadata.get("tag") or "")
    expected_tag_prefix = f"{expected_channel}-v{version}-build.{metadata.get('build_number')}-"
    if tag and short_commit and tag != f"{expected_tag_prefix}{short_commit}":
        findings.append(Finding(metadata_path, "release latest JSON tag must match channel version build and short_commit"))
    if not isinstance(metadata.get("changelog"), dict):
        findings.append(Finding(metadata_path, "release latest JSON changelog must be an object"))
    return findings


def _verify_release_dmg_checksum_files(release_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    for dmg_path in sorted(release_dir.glob("*.dmg")):
        sha_path = release_dir / f"{dmg_path.name}.sha256"
        if not sha_path.is_file():
            findings.append(Finding(sha_path, "release DMG checksum file is missing"))
            continue
        try:
            sha_file_value = sha_path.read_text(encoding="utf-8").split()[0].strip().lower()
        except (OSError, IndexError) as exc:
            findings.append(Finding(sha_path, f"release DMG checksum could not be read: {exc.__class__.__name__}"))
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", sha_file_value):
            findings.append(Finding(sha_path, "release DMG checksum file must start with a 64-character sha256"))
            continue
        try:
            actual_sha = _sha256_file(dmg_path)
        except OSError as exc:
            findings.append(Finding(dmg_path, f"release DMG could not be hashed: {exc}"))
            continue
        if actual_sha != sha_file_value:
            findings.append(Finding(dmg_path, "release DMG content does not match checksum file"))
    return findings


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _release_guard_env(metadata_path: Path, *, packaged: bool = False):
    saved = {key: os.environ.get(key) for key in _BUILD_GUARD_ENV_KEYS}
    try:
        for key in _BUILD_GUARD_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["OHA_YACHIYO_DEV"] = "1"
        os.environ["OHA_YACHIYO_BUILD_METADATA"] = str(metadata_path)
        if packaged:
            os.environ["OHA_YACHIYO_PACKAGED_BUILD"] = "1"
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
        packaged_metadata = temp_root / "packaged.json"
        packaged_metadata.write_text(json.dumps({"channel": "experimental"}), encoding="utf-8")
        with _release_guard_env(packaged_metadata, packaged=True):
            if build_metadata.development_features_enabled():
                findings.append(
                    Finding(
                        root / "apps" / "core" / "build_metadata.py",
                        "packaged build env must disable development features even when OHA_YACHIYO_DEV=1",
                    )
                )
            if bridge_server.debug_routes_enabled():
                findings.append(
                    Finding(
                        root / "apps" / "bridge" / "server.py",
                        "packaged build env must disable debug routes even when OHA_YACHIYO_DEV=1",
                    )
                )
            if credential_store.development_credential_fallback_enabled():
                findings.append(
                    Finding(
                        root / "apps" / "shell" / "credential_store.py",
                        "packaged build env must disable development credential fallback",
                    )
                )
            try:
                store = credential_store.DevFileCredentialStore(temp_root / "packaged" / "credentials.dev.json")
            except credential_store.CredentialStoreError:
                pass
            else:
                store.close()
                findings.append(
                    Finding(
                        root / "apps" / "shell" / "credential_store.py",
                        "packaged build env must not allow DevFileCredentialStore",
                    )
                )
    return findings


def _verify_release_packaging_documentation(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    path = _resolve(root, RELEASE_PACKAGING_DOC_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(path, f"could not read release packaging docs: {exc}")]
    for required_text, message in RELEASE_PACKAGING_DOC_REQUIRED_TEXT:
        if required_text not in text:
            findings.append(Finding(path, message))
    return findings


def _verify_user_facing_release_docs(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    cached_text: dict[Path, str] = {}
    for relative_path, required_text, message in USER_FACING_RELEASE_DOC_REQUIRED_TEXT:
        path = _resolve(root, relative_path)
        if path not in cached_text:
            try:
                cached_text[path] = path.read_text(encoding="utf-8")
            except OSError as exc:
                findings.append(Finding(path, f"could not read user-facing release docs: {exc}"))
                cached_text[path] = ""
        if required_text not in cached_text[path]:
            findings.append(Finding(path, message))
    return findings


def _verify_streaming_provider_smoke_contract_guards(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    targets = (
        (
            Path("scripts/smoke_openai_compatible_stream.py"),
            STREAMING_PROVIDER_SMOKE_SCRIPT_REQUIRED_TEXT,
        ),
        (
            Path("tests/test_streaming_provider_smoke.py"),
            STREAMING_PROVIDER_SMOKE_TEST_REQUIRED_TEXT,
        ),
        (
            Path("scripts/verify_release_candidate.py"),
            RELEASE_CANDIDATE_PROVIDER_SMOKE_REQUIRED_TEXT,
        ),
        (
            Path("scripts/verify_release_candidate.py"),
            RELEASE_CANDIDATE_VERIFIER_REQUIRED_TEXT,
        ),
        (
            Path("scripts/run_electron_ui_smokes.py"),
            ELECTRON_UI_SMOKE_RUNNER_REQUIRED_TEXT,
        ),
        (
            PACKAGED_UI_SAMPLING_SMOKE_SCRIPT,
            PACKAGED_UI_SAMPLING_SMOKE_REQUIRED_TEXT,
        ),
        (
            PACKAGED_CHAT_NATIVE_FILE_SMOKE_SCRIPT,
            PACKAGED_CHAT_NATIVE_FILE_SMOKE_REQUIRED_TEXT,
        ),
        (
            Path("apps/frontend/electron/main.ts"),
            ELECTRON_MAIN_CHAT_NATIVE_FILE_SMOKE_REQUIRED_TEXT,
        ),
    )
    for relative_path, required_texts in targets:
        path = _resolve(root, relative_path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding(path, f"could not read provider smoke contract source: {exc}"))
            continue
        for required_text, message in required_texts:
            if required_text not in text:
                findings.append(Finding(path, message))
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


def _packaged_app_dirs_from_paths(root: Path, paths: Sequence[Path | str]) -> list[Path]:
    app_dirs: list[Path] = []
    seen: set[Path] = set()

    def add_app_dir(candidate: Path) -> None:
        if candidate.name != PACKAGED_APP_NAME or not candidate.is_dir():
            return
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            return
        seen.add(resolved)
        app_dirs.append(candidate)

    for path in paths:
        resolved = _resolve(root, path)
        for candidate in (resolved, *resolved.parents):
            add_app_dir(candidate)
        if resolved.is_dir():
            for app_dir in sorted(resolved.rglob(PACKAGED_APP_NAME)):
                add_app_dir(app_dir)

    return app_dirs


def _verify_packaged_app_bundle(
    root: Path, paths: Sequence[Path | str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    output_dir = _resolve(root, PACKAGED_APP_OUTPUT_DIR)
    app_dirs = _packaged_app_dirs_from_paths(root, paths) if paths is not None else []
    if not app_dirs:
        app_dirs = sorted(output_dir.rglob(PACKAGED_APP_NAME)) if output_dir.exists() else []
    if not app_dirs:
        return [
            Finding(
                output_dir / PACKAGED_APP_NAME,
                "packaged app bundle must exist under dist/electron",
            )
        ]

    for app_dir in app_dirs:
        info_path = app_dir / "Contents" / "Info.plist"
        executable_name = ""
        if not info_path.is_file():
            findings.append(Finding(info_path, "packaged app Info.plist is missing"))
        else:
            try:
                info = plistlib.loads(info_path.read_bytes())
            except Exception as exc:
                findings.append(
                    Finding(info_path, f"packaged app Info.plist could not be parsed: {exc.__class__.__name__}")
                )
            else:
                bundle_names = {
                    str(info.get("CFBundleName") or "").strip(),
                    str(info.get("CFBundleDisplayName") or "").strip(),
                    str(info.get("CFBundleExecutable") or "").strip(),
                }
                if "Oha-Yachiyo" not in bundle_names:
                    findings.append(Finding(info_path, "packaged app Info.plist must identify Oha-Yachiyo"))
                if info.get("CFBundleIdentifier") != PACKAGED_APP_IDENTIFIER:
                    findings.append(
                        Finding(
                            info_path,
                            f"packaged app bundle identifier must be {PACKAGED_APP_IDENTIFIER}",
                        )
                    )
                executable_name = str(info.get("CFBundleExecutable") or "").strip()
                if not executable_name:
                    findings.append(Finding(info_path, "packaged app Info.plist must declare CFBundleExecutable"))
                for key, expected, message in PACKAGED_INFO_REQUIRED_VALUES:
                    if info.get(key) != expected:
                        findings.append(Finding(info_path, message))
                for key, message in PACKAGED_INFO_REQUIRED_PERMISSION_KEYS:
                    value = str(info.get(key) or "").strip()
                    if not value or "Oha-Yachiyo" not in value:
                        findings.append(Finding(info_path, message))

        if executable_name:
            executable_path = app_dir / "Contents" / "MacOS" / executable_name
            if not executable_path.is_file():
                findings.append(Finding(executable_path, "packaged app main executable is missing"))
            elif not os.access(executable_path, os.X_OK):
                findings.append(Finding(executable_path, "packaged app main executable is not executable"))

        backend_path = app_dir / PACKAGED_BACKEND_RELATIVE_PATH
        if not backend_path.is_file():
            findings.append(Finding(backend_path, "packaged backend executable is missing from app resources"))
        elif not os.access(backend_path, os.X_OK):
            findings.append(Finding(backend_path, "packaged backend executable is not executable"))
        else:
            try:
                backend_bytes = backend_path.read_bytes()
            except OSError as exc:
                findings.append(Finding(backend_path, f"packaged backend executable could not be read: {exc}"))
            else:
                if PACKAGED_BACKEND_BUILD_METADATA_MARKER not in backend_bytes:
                    findings.append(
                        Finding(
                            backend_path,
                            "packaged backend executable must include the app build metadata resource",
                        )
                    )

        asar_path = app_dir / PACKAGED_ASAR_RELATIVE_PATH
        if not asar_path.is_file():
            findings.append(Finding(asar_path, "packaged Electron app.asar is missing from app resources"))
        else:
            try:
                asar_bytes = asar_path.read_bytes()
            except OSError as exc:
                findings.append(Finding(asar_path, f"packaged Electron app.asar could not be read: {exc}"))
            else:
                for selector in _packaged_ui_e2e_required_selectors(root):
                    if selector.encode("utf-8") not in asar_bytes:
                        findings.append(
                            Finding(
                                asar_path,
                                f"packaged Electron app.asar must include UI E2E selector {selector!r}",
                            )
                        )
                for attribute in _packaged_ui_e2e_required_data_attributes(root):
                    if attribute.encode("utf-8") not in asar_bytes:
                        findings.append(
                            Finding(
                                asar_path,
                                f"packaged Electron app.asar must include UI E2E data attribute {attribute!r}",
                            )
                        )
                for forbidden in PACKAGED_UI_E2E_FORBIDDEN_TEXT:
                    if forbidden.encode("utf-8") in asar_bytes:
                        findings.append(
                            Finding(
                                asar_path,
                                f"packaged Electron app.asar must not include development-only UI E2E hook {forbidden!r}",
                            )
                        )

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
    main_chat_provider_contract_tests = _release_main_chat_provider_contract_tests(root)
    for test_path in main_chat_provider_contract_tests:
        if test_path not in workflow:
            findings.append(
                Finding(
                    workflow_path,
                    f"macOS release workflow smoke tests must run Main Chat provider contract {test_path}",
                )
            )
    agent_run_provider_contract_tests = _release_agent_run_provider_contract_tests(root)
    for test_path in agent_run_provider_contract_tests:
        if test_path not in workflow:
            findings.append(
                Finding(
                    workflow_path,
                    f"macOS release workflow smoke tests must run Agent Run provider contract {test_path}",
                )
            )
    findings.extend(_verify_chat_image_attachment_smoke_guard(root))

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
    provider_smoke = workflow.find("provider_smoke_args+=(--run-provider-smoke)")
    write_metadata = workflow.find("Write app build metadata")
    write_metadata_script = workflow.find("python scripts/prepare_app_build_metadata.py")
    build_backend = workflow.find("Build packaged backend")
    build_dmg = workflow.find("Build Electron DMG")
    verify_packaged_resources = workflow.find("Verify packaged app resources")
    prepare_release = workflow.find("Prepare release metadata")
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
    if build_backend >= 0 and build_dmg >= 0:
        for required_text, message in RELEASE_WORKFLOW_SMOKE_TEST_REQUIRED_TEXT:
            required_index = workflow.find(required_text)
            if (
                required_index >= 0
                and (required_index > build_backend or required_index > build_dmg)
            ):
                findings.append(
                    Finding(
                        workflow_path,
                        f"macOS release workflow smoke guard must run before packaged backend and DMG builds: {message}",
                    )
                )
        for test_path in main_chat_provider_contract_tests:
            required_index = workflow.find(test_path)
            if (
                required_index >= 0
                and (required_index > build_backend or required_index > build_dmg)
            ):
                findings.append(
                    Finding(
                        workflow_path,
                        "macOS release workflow Main Chat provider contract must run before "
                        f"packaged backend and DMG builds: {test_path}",
                    )
                )
        for test_path in agent_run_provider_contract_tests:
            required_index = workflow.find(test_path)
            if (
                required_index >= 0
                and (required_index > build_backend or required_index > build_dmg)
            ):
                findings.append(
                    Finding(
                        workflow_path,
                        "macOS release workflow Agent Run provider contract must run before "
                        f"packaged backend and DMG builds: {test_path}",
                    )
                )
    if (
        write_metadata < 0
        or build_backend < 0
        or build_dmg < 0
        or write_metadata > build_backend
        or write_metadata > build_dmg
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must write app build metadata before packaged backend and DMG builds",
            )
        )
    if write_metadata_script < 0:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must write app build metadata through scripts/prepare_app_build_metadata.py",
            )
        )
    elif (
        build_backend < 0
        or build_dmg < 0
        or write_metadata_script > build_backend
        or write_metadata_script > build_dmg
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must run app build metadata script before packaged backend and DMG builds",
            )
        )
    if (
        verify_packaged_resources < 0
        or build_dmg < 0
        or prepare_release < 0
        or verify_packaged_resources < build_dmg
        or verify_packaged_resources > prepare_release
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must verify packaged app resources after DMG build before release metadata",
            )
        )
    if signing_import >= 0 and build_dmg >= 0 and signing_import > build_dmg:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must import signing material before building the DMG",
            )
        )
    verify_release = workflow.find("Verify packaged release artifacts")
    if prepare_release < 0 or verify_release < 0 or verify_release < prepare_release:
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must verify release artifacts after preparing release metadata",
            )
        )
    verify_rc = workflow.find("python scripts/verify_release_candidate.py --require-artifacts")
    write_signoff_draft = workflow.find(
        "--manual-checks-json release/rc-verification.json --manual-checks-json release/electron-ui-smoke.json --write-manual-checks-draft release/manual-rc-checks.draft.json"
    )
    write_signoff_markdown = workflow.find(
        "--manual-checks-json release/manual-rc-checks.draft.json --write-manual-checks-markdown release/manual-rc-checks.md"
    )
    upload_artifact = workflow.find("Upload DMG artifact")
    if (
        prepare_release < 0
        or verify_rc < 0
        or upload_artifact < 0
        or verify_rc < prepare_release
        or verify_rc > upload_artifact
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must run local RC verification gate after preparing release artifacts before upload",
            )
        )
    if (
        verify_rc < 0
        or write_signoff_draft < 0
        or upload_artifact < 0
        or write_signoff_draft < verify_rc
        or write_signoff_draft > upload_artifact
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must generate manual RC check draft after the RC report before upload",
            )
        )
    if (
        write_signoff_draft < 0
        or write_signoff_markdown < 0
        or upload_artifact < 0
        or write_signoff_markdown < write_signoff_draft
        or write_signoff_markdown > upload_artifact
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must generate manual RC check Markdown after the draft before upload",
            )
        )
    if (
        provider_smoke < 0
        or verify_rc < 0
        or upload_artifact < 0
        or provider_smoke > verify_rc
        or provider_smoke > upload_artifact
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must fold opt-in provider smoke into the RC verification report before upload",
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
    parser.add_argument(
        "--check-packaged-app",
        action="store_true",
        help="Verify the built macOS .app bundle structure under dist/electron.",
    )
    args = parser.parse_args(argv)

    findings = verify_release_artifacts(
        paths=args.paths or None,
        allow_binary_targets=args.allow_binary,
        check_packaged_app_bundle=args.check_packaged_app,
    )
    if not findings:
        print("release artifact verification passed")
        return 0

    print("release artifact verification failed:")
    for finding in findings:
        print(f"- {finding.format()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
