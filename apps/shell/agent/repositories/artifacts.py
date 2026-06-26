"""Artifact projection and file access for Agent runtime runs."""

from __future__ import annotations

import base64
import mimetypes
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

_TEXT_ARTIFACT_READ_LIMIT = 300_000
_IMAGE_ARTIFACT_READ_LIMIT = 8_000_000


class RunArtifactRepository:
    """Projection store and file access boundary for run artifacts."""

    def __init__(
        self,
        conn: Any,
        *,
        agent_artifacts_dir: Path,
        workflow_artifacts_dir: Path,
        get_run: Callable[[str], dict[str, Any]],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        redact_json_value: Callable[[Any], Any],
        redact_secrets: Callable[[Any], str],
        safe_rel_path: Callable[[str], str],
        is_within: Callable[[Path, Path], bool],
        read_text: Callable[..., str],
    ) -> None:
        self._conn = conn
        self._agent_artifacts_dir = agent_artifacts_dir
        self._workflow_artifacts_dir = workflow_artifacts_dir
        self._get_run = get_run
        self._now = now
        self._json_dump = json_dump
        self._redact_json_value = redact_json_value
        self._redact_secrets = redact_secrets
        self._safe_rel_path = safe_rel_path
        self._is_within = is_within
        self._read_text = read_text

    def sync(self, run_id: str, artifacts: Any) -> None:
        self._conn.execute("DELETE FROM run_artifacts WHERE run_id=?", (run_id,))
        if not isinstance(artifacts, list):
            return
        now = self._now()
        for index, artifact in enumerate(item for item in artifacts if isinstance(item, dict)):
            artifact_id = f"{run_id}:artifact:{index}"
            self._conn.execute(
                """
                INSERT INTO run_artifacts (
                    artifact_id, run_id, sequence, kind, path, source_run_id,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    index,
                    str(artifact.get("kind") or "")[:80],
                    str(artifact.get("path") or "")[:500],
                    str(artifact.get("source_run_id") or artifact.get("run_id") or "")[:160],
                    self._json_dump(self._redact_json_value(artifact)),
                    now,
                ),
            )

    def read(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        rel = self._safe_rel_path(artifact_path)
        root = self._run_artifact_root(run)
        target = (root / rel).resolve()
        if not self._is_within(target, root) or not target.is_file():
            raise KeyError(rel)
        mime_type = mimetypes.guess_type(rel)[0] or ""
        size_bytes = target.stat().st_size
        if mime_type.startswith("image/"):
            if size_bytes > _IMAGE_ARTIFACT_READ_LIMIT:
                return {
                    "ok": True,
                    "run_id": run_id,
                    "path": rel,
                    "content": "",
                    "mime_type": mime_type,
                    "truncated": True,
                }
            content = base64.b64encode(target.read_bytes()).decode("ascii")
            return {
                "ok": True,
                "run_id": run_id,
                "path": rel,
                "content": f"data:{mime_type};base64,{content}",
                "mime_type": mime_type,
                "truncated": False,
            }

        content = self._read_text(target, limit=_TEXT_ARTIFACT_READ_LIMIT)
        return {
            "ok": True,
            "run_id": run_id,
            "path": rel,
            "content": self._redact_secrets(content),
            "truncated": size_bytes > _TEXT_ARTIFACT_READ_LIMIT,
        }

    def delete_files(self, run: dict[str, Any]) -> None:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            return
        root = self._artifact_base_dir(run)
        target = (root / run_id).resolve()
        if self._is_within(target, root) and target.exists():
            shutil.rmtree(target, ignore_errors=True)

    def _run_artifact_root(self, run: dict[str, Any]) -> Path:
        return self._artifact_base_dir(run) / str(run["run_id"])

    def _artifact_base_dir(self, run: dict[str, Any]) -> Path:
        return (
            self._agent_artifacts_dir
            if run.get("kind") in {"agent_run", "main_chat_run"}
            else self._workflow_artifacts_dir
        )
