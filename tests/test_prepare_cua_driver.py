from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import tarfile
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import scripts.prepare_cua_driver as prepare_module
from scripts.prepare_cua_driver import (
    CuaDriverPreparationError,
    load_lock,
    prepare_cua_driver,
    safe_extract_binary,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _archive(path: Path, payload: bytes, *, member_name: str = "cua-driver") -> bytes:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        member.mode = 0o755
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return path.read_bytes()


def _lock_payload(
    *,
    archive_name: str,
    archive_sha256: str,
    license_sha256: str,
    binary_content_sha256: str,
    binary_content_hash_algorithm: str = "mach-o-without-code-signature-v1",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "cua-driver",
        "version": "0.7.1",
        "tag": "cua-driver-rs-v0.7.1",
        "platform": "darwin-universal",
        "architectures": ["arm64", "x86_64"],
        "archive": {
            "name": archive_name,
            "url": (
                "https://github.com/trycua/cua/releases/download/"
                f"cua-driver-rs-v0.7.1/{archive_name}"
            ),
            "sha256": archive_sha256,
            "binary_member": "cua-driver",
            "binary_content_hash_algorithm": binary_content_hash_algorithm,
            "binary_content_sha256": binary_content_sha256,
        },
        "license": {
            "name": "LICENSE.md",
            "url": (
                "https://raw.githubusercontent.com/trycua/cua/"
                "cua-driver-rs-v0.7.1/LICENSE.md"
            ),
            "sha256": license_sha256,
            "spdx": "MIT",
        },
    }


def _write_lock(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_default_lock_pins_the_reviewed_release_inputs() -> None:
    lock = load_lock(ROOT / "packaging" / "cua-driver.lock.json")

    assert lock["version"] == "0.7.1"
    assert lock["tag"] == "cua-driver-rs-v0.7.1"
    assert lock["archive"]["name"] == (
        "cua-driver-rs-0.7.1-darwin-universal-binary.tar.gz"
    )
    assert lock["archive"]["sha256"] == (
        "43a78c1789c6f0fff12f87b5d4089e4d4da5f256832ca9a7c5f5fdaa79ba76d4"
    )
    assert lock["archive"]["binary_content_hash_algorithm"] == (
        "mach-o-without-code-signature-v1"
    )
    assert lock["archive"]["binary_content_sha256"] == (
        "7e9c8a57f060883e4c45cabb25fa2b4bf0fca850107316cee344a4c18ffed191"
    )
    assert lock["license"]["sha256"] == (
        "c0779290c1d4783169aa3dbfb55feb505e563ef8a004bbf55298ceffcfbda8d9"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1},
        {"schema_version": 2},
        ["not", "an", "object"],
    ],
)
def test_incomplete_or_invalid_lock_fails_closed(
    tmp_path: Path, payload: Any
) -> None:
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CuaDriverPreparationError):
        load_lock(lock_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tag", "cua-driver-rs-v0.7.1-tampered"),
        (
            "archive_url",
            "https://github.com/trycua/cua/releases/download/"
            "cua-driver-rs-v9.9.9/driver.tar.gz",
        ),
        (
            "license_url",
            "https://raw.githubusercontent.com/trycua/cua/"
            "cua-driver-rs-v9.9.9/LICENSE.md",
        ),
        ("content_algorithm", "unreviewed-signature-bypass-v1"),
    ],
)
def test_lock_rejects_tag_or_url_version_drift(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = _lock_payload(
        archive_name="driver.tar.gz",
        archive_sha256="0" * 64,
        license_sha256="1" * 64,
        binary_content_sha256="2" * 64,
    )
    if field == "tag":
        payload["tag"] = value
    elif field == "archive_url":
        payload["archive"]["url"] = value
    elif field == "license_url":
        payload["license"]["url"] = value
    else:
        payload["archive"]["binary_content_hash_algorithm"] = value
    lock_path = tmp_path / "lock.json"
    _write_lock(lock_path, payload)

    with pytest.raises(CuaDriverPreparationError):
        load_lock(lock_path)


def test_prepare_rejects_archive_sha_mismatch(tmp_path: Path) -> None:
    archive_path = tmp_path / "driver.tar.gz"
    _archive(archive_path, b"fake driver")
    license_path = tmp_path / "LICENSE.md"
    license_path.write_bytes(b"MIT\n")
    lock_path = tmp_path / "lock.json"
    _write_lock(
        lock_path,
        _lock_payload(
            archive_name=archive_path.name,
            archive_sha256="0" * 64,
            license_sha256=_sha256(license_path.read_bytes()),
            binary_content_sha256=_sha256(b"fake driver"),
        ),
    )

    with pytest.raises(CuaDriverPreparationError, match="SHA256 mismatch"):
        prepare_cua_driver(
            lock_path=lock_path,
            output_dir=tmp_path / "output",
            archive_path=archive_path,
            license_path=license_path,
            offline=True,
            validate_macos=False,
        )


def test_mach_o_content_hash_uses_a_temporary_copy_and_preserves_source(
    tmp_path: Path,
) -> None:
    source_payload = b"signed Mach-O bytes"
    canonical_payload = b"unsigned Mach-O bytes"
    binary_path = tmp_path / "cua-driver"
    binary_path.write_bytes(source_payload)
    binary_path.chmod(0o755)
    codesign_path = tmp_path / "codesign"
    codesign_path.write_text("fixture", encoding="utf-8")
    codesign_path.chmod(0o755)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(canonical_payload)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    content_sha256 = prepare_module._binary_content_sha256(
        binary_path,
        algorithm="mach-o-without-code-signature-v1",
        run=run,
        codesign_path=codesign_path,
    )

    assert content_sha256 == _sha256(canonical_payload)
    assert binary_path.read_bytes() == source_payload
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:2] == [str(codesign_path), "--remove-signature"]
    assert Path(command[-1]) != binary_path
    assert kwargs["timeout"] == 30
    assert kwargs["check"] is False


