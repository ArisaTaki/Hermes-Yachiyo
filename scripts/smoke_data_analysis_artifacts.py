#!/usr/bin/env python3
"""Smoke-test data analysis artifact generation and readback."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.runtime.followup_content_snapshot import data_analyze_content_snapshot

SAMPLE_CSV = "region,revenue,units\nEast,10,1\nWest,20,2\nEast,30,3\n"
SAMPLE_PATH = "inputs/sales.csv"
ARTIFACT_PATHS = [
    "reports/sales.md",
    "reports/sales-summary.csv",
    "reports/sales.html",
    "reports/sales-chart.png",
]
ARTIFACT_MANIFEST = [
    {"path": "reports/sales.md", "kind": "markdown"},
    {"path": "reports/sales-summary.csv", "kind": "csv"},
    {"path": "reports/sales.html", "kind": "html"},
    {"path": "reports/sales-chart.png", "kind": "chart"},
]


class SmokeError(RuntimeError):
    """Data analysis smoke failed."""


def _artifact_root(workdir: Path) -> Path:
    return workdir / "artifacts"


def _artifact_file(workdir: Path, rel_path: str) -> Path:
    root = _artifact_root(workdir).resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents and target != root:
        raise SmokeError(f"Artifact path escaped artifact root: {rel_path}")
    return target


def _write_sample_dataset(workdir: Path) -> None:
    sample = workdir / SAMPLE_PATH
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text(SAMPLE_CSV, encoding="utf-8")


def _broker(workdir: Path) -> ToolBroker:
    return ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        _artifact_root(workdir),
    )


def _readback_check(workdir: Path, rel_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_file(workdir, rel_path)
    payload: dict[str, Any] = {
        "path": rel_path,
        "exists": path.exists(),
        "kind": str(metadata.get("kind") or ""),
        "mime_type": str(metadata.get("mime_type") or ""),
        "size_bytes": 0,
        "matched": False,
    }
    if not path.exists() or not path.is_file():
        payload["error"] = "artifact file is missing"
        return payload

    size = path.stat().st_size
    payload["size_bytes"] = size
    if rel_path.endswith(".png"):
        matched = path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        payload["matched"] = matched
        payload["check"] = "png_signature"
        return payload

    text = path.read_text(encoding="utf-8")
    if rel_path.endswith(".md"):
        expected = ["# Data Analysis Report", "mean=20.0", "| East | 10 | 1 |"]
        payload["check"] = "markdown_report"
    elif rel_path.endswith(".csv"):
        expected = ["column,type,count", "revenue", "units"]
        payload["check"] = "csv_summary"
    elif rel_path.endswith(".html"):
        expected = ["<!doctype html>", "Data Analysis Report", "sales.csv"]
        payload["check"] = "html_report"
    else:
        expected = []
        payload["check"] = "non_empty"
    payload["matched"] = size > 0 and all(token in text for token in expected)
    return payload


def _selected_result_fields(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "path": str(result.get("path") or ""),
        "source_kind": str(result.get("source_kind") or ""),
        "rows": result.get("rows"),
        "columns": result.get("columns") or [],
        "artifact_paths": result.get("artifact_paths") or [],
        "artifact_manifest": result.get("artifact_manifest") or [],
    }


def run_smoke(workdir: Path) -> dict[str, Any]:
    resolved_workdir = workdir.expanduser().resolve()
    resolved_workdir.mkdir(parents=True, exist_ok=True)
    _write_sample_dataset(resolved_workdir)

    result = _broker(resolved_workdir).call(
        "data.analyze",
        {
            "path": SAMPLE_PATH,
            "artifact_path": ARTIFACT_PATHS[0],
            "artifact_paths": ARTIFACT_PATHS,
            "requested_outputs": ["report", "table", "chart"],
            "artifact_manifest": ARTIFACT_MANIFEST,
        },
    )
    if not isinstance(result, dict):
        raise SmokeError("data.analyze returned a non-object result")

    followup_snapshot = data_analyze_content_snapshot(
        result,
        {
            "path": SAMPLE_PATH,
            "source_kind": "csv",
            "artifact_manifest": ARTIFACT_MANIFEST,
        },
    )
    artifacts = [item for item in result.get("artifacts") or [] if isinstance(item, dict)]
    artifact_by_path = {str(item.get("path") or ""): item for item in artifacts}
    readback = [
        _readback_check(resolved_workdir, rel_path, artifact_by_path.get(rel_path, {}))
        for rel_path in ARTIFACT_PATHS
    ]
    expected_paths = list(ARTIFACT_PATHS)
    actual_paths = [str(item.get("path") or "") for item in artifacts]
    ok = (
        result.get("ok") is True
        and result.get("source_kind") == "csv"
        and result.get("rows") == 3
        and result.get("columns") == ["region", "revenue", "units"]
        and actual_paths == expected_paths
        and all(item.get("matched") is True for item in readback)
        and followup_snapshot.get("source_tool") == "data.analyze"
        and followup_snapshot.get("artifact_paths") == expected_paths
        and "Data analysis result for inputs/sales.csv (csv)." in str(followup_snapshot.get("text") or "")
    )
    evidence: dict[str, Any] = {
        "ok": ok,
        "mode": "data_analysis_artifact_smoke",
        "workspace": str(resolved_workdir),
        "artifact_root": str(_artifact_root(resolved_workdir)),
        "input_path": SAMPLE_PATH,
        "result": _selected_result_fields(result),
        "followup_snapshot": followup_snapshot,
        "readback": readback,
    }
    if not ok:
        evidence["error"] = "data analysis artifact smoke failed"
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "data-analysis-artifact-smoke",
        help="Workspace used for the sample dataset and generated artifacts.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = run_smoke(args.workdir)
    except Exception as exc:
        evidence = {
            "ok": False,
            "mode": "data_analysis_artifact_smoke",
            "workspace": str(args.workdir.expanduser()),
            "error": str(exc),
        }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
