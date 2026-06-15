"""Run deletion orchestration for Agent Runtime."""

from __future__ import annotations

from typing import Any, Callable


class RuntimeRunDeletionService:
    """Deletes terminal runs while preserving group and artifact cleanup semantics."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        group_runs: Callable[[str], list[dict[str, Any]]],
        delete_run_rows: Callable[..., list[str]],
        delete_artifacts: Callable[..., Any],
        delete_group: Callable[[str], Any],
        remove_group_run_ids: Callable[[str, set[str]], Any],
        commit: Callable[[], Any],
        is_active_run_status: Callable[[str], bool],
        error_type: type[Exception],
    ) -> None:
        self._get_run = get_run
        self._group_runs = group_runs
        self._delete_run_rows = delete_run_rows
        self._delete_artifacts = delete_artifacts
        self._delete_group = delete_group
        self._remove_group_run_ids = remove_group_run_ids
        self._commit = commit
        self._is_active_run_status = is_active_run_status
        self._error_type = error_type

    def delete(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        if self._is_active_run_status(str(run.get("status") or "")):
            raise self._error_type("Run 仍在进行中或待审批，取消或完成后才能删除")
        run_group_id = str(run.get("run_group_id") or "")
        targets = [run]
        delete_group = False
        if run.get("kind") == "workflow_run" and run_group_id:
            group_runs = self._group_runs(run_group_id)
            if any(
                self._is_active_run_status(str(item.get("status") or ""))
                for item in group_runs
            ):
                raise self._error_type(
                    "这个 Workflow Run 仍有进行中或待审批的子 Run，取消或完成后才能删除"
                )
            targets = group_runs or [run]
            delete_group = True
        deleted_run_ids = self._delete_run_rows(
            targets,
            delete_artifacts=self._delete_artifacts,
        )
        deleted_ids = set(deleted_run_ids)
        if delete_group and run_group_id:
            self._delete_group(run_group_id)
        else:
            self._remove_group_run_ids(run_group_id, deleted_ids)
        self._commit()
        return {
            "ok": True,
            "deleted_run_ids": deleted_run_ids,
            "deleted_run_count": len(deleted_run_ids),
        }
