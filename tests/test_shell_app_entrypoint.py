from apps.shell import app as shell_app


def test_shell_app_main_forwards_to_electron(monkeypatch):
    calls: list[str] = []

    from apps import desktop_launcher

    monkeypatch.setattr(desktop_launcher, "main", lambda: calls.append("electron"))

    shell_app.main()

    assert calls == ["electron"]
