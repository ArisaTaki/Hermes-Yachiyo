from __future__ import annotations

from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_requests_from_envelope_payload,
)


def test_runtime_execution_projection_skips_blocked_desktop_routes() -> None:
    envelope = {
        "envelope_id": "execution-envelope-test",
        "requests": [
            {
                "request_id": "blocked-open",
                "tool_name": "app.open",
                "input": {"app_name": "Music"},
                "status": "planned",
                "desktop_execution_route": {
                    "status": "real_virtual_desktop_provider_required",
                    "can_execute": False,
                    "blocking_conditions": [
                        "loopback_desktop_backend",
                        "real_virtual_desktop_backend_required",
                    ],
                },
            },
            {
                "request_id": "safe-discovery",
                "tool_name": "desktop.list_apps",
                "input": {"query": "Music"},
                "status": "planned",
                "desktop_execution_route": {
                    "status": "sandbox_ready",
                    "can_execute": True,
                    "blocking_conditions": [],
                },
            },
        ],
    }

    projected = runtime_execution_requests_from_envelope_payload(
        envelope,
        allowed_tools=["app.open", "desktop.list_apps"],
    )

    assert [request["tool"] for request in projected] == ["desktop.list_apps"]
    assert projected[0]["request_id"] == "safe-discovery"
    assert projected[0]["desktop_execution_route"]["status"] == "sandbox_ready"
