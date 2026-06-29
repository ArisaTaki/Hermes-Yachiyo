"""Built-in lightweight data analysis for Agent runs."""

from __future__ import annotations

import csv
import binascii
import html
import io
import json
import math
import re
import struct
import zlib
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


def analyze_data_file(
    path: Path,
    *,
    display_path: str,
    artifact_path: str,
    artifact_paths: list[str] | None = None,
    max_rows: int = 1000,
) -> dict[str, Any]:
    clean_max_rows = max(1, min(int(max_rows or 1000), 10000))
    clean_artifact_paths = _artifact_paths(artifact_path, artifact_paths)
    primary_artifact_path = clean_artifact_paths[0]
    suffix = path.suffix.lower()
    source_kind = _source_kind_for_suffix(suffix)
    try:
        if suffix == ".xlsx":
            table = _xlsx_table(path, max_rows=clean_max_rows)
        else:
            text = _read_text_file(path)
            if suffix == ".json":
                table = _json_table(text, max_rows=clean_max_rows)
            elif suffix == ".jsonl":
                table = _jsonl_table(text, max_rows=clean_max_rows)
            elif suffix == ".tsv":
                table = _delimited_table(text, delimiter="\t", max_rows=clean_max_rows)
            elif suffix == ".csv":
                table = _delimited_table(text, delimiter=",", max_rows=clean_max_rows)
            else:
                table = _text_table(text, max_rows=clean_max_rows)
                source_kind = "text_table" if table["columns"] else "text"
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        csv.Error,
        OSError,
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
    ) as exc:
        return _parse_error_result(display_path, source_kind=source_kind, error=exc)

    if not table["columns"]:
        if source_kind in {"csv", "tsv", "json", "jsonl", "xlsx"}:
            return _empty_structured_report(
                display_path=display_path,
                source_kind=source_kind,
                artifact_path=primary_artifact_path,
                artifact_paths=clean_artifact_paths,
                table=table,
            )
        return _plain_text_report(
            path,
            display_path=display_path,
            artifact_path=primary_artifact_path,
            artifact_paths=clean_artifact_paths,
            max_rows=clean_max_rows,
        )

    column_summaries = _column_summaries(table["rows"], table["columns"])
    content = _markdown_report(
        display_path=display_path,
        source_kind=source_kind,
        artifact_path=primary_artifact_path,
        table=table,
        column_summaries=column_summaries,
    )
    extra_artifacts = _extra_table_artifacts(
        clean_artifact_paths[1:],
        display_path=display_path,
        source_kind=source_kind,
        table=table,
        column_summaries=column_summaries,
    )
    return {
        "ok": True,
        "path": display_path,
        "source_kind": source_kind,
        "rows": table["row_count"],
        "analyzed_rows": len(table["rows"]),
        "columns": table["columns"],
        "column_summaries": column_summaries,
        "artifact_path": primary_artifact_path,
        "artifact_paths": clean_artifact_paths,
        "artifact_content": content,
        "extra_artifacts": extra_artifacts,
        "summary": (
            f"Analyzed {display_path}: {table['row_count']} rows, "
            f"{len(table['columns'])} columns. Report: {primary_artifact_path}."
        ),
    }


