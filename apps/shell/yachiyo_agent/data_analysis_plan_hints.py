"""Planning hints for data-analysis tasks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


def data_source_hint(text: str, metadata: Mapping[str, Any] | None = None) -> str:
    metadata = metadata or {}
    for key in ("attachment", "file", "path", "data_source"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    match = re.search(
        r"([^\s\"']+\.(?:csv|tsv|xlsx|xls|jsonl|json|parquet|txt|md|markdown))",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def data_source_kind_hint(source_hint: str, text: str = "") -> str:
    lowered_source = str(source_hint or "").lower()
    lowered_text = str(text or "").lower()
    suffixes = (
        ((".csv",), "csv"),
        ((".tsv",), "tsv"),
        ((".xlsx",), "xlsx"),
        ((".xls",), "xls"),
        ((".jsonl",), "jsonl"),
        ((".json",), "json"),
        ((".parquet",), "parquet"),
        ((".md", ".markdown"), "text_table"),
        ((".txt",), "text"),
    )
    for endings, kind in suffixes:
        if lowered_source.endswith(endings):
            return kind
    if any(marker in lowered_text for marker in ("表格", "table", "tabular")):
        return "text_table"
    return "unknown"


def data_analysis_artifacts_expected(
    expected_outputs: Iterable[str],
    text: str = "",
) -> list[str]:
    outputs = {str(item or "").strip() for item in expected_outputs if str(item or "").strip()}
    lowered = str(text or "").lower()
    artifacts = ["analysis-report.md"]
    if "chart" in outputs:
        artifacts.append("analysis-chart.png")
    if "table" in outputs or any(marker in lowered for marker in ("export csv", "导出 csv", "输出 csv")):
        artifacts.append("analysis-summary.csv")
    if any(marker in lowered for marker in ("html", "网页报告", "web report")):
        artifacts.append("analysis-report.html")
    return list(dict.fromkeys(artifacts))
