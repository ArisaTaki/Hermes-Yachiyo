from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGET_SCRIPT = ROOT / "scripts" / "check_frontend_bundle_budget.mjs"
LAUNCHER_TASK_LIGHT = (
    ROOT
    / "apps"
    / "frontend"
    / "src"
    / "features"
    / "yachiyo-chat"
    / "components"
    / "LauncherAgentTaskLight.tsx"
)
TASK_PERMISSION_RECOVERY = (
    ROOT
    / "apps"
    / "frontend"
    / "src"
    / "features"
    / "yachiyo-chat"
    / "taskPermissionRecovery.ts"
)
OPEN_DESIGN_VIEW = ROOT / "apps" / "frontend" / "src" / "views" / "OpenDesignView.tsx"
AGENT_STUDIO_VIEW = ROOT / "apps" / "frontend" / "src" / "views" / "AgentStudioView.tsx"
AGENT_STUDIO_CHROME = (
    ROOT
    / "apps"
    / "frontend"
    / "src"
    / "features"
    / "agent-studio"
    / "components"
    / "AgentStudioChrome.tsx"
)


def _write_asset(dist: Path, relative_path: str, content: str) -> None:
    target = dist / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_bundle_budget_reports_manifest_static_closures(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_asset(dist, "assets/index.js", "index-entry")
    _write_asset(dist, "assets/shared.js", "shared-runtime")
    _write_asset(dist, "assets/index.css", "index-css")
    _write_asset(dist, "assets/shared.css", "shared-css")
    _write_asset(dist, "assets/studio.js", "studio-entry")
    _write_asset(dist, "assets/studio-shared.js", "studio-shared-runtime")
    _write_asset(dist, "assets/studio.css", "studio-css")
    manifest = {
        "index.html": {
            "file": "assets/index.js",
            "isEntry": True,
            "imports": ["_shared.js"],
            "css": ["assets/index.css"],
        },
        "_shared.js": {
            "file": "assets/shared.js",
            "css": ["assets/shared.css"],
        },
        "_studio-shared.js": {"file": "assets/studio-shared.js"},
        "src/views/AgentStudioView.tsx": {
            "file": "assets/studio.js",
            "isDynamicEntry": True,
            "imports": ["index.html", "_studio-shared.js"],
            "css": ["assets/studio.css"],
        },
    }
    manifest_path = dist / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = subprocess.run(
        [
            "node",
            str(BUDGET_SCRIPT),
            "--dist",
            str(dist),
            "--manifest",
            str(manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["mode"] == "freeze"
    assert report["boot"]["js"]["files"] == [
        "assets/index.js",
        "assets/shared.js",
    ]
    assert report["boot"]["js"]["raw"] == len("index-entryshared-runtime")
    assert report["boot"]["css"]["files"] == [
        "assets/index.css",
        "assets/shared.css",
    ]
    assert report["studio_incremental"]["js"]["files"] == [
        "assets/studio-shared.js",
        "assets/studio.js",
    ]
    assert report["studio_incremental"]["js"]["raw"] == len(
        "studio-shared-runtimestudio-entry"
    )
    assert report["studio_incremental"]["css"]["files"] == ["assets/studio.css"]
    assert report["boot_plus_studio"]["raw"] == len(
        "index-entryshared-runtimeindex-cssshared-css"
        "studio-shared-runtimestudio-entrystudio-css"
    )
    assert report["max_js_chunk"]["file"] == "assets/studio-shared.js"
    assert report["max_js_chunk"]["raw"] == len("studio-shared-runtime")


def test_target_budget_exits_nonzero_and_writes_json_report(tmp_path) -> None:
    dist = tmp_path / "dist"
    _write_asset(dist, "assets/index.js", "x" * 430_001)
    _write_asset(dist, "assets/studio.js", "studio")
    manifest = {
        "index.html": {
            "file": "assets/index.js",
            "isEntry": True,
        },
        "src/views/AgentStudioView.tsx": {
            "file": "assets/studio.js",
            "isDynamicEntry": True,
            "imports": ["index.html"],
        },
    }
    manifest_path = dist / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path = tmp_path / "budget-report.json"

    result = subprocess.run(
        [
            "node",
            str(BUDGET_SCRIPT),
            "--dist",
            str(dist),
            "--manifest",
            str(manifest_path),
            "--mode",
            "target",
            "--report-json",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert report["ok"] is False
    assert report["mode"] == "target"
    boot_raw_check = next(
        check for check in report["checks"] if check["metric"] == "boot_js_raw"
    )
    assert boot_raw_check == {
        "metric": "boot_js_raw",
        "actual": 430_001,
        "limit": 420_000,
        "ok": False,
    }


def test_launcher_permission_recovery_does_not_import_full_task_card() -> None:
    launcher_source = LAUNCHER_TASK_LIGHT.read_text(encoding="utf-8")
    recovery_source = TASK_PERMISSION_RECOVERY.read_text(encoding="utf-8")

    assert "from '../taskPermissionRecovery'" in launcher_source
    assert "from './AgentTaskCard'" not in launcher_source
    assert "export type TaskPermissionRecoveryAction" in recovery_source
    assert "export function taskPermissionRecoveryFromTaskFacts" in recovery_source


def test_open_design_defers_launcher_task_ui_behind_local_suspense() -> None:
    source = OPEN_DESIGN_VIEW.read_text(encoding="utf-8")

    assert "import { LauncherAgentTaskLight }" not in source
    assert "const LauncherAgentTaskLight = lazy(() =>" in source
    assert "import('../features/yachiyo-chat/components/LauncherAgentTaskLight')" in source
    assert "function LauncherAgentTaskLightFallback" in source
    assert 'data-testid={`${mode}-mode-agent-task-loading`}' in source
    assert source.count("<Suspense fallback={<LauncherAgentTaskLightFallback") == 2


def test_studio_defers_non_default_heavy_tabs_with_preload_and_local_suspense() -> None:
    view_source = AGENT_STUDIO_VIEW.read_text(encoding="utf-8")
    chrome_source = AGENT_STUDIO_CHROME.read_text(encoding="utf-8")

    for component in (
        "AgentStudioGroupsTab",
        "AgentStudioRunsTab",
        "AgentStudioToolsTab",
        "AgentStudioWorkflowsTab",
    ):
        assert f"import {{ {component} }}" not in view_source
        assert f"const {component} = lazy(() =>" in view_source

    assert "function preloadAgentStudioTab" in view_source
    assert "function StudioTabSuspense" in view_source
    assert view_source.count("<StudioTabSuspense>") == 4
    assert "onPreloadTab={preloadAgentStudioTab}" in view_source
    assert "onMouseEnter={() => onPreloadTab(item)}" in chrome_source
    assert "onFocus={() => onPreloadTab(item)}" in chrome_source