def analyze_data_text(
    text: str,
    *,
    display_path: str,
    artifact_path: str,
    artifact_paths: list[str] | None = None,
    max_rows: int = 1000,
    source_kind: str = "text_table",
) -> dict[str, Any]:
    clean_max_rows = max(1, min(int(max_rows or 1000), 10000))
    clean_artifact_paths = _artifact_paths(artifact_path, artifact_paths)
    primary_artifact_path = clean_artifact_paths[0]
    clean_source_kind = str(source_kind or "text_table").strip() or "text_table"
    try:
        if clean_source_kind == "json":
            table = _json_table(text, max_rows=clean_max_rows)
        elif clean_source_kind == "jsonl":
            table = _jsonl_table(text, max_rows=clean_max_rows)
        elif clean_source_kind == "tsv":
            table = _delimited_table(text, delimiter="\t", max_rows=clean_max_rows)
        elif clean_source_kind == "csv":
            table = _delimited_table(text, delimiter=",", max_rows=clean_max_rows)
        else:
            table = _text_table(text, max_rows=clean_max_rows)
            clean_source_kind = "text_table" if table["columns"] else "text"
    except (json.JSONDecodeError, csv.Error, KeyError) as exc:
        return _parse_error_result(display_path, source_kind=clean_source_kind, error=exc)

    if not table["columns"]:
        if clean_source_kind in {"csv", "tsv", "json", "jsonl", "xlsx"}:
            return _empty_structured_report(
                display_path=display_path,
                source_kind=clean_source_kind,
                artifact_path=primary_artifact_path,
                artifact_paths=clean_artifact_paths,
                table=table,
            )
        return _plain_text_content_report(
            text,
            display_path=display_path,
            artifact_path=primary_artifact_path,
            artifact_paths=clean_artifact_paths,
            max_rows=clean_max_rows,
        )

    column_summaries = _column_summaries(table["rows"], table["columns"])
    content = _markdown_report(
        display_path=display_path,
        source_kind=clean_source_kind,
        artifact_path=primary_artifact_path,
        table=table,
        column_summaries=column_summaries,
    )
    extra_artifacts = _extra_table_artifacts(
        clean_artifact_paths[1:],
        display_path=display_path,
        source_kind=clean_source_kind,
        table=table,
        column_summaries=column_summaries,
    )
    return {
        "ok": True,
        "path": display_path,
        "source_kind": clean_source_kind,
        "rows": table["row_count"],
        "analyzed_rows": len(table["rows"]),
        "columns": table["columns"],
        "column_summaries": column_summaries,
        "artifact_path": primary_artifact_path,
        "artifact_paths": clean_artifact_paths,
        "artifact_content": content,
        "extra_artifacts": extra_artifacts,
        "summary": (
            f"Analyzed {display_path}: {table['row_count']} rows, "
            f"{len(table['columns'])} columns. Report: {primary_artifact_path}."
        ),
    }


def _plain_text_report(
    path: Path,
    *,
    display_path: str,
    artifact_path: str,
    artifact_paths: list[str],
    max_rows: int,
) -> dict[str, Any]:
    text = _read_text_file(path)
    return _plain_text_content_report(
        text,
        display_path=display_path,
        artifact_path=artifact_path,
        artifact_paths=artifact_paths,
        max_rows=max_rows,
    )


def _plain_text_content_report(
    text: str,
    *,
    display_path: str,
    artifact_path: str,
    artifact_paths: list[str],
    max_rows: int,
) -> dict[str, Any]:
    lines = text.splitlines()
    words = re.findall(r"\S+", text)
    preview = "\n".join(lines[: min(20, max_rows)])
    content = "\n".join(
        [
            "# Data Analysis Report",
            "",
            f"- Source: `{display_path}`",
            "- Source kind: `text`",
            f"- Lines: {len(lines)}",
            f"- Words: {len(words)}",
            f"- Characters: {len(text)}",
            "",
            "## Preview",
            "",
            "```text",
            preview,
            "```",
            "",
        ]
    )
    return {
        "ok": True,
        "path": display_path,
        "source_kind": "text",
        "rows": len(lines),
        "analyzed_rows": min(len(lines), max_rows),
        "columns": [],
        "column_summaries": [],
        "artifact_path": artifact_path,
        "artifact_paths": artifact_paths,
        "artifact_content": content,
        "extra_artifacts": _extra_text_artifacts(
            artifact_paths[1:],
            display_path=display_path,
            lines=lines,
            words=words,
            text=text,
            preview=preview,
        ),
        "summary": f"Analyzed text file {display_path}. Report: {artifact_path}.",
    }


def _empty_structured_report(
    *,
    display_path: str,
    source_kind: str,
    artifact_path: str,
    artifact_paths: list[str],
    table: dict[str, Any],
) -> dict[str, Any]:
    content = _markdown_report(
        display_path=display_path,
        source_kind=source_kind,
        artifact_path=artifact_path,
        table=table,
        column_summaries=[],
    )
    return {
        "ok": True,
        "path": display_path,
        "source_kind": source_kind,
        "rows": table["row_count"],
        "analyzed_rows": len(table["rows"]),
        "columns": [],
        "column_summaries": [],
        "artifact_path": artifact_path,
        "artifact_paths": artifact_paths,
        "artifact_content": content,
        "extra_artifacts": _extra_table_artifacts(
            artifact_paths[1:],
            display_path=display_path,
            source_kind=source_kind,
            table=table,
            column_summaries=[],
        ),
        "summary": f"Analyzed {display_path}: no tabular columns found. Report: {artifact_path}.",
    }


