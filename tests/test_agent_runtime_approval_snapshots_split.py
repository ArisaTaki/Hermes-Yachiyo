"""Tests for shared approval snapshot helpers split from runtime projections."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_snapshots import (
    ApprovalSnapshotBuilder,
    public_pending_approval,
)
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalPauseProjection
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_approval_snapshot_builder_projects_public_pending_approval() -> None:
    pending = {
        "approval_id": "approval-1",
        "tool": "terminal.run",
        "input_preview": {
            "command": "printf ok",
            "API_KEY": "sk-approval-secret123456",
        },
        "requested_at": "2026-06-15T00:00:00+00:00",
        "messages": [{"role": "user", "content": "private context"}],
        "workflow_context": "private workflow context",
    }
    builder = ApprovalSnapshotBuilder()

    snapshot = builder.public_pending_approval(pending)
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot == public_pending_approval(pending)
    assert snapshot == agent_runtime._public_pending_approval(pending)
    assert agent_runtime._public_pending_approval is public_pending_approval
    assert set(snapshot) == {
        "approval_id",
        "tool",
        "input_preview",
        "requested_at",
        "risk_level",
        "policy_reason",
    }
    assert snapshot["approval_id"] == "approval-1"
    assert snapshot["tool"] == "terminal.run"
    assert snapshot["input_preview"]["command"] == "printf ok"
    assert snapshot["risk_level"] == "high"
    assert snapshot["policy_reason"] == "terminal.run 可执行本地命令，按工具策略必须人工确认。"
    assert "sk-approval-secret123456" not in serialized
    assert "messages" not in snapshot
    assert "workflow_context" not in snapshot


def test_approval_snapshot_uses_input_when_preview_is_missing() -> None:
    pending = {
        "approval_id": "approval-2",
        "tool": "workspace.write_patch",
        "input": {
            "path": "README.md",
            "content": "token=sk-approval-input-secret123456",
        },
        "requested_at": "2026-06-15T00:00:00+00:00",
    }

    snapshot = public_pending_approval(pending)
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["input_preview"]["path"] == "README.md"
    assert snapshot["risk_level"] == "high"
    assert snapshot["policy_reason"] == "workspace.write_patch 会修改工作区文件，按工具策略必须人工确认。"
    assert "sk-approval-input-secret123456" not in serialized


def test_approval_snapshot_preserves_explicit_policy_reason_and_risk() -> None:
    pending = {
        "approval_id": "approval-plugin",
        "tool": "plugin.deploy",
        "risk_level": "high",
        "policy_reason": "Plugin can publish external changes.",
        "input_preview": {"target": "production"},
        "requested_at": "2026-06-15T00:00:00+00:00",
    }

    snapshot = public_pending_approval(pending)

    assert snapshot["risk_level"] == "high"
    assert snapshot["policy_reason"] == "Plugin can publish external changes."


def test_approval_snapshot_marks_foreground_desktop_tools_medium_risk() -> None:
    snapshot = public_pending_approval(
        {
            "approval_id": "approval-hotkey",
            "tool": "desktop.hotkey",
            "input_preview": {"key": "l", "modifiers": ["command"]},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert snapshot["risk_level"] == "medium"
    assert snapshot["policy_reason"] == (
        "将向当前前台窗口发送快捷键 Command+L，按工具策略需要人工确认。"
    )


def test_approval_snapshot_describes_foreground_text_and_click_approval() -> None:
    text_snapshot = public_pending_approval(
        {
            "approval_id": "approval-type-text",
            "tool": "desktop.type_text",
            "input_preview": {"text": "hello"},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )
    click_snapshot = public_pending_approval(
        {
            "approval_id": "approval-click",
            "tool": "desktop.click",
            "input_preview": {"x": 12.0, "y": 34, "click_count": 2},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )
    click_ui_element_snapshot = public_pending_approval(
        {
            "approval_id": "approval-click-ui-element",
            "tool": "desktop.click_ui_element",
            "input_preview": {"target": "发送", "role_filter": "button"},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert text_snapshot["risk_level"] == "medium"
    assert text_snapshot["policy_reason"] == (
        "将向当前前台窗口输入文字（5 个字符），按工具策略需要人工确认。"
    )
    assert click_snapshot["risk_level"] == "medium"
    assert click_snapshot["policy_reason"] == (
        "将双击坐标 12, 34 处的当前前台窗口，按工具策略需要人工确认。"
    )
    assert click_ui_element_snapshot["risk_level"] == "medium"
    assert click_ui_element_snapshot["policy_reason"] == (
        "将点击当前前台界面中匹配“发送”的控件，按工具策略需要人工确认。"
    )


def test_approval_snapshot_marks_browser_input_tools_medium_risk() -> None:
    snapshot = public_pending_approval(
        {
            "approval_id": "approval-browser-click",
            "tool": "browser.click",
            "input_preview": {"selector": "button[type=submit]"},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert snapshot["risk_level"] == "medium"
    assert snapshot["policy_reason"] == (
        "将点击当前浏览器页面中的选择器 button[type=submit]，按工具策略需要人工确认。"
    )

    point_snapshot = public_pending_approval(
        {
            "approval_id": "approval-browser-point",
            "tool": "browser.click",
            "input_preview": {
                "selector": "point=120,240",
                "fallback_x": 120,
                "fallback_y": 240,
                "click_count": 1,
            },
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert point_snapshot["risk_level"] == "medium"
    assert point_snapshot["policy_reason"] == (
        "将点击当前浏览器页面位置 120, 240，按工具策略需要人工确认。"
    )


def test_approval_snapshot_describes_browser_type_text_approval() -> None:
    snapshot = public_pending_approval(
        {
            "approval_id": "approval-browser-type",
            "tool": "browser.type_text",
            "input_preview": {"selector": "input[name=q]", "text": "yachiyo"},
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert snapshot["risk_level"] == "medium"
    assert snapshot["policy_reason"] == (
        "将向当前浏览器页面选择器 input[name=q] 输入文字（7 个字符），按工具策略需要人工确认。"
    )

    point_snapshot = public_pending_approval(
        {
            "approval_id": "approval-browser-type-point",
            "tool": "browser.type_text",
            "input_preview": {
                "selector": "point=120,240",
                "text": "hello",
                "fallback_x": 120,
                "fallback_y": 240,
            },
            "requested_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert point_snapshot["risk_level"] == "medium"
    assert point_snapshot["policy_reason"] == (
        "将向当前浏览器页面位置 120, 240 输入文字（5 个字符），按工具策略需要人工确认。"
    )


def test_workflow_approval_pause_projection_uses_shared_public_snapshot() -> None:
    projection = WorkflowApprovalPauseProjection(
        approval_id="approval-workflow",
        node_id="gate",
        node_kind="approval",
        label="Human Gate",
        criteria="Review output",
        context="private workflow context sk-workflow-approval-secret123456",
        next_index=3,
        next_node_id="after-gate",
        requested_at="2026-06-15T00:00:00+00:00",
    )

    pending = projection.pending_approval()
    public = projection.public_pending_approval()
    serialized = json.dumps(public, ensure_ascii=False)

    assert public == public_pending_approval(pending)
    assert public["tool"] == "workflow.approval"
    assert public["workflow_node_id"] == "gate"
    assert public["workflow_node_label"] == "Human Gate"
    assert public["input_preview"]["checkpoint"] == "Human Gate"
    assert public["input_preview"]["criteria"] == "Review output"
    assert public["policy_reason"] == "Workflow 审批节点要求人工确认：Review output"
    assert "workflow_context" not in public
    assert "workflow_next_index" not in public
    assert "sk-workflow-approval-secret123456" not in serialized


def test_agent_runtime_service_uses_approval_snapshot_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_snapshots, ApprovalSnapshotBuilder)
        assert agent_runtime.ApprovalSnapshotBuilder is ApprovalSnapshotBuilder
    finally:
        service.close()
