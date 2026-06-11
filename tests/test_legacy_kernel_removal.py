"""Source-level guards for removed Hermes execution-kernel entry points."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_TARGETS = [
    ROOT / "apps",
    ROOT / "integrations",
    ROOT / "packages",
    ROOT / "scripts",
    ROOT / "pyproject.toml",
]
ACTIVE_USER_DOC_TARGETS = [
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "README.ja.md",
    ROOT / "docs" / "desktop-frontend-architecture.md",
    ROOT / "docs" / "live2d-assets.md",
    ROOT / "docs" / "release-packaging.md",
    ROOT / "docs" / "tts-voice-assets.md",
]
IGNORED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".vite",
    "dist",
    "dist-electron",
    "node_modules",
}
TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_KERNEL_TOKENS = [
    "HermesExecutor",
    "HermesUnavailableExecutor",
    "Hermes CLI",
    "Hermes stream",
    "Hermes installer",
    "Hermes readiness",
    "Hermes-Yachiyo",
    "hermes-yachiyo",
    "HERMES_YACHIYO",
    "/ui/hermes",
    "hermes/install",
    "hermes/status",
    "hermes/config",
    "hermes_profile",
    "hermes_provider",
    "hermes_toolsets",
    "can_use_as_hermes",
    "syncHermes",
    "run_yachiyo",
    "yachiyo_delegation",
    "yachiyo_group_dispatch",
    "yachiyo_only",
    "YACHIYO_ONLY",
    "include_hermes",
    "INCLUDE_HERMES",
    "hermes_home",
    "get_yachiyo_workspace_dir",
    "yachiyo_workspace",
    "yachiyo-workspace",
    "yachiyo_agent",
    "Runtime: Yachiyo Agent Runtime",
    ".yachiyo_init",
    "configs/yachiyo.json",
]
FORBIDDEN_ACTIVE_DOC_TOKENS = [
    "Hermes",
    "hermes",
    "HERMES",
    "Hermes-Yachiyo",
    "hermes-yachiyo",
    "HERMES_YACHIYO",
    "HermesRuntime",
    "Hermes Agent",
    "Hermes installer",
    "Hermes readiness",
    "Hermes 状态",
    "hermes setup",
    "hermes status",
    "hermes config",
    "~/.hermes-yachiyo",
    "~/.hermes/yachiyo",
    "github.com/kuguya-AI-app-develop/Hermes-Yachiyo",
    "github.com/kuguya-AI-app-develop/Oha-Yachiyo",
]


def _iter_source_files():
    for target in SCAN_TARGETS:
        if target.is_file():
            yield target
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path.suffix not in TEXT_SUFFIXES:
                continue
            yield path


def test_runtime_sources_do_not_reintroduce_legacy_hermes_kernel_entrypoints() -> None:
    findings: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_KERNEL_TOKENS:
            if token in text:
                findings.append(f"{path.relative_to(ROOT)} contains {token!r}")

    assert findings == []


def test_active_user_facing_docs_do_not_reintroduce_legacy_hermes_identity() -> None:
    findings: list[str] = []
    for path in ACTIVE_USER_DOC_TARGETS:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_ACTIVE_DOC_TOKENS:
            if token in text:
                findings.append(f"{path.relative_to(ROOT)} contains {token!r}")

    assert findings == []
