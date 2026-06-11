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
_OLD_KERNEL_NAME = "Her" "mes"
_OLD_KERNEL_LOWER = "her" "mes"
_OLD_PROTOCOL_PRODUCT = "yachi" "yo"
_LEGACY_KERNEL_TOKENS: tuple[str, ...] = (
    f"{_OLD_KERNEL_NAME}Executor",
    f"{_OLD_KERNEL_NAME}UnavailableExecutor",
    f"{_OLD_KERNEL_NAME} CLI",
    f"{_OLD_KERNEL_NAME} stream",
    f"{_OLD_KERNEL_NAME} installer",
    f"{_OLD_KERNEL_NAME} readiness",
    f"/ui/{_OLD_KERNEL_LOWER}",
    f"{_OLD_KERNEL_LOWER}/install",
    f"{_OLD_KERNEL_LOWER}/status",
    f"{_OLD_KERNEL_LOWER}/config",
    f"{_OLD_KERNEL_LOWER}_profile",
    f"{_OLD_KERNEL_LOWER}_provider",
    f"{_OLD_KERNEL_LOWER}_toolsets",
    f"can_use_as_{_OLD_KERNEL_LOWER}",
    f"sync{_OLD_KERNEL_NAME}",
    f"include_{_OLD_KERNEL_LOWER}",
    f"INCLUDE_{_OLD_KERNEL_LOWER.upper()}",
    f"{_OLD_KERNEL_LOWER}_home",
    f"{_OLD_KERNEL_LOWER}_stream_bridge",
    f"{_OLD_KERNEL_LOWER}-bridge",
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
    (
        "Run opt-in real provider streaming smoke",
        "macOS release workflow must expose opt-in real provider streaming smoke",
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
        "python scripts/smoke_openai_compatible_stream.py",
        "macOS release workflow must run the real provider streaming smoke helper when configured",
    ),
    (
        "--require-content",
        "macOS release workflow provider smoke must require streamed content",
    ),
    (
        "--require-tool-call",
        "macOS release workflow provider smoke must require streamed tool calls",
    ),
    (
        "--expect-tool-name workspace_read",
        "macOS release workflow provider smoke must assert the workspace_read tool call",
    ),
    (
        "--expect-tool-argument-substring README.md",
        "macOS release workflow provider smoke must assert the workspace_read README argument",
    ),
    (
        "--expect-tool-argument-json-field path=README.md",
        "macOS release workflow provider smoke must assert the workspace_read path JSON field",
    ),
    (
        "--expect-finish-reason tool_calls",
        "macOS release workflow provider smoke must assert tool-call finish_reason",
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
        "tests/test_agent_runtime.py::test_main_chat_approval_timeout_records_replayable_fact_and_is_idempotent",
        "macOS release workflow smoke tests must cover Native approval timeout replay idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_records_failed_run_event_when_approved_tool_fails",
        "macOS release workflow smoke tests must cover main chat approved tool failure replay",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_repeated_approval_does_not_execute_tool_twice",
        "macOS release workflow smoke tests must cover main chat repeated approval idempotency",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_durable_approval_claim_blocks_duplicate_execution",
        "macOS release workflow smoke tests must cover durable approval claim across runtime instances",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_executes_approved_tool_and_remaining_requests",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator approved tool resume flow",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_stops_on_fatal_tool_failure",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator fatal tool failure boundary",
    ),
    (
        "tests/test_agent_runtime.py::test_approval_resume_coordinator_continues_custom_api_agent_after_approved_tool",
        "macOS release workflow smoke tests must cover ApprovalResumeCoordinator custom API resume flow",
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
        "tests/test_bridge_server.py::test_run_cancel_route_handler_is_idempotent",
        "macOS release workflow smoke tests must cover UI Run cancel route idempotency",
    ),
    (
        "tests/test_bridge_server.py::test_chat_cancel_bridge_route_cancels_native_run_and_ignores_late_output",
        "macOS release workflow smoke tests must cover Chat cancel late-output HTTP roundtrip",
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
        "tests/test_agent_runtime.py::test_run_event_repository_allocates_sequences_under_concurrent_writers",
        "macOS release workflow smoke tests must cover RunEvent concurrent replay cursor projection",
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
        "tests/test_agent_runtime.py::test_main_chat_tool_exception_is_redacted_from_tool_messages_events_and_storage",
        "macOS release workflow smoke tests must cover tool exception redaction",
    ),
    (
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_sse_delta_tool_call_object_arguments",
        "macOS release workflow smoke tests must cover NativeRunEngine SSE object tool-call arguments",
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
        "tests/test_credential_store.py",
        "macOS release workflow smoke tests must cover release-like CredentialStore guards",
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
        "tests/test_bridge_server.py::test_chat_delegated_summary_bridge_route_runs_native_followup",
        "macOS release workflow smoke tests must cover auto delegation Native summary flow",
    ),
    (
        "tests/test_tts.py",
        "macOS release workflow smoke tests must cover manual TTS",
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

    if check_release_security_guards:
        findings.extend(_verify_release_security_guards(root_path))
        findings.extend(_verify_tracked_generated_artifacts(root_path))
        findings.extend(_verify_release_packaging_guards(root_path))
        findings.extend(_verify_macos_signing_guards(root_path))
        findings.extend(_verify_release_workflow_guards(root_path))

    return findings


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
    provider_smoke = workflow.find("Run opt-in real provider streaming smoke")
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
    if (
        provider_smoke < 0
        or build_backend < 0
        or build_dmg < 0
        or provider_smoke > build_backend
        or provider_smoke > build_dmg
    ):
        findings.append(
            Finding(
                workflow_path,
                "macOS release workflow must run opt-in real provider streaming smoke before packaged backend and DMG builds",
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
