"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_release_artifacts import Finding, verify_release_artifacts

DEFAULT_ARTIFACT_PATHS: tuple[Path, ...] = (
    Path("dist/backend"),
    Path("dist/electron"),
    Path("release"),
)
MANUAL_RELEASE_CANDIDATE_CHECKS: tuple[str, ...] = (
    "Mount the DMG and launch Oha-Yachiyo.app once with the documented Gatekeeper first-launch flow.",
    "Confirm the packaged app starts its local bridge and does not connect to a development backend.",
    "Grant Screen Recording permission to Oha-Yachiyo.app and verify the local screenshot/proactive probe path.",
    "If real provider credentials are available, run the opt-in streaming/tool-call provider smoke in release workflow.",
)


def existing_artifact_paths(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in DEFAULT_ARTIFACT_PATHS if (root / path).exists())


def release_ui_smoke_scripts(root: Path) -> tuple[Path, ...]:
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return ()
    return tuple(sorted(path.relative_to(root) for path in scripts_dir.glob("smoke_*_ui.mjs") if path.is_file()))


def _print_findings(title: str, findings: Sequence[Finding]) -> None:
    if not findings:
        print(f"{title}: passed")
        return
    print(f"{title}: failed")
    for finding in findings:
        print(f"- {finding.format()}")


def verify_release_candidate(
    *,
    root: Path = PROJECT_ROOT,
    artifact_paths: Sequence[Path] | None = None,
    require_artifacts: bool = False,
    run_ui_smoke: bool = False,
    smoke_scripts: Sequence[Path] | None = None,
) -> int:
    root = Path(root)
    failed = False

    source_findings = verify_release_artifacts(root=root)
    _print_findings("source release guards", source_findings)
    failed = failed or bool(source_findings)

    selected_artifacts = tuple(artifact_paths) if artifact_paths is not None else existing_artifact_paths(root)
    if selected_artifacts:
        artifact_findings = verify_release_artifacts(
            root=root,
            paths=selected_artifacts,
            allow_binary_targets=True,
            check_packaged_app_bundle=True,
        )
        _print_findings("built artifact guards", artifact_findings)
        failed = failed or bool(artifact_findings)
    elif require_artifacts:
        print(
            "built artifact guards: failed\n"
            "- release candidate artifacts not found under dist/backend, dist/electron, or release"
        )
        failed = True
    else:
        print("built artifact guards: skipped; pass --require-artifacts for a release-candidate gate")

    selected_smoke_scripts = tuple(smoke_scripts) if smoke_scripts is not None else release_ui_smoke_scripts(root)
    if run_ui_smoke:
        if not selected_smoke_scripts:
            print("Electron UI smoke: failed\n- no scripts/smoke_*_ui.mjs scripts found")
            failed = True
        for script in selected_smoke_scripts:
            print(f"Electron UI smoke: node {script}")
            result = subprocess.run(["node", str(script)], cwd=root, check=False)
            if result.returncode != 0:
                print(f"- {script} failed with exit code {result.returncode}")
                failed = True
    else:
        print("Electron UI smoke: skipped; pass --run-ui-smoke after installing frontend dependencies")

    print("manual release-candidate checks:")
    for check in MANUAL_RELEASE_CANDIDATE_CHECKS:
        print(f"- {check}")

    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local Oha-Yachiyo release-candidate verification gates."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional built artifact paths. Defaults to existing dist/backend, dist/electron, and release.",
    )
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail when no built release artifacts are present.",
    )
    parser.add_argument(
        "--run-ui-smoke",
        action="store_true",
        help="Run every scripts/smoke_*_ui.mjs Electron UI smoke.",
    )
    args = parser.parse_args(argv)
    return verify_release_candidate(
        artifact_paths=args.paths or None,
        require_artifacts=args.require_artifacts,
        run_ui_smoke=args.run_ui_smoke,
    )


if __name__ == "__main__":
    raise SystemExit(main())
