"""Built-in lightweight data analysis for Agent runs."""

from __future__ import annotations

import csv
import io
import json
import math
import re
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
    max_rows: int = 1000,
) -> dict[str, Any]:
    clean_max_rows = max(1, min(int(max_rows or 1000), 10000))
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        table = _xlsx_table(path, max_rows=clean_max_rows)
        source_kind = "xlsx"
    else:
        text = path.read_text(encoding="utf-8")
        if suffix == ".json":
            table = _json_table(text, max_rows=clean_max_rows)
            source_kind = "json"
        elif suffix == ".tsv":
            table = _delimited_table(text, delimiter="\t", max_rows=clean_max_rows)
            source_kind = "tsv"
        elif suffix == ".csv":
            table = _delimited_table(text, delimiter=",", max_rows=clean_max_rows)
            source_kind = "csv"
        else:
            table = _text_table(text, max_rows=clean_max_rows)
            source_kind = "text_table" if table["columns"] else "text"

    if not table["columns"]:
        return _plain_text_report(
            path,
            display_path=display_path,
            artifact_path=artifact_path,
            max_rows=clean_max_rows,
        )

    column_summaries = _column_summaries(table["rows"], table["columns"])
    content = _markdown_report(
        display_path=display_path,
        source_kind=source_kind,
        artifact_path=artifact_path,
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
        "artifact_path": artifact_path,
        "artifact_content": content,
        "summary": (
            f"Analyzed {display_path}: {table['row_count']} rows, "
            f"{len(table['columns'])} columns. Report: {artifact_path}."
        ),
    }


def _plain_text_report(
    path: Path,
    *,
    display_path: str,
    artifact_path: str,
    max_rows: int,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
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
        "artifact_content": content,
        "summary": f"Analyzed text file {display_path}. Report: {artifact_path}.",
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
