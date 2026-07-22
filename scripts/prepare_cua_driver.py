#!/usr/bin/env python3
"""Prepare the pinned macOS Cua Driver sidecar for Electron packaging."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "packaging" / "cua-driver.lock.json"
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "cua-driver" / "macos"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_MAX_BINARY_BYTES = 128 * 1024 * 1024
_MAX_LICENSE_BYTES = 1024 * 1024
_TOP_LEVEL_KEYS = {
    "schema_version",
    "name",
    "version",
    "tag",
    "platform",
    "architectures",
    "archive",
    "license",
}
_ARCHIVE_KEYS = {
    "name",
    "url",
    "sha256",
    "binary_member",
    "binary_content_hash_algorithm",
    "binary_content_sha256",
}
_LICENSE_KEYS = {"name", "url", "sha256", "spdx"}
_BINARY_CONTENT_HASH_ALGORITHM = "mach-o-without-code-signature-v1"


class CuaDriverPreparationError(RuntimeError):
    """The pinned driver could not be prepared safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CuaDriverPreparationError(f"{label} is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CuaDriverPreparationError(f"{label} must be a regular file: {path}")
    return path


def _string_field(payload: Mapping[str, Any], name: str, *, section: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CuaDriverPreparationError(f"{section}.{name} must be a non-empty string")
    return value.strip()


def _sha256_field(payload: Mapping[str, Any], name: str, *, section: str) -> str:
    value = _string_field(payload, name, section=section).lower()
    if not _SHA256_PATTERN.fullmatch(value):
        raise CuaDriverPreparationError(f"{section}.{name} must be a lowercase SHA256")
    return value


def _safe_file_name(value: str, *, field: str) -> str:
    if value in {"", ".", ".."} or Path(value).name != value or "\\" in value:
        raise CuaDriverPreparationError(f"{field} must be a plain file name")
    return value


def _https_url(value: str, *, field: str, allowed_host: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CuaDriverPreparationError(f"{field} must use the official HTTPS host")
    if "/trycua/cua/" not in parsed.path:
        raise CuaDriverPreparationError(f"{field} must reference trycua/cua")
    return value


def load_lock(path: Path = DEFAULT_LOCK_PATH) -> dict[str, Any]:
    """Load and strictly validate the source-controlled dependency lock."""

    lock_path = _regular_file(Path(path), label="Cua Driver lock")
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CuaDriverPreparationError(f"Invalid Cua Driver lock: {lock_path}") from exc
    if not isinstance(payload, dict):
        raise CuaDriverPreparationError("Cua Driver lock must contain one JSON object")
    if set(payload) != _TOP_LEVEL_KEYS:
        raise CuaDriverPreparationError("Cua Driver lock has missing or unsupported fields")
    if payload.get("schema_version") != 1:
        raise CuaDriverPreparationError("Unsupported Cua Driver lock schema_version")
    if _string_field(payload, "name", section="lock") != "cua-driver":
        raise CuaDriverPreparationError("lock.name must be cua-driver")
    version = _string_field(payload, "version", section="lock")
    if not _VERSION_PATTERN.fullmatch(version):
        raise CuaDriverPreparationError("lock.version must be a semantic version")
    tag = _string_field(payload, "tag", section="lock")
    if tag != f"cua-driver-rs-v{version}":
        raise CuaDriverPreparationError("lock.tag must exactly identify the locked version")
    if _string_field(payload, "platform", section="lock") != "darwin-universal":
        raise CuaDriverPreparationError("lock.platform must be darwin-universal")

    architectures = payload.get("architectures")
    if (
        not isinstance(architectures, list)
        or not architectures
        or any(not isinstance(value, str) or not value for value in architectures)
        or len(set(architectures)) != len(architectures)
        or set(architectures) != {"arm64", "x86_64"}
    ):
        raise CuaDriverPreparationError("lock.architectures must contain arm64 and x86_64")

    archive = payload.get("archive")
    if not isinstance(archive, dict) or set(archive) != _ARCHIVE_KEYS:
        raise CuaDriverPreparationError("lock.archive has missing or unsupported fields")
    archive_name = _safe_file_name(
        _string_field(archive, "name", section="archive"),
        field="archive.name",
    )
    archive_url = _https_url(
        _string_field(archive, "url", section="archive"),
        field="archive.url",
        allowed_host="github.com",
    )
    if urlparse(archive_url).path != (
        f"/trycua/cua/releases/download/{tag}/{archive_name}"
    ):
        raise CuaDriverPreparationError(
            "archive.url must match lock.tag and archive.name"
        )
    _sha256_field(archive, "sha256", section="archive")
    binary_member = _safe_file_name(
        _string_field(archive, "binary_member", section="archive"),
        field="archive.binary_member",
    )
    if binary_member != "cua-driver":
        raise CuaDriverPreparationError("archive.binary_member must be cua-driver")
    content_hash_algorithm = _string_field(
        archive,
        "binary_content_hash_algorithm",
        section="archive",
    )
    if content_hash_algorithm != _BINARY_CONTENT_HASH_ALGORITHM:
        raise CuaDriverPreparationError(
            "archive.binary_content_hash_algorithm must be "
            f"{_BINARY_CONTENT_HASH_ALGORITHM}"
        )
    _sha256_field(archive, "binary_content_sha256", section="archive")

    license_record = payload.get("license")
    if not isinstance(license_record, dict) or set(license_record) != _LICENSE_KEYS:
        raise CuaDriverPreparationError("lock.license has missing or unsupported fields")
    license_name = _safe_file_name(
        _string_field(license_record, "name", section="license"),
        field="license.name",
    )
    if license_name != "LICENSE.md":
        raise CuaDriverPreparationError("license.name must be LICENSE.md")
    license_url = _https_url(
        _string_field(license_record, "url", section="license"),
        field="license.url",
        allowed_host="raw.githubusercontent.com",
    )
    if urlparse(license_url).path != f"/trycua/cua/{tag}/{license_name}":
        raise CuaDriverPreparationError(
            "license.url must match lock.tag and license.name"
        )
    _sha256_field(license_record, "sha256", section="license")
    if _string_field(license_record, "spdx", section="license") != "MIT":
        raise CuaDriverPreparationError("license.spdx must be MIT")
    return payload


def _default_cache_dir() -> Path:
    override = os.environ.get("OHA_YACHIYO_CUA_DRIVER_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Caches" / "Oha-Yachiyo" / "cua-driver"
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "oha-yachiyo" / "cua-driver"


def _verify_hash(path: Path, expected_sha256: str, *, label: str) -> None:
    actual = _sha256_file(_regular_file(path, label=label))
    if actual != expected_sha256:
        raise CuaDriverPreparationError(
            f"{label} SHA256 mismatch: expected {expected_sha256}, got {actual}"
        )


def _binary_content_sha256(
    binary_path: Path,
    *,
    algorithm: str,
    run: Callable[..., Any] = subprocess.run,
    codesign_path: Path = Path("/usr/bin/codesign"),
) -> str:
    """Hash stable binary content without ever mutating the packaged source."""

    source = _regular_file(binary_path, label="Cua Driver binary")
    if algorithm != _BINARY_CONTENT_HASH_ALGORITHM:
        raise CuaDriverPreparationError(
            f"Unsupported Cua Driver content hash algorithm: {algorithm}"
        )

    codesign = _regular_file(Path(codesign_path), label="codesign")
    if not os.access(codesign, os.X_OK):
        raise CuaDriverPreparationError(f"codesign is not executable: {codesign}")
    with tempfile.TemporaryDirectory(
        prefix=".cua-driver-content-", dir=source.parent
    ) as temporary:
        canonical_binary = Path(temporary) / "cua-driver"
        shutil.copyfile(source, canonical_binary)
        canonical_binary.chmod(0o700)
        command = [str(codesign), "--remove-signature", str(canonical_binary)]
        try:
            completed = run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CuaDriverPreparationError(
                "Unable to remove the Cua Driver signature for content hashing"
            ) from exc
        if completed.returncode != 0:
            detail = str(completed.stderr or completed.stdout or "").strip()
            raise CuaDriverPreparationError(
                f"codesign --remove-signature failed: {detail}"
            )
        return _sha256_file(
            _regular_file(canonical_binary, label="canonical Cua Driver binary")
        )


def _download(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: BaseException | None = None
    for attempt in range(attempts):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".download",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            total = 0
            with os.fdopen(descriptor, "wb") as output:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Oha-Yachiyo-Cua-Driver-Builder/1"},
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise CuaDriverPreparationError(
                                "Downloaded dependency exceeds size limit"
                            )
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, destination)
            return
        except (
            http.client.HTTPException,
            OSError,
            urllib.error.URLError,
        ) as exc:
            last_error = exc
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        if attempt + 1 < attempts:
            sleep(0.2 * (2**attempt))
    raise CuaDriverPreparationError(
        f"Failed to download {url} after {attempts} attempts"
    ) from last_error


def _dependency_input(
    *,
    explicit_path: Path | None,
    cache_path: Path,
    url: str,
    sha256: str,
    label: str,
    offline: bool,
    max_bytes: int,
    downloader: Callable[..., None] = _download,
) -> Path:
    if explicit_path is not None:
        source = Path(explicit_path).expanduser()
        _verify_hash(source, sha256, label=label)
        return source
    if cache_path.exists():
        try:
            _verify_hash(cache_path, sha256, label=f"cached {label}")
            return cache_path
        except CuaDriverPreparationError:
            if offline:
                raise
            cache_path.unlink()
    if offline:
        raise CuaDriverPreparationError(
            f"Offline preparation requires cached {label}: {cache_path}"
        )
    downloader(url, cache_path, max_bytes=max_bytes)
    _verify_hash(cache_path, sha256, label=f"downloaded {label}")
    return cache_path


def safe_extract_binary(archive_path: Path, destination: Path, *, member_name: str) -> None:
    """Extract only the locked root-level regular file, never archive paths."""

    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) != 1:
                raise CuaDriverPreparationError(
                    "Cua Driver archive must contain exactly one regular file"
                )
            member = members[0]
            if (
                member.name != member_name
                or not member.isfile()
                or member.issym()
                or member.islnk()
                or member.size <= 0
                or member.size > _MAX_BINARY_BYTES
            ):
                raise CuaDriverPreparationError(
                    "Cua Driver archive member does not match the locked binary"
                )
            source = archive.extractfile(member)
            if source is None:
                raise CuaDriverPreparationError("Cua Driver archive binary is unreadable")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source, destination.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    except (OSError, tarfile.TarError) as exc:
        raise CuaDriverPreparationError("Invalid Cua Driver archive") from exc
    destination.chmod(0o755)


def _run_checked(command: Sequence[str], *, label: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [str(part) for part in command],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CuaDriverPreparationError(f"Unable to run {label}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise CuaDriverPreparationError(f"{label} failed: {detail}")
    return completed


def validate_macos_binary(
    binary_path: Path,
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the executable surface and both Mach-O architectures on macOS."""

    version = str(lock["version"])
    version_output = _run_checked([str(binary_path), "--version"], label="cua-driver --version")
    if version_output.stdout.strip() != f"cua-driver {version}":
        raise CuaDriverPreparationError("Cua Driver binary version does not match the lock")

    manifest_output = _run_checked([str(binary_path), "manifest"], label="cua-driver manifest")
    try:
        manifest = json.loads(manifest_output.stdout)
    except json.JSONDecodeError as exc:
        raise CuaDriverPreparationError("Cua Driver manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or str(manifest.get("binary_version")) != version:
        raise CuaDriverPreparationError("Cua Driver manifest version does not match the lock")
    invocation = manifest.get("mcp_invocation")
    if not isinstance(invocation, dict) or invocation.get("args") != ["mcp"]:
        raise CuaDriverPreparationError("Cua Driver manifest has an unexpected MCP invocation")
    subcommands = manifest.get("subcommands")
    mcp_command = next(
        (
            item
            for item in subcommands
            if isinstance(item, dict) and item.get("name") == "mcp"
        ),
        None,
    ) if isinstance(subcommands, list) else None
    argument_names = {
        item.get("name")
        for item in (mcp_command or {}).get("args", [])
        if isinstance(item, dict)
    }
    if not {"--embedded", "--host-bundle-id"}.issubset(argument_names):
        raise CuaDriverPreparationError("Cua Driver manifest lacks the embedded host contract")

    lipo = shutil.which("lipo")
    if not lipo:
        raise CuaDriverPreparationError("lipo is required to validate the universal binary")
    lipo_output = _run_checked([lipo, "-archs", str(binary_path)], label="lipo -archs")
    actual_architectures = set(lipo_output.stdout.split())
    expected_architectures = set(str(value) for value in lock["architectures"])
    if actual_architectures != expected_architectures:
        raise CuaDriverPreparationError("Cua Driver binary architectures do not match the lock")
    return {
        "binary_version": version,
        "manifest_schema_version": str(manifest.get("schema_version") or ""),
        "embedded_mcp": True,
        "architectures": sorted(actual_architectures),
    }


def _lock_reference(lock_path: Path) -> str:
    resolved = lock_path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def prepare_cua_driver(
    *,
    lock_path: Path = DEFAULT_LOCK_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    cache_dir: Path | None = None,
    archive_path: Path | None = None,
    license_path: Path | None = None,
    offline: bool = False,
    clean: bool = False,
    validate_macos: bool | None = None,
    content_digest: Callable[..., str] = _binary_content_sha256,
) -> dict[str, Any]:
    lock_path = Path(lock_path)
    output_dir = Path(output_dir)
    cache_dir = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
    lock = load_lock(lock_path)
    archive = lock["archive"]
    license_record = lock["license"]

    archive_source = _dependency_input(
        explicit_path=archive_path,
        cache_path=cache_dir / str(archive["name"]),
        url=str(archive["url"]),
        sha256=str(archive["sha256"]),
        label="Cua Driver archive",
        offline=offline,
        max_bytes=_MAX_BINARY_BYTES,
    )
    license_source = _dependency_input(
        explicit_path=license_path,
        cache_path=cache_dir / str(license_record["name"]),
        url=str(license_record["url"]),
        sha256=str(license_record["sha256"]),
        label="Cua Driver license",
        offline=offline,
        max_bytes=_MAX_LICENSE_BYTES,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    with tempfile.TemporaryDirectory(
        prefix=".cua-driver-stage-", dir=output_dir.parent
    ) as temporary:
        staging = Path(temporary)
        binary_path = staging / "cua-driver"
        safe_extract_binary(
            archive_source,
            binary_path,
            member_name=str(archive["binary_member"]),
        )
        content_hash_algorithm = str(archive["binary_content_hash_algorithm"])
        content_sha256 = content_digest(
            binary_path,
            algorithm=content_hash_algorithm,
        )
        expected_content_sha256 = str(archive["binary_content_sha256"])
        if content_sha256 != expected_content_sha256:
            raise CuaDriverPreparationError(
                "Cua Driver binary content SHA256 mismatch: "
                f"expected {expected_content_sha256}, got {content_sha256}"
            )
        shutil.copyfile(
            _regular_file(license_source, label="Cua Driver license"),
            staging / "LICENSE.md",
        )
        (staging / "LICENSE.md").chmod(0o644)

        should_validate = (
            platform.system() == "Darwin"
            if validate_macos is None
            else validate_macos
        )
        validation = (
            validate_macos_binary(binary_path, lock)
            if should_validate
            else {
                "binary_version": str(lock["version"]),
                "manifest_schema_version": "not-run",
                "embedded_mcp": True,
                "architectures": sorted(str(value) for value in lock["architectures"]),
            }
        )
        manifest = {
            "schema_version": 1,
            "component": str(lock["name"]),
            "version": str(lock["version"]),
            "tag": str(lock["tag"]),
            "platform": str(lock["platform"]),
            "architectures": list(lock["architectures"]),
            "lock": {
                "path": _lock_reference(lock_path),
                "sha256": _sha256_file(lock_path),
            },
            "source": {
                "archive_name": str(archive["name"]),
                "archive_url": str(archive["url"]),
                "archive_sha256": str(archive["sha256"]),
            },
            "binary": {
                "file": "cua-driver",
                "sha256": _sha256_file(binary_path),
                "content_hash_algorithm": content_hash_algorithm,
                "content_sha256": content_sha256,
                "size": binary_path.stat().st_size,
                "mode": "0755",
            },
            "license": {
                "file": "LICENSE.md",
                "spdx": str(license_record["spdx"]),
                "source_url": str(license_record["url"]),
                "sha256": str(license_record["sha256"]),
            },
            "validation": validation,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "manifest.json").chmod(0o644)

        output_dir.mkdir(parents=True, exist_ok=True)
        for name in ("cua-driver", "LICENSE.md", "manifest.json"):
            os.replace(staging / name, output_dir / name)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--archive", type=Path, help="Use a local locked archive")
    parser.add_argument(
        "--license",
        dest="license_path",
        type=Path,
        help="Use a local locked LICENSE.md",
    )
    parser.add_argument("--offline", action="store_true", help="Forbid network access")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove generated output before preparing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = prepare_cua_driver(
            lock_path=args.lock,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            archive_path=args.archive,
            license_path=args.license_path,
            offline=args.offline,
            clean=args.clean,
        )
    except CuaDriverPreparationError as exc:
        print(f"prepare_cua_driver: {exc}", file=sys.stderr)
        return 1
    print(
        f"Prepared cua-driver {manifest['version']} at {Path(args.output_dir).resolve()}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
