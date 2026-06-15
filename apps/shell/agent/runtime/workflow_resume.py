"""Workflow resume and cross-run transition coordinators."""

from __future__ import annotations

from typing import Any


class RunTransitionProjectionCoordinator:
    """Projects cross-run state transitions after a Run changes state."""

    def __init__(
        self,
        *,
        update_agent_run_group_if_root: Any,
        resume_parent_workflows_after_child_update: Any,
        workflow_run_is_group_root: Any,
        update_run_group: Any,
        get_run: Any,
    ) -> None:
        self._update_agent_run_group_if_root = update_agent_run_group_if_root
        self._resume_parent_workflows_after_child_update = resume_parent_workflows_after_child_update
        self._workflow_run_is_group_root = workflow_run_is_group_root
        self._update_run_group = update_run_group
        self._get_run = get_run

    def project_child_run_transition(self, result: dict[str, Any]) -> dict[str, Any]:
        self._update_agent_run_group_if_root(result)
        self._resume_parent_workflows_after_child_update(result)
        return result

    def project_agent_run_group_if_root(self, result: dict[str, Any]) -> dict[str, Any]:
        self._update_agent_run_group_if_root(result)
        run_id = str(result.get("run_id") or "")
        if not run_id:
            return result
        return self._get_run(run_id)

    def project_cancelled_workflow_group_if_root(
        self,
        run: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._workflow_run_is_group_root(run):
            return result
        self._update_run_group(
            str(run.get("run_group_id") or ""),
            status="cancelled",
            summary=str(result.get("result") or ""),
        )
        return self._get_run(str(run.get("run_id") or result.get("run_id") or ""))


class WorkflowParentRunLocator:
    """Locates parent Workflow Runs waiting on a child Agent or Workflow Run."""

    def __init__(
        self,
        *,
        get_run_group: Any,
        get_run: Any,
    ) -> None:
        self._get_run_group = get_run_group
        self._get_run = get_run

    def parent_runs_waiting_for_child(
        self,
        child_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if child_run.get("kind") not in {"agent_run", "workflow_run"} or not child_run.get("run_group_id"):
            return []
        try:
            group = self._get_run_group(str(child_run["run_group_id"]))
        except KeyError:
            return []
        parents: list[dict[str, Any]] = []
        child_run_id = str(child_run.get("run_id") or "")
        for run_id in [str(item) for item in group.get("child_run_ids") or [] if str(item)]:
            if run_id == child_run_id:
                continue
            try:
                candidate = self._get_run(run_id)
            except KeyError:
                continue
            candidate_status = str(candidate.get("status") or "")
            if (
                candidate.get("kind") != "workflow_run"
                or candidate_status not in {"approval_required", "running", "processing"}
            ):
                continue
            if any(
                event.get("event") == "workflow.run.approval_required"
                and str(event.get("child_run_id") or "") == child_run_id
                for event in candidate.get("timeline") or []
                if isinstance(event, dict)
            ):
                parents.append(candidate)
        return parents

    def workflow_run_is_group_root(self, workflow_run: dict[str, Any]) -> bool:
        run_group_id = str(workflow_run.get("run_group_id") or "")
        if not run_group_id:
            return False
        try:
            group = self._get_run_group(run_group_id)
        except KeyError:
            return False
        child_run_ids = [str(item) for item in group.get("child_run_ids") or [] if str(item)]
        return (
            group.get("source") == "workflow"
            or child_run_ids[:1] == [workflow_run.get("run_id")]
        )


class WorkflowResumePlanner:
    """Resolves Workflow snapshots and child resume positions."""

    def __init__(
        self,
        *,
        get_workflow: Any,
        workflow_path: Any,
        node_kind: Any,
        nodes_by_id: Any | None = None,
        next_node_id: Any | None = None,
    ) -> None:
        self._get_workflow = get_workflow
        self._workflow_path = workflow_path
        self._node_kind = node_kind
        self._nodes_by_id = nodes_by_id or self._default_nodes_by_id
        self._next_node_id = next_node_id

    def workflow_for_run_resume(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        for event in workflow_run.get("timeline") or []:
            if not isinstance(event, dict) or event.get("event") != "workflow.run.started":
                continue
            snapshot = event.get("workflow_snapshot")
            if not isinstance(snapshot, dict):
                continue
            nodes = snapshot.get("nodes")
            edges = snapshot.get("edges")
            if isinstance(nodes, list) and isinstance(edges, list):
                return {
                    "workflow_id": str(snapshot.get("workflow_id") or workflow_run.get("runnable_id") or ""),
                    "name": str(snapshot.get("name") or "Workflow"),
                    "nodes": nodes,
                    "edges": edges,
                    "enabled": True,
                }
        return self._get_workflow(str(workflow_run["runnable_id"]))

    def resume_start_index(
        self,
        workflow: dict[str, Any],
        workflow_run: dict[str, Any],
        child_run_id: str,
    ) -> int | None:
        child_node_events = {"workflow.node.agent", "workflow.node.workflow"}
        target_child_ordinal = 0
        for event in workflow_run.get("timeline") or []:
            if not isinstance(event, dict) or event.get("event") not in child_node_events:
                continue
            target_child_ordinal += 1
            if str(event.get("child_run_id") or "") == child_run_id:
                break
        else:
            return None
        seen_child_nodes = 0
        for index, node in enumerate(self._workflow_path(workflow)):
            if self._node_kind(node) not in {"agent", "workflow"}:
                continue
            seen_child_nodes += 1
            if seen_child_nodes == target_child_ordinal:
                return index + 1
        return None

    def next_node_id(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any] | str,
        context: str,
    ) -> str:
        if isinstance(node, str):
            node = self._nodes_by_id(workflow).get(node) or {}
        if not node or self._next_node_id is None:
            return ""
        return str(self._next_node_id(workflow, node, context) or "")

    def _default_nodes_by_id(self, workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("id") or ""): node
            for node in self._workflow_path(workflow)
            if isinstance(node, dict)
        }