def _delimited_table(text: str, *, delimiter: str, max_rows: int) -> dict[str, Any]:
    sample = text[:4096]
    if delimiter:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    else:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
    rows = [list(row) for _, row in zip(range(max_rows + 1), reader)]
    return _table_from_rows(rows)


def _read_text_file(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text(encoding="utf-8")


def _json_table(text: str, *, max_rows: int) -> dict[str, Any]:
    data = json.loads(text)
    records = _json_records(data)
    rows = records[:max_rows]
    columns = _ordered_columns(rows)
    return {
        "columns": columns,
        "rows": [{column: _stringify(row.get(column)) for column in columns} for row in rows],
        "row_count": len(records),
    }


def _jsonl_table(text: str, *, max_rows: int) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    row_count = 0
    for line in text.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue
        row_count += 1
        if len(records) >= max_rows:
            continue
        item = json.loads(clean_line)
        if isinstance(item, dict):
            records.append(_flatten_dict(item))
        else:
            records.append({"value": item})
    columns = _ordered_columns(records)
    return {
        "columns": columns,
        "rows": [{column: _stringify(row.get(column)) for column in columns} for row in records],
        "row_count": row_count,
    }


def _json_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return [_flatten_dict(item) for item in data]
        return [{"value": item} for item in data]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                return [_flatten_dict(item) for item in value]
        return [{"key": key, "value": value} for key, value in data.items()]
    return [{"value": data}]


def _xlsx_table(path: Path, *, max_rows: int) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        sheet_name = _first_worksheet_name(archive)
        if not sheet_name:
            return {"columns": [], "rows": [], "row_count": 0}
        xml = archive.read(sheet_name)
    root = ElementTree.fromstring(xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    raw_rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", ns):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", ns):
            ref = str(cell.attrib.get("r") or "")
            column_index = _xlsx_column_index(ref)
            values[column_index] = _xlsx_cell_value(cell, shared_strings, ns)
        if values:
            width = max(values) + 1
            raw_rows.append([values.get(index, "") for index in range(width)])
        if len(raw_rows) >= max_rows + 1:
            break
    return _table_from_rows(raw_rows)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for item in root.findall("x:si", ns):
        texts = [node.text or "" for node in item.findall(".//x:t", ns)]
        strings.append("".join(texts))
    return strings


def _first_worksheet_name(archive: zipfile.ZipFile) -> str:
    names = sorted(
        name
        for name in archive.namelist()
        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
    )
    return names[0] if names else ""


def _xlsx_column_index(ref: str) -> int:
    letters = re.sub(r"[^A-Za-z]", "", ref).upper()
    if not letters:
        return 0
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _xlsx_cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
    ns: dict[str, str],
) -> str:
    value_node = cell.find("x:v", ns)
    raw = value_node.text if value_node is not None else ""
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    inline = cell.find("x:is/x:t", ns)
    if inline is not None:
        return inline.text or ""
    return raw or ""


def _text_table(text: str, *, max_rows: int) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {"columns": [], "rows": [], "row_count": 0}
    if any("\t" in line for line in lines[:5]):
        return _delimited_table("\n".join(lines), delimiter="\t", max_rows=max_rows)
    if any("|" in line for line in lines[:5]):
        rows = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in lines
            if not re.fullmatch(r"[-:| ]+", line)
        ][: max_rows + 1]
        return _table_from_rows(rows)
    return {"columns": [], "rows": [], "row_count": len(lines)}


def _table_from_rows(raw_rows: list[list[str]]) -> dict[str, Any]:
    if not raw_rows:
        return {"columns": [], "rows": [], "row_count": 0}
    header = [_clean_header(value, index) for index, value in enumerate(raw_rows[0])]
    rows = raw_rows[1:]
    if not rows:
        return {"columns": header, "rows": [], "row_count": 0}
    width = max(len(header), *(len(row) for row in rows))
    columns = [
        header[index] if index < len(header) else f"Column {index + 1}"
        for index in range(width)
    ]
    records = [
        {
            columns[index]: _stringify(row[index]) if index < len(row) else ""
            for index in range(width)
        }
        for row in rows
    ]
    return {"columns": columns, "rows": records, "row_count": len(records)}


def _clean_header(value: Any, index: int) -> str:
    text = str(value or "").strip()
    return text or f"Column {index + 1}"


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            clean_key = str(key)
            if clean_key not in columns:
                columns.append(clean_key)
    return columns


def _flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in data.items():
        clean_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_dict(value, clean_key))
        else:
            flattened[clean_key] = value
    return flattened


