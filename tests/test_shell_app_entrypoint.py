import sys

from apps.shell import app as shell_app


def test_shell_app_main_defaults_to_electron(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(shell_app, "_legacy_pywebview_requested", lambda: False)

    from apps import desktop_launcher

    monkeypatch.setattr(desktop_launcher, "main", lambda: calls.append("electron"))

    shell_app.main()

    assert calls == ["electron"]


def test_shell_app_main_keeps_explicit_legacy_entrypoint(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(shell_app, "_legacy_pywebview_requested", lambda: True)
    monkeypatch.setattr(shell_app, "_launch_legacy_pywebview", lambda: calls.append("legacy"))

    shell_app.main()

    assert calls == ["legacy"]


def test_legacy_pywebview_requested_from_command_name(monkeypatch):
    monkeypatch.delenv("HERMES_YACHIYO_LEGACY_PYWEBVIEW", raising=False)
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/hermes-yachiyo-legacy-pywebview"])

    assert shell_app._legacy_pywebview_requested()


def test_legacy_pywebview_requested_from_env(monkeypatch):
    monkeypatch.setenv("HERMES_YACHIYO_LEGACY_PYWEBVIEW", "1")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/hermes-yachiyo"])

    assert shell_app._legacy_pywebview_requested()
