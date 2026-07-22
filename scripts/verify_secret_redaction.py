"""Verify runtime output files do not contain obvious unredacted secrets."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.security import contains_sensitive_text

DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
_TEXT_SUFFIXES = {
    "",
    ".crash",
    ".db",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".out",
    ".sqlite",
    ".sqlite3",
    ".stderr",
    ".stdout",
    ".txt",
    ".wal",
}
_SQLITE_BINARY_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".wal"}
_SQLITE_SIDECAR_ENDINGS = ("-wal", "-journal")
_PRINTABLE_BYTE_RUN_RE = re.compile(rb"[\x20-\x7e]{6,}")
# SQLite can place adjacent text columns in one printable run, so the known
# prefix/field/rotation shape is the boundary; a leading word boundary is not.
_STRICT_KEYCHAIN_CREDENTIAL_REF_RE = re.compile(
    rb"(?:"
    rb"(?:model_source|model_profile):[A-Za-z0-9][A-Za-z0-9._-]{0,127}:api_key"
    rb"|agent:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:model_api_key"
    rb")"
    rb":[0-9a-f]{32}"
    rb"(?![A-Za-z0-9_.:-])"
)
_TRAILING_PARTIAL_KEYCHAIN_CREDENTIAL_REF_RE = re.compile(
    rb"(?:"
    rb"(?:model_source|model_profile):[A-Za-z0-9][A-Za-z0-9._-]{0,127}:api_key"
    rb"|agent:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:model_api_key"
    rb")"
    rb":[0-9a-f]{0,31}$"
)
# A long live SQLite value can continue on an overflow page.  The four-byte
# overflow-page header breaks the preceding printable run, so the safe runtime
# ids ``task-workspace-<12 hex>`` and ``task-core-<12 hex>`` can appear to
# begin with an otherwise secret-looking ``sk-`` fragment. Exempt only those
# exact continuation shapes
# at the start of a printable run; normal sk-* values and longer tokens remain
# findings.
_STRICT_RUNTIME_ID_OVERFLOW_CONTINUATION_RE = re.compile(
    rb"\Ask-(?:workspace|core)-[0-9a-f]{12}(?=[\"}\],])"
)
_TRAILING_PARTIAL_RUNTIME_ID_OVERFLOW_CONTINUATION_RE = re.compile(
    rb"\Ask-(?:workspace|core)-[0-9a-f]{0,11}$"
)
_SQLITE_SCAN_CHUNK_BYTES = 1024 * 1024
_SQLITE_SCAN_OVERLAP_BYTES = 512
_SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    message: str
    line: int | None = None

    def format(self, root: Path = ROOT) -> str:
        try:
            display_path = self.path.resolve().relative_to(root.resolve())
        except ValueError:
            display_path = self.path
        suffix = f":{self.line}" if self.line is not None else ""
        return f"{display_path}{suffix}: {self.message}"


def default_scan_paths() -> list[Path]:
    home = Path(os.getenv("OHA_YACHIYO_HOME", "~/.oha-yachiyo")).expanduser()
    config_home = Path(os.getenv("OHA_YACHIYO_CONFIG_HOME", "~/.oha-yachiyo-config")).expanduser()
    candidates = [
        home,
        config_home,
        Path.home() / "Library" / "Logs" / "Oha-Yachiyo",
        Path.home() / "Library" / "Logs" / "oha-yachiyo",
    ]
    return [path for path in candidates if path.exists()]


def verify_secret_redaction(
    paths: Sequence[Path | str] | None = None,
    *,
    root: Path | str = ROOT,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    include_missing: bool = False,
) -> list[SecretFinding]:
    root_path = Path(root)
    scan_paths = [Path(path) for path in paths] if paths is not None else default_scan_paths()
    findings: list[SecretFinding] = []
    for path in _iter_files(root_path, scan_paths, include_missing=include_missing):
        findings.extend(_scan_file(path, max_file_bytes=max_file_bytes))
    return findings


def _resolve(root: Path, path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return root / candidate


def _iter_files(root: Path, paths: Iterable[Path | str], *, include_missing: bool) -> Iterable[Path]:
    for path in paths:
        resolved = _resolve(root, path)
        if not resolved.exists():
            if include_missing:
                yield resolved
            continue
        if resolved.is_file():
            yield resolved
            continue
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if _should_skip_path(child):
                    continue
                if child.is_file():
                    yield child


def _should_skip_path(path: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def _scan_file(path: Path, *, max_file_bytes: int) -> list[SecretFinding]:
    if not path.exists():
        return [SecretFinding(path, "scan target is missing")]
    if not path.is_file():
        return []
    if path.suffix.lower() not in _TEXT_SUFFIXES and not _is_sqlite_binary_path(path):
        return []
    sqlite_binary = _is_sqlite_binary_path(path)
    try:
        if not sqlite_binary and path.stat().st_size > max_file_bytes:
            return [SecretFinding(path, f"file exceeds max scan size {max_file_bytes} bytes")]
    except OSError as exc:
        return [SecretFinding(path, f"could not stat file: {exc.__class__.__name__}")]
    if sqlite_binary:
        try:
            contains_secret = _sqlite_file_contains_sensitive_binary_run(path)
        except OSError as exc:
            return [SecretFinding(path, f"could not read file: {exc.__class__.__name__}")]
        if not contains_secret:
            return []
        return [SecretFinding(path, "contains unredacted secret-like text")]
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [SecretFinding(path, f"could not read file: {exc.__class__.__name__}")]
    text = data.decode("utf-8", errors="ignore")
    if not contains_sensitive_text(text):
        return []
    line = _first_sensitive_line(text)
    return [SecretFinding(path, "contains unredacted secret-like text", line=line)]


def _is_sqlite_binary_path(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() in _SQLITE_BINARY_SUFFIXES
        or name.endswith(_SQLITE_SIDECAR_ENDINGS)
    )


def _contains_sensitive_binary_run(
    data: bytes,
    *,
    defer_trailing_credential_ref: bool = False,
) -> bool:
    """Scan SQLite/WAL bytes without joining unrelated page fragments.

    SQLite free pages and partially overwritten cells can interleave control
    bytes with old text. Treating the whole file as one decoded string can turn
    fragments of a safe ``[redacted]`` placeholder into a false secret match.
    Real API keys and assignment values are stored as contiguous printable
    bytes, so scanning each printable run preserves detection without joining
    unrelated fragments.
    """

    for match in _PRINTABLE_BYTE_RUN_RE.finditer(data):
        printable_run = _STRICT_RUNTIME_ID_OVERFLOW_CONTINUATION_RE.sub(
            b"[runtime-id-continuation]",
            match.group(),
        )
        printable_run = _STRICT_KEYCHAIN_CREDENTIAL_REF_RE.sub(
            b"[credential-reference]",
            printable_run,
        )
        if defer_trailing_credential_ref and match.end() == len(data):
            printable_run = (
                _TRAILING_PARTIAL_RUNTIME_ID_OVERFLOW_CONTINUATION_RE.sub(
                    b"[pending-runtime-id-continuation]",
                    printable_run,
                )
            )
            printable_run = _TRAILING_PARTIAL_KEYCHAIN_CREDENTIAL_REF_RE.sub(
                b"[pending-credential-reference]",
                printable_run,
            )
        if contains_sensitive_text(printable_run.decode("ascii")):
            return True
    return False


def _sqlite_file_contains_sensitive_binary_run(path: Path) -> bool:
    """Stream a SQLite database or sidecar while preserving chunk boundaries."""

    chunk_bytes = max(1, int(_SQLITE_SCAN_CHUNK_BYTES))
    carry = b""
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            data = carry + chunk
            if _contains_sensitive_binary_run(
                data,
                defer_trailing_credential_ref=True,
            ):
                return True
            carry = _trailing_printable_bytes(data)[-_SQLITE_SCAN_OVERLAP_BYTES:]
    return bool(carry and _contains_sensitive_binary_run(carry))


def _trailing_printable_bytes(data: bytes) -> bytes:
    start = len(data)
    while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
        start -= 1
    return data[start:]


def _first_sensitive_line(text: str) -> int | None:
    for index, line in enumerate(text.splitlines(), start=1):
        if contains_sensitive_text(line):
            return index
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan Oha-Yachiyo runtime output files for obvious unredacted secrets."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to scan. Defaults to OHA_YACHIYO_HOME, config home, and app log dirs.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help=f"Maximum file size to scan; default {DEFAULT_MAX_FILE_BYTES}.",
    )
    parser.add_argument(
        "--include-missing",
        action="store_true",
        help="Report missing explicit paths as findings.",
    )
    args = parser.parse_args(argv)

    paths = args.paths or None
    findings = verify_secret_redaction(
        paths=paths,
        max_file_bytes=max(1, int(args.max_file_bytes)),
        include_missing=bool(args.include_missing),
    )
    if not findings:
        print("secret redaction verification passed")
        return 0
    print("secret redaction verification failed:")
    for finding in findings:
        print(f"- {finding.format()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
