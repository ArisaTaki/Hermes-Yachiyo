#!/usr/bin/env python3
"""Collect a redacted Oha-Yachiyo release diagnostics bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.security import (  # noqa: E402
    contains_sensitive_text,
    redact_log_text,
    sanitize_sensitive_value,
)

DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
SUPPORTED_TEXT_SUFFIXES = {
    ".crash",
    ".err",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".out",
    ".stderr",
    ".stdout",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class DiagnosticFile:
    path: Path
    source: str
    explicit: bool = False


def collect_release_diagnostics(
    *,
    label: str | None = None,
    output_zip: Path | None = None,
    includes: Sequence[Path | str] = (),
    include_app_logs: bool = False,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    """Write a zip with redacted RC/signoff reports and optional log files."""

    clean_label = _clean_label(label or _git_short_commit() or "current")
    target = _resolve_output_zip(
        output_zip or Path("tmp") / f"oha-yachiyo-diagnostics-{clean_label}.zip"
    )
    max_bytes = max(1, int(max_file_bytes))
    requested_sources = _requested_sources(
        clean_label,
        includes=includes,
        include_app_logs=include_app_logs,
    )
    files = _expand_requested_sources(requested_sources)
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    used_archive_names: set[str] = set()

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for diagnostic_file in files:
            if _same_file(diagnostic_file.path, target):
                skipped.append(_skip_entry(diagnostic_file, "output_zip"))
                continue
            archive_name = _archive_name(
                diagnostic_file.path,
                used_archive_names=used_archive_names,
            )
            try:
                content, byte_count = _redacted_file_content(
                    diagnostic_file.path,
                    max_file_bytes=max_bytes,
                )
            except SkipFile as exc:
                skipped.append(_skip_entry(diagnostic_file, exc.reason))
                continue
            archive.writestr(archive_name, content)
            included.append(
                {
                    "source": _display_path(diagnostic_file.path),
                    "archive_path": archive_name,
                    "source_kind": diagnostic_file.source,
                    "bytes": byte_count,
                    "redacted": True,
                }
            )

        manifest = _manifest(
            label=clean_label,
            output_zip=target,
            requested_sources=requested_sources,
            included=included,
            skipped=skipped,
        )
        archive.writestr(
            "diagnostics/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    return manifest


def _requested_sources(
    label: str,
    *,
    includes: Sequence[Path | str],
    include_app_logs: bool,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {"kind": "release_artifact_glob", "pattern": f"tmp/rc-verification-{label}-*.json"},
        {"kind": "release_artifact_glob", "pattern": f"tmp/rc-verification-{label}-*.md"},
        {"kind": "release_artifact_glob", "pattern": f"tmp/rc-signoff-{label}-*.json"},
        {"kind": "release_artifact_glob", "pattern": f"tmp/rc-signoff-{label}-*.md"},
        {"kind": "release_artifact_glob", "pattern": f"tmp/external-integrations-smoke-{label}.json"},
        {"kind": "release_artifact_glob", "pattern": f"tmp/oha-parity-summary-{label}.json"},
    ]
    for include in includes:
        sources.append(
            {
                "kind": "explicit_include",
                "path": str(include),
            }
        )
    if include_app_logs:
        for path in _default_app_log_paths():
            sources.append(
                {
                    "kind": "app_log_dir",
                    "path": str(path),
                }
            )
    return sources


def _expand_requested_sources(sources: Sequence[dict[str, Any]]) -> list[DiagnosticFile]:
    files: list[DiagnosticFile] = []
    seen: set[Path] = set()
    for source in sources:
        kind = str(source.get("kind") or "source")
        pattern = source.get("pattern")
        if isinstance(pattern, str):
            matches = sorted(ROOT.glob(pattern))
            if not matches:
                files.append(DiagnosticFile(ROOT / pattern, kind))
                continue
            for match in matches:
                _append_file(files, seen, match, source=kind)
            continue
        raw_path = source.get("path")
        if not raw_path:
            continue
        resolved = _resolve_path(Path(str(raw_path)))
        if not resolved.exists():
            files.append(
                DiagnosticFile(
                    resolved,
                    kind,
                    explicit=kind == "explicit_include",
                )
            )
            continue
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if _should_skip_path(child) or not child.is_file():
                    continue
                _append_file(
                    files,
                    seen,
                    child,
                    source=kind,
                    explicit=kind == "explicit_include",
                )
        else:
            _append_file(
                files,
                seen,
                resolved,
                source=kind,
                explicit=kind == "explicit_include",
            )
    return files


def _append_file(
    files: list[DiagnosticFile],
    seen: set[Path],
    path: Path,
    *,
    source: str,
    explicit: bool = False,
) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    files.append(DiagnosticFile(resolved, source, explicit=explicit))


def _redacted_file_content(path: Path, *, max_file_bytes: int) -> tuple[str, int]:
    if not path.exists():
        raise SkipFile("missing")
    if not path.is_file():
        raise SkipFile("not_file")
    if _should_skip_path(path):
        raise SkipFile("skipped_path")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        raise SkipFile("unsupported_suffix")
    try:
        byte_count = path.stat().st_size
    except OSError as exc:
        raise SkipFile(f"stat_failed:{exc.__class__.__name__}") from exc
    if byte_count > max_file_bytes:
        raise SkipFile("too_large")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SkipFile(f"read_failed:{exc.__class__.__name__}") from exc
    if _looks_binary(data):
        raise SkipFile("binary")
    text = data.decode("utf-8", errors="replace")
    if suffix == ".json":
        redacted = _redacted_json_text(text)
    elif suffix == ".jsonl":
        redacted = _redacted_jsonl_text(text)
    else:
        redacted = redact_log_text(text)
    if contains_sensitive_text(redacted):
        raise SkipFile("redaction_failed")
    return redacted if redacted.endswith("\n") else redacted + "\n", byte_count


def _redacted_json_text(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return redact_log_text(text)
    redacted = sanitize_sensitive_value(
        payload,
        max_depth=8,
        text_limit=0,
        max_items=500,
        collapse_whitespace=False,
        trim=False,
    )
    return json.dumps(redacted, ensure_ascii=False, indent=2)


def _redacted_jsonl_text(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            lines.append("")
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            lines.append(redact_log_text(line))
            continue
        redacted = sanitize_sensitive_value(
            payload,
            max_depth=8,
            text_limit=0,
            max_items=500,
            collapse_whitespace=False,
            trim=False,
        )
        lines.append(json.dumps(redacted, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def _manifest(
    *,
    label: str,
    output_zip: Path,
    requested_sources: Sequence[dict[str, Any]],
    included: Sequence[dict[str, Any]],
    skipped: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    redaction_failures = [
        item for item in skipped if item.get("reason") == "redaction_failed"
    ]
    return {
        "ok": bool(included) and not redaction_failures,
        "bundle_format": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "output_zip": _display_path(output_zip),
        "redaction": {
            "applied": True,
            "fail_closed": True,
            "helper": "packages.security",
        },
        "requested_sources": [_public_source_entry(item) for item in requested_sources],
        "included_count": len(included),
        "skipped_count": len(skipped),
        "included": list(included),
        "skipped": list(skipped),
    }


def _public_source_entry(source: Mapping[str, Any]) -> dict[str, str]:
    result = {"kind": str(source.get("kind") or "source")}
    if source.get("pattern"):
        result["pattern"] = str(source["pattern"])
    elif source.get("path"):
        result["path"] = _display_path(_resolve_path(Path(str(source["path"]))))
    return result


def _skip_entry(diagnostic_file: DiagnosticFile, reason: str) -> dict[str, Any]:
    return {
        "source": _display_path(diagnostic_file.path),
        "source_kind": diagnostic_file.source,
        "reason": reason,
        "explicit": diagnostic_file.explicit,
    }


def _archive_name(path: Path, *, used_archive_names: set[str]) -> str:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
        base = "diagnostics/" + relative.as_posix()
    except ValueError:
        base = "diagnostics/external/" + _safe_external_name(path)
    candidate = base
    suffix = path.suffix
    stem = candidate[: -len(suffix)] if suffix else candidate
    index = 2
    while candidate in used_archive_names:
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used_archive_names.add(candidate)
    return candidate


def _safe_external_name(path: Path) -> str:
    parts = [part for part in path.parts if part not in {"/", ""}]
    visible = parts[-3:] if len(parts) >= 3 else parts
    text = "__".join(visible) or path.name or "external"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in text)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return "external/" + _safe_external_name(path)


def _resolve_output_zip(path: Path) -> Path:
    return _resolve_path(path)


def _resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return ROOT / expanded


def _looks_binary(data: bytes) -> bool:
    return b"\0" in data[:4096]


def _should_skip_path(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _default_app_log_paths() -> list[Path]:
    home = Path.home()
    return [
        home / "Library" / "Logs" / "Oha-Yachiyo",
        home / "Library" / "Logs" / "oha-yachiyo",
        Path("~/.oha-yachiyo/logs").expanduser(),
        Path("~/.oha-yachiyo-config/logs").expanduser(),
    ]


def _clean_label(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in "._-" else "-" for char in value.strip())
    return clean or "current"


def _git_short_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


class SkipFile(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="RC label or short commit. Defaults to current git HEAD.")
    parser.add_argument(
        "--output-zip",
        type=Path,
        help="Bundle path. Defaults to tmp/oha-yachiyo-diagnostics-<label>.zip.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        type=Path,
        help="Extra text file or directory to include after redaction. Can be repeated.",
    )
    parser.add_argument(
        "--include-app-logs",
        action="store_true",
        help="Also include standard local Oha-Yachiyo app log directories when present.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help=f"Skip individual files larger than this; default {DEFAULT_MAX_FILE_BYTES}.",
    )
    args = parser.parse_args(argv)

    manifest = collect_release_diagnostics(
        label=args.label,
        output_zip=args.output_zip,
        includes=args.include,
        include_app_logs=bool(args.include_app_logs),
        max_file_bytes=args.max_file_bytes,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
