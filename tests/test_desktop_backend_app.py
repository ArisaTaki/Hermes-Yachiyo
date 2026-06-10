import os
from types import SimpleNamespace

from apps.bridge.server import bridge_request_violation
from apps.desktop_backend.app import _bridge_endpoint_from_env, _ensure_bridge_session_token


def test_bridge_endpoint_prefers_electron_env_url(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:49321")

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 49321)


def test_bridge_endpoint_rejects_packaged_default_in_source_backend(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:18420")
    monkeypatch.setattr("apps.desktop_backend.app._running_from_packaged_backend", lambda: False)

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 8420)


def test_bridge_endpoint_allows_packaged_default_in_frozen_backend(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:18420")
    monkeypatch.setattr("apps.desktop_backend.app._running_from_packaged_backend", lambda: True)

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 18420)


def test_bridge_endpoint_falls_back_to_config_for_invalid_env_url(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:not-a-port")

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 8420)


def test_desktop_backend_generates_bridge_session_token_when_missing(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_TOKEN", raising=False)

    generated = _ensure_bridge_session_token()

    assert generated is True
    token = os.getenv("OHA_YACHIYO_BRIDGE_TOKEN") or ""
    assert len(token) >= 32
    assert bridge_request_violation("POST", {"host": "127.0.0.1:8420"}) == "invalid_bridge_token"
    assert bridge_request_violation(
        "POST",
        {"host": "127.0.0.1:8420", "x-oha-yachiyo-bridge-token": token},
    ) == ""


def test_desktop_backend_preserves_injected_bridge_session_token(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_TOKEN", "injected-token")

    generated = _ensure_bridge_session_token()

    assert generated is False
    assert os.getenv("OHA_YACHIYO_BRIDGE_TOKEN") == "injected-token"
