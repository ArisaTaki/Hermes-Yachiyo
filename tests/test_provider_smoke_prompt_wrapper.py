"""Provider smoke prompt wrapper tests."""

from __future__ import annotations

from types import SimpleNamespace

from scripts import run_provider_smoke_with_prompt as wrapper


def test_provider_smoke_prompt_wrapper_stdin_uses_hidden_prompt_for_tty(
    monkeypatch,
):
    class TtyStdin:
        def isatty(self):
            return True

        def readline(self):
            raise AssertionError("TTY stdin should use getpass instead of readline")

    monkeypatch.setattr(wrapper.sys, "stdin", TtyStdin())
    monkeypatch.setattr(wrapper.getpass, "getpass", lambda _prompt: "tp-tty-secret")

    assert wrapper._api_key_from_stdin() == "tp-tty-secret"


def test_provider_smoke_prompt_wrapper_keeps_api_key_out_of_argv_and_output(
    monkeypatch,
    capsys,
):
    secret = "tp-test-provider-smoke-secret"
    calls: list[dict[str, object]] = []

    monkeypatch.delenv(wrapper.API_KEY_ENV, raising=False)
    monkeypatch.setenv(wrapper.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(wrapper.MODEL_ENV, "provider-model")
    monkeypatch.setattr(wrapper.getpass, "getpass", lambda _prompt: secret)

    def fake_run(command, **kwargs):
        calls.append(
            {
                "command": command,
                "cwd": kwargs.get("cwd"),
                "env": kwargs.get("env"),
                "text": kwargs.get("text"),
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    assert (
        wrapper.main(
            [
                "--",
                "--source-only",
                "--report-json",
                "tmp/provider-smoke.json",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert secret not in output
    assert calls
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert secret not in " ".join(command)
    assert "--run-provider-smoke" in command
    assert "--source-only" in command
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env[wrapper.API_KEY_ENV] == secret
    assert env[wrapper.BASE_URL_ENV] == "https://provider.example/v1"
    assert env[wrapper.MODEL_ENV] == "provider-model"


def test_provider_smoke_prompt_wrapper_dry_run_does_not_call_verifier(
    monkeypatch,
    capsys,
):
    monkeypatch.setenv(wrapper.BASE_URL_ENV, "https://provider.example/v1")
    monkeypatch.setenv(wrapper.MODEL_ENV, "provider-model")
    monkeypatch.setenv(wrapper.API_KEY_ENV, "tp-test-env-secret")

    def fail_run(*_args, **_kwargs):
        raise AssertionError("dry run must not execute the verifier")

    monkeypatch.setattr(wrapper.subprocess, "run", fail_run)

    assert wrapper.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "tp-test-env-secret" not in output
    assert "OHA_YACHIYO_SMOKE_API_KEY=set" in output


def test_provider_smoke_prompt_wrapper_reports_missing_non_secret_fields(
    monkeypatch,
    capsys,
):
    monkeypatch.delenv(wrapper.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(wrapper.MODEL_ENV, raising=False)
    monkeypatch.delenv(wrapper.API_KEY_ENV, raising=False)

    def fail_prompt(_prompt):
        raise AssertionError("missing non-secret fields should be reported before prompting")

    monkeypatch.setattr(wrapper.getpass, "getpass", fail_prompt)

    assert wrapper.main([]) == 2
    captured = capsys.readouterr()
    assert wrapper.BASE_URL_ENV in captured.err
    assert wrapper.MODEL_ENV in captured.err
    assert wrapper.API_KEY_ENV in captured.err
