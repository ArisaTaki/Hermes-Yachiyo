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


def data_source_scope_hint(text: str, metadata: Mapping[str, Any] | None = None) -> str:
    metadata = metadata or {}
    for key in ("data_source_scope", "folder", "directory", "location"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    path_match = re.search(r"((?:~|/)[^\s，,。]+)", text)
    if path_match:
        return path_match.group(1).rstrip("。.,")
    lowered = str(text or "").lower()
    named_folder_match = re.search(
        r"(?:读取|读|找一下|找下|查找|从|在|打开|使用|用)?\s*"
        r"(?P<folder>[A-Za-z0-9_.-]+)\s*(?:目录|文件夹)",
        text,
        flags=re.IGNORECASE,
    )
    if named_folder_match:
        return str(named_folder_match.group("folder") or "").strip()
    if re.search(
        r"(?:桌面(?:上|里|中|内|文件夹|目录)|桌面\s*(?:的)?(?:文件|数据|表格)|"
        r"桌面.{0,12}(?:文件|数据|表格|csv|tsv|xlsx|xls|json|销售|sales))",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"(?:desktop\s+(?:folder|directory|files?|data|dataset|table)|"
        r"(?:on|in|from)\s+(?:the\s+)?desktop)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return "Desktop"
    known_locations = (
        ("downloads", "Downloads"),
        ("download folder", "Downloads"),
        ("下载文件夹", "Downloads"),
        ("下载目录", "Downloads"),
        ("documents", "Documents"),
        ("文档", "Documents"),
    )
    for marker, location in known_locations:
        if marker in lowered:
            return location
    return ""


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
    context_kind = _context_data_source_kind_hint(lowered_text)
    if context_kind:
        return context_kind
    if any(
        marker in lowered_text
        for marker in ("价格表", "销售表", "数据表", "明细表", "报表", "price table", "pricing table")
    ):
        return "text_table"
    if any(marker in lowered_text for marker in ("表格", "table", "tabular")):
        return "text_table"
    return "unknown"


def _context_data_source_kind_hint(lowered_text: str) -> str:
    context_en = r"(?:clipboard|selected(?:\s+text)?|selection|current\s+(?:page|window|selection))"
    context_zh = r"(?:剪贴板|粘贴板|选中(?:的)?|当前选中(?:的)?|当前网页|当前页面|当前窗口)"
    format_map = (
        ("jsonl", "jsonl"),
        ("json", "json"),
        ("csv", "csv"),
        ("tsv", "tsv"),
        ("xlsx", "xlsx"),
        ("xls", "xls"),
    )
    for token, kind in format_map:
        if re.search(
            rf"{context_en}(?:\s+(?:contents?|data|text|table))?\s+{token}\b",
            lowered_text,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"\b{token}\b\s+(?:data\s+)?(?:in|from|on|inside)\s+(?:the\s+)?{context_en}",
            lowered_text,
            flags=re.IGNORECASE,
        ):
            return kind
        if re.search(
            rf"{context_zh}(?:里|里的|中|中的|内容|数据|表格)?\s*(?:的)?\s*{token}",
            lowered_text,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"{token}\s*(?:数据|内容|表格)?\s*(?:在|来自)?\s*{context_zh}",
            lowered_text,
            flags=re.IGNORECASE,
        ):
            return kind
    return ""


def data_analysis_artifacts_expected(
    expected_outputs: Iterable[str],
    text: str = "",
) -> list[str]:
    outputs = {str(item or "").strip() for item in expected_outputs if str(item or "").strip()}
    lowered = str(text or "").lower()
    artifacts = ["analysis-report.md"]
    if "chart" in outputs:
        artifacts.append("analysis-chart.png")
    if "table" in outputs or any(
        marker in lowered
        for marker in (
            "export csv",
            "export as csv",
            "output csv",
            "csv file",
            "导出 csv",
            "导出成 csv",
            "导出为 csv",
            "输出 csv",
            "生成 csv",
            "做成 csv",
            "提取成 csv",
            "提取为 csv",
            "csv 文件",
        )
    ):
        artifacts.append("analysis-summary.csv")
    if any(marker in lowered for marker in ("html", "网页报告", "web report")):
        artifacts.append("analysis-report.html")
    return list(dict.fromkeys(artifacts))


def data_analysis_artifact_manifest(artifact_paths: Iterable[str]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for path in artifact_paths:
        clean_path = str(path or "").strip()
        if not clean_path:
            continue
        manifest.append({"path": clean_path, "kind": data_analysis_artifact_kind(clean_path)})
    return manifest


def data_analysis_artifact_kind(path: str) -> str:
    lowered = str(path or "").lower()
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".html"):
        return "html"
    if lowered.endswith(".png"):
        return "chart"
    if lowered.endswith(".json"):
        return "json"
    return "markdown"