def _column_summaries(rows: list[dict[str, str]], columns: list[str]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for column in columns:
        values = [row.get(column, "") for row in rows]
        present = [value for value in values if str(value).strip()]
        numeric = [_to_number(value) for value in present]
        numeric_values = [value for value in numeric if value is not None and math.isfinite(value)]
        if present and len(numeric_values) == len(present):
            summaries.append(
                {
                    "name": column,
                    "type": "number",
                    "count": len(values),
                    "missing": len(values) - len(present),
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "mean": round(sum(numeric_values) / len(numeric_values), 4),
                }
            )
        else:
            top_values = Counter(str(value).strip() for value in present).most_common(3)
            summaries.append(
                {
                    "name": column,
                    "type": "text",
                    "count": len(values),
                    "missing": len(values) - len(present),
                    "unique": len(set(present)),
                    "top_values": [
                        {"value": value, "count": count}
                        for value, count in top_values
                    ],
                }
            )
    return summaries


def _to_number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _markdown_report(
    *,
    display_path: str,
    source_kind: str,
    artifact_path: str,
    table: dict[str, Any],
    column_summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# Data Analysis Report",
        "",
        f"- Source: `{display_path}`",
        f"- Source kind: `{source_kind}`",
        f"- Rows analyzed: {len(table['rows'])}",
        f"- Total rows observed: {table['row_count']}",
        f"- Columns: {len(table['columns'])}",
        f"- Artifact: `{artifact_path}`",
        "",
        "## Column Summary",
        "",
        "| Column | Type | Missing | Summary |",
        "| --- | --- | ---: | --- |",
    ]
    for summary in column_summaries:
        lines.append(_summary_row(summary))
    lines.extend(["", "## Preview", "", _preview_table(table["rows"], table["columns"])])
    return "\n".join(lines).rstrip() + "\n"


def _summary_row(summary: dict[str, Any]) -> str:
    if summary["type"] == "number":
        details = f"min={summary['min']}, max={summary['max']}, mean={summary['mean']}"
    else:
        top = ", ".join(
            f"{item['value']} ({item['count']})"
            for item in summary.get("top_values", [])
        )
        details = f"unique={summary.get('unique', 0)}" + (f"; top={top}" if top else "")
    return (
        f"| {_escape_table(summary['name'])} | {summary['type']} | "
        f"{summary['missing']} | {_escape_table(details)} |"
    )


def _preview_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    preview_rows = rows[:5]
    if not preview_rows:
        return "_No rows to preview._"
    header = "| " + " | ".join(_escape_table(column) for column in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_escape_table(row.get(column, "")) for column in columns) + " |"
        for row in preview_rows
    ]
    return "\n".join([header, divider, *body])


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _source_kind_for_suffix(suffix: str) -> str:
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".tsv":
        return "tsv"
    if suffix == ".csv":
        return "csv"
    return "text"


def _parse_error_result(
    display_path: str,
    *,
    source_kind: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "ok": False,
        "path": display_path,
        "source_kind": source_kind,
        "error": "数据文件解析失败",
        "detail": str(error),
        "hint": (
            "请确认文件格式、编码和扩展名匹配；复杂或专有格式应改走 "
            "workspace.read + terminal.run 的可审批分析路径。"
        ),
        "suggested_tool": "terminal.run",
    }


def _artifact_paths(artifact_path: str, artifact_paths: list[str] | None) -> list[str]:
    candidates = [str(artifact_path or "analysis-report.md").strip() or "analysis-report.md"]
    candidates.extend(str(path or "").strip() for path in artifact_paths or [])
    result: list[str] = []
    for path in candidates:
        if path and path not in result:
            result.append(path)
    return result or ["analysis-report.md"]