def test_mach_o_content_hash_fails_closed_when_codesign_fails(
    tmp_path: Path,
) -> None:
    binary_path = tmp_path / "cua-driver"
    binary_path.write_bytes(b"signed Mach-O bytes")
    binary_path.chmod(0o755)
    codesign_path = tmp_path / "codesign"
    codesign_path.write_text("fixture", encoding="utf-8")
    codesign_path.chmod(0o755)

    with pytest.raises(CuaDriverPreparationError, match="remove-signature failed"):
        prepare_module._binary_content_sha256(
            binary_path,
            algorithm="mach-o-without-code-signature-v1",
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="not signed",
            ),
            codesign_path=codesign_path,
        )

    assert binary_path.read_bytes() == b"signed Mach-O bytes"


def test_prepare_rejects_binary_content_sha_mismatch(tmp_path: Path) -> None:
    binary = b"fake universal driver"
    archive_path = tmp_path / "driver.tar.gz"
    archive_bytes = _archive(archive_path, binary)
    license_payload = b"MIT License\n"
    license_path = tmp_path / "LICENSE.md"
    license_path.write_bytes(license_payload)
    lock_path = tmp_path / "lock.json"
    _write_lock(
        lock_path,
        _lock_payload(
            archive_name=archive_path.name,
            archive_sha256=_sha256(archive_bytes),
            license_sha256=_sha256(license_payload),
            binary_content_sha256="0" * 64,
        ),
    )

    with pytest.raises(CuaDriverPreparationError, match="content SHA256 mismatch"):
        prepare_cua_driver(
            lock_path=lock_path,
            output_dir=tmp_path / "output",
            archive_path=archive_path,
            license_path=license_path,
            offline=True,
            validate_macos=False,
            content_digest=lambda *_args, **_kwargs: _sha256(binary),
        )

    assert archive_path.read_bytes() == archive_bytes


