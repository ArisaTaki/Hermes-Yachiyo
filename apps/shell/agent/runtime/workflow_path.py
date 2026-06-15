"""Workflow path planning and replay snapshot helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


def _json_load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_rel_path(value: str) -> str:
    candidate = str(value or "").replace("\\", "/").strip()
    if not candidate or candidate.startswith("/") or candidate.startswith("../") or "/../" in candidate:
        raise AgentRuntimeError("路径必须是相对路径，且不能越界")
    return candidate


def _slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized[:48] or fallback


class WorkflowPathPlanner:
    """Plans Workflow node traversal, node metadata, and artifact paths."""

    def __init__(self, *, node_kind: Any) -> None:
        self._node_kind = node_kind

    def workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = self.nodes_by_id(workflow)
        outgoing = self.outgoing_edges(workflow)
        start = self.start_node(workflow)
        result = [start]
        current = str(start["id"])
        seen = {current}
        while current in outgoing:
            current = str(outgoing[current][0].get("target") or "")
            if not current or current not in nodes or current in seen:
                break
            seen.add(current)
            result.append(nodes[current])
        return result

    def workflow_order(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = self.nodes_by_id(workflow)
        outgoing = self.outgoing_edges(workflow)
        start = self.start_node(workflow)
        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        def visit(node_id: str) -> None:
            if not node_id or node_id in seen or node_id not in nodes:
                return
            seen.add(node_id)
            node = nodes[node_id]
            result.append(node)
            for edge in outgoing.get(node_id, []):
                visit(str(edge.get("target") or ""))

        visit(str(start["id"]))
        return result

    @staticmethod
    def nodes_by_id(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(node["id"]): node for node in workflow["nodes"]}

    @staticmethod
    def start_node(workflow: dict[str, Any]) -> dict[str, Any]:
        for node in workflow["nodes"]:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
            node_type = str(node.get("type") or "").strip()
            kind = data_kind if data_kind and node_type in {"", "input", "default", "output"} else node_type or data_kind
            if str(node.get("id") or "") and kind == "start":
                return node
        raise StopIteration("Workflow 缺少 Start 节点")

    @staticmethod
    def outgoing_edges(workflow: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for index, edge in enumerate(workflow.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            if not source:
                continue
            outgoing.setdefault(source, []).append({**edge, "_order": index})
        for edges in outgoing.values():
            edges.sort(key=WorkflowPathPlanner._edge_sort_key)
        return outgoing

    @staticmethod
    def _edge_sort_key(edge: dict[str, Any]) -> tuple[int, int]:
        branch = WorkflowPathPlanner.edge_branch(edge)
        branch_order = 0 if branch == "true" else 1 if branch == "false" else 2
        try:
            order = int(edge.get("_order") or 0)
        except (TypeError, ValueError):
            order = 0
        return branch_order, order

    @staticmethod
    def edge_branch(edge: dict[str, Any]) -> str:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        raw = (
            edge.get("branch")
            or edge.get("condition")
            or edge.get("label")
            or edge.get("sourceHandle")
            or data.get("branch")
            or data.get("condition")
            or data.get("label")
            or data.get("sourceHandle")
            or ""
        )
        value = str(raw or "").strip().lower()
        if value in {"true", "yes", "y", "pass", "passed", "match", "matched", "ok", "success"}:
            return "true"
        if value in {"false", "no", "n", "fail", "failed", "miss", "unmatched", "else", "fallback"}:
            return "false"
        return ""

    @staticmethod
    def condition_text(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("condition", "contains", "match", "criteria", "expression", "if", "prompt"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def condition_operator(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        operator = str(data.get("operator") or data.get("mode") or "").strip().lower()
        return operator or "contains"

    @classmethod
    def condition_matches(cls, node: dict[str, Any], context: str) -> bool:
        condition = cls.condition_text(node)
        operator = cls.condition_operator(node)
        haystack = str(context or "")
        if not condition:
            return bool(haystack.strip())
        if operator in {"equals", "eq", "=="}:
            return haystack.strip().lower() == condition.lower()
        if operator in {"not_equals", "ne", "!="}:
            return haystack.strip().lower() != condition.lower()
        if operator in {"regex", "re"}:
            try:
                return re.search(condition, haystack, flags=re.IGNORECASE | re.MULTILINE) is not None
            except re.error as exc:
                raise AgentRuntimeError(f"Condition 节点正则表达式无效：{exc}") from exc
        matched = condition.lower() in haystack.lower()
        if operator in {"not_contains", "not", "!"}:
            return not matched
        return matched

    def condition_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        node_id = str(node.get("id") or "")
        outgoing = self.outgoing_edges(workflow).get(node_id, [])
        matched = self.condition_matches(node, context)
        desired = "true" if matched else "false"
        selected_edge = next((edge for edge in outgoing if self.edge_branch(edge) == desired), None)
        if selected_edge is None and outgoing:
            selected_edge = outgoing[0 if matched else min(1, len(outgoing) - 1)]
        target_node_id = str(selected_edge.get("target") or "") if selected_edge else ""
        return {
            "condition": self.condition_text(node),
            "operator": self.condition_operator(node),
            "matched": matched,
            "branch": desired,
            "target_node_id": target_node_id,
        }

    @staticmethod
    def loop_max_iterations(node: dict[str, Any]) -> int:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        raw = (
            data.get("max_iterations")
            or data.get("maxIterations")
            or data.get("iteration_limit")
            or data.get("iterationLimit")
            or data.get("limit")
            or 3
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 3
        return max(1, min(value, 25))

    @staticmethod
    def loop_edge_role(edge: dict[str, Any]) -> str:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        raw = (
            edge.get("branch")
            or edge.get("condition")
            or edge.get("label")
            or edge.get("sourceHandle")
            or data.get("branch")
            or data.get("condition")
            or data.get("label")
            or data.get("sourceHandle")
            or ""
        )
        value = str(raw or "").strip().lower()
        if value in {
            "true",
            "yes",
            "y",
            "pass",
            "passed",
            "match",
            "matched",
            "ok",
            "success",
            "continue",
            "loop",
            "repeat",
            "again",
            "next",
        }:
            return "continue"
        if value in {
            "false",
            "no",
            "n",
            "fail",
            "failed",
            "miss",
            "unmatched",
            "else",
            "fallback",
            "exit",
            "done",
            "break",
            "stop",
            "finish",
        }:
            return "exit"
        return ""

    def loop_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
        *,
        previous_iterations: int = 0,
    ) -> dict[str, Any]:
        node_id = str(node.get("id") or "")
        outgoing = self.outgoing_edges(workflow).get(node_id, [])
        matched = self.condition_matches(node, context)
        max_iterations = self.loop_max_iterations(node)
        previous_iterations = max(0, int(previous_iterations or 0))
        limit_reached = matched and previous_iterations >= max_iterations
        selected_role = "continue" if matched and not limit_reached else "exit"
        selected_edge = next((edge for edge in outgoing if self.loop_edge_role(edge) == selected_role), None)
        if selected_edge is None:
            fallback_role = "exit" if selected_role == "continue" else "continue"
            selected_edge = next((edge for edge in outgoing if self.loop_edge_role(edge) == fallback_role), None)
        if selected_edge is None and outgoing:
            selected_edge = outgoing[0 if selected_role == "continue" else min(1, len(outgoing) - 1)]
        target_node_id = str(selected_edge.get("target") or "") if selected_edge else ""
        next_iterations = previous_iterations + 1 if selected_role == "continue" else previous_iterations
        return {
            "condition": self.condition_text(node),
            "operator": self.condition_operator(node),
            "matched": matched,
            "branch": selected_role,
            "target_node_id": target_node_id,
            "previous_iterations": previous_iterations,
            "iteration": next_iterations,
            "max_iterations": max_iterations,
            "limit_reached": limit_reached,
        }

    def loop_step_limit(self, workflow: dict[str, Any]) -> int:
        nodes = list(workflow.get("nodes") or [])
        loop_budget = sum(
            self.loop_max_iterations(node)
            for node in nodes
            if self._node_kind(node) == "loop"
        )
        return max(len(nodes) + 1, len(nodes) * (loop_budget + 2) + 5)

    @staticmethod
    def loop_iterations_from_timeline(timeline: list[dict[str, Any]]) -> dict[str, int]:
        iterations: dict[str, int] = {}
        for event in timeline:
            if not isinstance(event, dict) or event.get("event") != "workflow.node.loop":
                continue
            node_id = str(event.get("workflow_node_id") or "")
            if not node_id:
                continue
            try:
                iteration = int(event.get("workflow_node_loop_iteration") or 0)
            except (TypeError, ValueError):
                iteration = 0
            iterations[node_id] = max(iterations.get(node_id, 0), max(0, iteration))
        return iterations

    def next_node_id(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> str:
        if self._node_kind(node) == "condition":
            return str(self.condition_selection(workflow, node, context).get("target_node_id") or "")
        edges = self.outgoing_edges(workflow).get(str(node.get("id") or ""), [])
        if not edges:
            return ""
        return str(edges[0].get("target") or "")

    def parallel_plan(self, workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        nodes = self.nodes_by_id(workflow)
        outgoing = self.outgoing_edges(workflow)
        node_id = str(node.get("id") or "")
        branches: list[dict[str, Any]] = []
        raw_branch_paths: list[list[str]] = []
        for edge in outgoing.get(node_id, []):
            entry_node_id = str(edge.get("target") or "")
            path: list[str] = []
            seen: set[str] = set()
            current = entry_node_id
            while current and current in nodes and current not in seen:
                seen.add(current)
                path.append(current)
                next_edges = outgoing.get(current, [])
                if len(next_edges) != 1:
                    break
                current = str(next_edges[0].get("target") or "")
            raw_branch_paths.append(path)
        common_nodes = set(raw_branch_paths[0]) if raw_branch_paths else set()
        for path in raw_branch_paths[1:]:
            common_nodes &= set(path)
        join_node_id = ""
        if common_nodes and raw_branch_paths:
            join_node_id = next((node_id for node_id in raw_branch_paths[0] if node_id in common_nodes), "")
        for path in raw_branch_paths:
            branch_nodes = path
            if join_node_id in branch_nodes:
                branch_nodes = branch_nodes[:branch_nodes.index(join_node_id)]
            entry_node_id = branch_nodes[0] if branch_nodes else (path[0] if path else "")
            branch_label = ""
            if entry_node_id and entry_node_id in nodes:
                data = nodes[entry_node_id].get("data") if isinstance(nodes[entry_node_id].get("data"), dict) else {}
                branch_label = str(data.get("label") or entry_node_id).strip()
            branches.append(
                {
                    "entry_node_id": entry_node_id,
                    "label": branch_label or entry_node_id or "Branch",
                    "node_ids": branch_nodes,
                }
            )
        return {
            "join_node_id": join_node_id,
            "branches": branches,
        }

    @staticmethod
    def artifact_path(label: str, artifacts: list[dict[str, Any]], configured_path: str = "") -> str:
        configured = str(configured_path or "").strip()
        if configured:
            rel = _safe_rel_path(configured)
            rel_path = Path(rel)
            if rel_path.suffix:
                base = rel_path.with_suffix("")
                suffix = rel_path.suffix
            else:
                base = rel_path
                suffix = ".md"
        else:
            base = Path(_slug(label, "artifact"))
            suffix = ".md"
        existing_paths = {
            str(item.get("path") or "")
            for item in artifacts
            if isinstance(item, dict) and item.get("kind") == "workflow_artifact"
        }
        candidate = f"{base}{suffix}"
        index = 2
        while candidate in existing_paths:
            candidate = f"{base}-{index}{suffix}"
            index += 1
        return candidate

    @staticmethod
    def node_task(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("task", "instructions", "step_task", "prompt"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def workflow_id(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("workflow_id", "workflowId", "child_workflow_id", "childWorkflowId", "runnable_id", "runnableId"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def approval_criteria(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for key in ("criteria", "approval_criteria", "instructions", "task", "prompt"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def child_goal(workflow_goal: str, step_task: str) -> str:
        clean_workflow_goal = str(workflow_goal or "").strip()
        clean_step_task = str(step_task or "").strip()
        if not clean_step_task:
            return clean_workflow_goal
        if not clean_workflow_goal:
            return clean_step_task
        return f"{clean_step_task}\n\nWorkflow Goal:\n{clean_workflow_goal}"

    def path_snapshot(self, workflow: dict[str, Any]) -> list[dict[str, str]]:
        snapshot: list[dict[str, str]] = []
        planned_artifacts: list[dict[str, Any]] = []
        for node in self.workflow_order(workflow):
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            kind = self._node_kind(node)
            node_id = str(node.get("id") or "")
            label = str(data.get("label") or node_id or kind)
            item = {
                "id": node_id,
                "kind": kind,
                "label": label,
            }
            if kind == "artifact":
                artifact_path = self.artifact_path(
                    label,
                    planned_artifacts,
                    str(data.get("artifact_path") or data.get("artifactPath") or ""),
                )
                item["artifact_path"] = artifact_path
                planned_artifacts.append({"kind": "workflow_artifact", "path": artifact_path})
            if kind == "agent":
                step_task = self.node_task(node)
                if step_task:
                    item["task"] = step_task
            if kind == "approval":
                criteria = self.approval_criteria(node)
                if criteria:
                    item["criteria"] = criteria
            if kind == "condition":
                condition = self.condition_text(node)
                if condition:
                    item["condition"] = condition
                    item["operator"] = self.condition_operator(node)
            if kind == "loop":
                condition = self.condition_text(node)
                if condition:
                    item["condition"] = condition
                    item["operator"] = self.condition_operator(node)
                item["max_iterations"] = str(self.loop_max_iterations(node))
            if kind == "parallel":
                item["branch_count"] = str(len(self.outgoing_edges(workflow).get(node_id, [])))
            if kind == "workflow":
                workflow_id = self.workflow_id(node)
                if workflow_id:
                    item["workflow_id"] = workflow_id
                step_task = self.node_task(node)
                if step_task:
                    item["task"] = step_task
            snapshot.append(item)
        return snapshot

    @staticmethod
    def runtime_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_id": str(workflow.get("workflow_id") or ""),
            "name": str(workflow.get("name") or "Workflow"),
            "nodes": _json_load(_json_dump(workflow.get("nodes") or []), []),
            "edges": _json_load(_json_dump(workflow.get("edges") or []), []),
        }
