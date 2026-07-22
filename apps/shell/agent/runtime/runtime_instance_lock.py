"""Cross-process ownership lock for one runtime database identity."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class RuntimeProcessInstanceLock:
    """Holds a non-blocking OS lock until explicit release or process death."""

    def __init__(
        self,
        *,
        db_path: Path | str | None,
        workspace_dir: Path | str | None = None,
    ) -> None:
        self.path = runtime_instance_lock_path(db_path, workspace_dir)
        self._handle: BinaryIO | None = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o600)
        handle = os.fdopen(fd, "r+b", buffering=0)
        try:
            if not _try_lock(handle):
                handle.close()
                return False
        except Exception:
            handle.close()
            raise
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


def runtime_instance_lock_path(
    db_path: Path | str | None,
    workspace_dir: Path | str | None = None,
) -> Path:
    clean_db_path = str(db_path or "").strip()
    if clean_db_path and clean_db_path != ":memory:":
        resolved_db_path = Path(clean_db_path).expanduser().resolve(strict=False)
        return resolved_db_path.with_name(f"{resolved_db_path.name}.instance.lock")
    workspace = Path(workspace_dir or Path.cwd()).expanduser().resolve(strict=False)
    return workspace / ".runtime-db.instance.lock"


def _try_lock(handle: BinaryIO) -> bool:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise


def _unlock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
