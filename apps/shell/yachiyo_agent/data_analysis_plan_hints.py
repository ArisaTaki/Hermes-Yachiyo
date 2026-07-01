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


def named_data_source_hint(text: str) -> dict[str, str]:
    value = str(text or "").strip()
    if not value:
        return {}
    kind_pattern = r"csv|tsv|xlsx|xls|excel|jsonl|json|parquet|txt|md|markdown"
    quoted_name = r"[\"'“”‘’「」『』]?(?P<name>[\w\u4e00-\u9fff ._-]{1,80}?)[\"'“”‘’「」『』]?"
    patterns = (
        rf"(?:叫做|叫|名为|名字叫)\s*{quoted_name}\s*(?:的)?\s*(?P<kind>{kind_pattern})\b",
        rf"(?P<kind>{kind_pattern})\s*(?:文件|表格|数据|数据集|电子表格)?\s*"
        rf"(?:叫做|叫|名为|名字叫)\s*{quoted_name}",
        rf"\b(?P<kind>{kind_pattern})\s+"
        rf"(?:file\s+|spreadsheet\s+|dataset\s+|data\s+)?(?:named|called)\s+"
        rf"[\"']?(?P<name_en>[A-Za-z0-9_.-]{{1,80}})[\"']?",
        rf"\b(?:file|spreadsheet|dataset|data)?\s*(?:named|called)\s+"
        rf"[\"']?(?P<name_en_first>[A-Za-z0-9_.-]{{1,80}})[\"']?\s+"
        rf"(?:with\s+)?(?:the\s+)?(?:extension\s+)?(?P<kind_en_first>{kind_pattern})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_name = groups.get("name") or groups.get("name_en") or groups.get("name_en_first") or ""
        kind = _normalize_data_source_kind(
            groups.get("kind") or groups.get("kind_en_first") or ""
        )
        name = _clean_named_data_source_name(raw_name, kind)
        if name and kind:
            return {"name": name, "kind": kind}
    return {}


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
    folder_contents_match = re.search(
        r"(?:读取|读|找一下|找下|查找|从|在|打开|使用|用|分析)?\s*"
        r"(?P<folder>[A-Za-z0-9_.-]+)\s*"
        r"(?:里|里的|中|中的|内|内的|下|下面|中的)\s*"
        r".{0,24}?"
        r"(?:数据|数据集|文件|表格|电子表格|销售|报表|明细|"
        r"csv|tsv|xlsx|xls|jsonl?|parquet|txt|markdown|md)",
        text,
        flags=re.IGNORECASE,
    )
    if folder_contents_match:
        return str(folder_contents_match.group("folder") or "").strip()
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
    if _looks_like_download_data_scope(text):
        return "Downloads"
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


def _looks_like_download_data_scope(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    data_terms = (
        r"(?:数据|数据集|文件|表格|电子表格|销售|报表|明细|"
        r"csv|tsv|xlsx|xls|jsonl?|parquet|txt|markdown|md)"
    )
    data_file = r"[^\s，,。；;]+?\.(?:csv|tsv|xlsx|xls|jsonl|json|parquet|txt|md|markdown)"
    downloaded_source = (
        r"(?:(?:最近|最新|最后|上一个|刚刚?|刚才|新近)\s*下载(?:的|下来|好|完成)?|"
        r"(?<!可)下载(?:的|下来|好|完成))"
    )
    if re.search(
        rf"{downloaded_source}\s*(?:{data_file}|{data_terms})",
        value,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"(?:{data_file}|{data_terms})\s*(?:是|来自|在|从)?\s*"
        rf"{downloaded_source}",
        value,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:recently|latest|last|newly|just)\s+downloaded\s+"
            r"(?:data|dataset|file|table|spreadsheet|csv|tsv|xlsx|xls|jsonl?|parquet|txt|"
            r"[^\s]+\.(?:csv|tsv|xlsx|xls|jsonl|json|parquet|txt|md|markdown))\b",
            lowered,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bdownloaded\s+"
            r"(?:data|dataset|table|spreadsheet|csv|tsv|xlsx|xls|jsonl?|parquet|"
            r"[^\s]+\.(?:csv|tsv|xlsx|xls|jsonl|json|parquet|txt|md|markdown))\b",
            lowered,
            flags=re.IGNORECASE,
        )
    )


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
    scoped_format_kind = _scoped_data_source_kind_hint(lowered_text)
    if scoped_format_kind:
        return scoped_format_kind
    bare_format_kind = _bare_data_source_kind_hint(lowered_text)
    if bare_format_kind:
        return bare_format_kind
    named_source = named_data_source_hint(text)
    if named_source.get("kind"):
        return str(named_source["kind"])
    generic_structured_source_kind = _generic_structured_data_source_kind_hint(
        lowered_text
    )
    if generic_structured_source_kind:
        return generic_structured_source_kind
    if any(
        marker in lowered_text
        for marker in ("价格表", "销售表", "数据表", "明细表", "报表", "price table", "pricing table")
    ):
        return "text_table"
    if any(
        marker in lowered_text
        for marker in ("表格", "这张表", "这个表", "当前表", "前台表", "table", "tabular")
    ):
        return "text_table"
    return "unknown"