def _extra_table_artifacts(
    artifact_paths: list[str],
    *,
    display_path: str,
    source_kind: str,
    table: dict[str, Any],
    column_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in artifact_paths:
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            artifacts.append(
                {
                    "path": path,
                    "kind": "csv",
                    "mime_type": "text/csv",
                    "content": _summary_csv(column_summaries),
                }
            )
        elif suffix == ".html":
            artifacts.append(
                {
                    "path": path,
                    "kind": "html",
                    "mime_type": "text/html",
                    "content": _html_report(
                        display_path=display_path,
                        source_kind=source_kind,
                        table=table,
                        column_summaries=column_summaries,
                    ),
                }
            )
        elif suffix == ".png":
            content = _chart_png(column_summaries)
            artifacts.append(
                {
                    "path": path,
                    "kind": "image",
                    "mime_type": "image/png",
                    "content_bytes": content,
                    "size_bytes": len(content),
                    "width": 640,
                    "height": 360,
                }
            )
    return artifacts


def _extra_text_artifacts(
    artifact_paths: list[str],
    *,
    display_path: str,
    lines: list[str],
    words: list[str],
    text: str,
    preview: str,
) -> list[dict[str, Any]]:
    metrics = [
        {
            "name": "lines",
            "type": "number",
            "missing": 0,
            "mean": len(lines),
            "min": len(lines),
            "max": len(lines),
        },
        {
            "name": "words",
            "type": "number",
            "missing": 0,
            "mean": len(words),
            "min": len(words),
            "max": len(words),
        },
        {
            "name": "characters",
            "type": "number",
            "missing": 0,
            "mean": len(text),
            "min": len(text),
            "max": len(text),
        },
    ]
    artifacts: list[dict[str, Any]] = []
    for path in artifact_paths:
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            artifacts.append(
                {
                    "path": path,
                    "kind": "csv",
                    "mime_type": "text/csv",
                    "content": _summary_csv(metrics),
                }
            )
        elif suffix == ".html":
            artifacts.append(
                {
                    "path": path,
                    "kind": "html",
                    "mime_type": "text/html",
                    "content": _text_html_report(
                        display_path=display_path,
                        lines=lines,
                        words=words,
                        text=text,
                        preview=preview,
                    ),
                }
            )
        elif suffix == ".png":
            content = _chart_png(metrics)
            artifacts.append(
                {
                    "path": path,
                    "kind": "image",
                    "mime_type": "image/png",
                    "content_bytes": content,
                    "size_bytes": len(content),
                    "width": 640,
                    "height": 360,
                }
            )
    return artifacts


def _summary_csv(column_summaries: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["column", "type", "count", "missing", "min", "max", "mean", "unique", "top_values"]
    )
    for summary in column_summaries:
        top_values = "; ".join(
            f"{item.get('value', '')} ({item.get('count', 0)})"
            for item in summary.get("top_values", [])
            if isinstance(item, dict)
        )
        writer.writerow(
            [
                summary.get("name", ""),
                summary.get("type", ""),
                summary.get("count", ""),
                summary.get("missing", ""),
                summary.get("min", ""),
                summary.get("max", ""),
                summary.get("mean", ""),
                summary.get("unique", ""),
                top_values,
            ]
        )
    return output.getvalue()


def _html_report(
    *,
    display_path: str,
    source_kind: str,
    table: dict[str, Any],
    column_summaries: list[dict[str, Any]],
) -> str:
    summary_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(summary.get('name', '')))}</td>"
        f"<td>{html.escape(str(summary.get('type', '')))}</td>"
        f"<td>{html.escape(str(summary.get('missing', '')))}</td>"
        f"<td>{html.escape(_summary_details(summary))}</td>"
        "</tr>"
        for summary in column_summaries
    )
    preview_rows = "\n".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(column, '')))}</td>"
            for column in table["columns"]
        )
        + "</tr>"
        for row in table["rows"][:20]
    )
    preview_header = "".join(
        f"<th>{html.escape(str(column))}</th>" for column in table["columns"]
    )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Data Analysis Report</title>",
            _html_style(),
            "</head>",
            "<body>",
            "<main>",
            "<h1>Data Analysis Report</h1>",
            "<dl>",
            f"<dt>Source</dt><dd>{html.escape(display_path)}</dd>",
            f"<dt>Source kind</dt><dd>{html.escape(source_kind)}</dd>",
            f"<dt>Rows analyzed</dt><dd>{len(table['rows'])}</dd>",
            f"<dt>Total rows observed</dt><dd>{table['row_count']}</dd>",
            f"<dt>Columns</dt><dd>{len(table['columns'])}</dd>",
            "</dl>",
            "<h2>Column Summary</h2>",
            "<table><thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Summary</th></tr></thead>",
            f"<tbody>{summary_rows}</tbody></table>",
            "<h2>Preview</h2>",
            f"<table><thead><tr>{preview_header}</tr></thead><tbody>{preview_rows}</tbody></table>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _text_html_report(
    *,
    display_path: str,
    lines: list[str],
    words: list[str],
    text: str,
    preview: str,
) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Text Analysis Report</title>",
            _html_style(),
            "</head>",
            "<body>",
            "<main>",
            "<h1>Text Analysis Report</h1>",
            "<dl>",
            f"<dt>Source</dt><dd>{html.escape(display_path)}</dd>",
            f"<dt>Lines</dt><dd>{len(lines)}</dd>",
            f"<dt>Words</dt><dd>{len(words)}</dd>",
            f"<dt>Characters</dt><dd>{len(text)}</dd>",
            "</dl>",
            "<h2>Preview</h2>",
            f"<pre>{html.escape(preview)}</pre>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _html_style() -> str:
    return (
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;color:#172033;background:#f7f8fb}"
        "main{max-width:1040px;margin:0 auto;padding:32px}"
        "h1{font-size:28px;margin:0 0 20px}h2{font-size:18px;margin:28px 0 10px}"
        "dl{display:grid;grid-template-columns:160px 1fr;gap:8px 16px}"
        "dt{font-weight:700;color:#4b5875}dd{margin:0}"
        "table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #d8deea;padding:8px;text-align:left}"
        "th{background:#edf1f7}pre{white-space:pre-wrap;background:#fff;border:1px solid #d8deea;padding:16px}"
        "</style>"
    )


