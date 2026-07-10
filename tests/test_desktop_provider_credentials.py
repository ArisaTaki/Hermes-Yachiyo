from __future__ import annotations

from apps.shell.agent.runtime.desktop_provider_credentials import (
    DESKTOP_PROVIDER_TOKEN_ENV,
    desktop_provider_token_from_file,
    desktop_provider_token_from_manifest,
    public_desktop_provider_env,
)


def test_desktop_provider_token_resolves_nested_environment_reference() -> None:
    token = desktop_provider_token_from_manifest(
        {"authentication": {"token_env": "TEST_VIRTUAL_DESKTOP_TOKEN"}},
        environment={"TEST_VIRTUAL_DESKTOP_TOKEN": "secret-token"},
    )

    assert token == "secret-token"


def test_desktop_provider_token_keeps_legacy_manifest_field() -> None:
    assert desktop_provider_token_from_manifest({"token": "legacy-token"}) == (
        "legacy-token"
    )


def test_desktop_provider_token_resolves_owner_only_file(tmp_path) -> None:
    token_file = tmp_path / "provider.token"
    token_file.write_text("file-token\n", encoding="utf-8")
    token_file.chmod(0o600)

    assert desktop_provider_token_from_file(token_file) == "file-token"
    assert desktop_provider_token_from_manifest(
        {"authentication": {"token_file": str(token_file)}}
    ) == "file-token"


def test_desktop_provider_token_rejects_unsafe_file_permissions(tmp_path) -> None:
    token_file = tmp_path / "provider.token"
    token_file.write_text("file-token\n", encoding="utf-8")
    token_file.chmod(0o644)

    try:
        desktop_provider_token_from_file(token_file)
    except ValueError as exc:
        assert "permissions must be 0600" in str(exc)
    else:
        raise AssertionError("unsafe desktop provider token file was accepted")


def test_desktop_provider_token_rejects_symlink(tmp_path) -> None:
    target = tmp_path / "provider-target.token"
    target.write_text("file-token\n", encoding="utf-8")
    target.chmod(0o600)
    token_file = tmp_path / "provider.token"
    token_file.symlink_to(target)

    try:
        desktop_provider_token_from_file(token_file)
    except ValueError as exc:
        assert "must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlinked desktop provider token file was accepted")


def test_public_desktop_provider_env_omits_credentials() -> None:
    public_env = public_desktop_provider_env(
        {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:29097",
            DESKTOP_PROVIDER_TOKEN_ENV: "secret-token",
            "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_TOKEN": "legacy-secret",
        }
    )

    assert public_env == {
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:29097"
    }