def _generic_structured_data_source_kind_hint(lowered_text: str) -> str:
    patterns = (
        r"数据文件",
        r"数据源",
        r"\bdatasets?\b",
        r"\bdata\s+files?\b",
        r"\bdata\s+sources?\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lowered_text, flags=re.IGNORECASE):
            if _format_token_is_output_target(lowered_text, match.start()):
                continue
            return "text_table"
    return ""


def _normalize_data_source_kind(kind: str) -> str:
    value = str(kind or "").strip().lower()
    return {
        "excel": "xlsx",
        "markdown": "md",
    }.get(value, value)


def _clean_named_data_source_name(name: str, kind: str) -> str:
    value = str(name or "").strip().strip("\"'“”‘’「」『』")
    value = re.sub(r"[，,。；;:：!?！？]+$", "", value).strip()
    if not value:
        return ""
    extension = f".{kind.lower()}"
    if value.lower().endswith(extension):
        value = value[: -len(extension)].rstrip(". ")
    return value


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


def _scoped_data_source_kind_hint(lowered_text: str) -> str:
    source_scope = (
        r"(?:downloads?|download\s+folder|desktop|documents?|folder|directory|"
        r"下载(?:文件夹|目录)?|桌面|文档|目录|文件夹|文件|数据源|数据集|"
        r"[a-z0-9_.-]+\s*目录|[a-z0-9_.-]+\s*文件夹|"
        r"[a-z0-9_.-]+\s*(?:里|里的|中|中的|内|内的|下|下面))"
    )
    format_map = (
        ("jsonl", "jsonl"),
        ("json", "json"),
        ("parquet", "parquet"),
        ("csv", "csv"),
        ("tsv", "tsv"),
        ("xlsx", "xlsx"),
        ("xls", "xls"),
        ("excel", "xlsx"),
    )
    for token, kind in format_map:
        token_pattern = rf"\b{re.escape(token)}\b" if token.isascii() else re.escape(token)
        for match in re.finditer(token_pattern, lowered_text, flags=re.IGNORECASE):
            if _format_token_is_output_target(lowered_text, match.start()):
                continue
            before = lowered_text[: match.start()]
            after = lowered_text[match.end() :]
            if re.search(source_scope, before[-80:], flags=re.IGNORECASE):
                return kind
            if re.search(source_scope, after[:80], flags=re.IGNORECASE):
                return kind
    return ""


def _bare_data_source_kind_hint(lowered_text: str) -> str:
    format_map = (
        ("jsonl", "jsonl"),
        ("parquet", "parquet"),
        ("markdown", "text_table"),
        ("json", "json"),
        ("csv", "csv"),
        ("tsv", "tsv"),
        ("xlsx", "xlsx"),
        ("xls", "xls"),
        ("txt", "text"),
        ("md", "text_table"),
    )
    for token, kind in format_map:
        token_pattern = rf"(?<![a-z0-9_.-]){re.escape(token)}(?![a-z0-9_.-])"
        for match in re.finditer(token_pattern, lowered_text, flags=re.IGNORECASE):
            if _format_token_is_output_target(lowered_text, match.start()):
                continue
            return kind
    return ""


def _format_token_is_output_target(lowered_text: str, token_start: int) -> bool:
    prefix = lowered_text[max(0, token_start - 18) : token_start]
    return bool(
        re.search(
            r"(?:(?:输出|导出|保存|生成|写|整理|做|转)(?:成|为)?|另存为|"
            r"output|export|save|write|generate|convert\s+to)\s*$",
            prefix,
            flags=re.IGNORECASE,
        )
    )


def data_analysis_artifacts_expected(
    expected_outputs: Iterable[str],
    text: str = "",
) -> list[str]:
    outputs = {str(item or "").strip() for item in expected_outputs if str(item or "").strip()}
    lowered = str(text or "").lower()
    artifacts = ["analysis-report.md"]
    if "chart" in outputs:
        artifacts.append("analysis-chart.png")
    if "presentation" in outputs or any(
        marker in lowered
        for marker in (
            "ppt",
            "pptx",
            "slide deck",
            "slides",
            "presentation",
            "keynote",
            "演示",
            "演示文稿",
            "幻灯片",
        )
    ):
        artifacts.append("analysis-presentation.pptx")
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
    if lowered.endswith((".ppt", ".pptx", ".key")):
        return "presentation"
    if lowered.endswith(".json"):
        return "json"
    return "markdown"
