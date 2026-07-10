from __future__ import annotations

from typing import Any

import pytest

from apps.bridge.routes import (
    yachiyo_studio_handlers,
    yachiyo_studio_tool_handlers,
)
from apps.bridge.routes.yachiyo_models import VirtualDesktopGuestProvisionBody


@pytest.mark.asyncio
async def test_virtual_desktop_provision_handler_delegates_public_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Service:
        def provision_virtual_desktop_guest(
            self,
            request: dict[str, Any],
        ) -> dict[str, Any]:
            calls.append(request)
            return {
                "ok": True,
                "status": "provisioned",
                "provider_manifest": "/tmp/provider.manifest.json",
            }

    monkeypatch.setattr(
        yachiyo_studio_tool_handlers,
        "studio_service",
        lambda _request=None: Service(),
    )
    body = VirtualDesktopGuestProvisionBody(
        ssh_target="yachiyo@192.0.2.10",
        session_id="vm-session-1",
        approved=True,
    )

    result = await yachiyo_studio_handlers.provision_virtual_desktop_guest(body)

    assert result["status"] == "provisioned"
    assert calls == [
        {
            "ssh_target": "yachiyo@192.0.2.10",
            "session_id": "vm-session-1",
            "approved": True,
            "start_session": True,
        }
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_binary", "/tmp/arbitrary-binary"),
        ("ssh_options", ["ProxyCommand=/tmp/arbitrary-command"]),
    ],
)
def test_virtual_desktop_provision_contract_rejects_unsafe_overrides(
    field: str,
    value: Any,
) -> None:
    with pytest.raises(ValueError):
        VirtualDesktopGuestProvisionBody.model_validate(
            {
                "ssh_target": "yachiyo@192.0.2.10",
                "session_id": "vm-session-1",
                "approved": True,
                field: value,
            }
        )