def test_download_retries_network_errors_then_atomically_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete driver archive"
    calls = 0
    delays: list[float] = []

    class Response:
        def __init__(self) -> None:
            self._remaining = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            chunk, self._remaining = self._remaining, b""
            return chunk

    def urlopen(*_args: Any, **_kwargs: Any) -> Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.URLError("temporary network error")
        return Response()

    monkeypatch.setattr(prepare_module.urllib.request, "urlopen", urlopen)
    destination = tmp_path / "cache" / "driver.tar.gz"

    prepare_module._download(
        "https://github.com/trycua/cua/releases/download/test/driver.tar.gz",
        destination,
        max_bytes=1024,
        sleep=delays.append,
    )

    assert calls == 3
    assert delays == [0.2, 0.4]
    assert destination.read_bytes() == payload
    assert list(destination.parent.glob(".*.download")) == []


def test_safe_extraction_rejects_traversal_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    _archive(archive_path, b"fake driver", member_name="../cua-driver")

    with pytest.raises(CuaDriverPreparationError):
        safe_extract_binary(
            archive_path,
            tmp_path / "cua-driver",
            member_name="cua-driver",
        )

    assert not (tmp_path.parent / "cua-driver").exists()


def test_local_offline_prepare_writes_auditable_metadata(tmp_path: Path) -> None:
    binary = b"fake universal driver"
    archive_path = tmp_path / "driver.tar.gz"
    archive_bytes = _archive(archive_path, binary)
    license_payload = b"MIT License\n"
    license_path = tmp_path / "LICENSE.md"
    license_path.write_bytes(license_payload)
    lock_path = tmp_path / "lock.json"
    _write_lock(
        lock_path,
        _lock_payload(
            archive_name=archive_path.name,
            archive_sha256=_sha256(archive_bytes),
            license_sha256=_sha256(license_payload),
            binary_content_sha256=_sha256(binary),
        ),
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "stale.txt").write_text("old", encoding="utf-8")

    manifest = prepare_cua_driver(
        lock_path=lock_path,
        output_dir=output_dir,
        archive_path=archive_path,
        license_path=license_path,
        offline=True,
        clean=True,
        validate_macos=False,
        content_digest=lambda *_args, **_kwargs: _sha256(binary),
    )

    assert {path.name for path in output_dir.iterdir()} == {
        "cua-driver",
        "LICENSE.md",
        "manifest.json",
    }
    assert (output_dir / "cua-driver").read_bytes() == binary
    assert stat.S_IMODE((output_dir / "cua-driver").stat().st_mode) == 0o755
    written_manifest = json.loads((output_dir / "manifest.json").read_text("utf-8"))
    assert written_manifest == manifest
    assert manifest["version"] == "0.7.1"
    assert manifest["lock"]["path"] == str(lock_path.resolve())
    assert manifest["lock"]["sha256"] == _sha256(lock_path.read_bytes())
    assert manifest["binary"]["sha256"] == _sha256(binary)
    assert manifest["binary"]["content_hash_algorithm"] == (
        "mach-o-without-code-signature-v1"
    )
    assert manifest["binary"]["content_sha256"] == _sha256(binary)
    assert manifest["license"]["sha256"] == _sha256(license_payload)
    assert manifest["validation"]["embedded_mcp"] is True


def test_offline_prepare_requires_cached_archive_and_license(tmp_path: Path) -> None:
    with pytest.raises(CuaDriverPreparationError, match="cached Cua Driver archive"):
        prepare_cua_driver(
            lock_path=ROOT / "packaging" / "cua-driver.lock.json",
            output_dir=tmp_path / "output",
            cache_dir=tmp_path / "empty-cache",
            offline=True,
            validate_macos=False,
        )


def test_offline_prepare_rejects_cache_with_archive_but_no_license(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    archive_name = "driver.tar.gz"
    archive_bytes = _archive(cache_dir / archive_name, b"fake driver")
    license_payload = b"MIT License\n"
    lock_path = tmp_path / "lock.json"
    _write_lock(
        lock_path,
        _lock_payload(
            archive_name=archive_name,
            archive_sha256=_sha256(archive_bytes),
            license_sha256=_sha256(license_payload),
            binary_content_sha256=_sha256(b"fake driver"),
        ),
    )

    with pytest.raises(CuaDriverPreparationError, match="cached Cua Driver license"):
        prepare_cua_driver(
            lock_path=lock_path,
            output_dir=tmp_path / "output",
            cache_dir=cache_dir,
            offline=True,
            validate_macos=False,
        )
