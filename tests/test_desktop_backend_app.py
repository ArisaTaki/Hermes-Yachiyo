from types import SimpleNamespace

from apps.desktop_backend.app import _bridge_endpoint_from_env


def test_bridge_endpoint_prefers_electron_env_url(monkeypatch):
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:49321")

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 49321)


def test_bridge_endpoint_falls_back_to_config_for_invalid_env_url(monkeypatch):
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:not-a-port")

    endpoint = _bridge_endpoint_from_env(
        SimpleNamespace(bridge_host="127.0.0.1", bridge_port=8420)
    )

    assert endpoint == ("127.0.0.1", 8420)
