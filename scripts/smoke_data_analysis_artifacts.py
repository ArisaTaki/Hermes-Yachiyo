#!/usr/bin/env python3
"""Smoke-test data analysis artifact generation and readback."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
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

DATASET_CASES = [
    {
        "id": "csv",
        "input_path": SAMPLE_PATH,
        "source_kind": "csv",
        "rows": 3,
        "columns": ["region", "revenue", "units"],
        "artifact_paths": ARTIFACT_PATHS,
        "artifact_manifest": ARTIFACT_MANIFEST,
    },
    {
        "id": "json",
        "input_path": "inputs/sales.json",
        "source_kind": "json",
        "rows": 3,
        "columns": ["region", "revenue", "units"],
        "artifact_paths": [
            "reports/sales-json.md",
            "reports/sales-json-summary.csv",
            "reports/sales-json.html",
            "reports/sales-json-chart.png",
        ],
        "artifact_manifest": [
            {"path": "reports/sales-json.md", "kind": "markdown"},
            {"path": "reports/sales-json-summary.csv", "kind": "csv"},
            {"path": "reports/sales-json.html", "kind": "html"},
            {"path": "reports/sales-json-chart.png", "kind": "chart"},
        ],
    },
    {
        "id": "text_table",
        "input_path": "inputs/sales-table.md",
        "source_kind": "text_table",
        "rows": 3,
        "columns": ["region", "revenue", "units"],
        "artifact_paths": [
            "reports/sales-table.md",
            "reports/sales-table-summary.csv",
            "reports/sales-table.html",
            "reports/sales-table-chart.png",
        ],
        "artifact_manifest": [
            {"path": "reports/sales-table.md", "kind": "markdown"},
            {"path": "reports/sales-table-summary.csv", "kind": "csv"},
            {"path": "reports/sales-table.html", "kind": "html"},
            {"path": "reports/sales-table-chart.png", "kind": "chart"},
        ],
    },
    {
        "id": "xlsx",
        "input_path": "inputs/sales.xlsx",
        "source_kind": "xlsx",
        "rows": 3,
        "columns": ["region", "revenue", "units"],
        "artifact_paths": [
            "reports/sales-xlsx.md",
            "reports/sales-xlsx-summary.csv",
            "reports/sales-xlsx.html",
            "reports/sales-xlsx-chart.png",
        ],
        "artifact_manifest": [
            {"path": "reports/sales-xlsx.md", "kind": "markdown"},
            {"path": "reports/sales-xlsx-summary.csv", "kind": "csv"},
            {"path": "reports/sales-xlsx.html", "kind": "html"},
            {"path": "reports/sales-xlsx-chart.png", "kind": "chart"},
        ],
    },
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


def _write_sample_datasets(workdir: Path) -> None:
    _write_sample_dataset(workdir)
    (workdir / "inputs" / "sales.json").write_text(
        json.dumps(
            [
                {"region": "East", "revenue": 10, "units": 1},
                {"region": "West", "revenue": 20, "units": 2},
                {"region": "East", "revenue": 30, "units": 3},
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (workdir / "inputs" / "sales-table.md").write_text(
        "\n".join(
            [
                "| region | revenue | units |",
                "| --- | ---: | ---: |",
                "| East | 10 | 1 |",
                "| West | 20 | 2 |",
                "| East | 30 | 3 |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_sample_xlsx(workdir / "inputs" / "sales.xlsx")


def _write_sample_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<si><t>region</t></si><si><t>revenue</t></si><si><t>units</t></si>"
                "<si><t>East</t></si><si><t>West</t></si>"
                "</sst>"
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>"
                '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
                '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>10</v></c><c r="C2"><v>1</v></c></row>'
                '<row r="3"><c r="A3" t="s"><v>4</v></c><c r="B3"><v>20</v></c><c r="C3"><v>2</v></c></row>'
                '<row r="4"><c r="A4" t="s"><v>3</v></c><c r="B4"><v>30</v></c><c r="C4"><v>3</v></c></row>'
                "</sheetData>"
                "</worksheet>"
            ),
        )


def _broker(workdir: Path) -> ToolBroker:
    return ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        _artifact_root(workdir),
    )


def _readback_check(
    workdir: Path,
    rel_path: str,
    metadata: dict[str, Any],
    *,
    source_path: str = SAMPLE_PATH,
) -> dict[str, Any]:
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
        expected = ["<!doctype html>", "Data Analysis Report", Path(source_path).name]
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


def _run_case(
    broker: ToolBroker,
    workdir: Path,
    case: dict[str, Any],
) -> dict[str, Any]:
    input_path = str(case["input_path"])
    artifact_paths = [str(path) for path in case["artifact_paths"]]
    artifact_manifest = [
        {"path": str(item["path"]), "kind": str(item["kind"])}
        for item in case["artifact_manifest"]
    ]
    result = broker.call(
        "data.analyze",
        {
            "path": input_path,
            "artifact_path": artifact_paths[0],
            "artifact_paths": artifact_paths,
            "requested_outputs": ["report", "table", "chart"],
            "artifact_manifest": artifact_manifest,
        },
    )
    if not isinstance(result, dict):
        raise SmokeError("data.analyze returned a non-object result")

    followup_snapshot = data_analyze_content_snapshot(
        result,
        {
            "path": input_path,
            "source_kind": str(case["source_kind"]),
            "artifact_manifest": artifact_manifest,
        },
    )
    artifacts = [item for item in result.get("artifacts") or [] if isinstance(item, dict)]
    artifact_by_path = {str(item.get("path") or ""): item for item in artifacts}
    readback = [
        _readback_check(
            workdir,
            rel_path,
            artifact_by_path.get(rel_path, {}),
            source_path=input_path,
        )
        for rel_path in artifact_paths
    ]
    actual_paths = [str(item.get("path") or "") for item in artifacts]
    checks = {
        "tool_result_ok": result.get("ok") is True,
        "source_kind": result.get("source_kind") == case["source_kind"],
        "rows": result.get("rows") == case["rows"],
        "columns": result.get("columns") == case["columns"],
        "artifact_paths": actual_paths == artifact_paths,
        "readback": all(item.get("matched") is True for item in readback),
        "followup_source_tool": followup_snapshot.get("source_tool") == "data.analyze",
        "followup_artifact_paths": followup_snapshot.get("artifact_paths") == artifact_paths,
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "input_path": input_path,
        "expected_source_kind": str(case["source_kind"]),
        "result": _selected_result_fields(result),
        "followup_snapshot": followup_snapshot,
        "readback": readback,
        "checks": checks,
    }


def run_smoke(workdir: Path) -> dict[str, Any]:
    resolved_workdir = workdir.expanduser().resolve()
    resolved_workdir.mkdir(parents=True, exist_ok=True)
    _write_sample_datasets(resolved_workdir)

    broker = _broker(resolved_workdir)
    cases = [_run_case(broker, resolved_workdir, case) for case in DATASET_CASES]
    primary_case = next((case for case in cases if case["id"] == "csv"), cases[0])
    result = primary_case["result"]
    followup_snapshot = primary_case["followup_snapshot"]
    readback = primary_case["readback"]
    expected_paths = list(ARTIFACT_PATHS)
    ok = (
        primary_case.get("ok") is True
        and all(item.get("matched") is True for item in readback)
        and followup_snapshot.get("source_tool") == "data.analyze"
        and followup_snapshot.get("artifact_paths") == expected_paths
        and "Data analysis result for inputs/sales.csv (csv)." in str(followup_snapshot.get("text") or "")
        and all(case.get("ok") is True for case in cases)
    )
    evidence: dict[str, Any] = {
        "ok": ok,
        "mode": "data_analysis_artifact_smoke",
        "case_count": len(cases),
        "source_kinds": [str(case.get("result", {}).get("source_kind") or "") for case in cases],
        "workspace": str(resolved_workdir),
        "artifact_root": str(_artifact_root(resolved_workdir)),
        "input_path": SAMPLE_PATH,
        "result": result,
        "followup_snapshot": followup_snapshot,
        "readback": readback,
        "cases": cases,
        "checks": {
            "csv_case_passed": primary_case.get("ok") is True,
            "all_cases_passed": all(case.get("ok") is True for case in cases),
            "covers_csv_json_text_table_xlsx": [
                str(case.get("result", {}).get("source_kind") or "") for case in cases
            ]
            == ["csv", "json", "text_table", "xlsx"],
        },
    }
    if not ok:
        evidence["error"] = "data analysis artifact smoke failed"
    return evidence


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "data-analysis-artifact-smoke",
        help="Workspace used for the sample dataset and generated artifacts.",
    )
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
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
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"data analysis artifact smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
