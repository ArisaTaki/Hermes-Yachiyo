"""Run rerun orchestration for Agent Runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


class RuntimeRunRerunService:
    """Creates replayable reruns for completed Agent and Workflow runs."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        create_agent_run: Callable[[dict[str, Any]], dict[str, Any]],
        create_workflow_run: Callable[[dict[str, Any]], dict[str, Any]],
        timeline_factory: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        update_run: Callable[..., dict[str, Any]],
        resolve_runnable: Callable[..., dict[str, Any] | None],
        final_statuses: set[str],
        error_type: type[Exception],
    ) -> None:
        self._get_run = get_run
        self._create_agent_run = create_agent_run
        self._create_workflow_run = create_workflow_run
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._resolve_runnable = resolve_runnable
        self._final_statuses = set(final_statuses)
        self._error_type = error_type

    def rerun(
        self,
        run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        original = self._get_run(run_id)
        rerun_request = self._rerun_request(request)
        original_status = str(original.get("status") or "")
        if original_status not in self._final_statuses:
            raise self._error_type("当前 Run 还在进行中，不能重跑")
        user_goal = str(original.get("user_goal") or "").strip()
        if not user_goal:
            raise self._error_type("原 Run 没有记录任务目标，无法重跑")
        kind = str(original.get("kind") or "")
        runnable_id = str(original.get("runnable_id") or "")
        if kind == "agent_run":
            if rerun_request["scope"] != "run":
                raise self._error_type("Agent Run 不支持 Workflow 节点重跑")
            rerun = self._create_agent_run(
                {
                    "agent_id": runnable_id,
                    "user_goal": user_goal,
                    "source": "rerun",
                }
            )
            rerun_key = "agent_run_id"
        elif kind == "workflow_run":
            workflow_payload = {
                "workflow_id": runnable_id,
                "user_goal": user_goal,
                "source": "rerun",
            }
            if rerun_request["scope"] != "run":
                workflow_payload.update(
                    {
                        "start_node_id": rerun_request["workflow_start_node_id"],
                        "rerun_scope": rerun_request["scope"],
                        "workflow_node_id": rerun_request["workflow_node_id"],
                        "workflow_node_label": rerun_request["workflow_node_label"],
                        "workflow_edge_branch": rerun_request["workflow_edge_branch"],
                        "workflow_node_selected_target": rerun_request[
                            "workflow_node_selected_target"
                        ],
                    }
                )
            rerun = self._create_workflow_run(workflow_payload)
            rerun_key = "workflow_run_id"
        else:
            raise self._error_type("不支持重跑这个 Run 类型")

        rerun_payload = self._rerun_payload(
            original,
            original_status=original_status,
            user_goal=user_goal,
            kind=kind,
            runnable_id=runnable_id,
            rerun_request=rerun_request,
        )
        rerun_event = self._timeline(
            "run.rerun.started",
            f"Rerun of {original.get('runnable_name') or runnable_id}",
            **rerun_payload,
        )
        self._append_run_event(
            str(rerun["run_id"]),
            "run.rerun.started",
            rerun_payload,
        )
        updated = self._update_run(
            str(rerun["run_id"]),
            timeline=[
                rerun_event,
                *[
                    event
                    for event in rerun.get("timeline") or []
                    if isinstance(event, dict)
                ],
            ],
        )
        updated[rerun_key] = updated["run_id"]
        updated["runnable"] = self._resolve_runnable(runnable_id=runnable_id)
        return updated

    def _rerun_request(self, request: Mapping[str, Any] | None) -> dict[str, Any]:
        source = dict(request or {})
        scope = str(source.get("scope") or "").strip().lower()
        workflow_node_id = str(source.get("workflow_node_id") or "").strip()
        workflow_node_label = str(source.get("workflow_node_label") or "").strip()
        workflow_edge_branch = str(source.get("workflow_edge_branch") or "").strip()
        workflow_node_selected_target = str(
            source.get("workflow_node_selected_target") or ""
        ).strip()
        if not scope:
            if workflow_node_selected_target or workflow_edge_branch:
                scope = "workflow_branch"
            elif workflow_node_id:
                scope = "workflow_node"
            else:
                scope = "run"
        if scope not in {"run", "workflow_node", "workflow_branch"}:
            raise self._error_type("不支持这个重跑范围")
        workflow_start_node_id = workflow_node_selected_target or workflow_node_id
        if scope != "run" and not workflow_start_node_id:
            raise self._error_type("Workflow 节点重跑需要 workflow_node_id 或 workflow_node_selected_target")
        return {
            "scope": scope,
            "workflow_node_id": workflow_node_id,
            "workflow_node_label": workflow_node_label,
            "workflow_edge_branch": workflow_edge_branch,
            "workflow_node_selected_target": workflow_node_selected_target,
            "workflow_start_node_id": workflow_start_node_id,
            "reason": str(source.get("reason") or "").strip(),
        }

    @staticmethod
    def _rerun_payload(
        original: dict[str, Any],
        *,
        original_status: str,
        user_goal: str,
        kind: str,
        runnable_id: str,
        rerun_request: dict[str, Any],
    ) -> dict[str, Any]:
        original_run_id = str(original.get("run_id") or "")
        runnable_name = str(original.get("runnable_name") or "")
        payload = {
            "rerun_of_run_id": original_run_id,
            "rerun_of_kind": kind,
            "rerun_of_status": original_status,
            "rerun_of_runnable_id": runnable_id,
            "rerun_of_runnable_name": runnable_name,
            "original_created_at": str(original.get("created_at") or ""),
            "original_updated_at": str(original.get("updated_at") or ""),
            "input_preview": {
                "original_run_id": original_run_id,
                "original_status": original_status,
                "original_target": runnable_name or runnable_id,
                "original_goal": user_goal,
            },
        }
        if rerun_request["scope"] != "run":
            scoped_payload = {
                "rerun_scope": rerun_request["scope"],
                "workflow_node_id": rerun_request["workflow_node_id"],
                "workflow_node_label": rerun_request["workflow_node_label"],
                "workflow_edge_branch": rerun_request["workflow_edge_branch"],
                "workflow_node_selected_target": rerun_request[
                    "workflow_node_selected_target"
                ],
                "workflow_start_node_id": rerun_request["workflow_start_node_id"],
                "rerun_reason": rerun_request["reason"],
            }
            payload.update(scoped_payload)
            payload["input_preview"] = {
                **payload["input_preview"],
                **scoped_payload,
            }
        return payload
