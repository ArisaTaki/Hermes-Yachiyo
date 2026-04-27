"""Bridge /assistant/intent 路由测试。"""

from __future__ import annotations

import pytest

from apps.bridge.routes import assistant as assistant_route
from apps.core.state import AppState
from packages.protocol.schemas import AssistantIntentRequest


class _RuntimeStub:
    def __init__(self) -> None:
        self.state = AppState()

    def is_hermes_ready(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"task_counts": {"pending": 1, "running": 0, "completed": 2}}


@pytest.mark.asyncio
async def test_assistant_intent_returns_status(monkeypatch):
    runtime = _RuntimeStub()
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)

    result = await assistant_route.assistant_intent(
        AssistantIntentRequest(text="查一下状态", source="astrbot")
    )

    assert result.ok is True
    assert result.action == "status"
    assert "Hermes" in result.message
    assert result.task_id is None


@pytest.mark.asyncio
async def test_assistant_intent_creates_low_risk_task(monkeypatch):
    runtime = _RuntimeStub()
    monkeypatch.setattr(assistant_route, "get_runtime", lambda: runtime)

    result = await assistant_route.assistant_intent(
        AssistantIntentRequest(text="帮我整理桌面上的信息", source="astrbot")
    )
    task = runtime.state.get_task(result.task_id or "")

    assert result.ok is True
    assert result.action == "create_low_risk_task"
    assert task is not None
    assert task.risk_level.value == "low"