def _summary_details(summary: dict[str, Any]) -> str:
    if summary.get("type") == "number":
        return f"min={summary.get('min')}, max={summary.get('max')}, mean={summary.get('mean')}"
    top = ", ".join(
        f"{item.get('value', '')} ({item.get('count', 0)})"
        for item in summary.get("top_values", [])
        if isinstance(item, dict)
    )
    return f"unique={summary.get('unique', 0)}" + (f"; top={top}" if top else "")


def _chart_png(column_summaries: list[dict[str, Any]]) -> bytes:
    width = 640
    height = 360
    pixels = bytearray([248, 250, 252] * width * height)
    _fill_rect(pixels, width, 48, 48, width - 96, height - 96, (255, 255, 255))
    _stroke_rect(pixels, width, 48, 48, width - 96, height - 96, (211, 218, 230))
    values = _chart_values(column_summaries)
    if not values:
        values = [1.0]
    max_value = max(abs(value) for value in values) or 1.0
    plot_x = 82
    plot_y = 70
    plot_w = width - 140
    plot_h = height - 140
    for index in range(5):
        y = plot_y + round(plot_h * index / 4)
        _fill_rect(pixels, width, plot_x, y, plot_w, 1, (230, 235, 244))
    gap = max(8, round(plot_w / max(1, len(values)) * 0.18))
    bar_w = max(14, round((plot_w - gap * (len(values) + 1)) / max(1, len(values))))
    colors = [(20, 184, 166), (59, 130, 246), (245, 158, 11), (168, 85, 247), (16, 185, 129)]
    for index, value in enumerate(values):
        ratio = min(1.0, abs(value) / max_value)
        bar_h = max(3, round(plot_h * ratio))
        x = plot_x + gap + index * (bar_w + gap)
        y = plot_y + plot_h - bar_h
        _fill_rect(pixels, width, x, y, bar_w, bar_h, colors[index % len(colors)])
    return _png_rgb(width, height, bytes(pixels))


def _chart_values(column_summaries: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for summary in column_summaries:
        if summary.get("type") == "number":
            values.append(float(summary.get("mean") or 0))
        elif summary.get("top_values"):
            first = summary["top_values"][0]
            if isinstance(first, dict):
                values.append(float(first.get("count") or 0))
        if len(values) >= 8:
            break
    return values


def _fill_rect(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
) -> None:
    for row in range(max(0, y), max(0, y) + max(0, rect_height)):
        if row >= len(pixels) // (width * 3):
            break
        for col in range(max(0, x), min(width, x + max(0, rect_width))):
            offset = (row * width + col) * 3
            pixels[offset : offset + 3] = bytes(color)


def _stroke_rect(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
) -> None:
    _fill_rect(pixels, width, x, y, rect_width, 1, color)
    _fill_rect(pixels, width, x, y + rect_height - 1, rect_width, 1, color)
    _fill_rect(pixels, width, x, y, 1, rect_height, color)
    _fill_rect(pixels, width, x + rect_width - 1, y, 1, rect_height, color)


def _png_rgb(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    rows = []
    stride = width * 3
    for row in range(height):
        rows.append(b"\x00" + pixels[row * stride : (row + 1) * stride])
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=6))
        + chunk(b"IEND", b"")
    )
