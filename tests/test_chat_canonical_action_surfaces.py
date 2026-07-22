from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_composer_is_navigation_only_for_pending_approvals() -> None:
    source = _source(
        "apps/frontend/src/features/yachiyo-chat/components/ComposerApprovalNotice.tsx"
    )

    assert 'data-testid="chat-composer-approval-canonical-hint"' in source
    assert 'data-testid="chat-composer-approval-reveal"' in source
    assert 'data-testid="chat-composer-approval-open-run-detail"' in source
    assert 'data-testid="chat-composer-approval-approve"' not in source
    assert 'data-testid="chat-composer-approval-reject"' not in source


def test_message_approval_actions_are_only_a_missing_task_snapshot_fallback() -> None:
    source = _source(
        "apps/frontend/src/features/yachiyo-chat/components/MessageBubble.tsx"
    )

    assert "const showCanonicalTaskApproval = Boolean(" in source
    assert "&& !showCanonicalTaskApproval;" in source
    assert "approvalDetails && !showCanonicalTaskApproval" in source
    assert 'data-testid="chat-message-approval-actions"' in source


def test_task_recovery_renders_one_cross_source_deduplicated_action_list() -> None:
    source = _source(
        "apps/frontend/src/features/yachiyo-chat/components/AgentTaskCard.tsx"
    )

    assert 'data-testid="yachiyo-agent-task-canonical-recovery"' in source
    assert source.count('data-testid="yachiyo-agent-task-recovery-actions"') == 1
    assert source.count('data-testid="yachiyo-agent-task-run-recovery-action"') == 1
    assert "function taskCanonicalRecoveryItems(" in source
    assert "function taskCanonicalRecoveryIdentity(" in source
    assert "String(action.replan_request_id || '').trim()" in source
    assert "String(action.action_id || '').trim()" in source
    assert "String(action.tool || '').trim()" in source
    assert "JSON.stringify(taskCanonicalRecoveryValue(action.input || {}))" in source
    assert "if (!existing.sources.includes(source)) existing.sources.push(source);" in source
    assert 'data-testid="yachiyo-agent-task-run-replan-recovery-action"' not in source
    assert 'data-testid="yachiyo-agent-task-run-runtime-retry-action"' not in source
    assert 'data-testid="yachiyo-agent-task-run-retry-action"' not in source


def test_approval_smoke_enforces_one_mutating_surface() -> None:
    source = _source("scripts/smoke_chat_approval_ui.mjs")

    assert "canonical task approval" in source
    assert "chat-composer-approval-canonical-hint" in source
    assert "yachiyo-task-approval-approve" in source
    assert "yachiyo-task-approval-reject" in source
    assert "!document.querySelector('[data-testid=\"chat-message-approval-actions\"]')" in source
    assert "!document.querySelector('[data-testid=\"chat-composer-approval-approve\"]')" in source
    assert "!document.querySelector('[data-testid=\"chat-composer-approval-reject\"]')" in source
