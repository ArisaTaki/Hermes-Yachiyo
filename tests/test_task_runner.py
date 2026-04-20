import asyncio

import pytest

from apps.core.state import AppState
from apps.core.task_runner import TaskRunner


@pytest.mark.asyncio
async def test_stop_awaits_in_progress_task_cancellation():
    runner = TaskRunner(AppState())
    child = asyncio.create_task(asyncio.sleep(60))
    runner._in_progress["task1"] = child

    await runner.stop()

    assert child.done()
    assert runner._in_progress == {}
