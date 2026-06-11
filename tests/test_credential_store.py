"""Credential store guard tests."""

from __future__ import annotations

import json

import pytest

from apps.shell.credential_store import (
    CredentialStoreError,
    DevFileCredentialStore,
    UnavailableCredentialStore,
    create_credential_store,
    development_credential_fallback_enabled,
)


def _write_metadata(tmp_path, *, channel: str) -> str:
    path = tmp_path / "oha-yachiyo-build.json"
    path.write_text(json.dumps({"channel": channel}), encoding="utf-8")
    return str(path)


def _clear_build_env(monkeypatch) -> None:
    for key in (
        "OHA_YACHIYO_DEV",
        "OHA_YACHIYO_BUILD_METADATA",
        "OHA_YACHIYO_BUILD_CHANNEL",
        "OHA_YACHIYO_RELEASE_BUILD",
        "OHA_YACHIYO_ALPHA_BUILD",
        "OHA_YACHIYO_PACKAGED_BUILD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_dev_file_credential_store_requires_development_guard(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)

    assert development_credential_fallback_enabled() is False
    with pytest.raises(CredentialStoreError, match="disabled"):
        DevFileCredentialStore(tmp_path / "credentials.dev.json")


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_dev_file_credential_store_is_disabled_by_release_metadata(monkeypatch, tmp_path, channel):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel=channel))

    assert development_credential_fallback_enabled() is False
    with pytest.raises(CredentialStoreError, match="disabled"):
        DevFileCredentialStore(tmp_path / "credentials.dev.json")


def test_dev_file_credential_store_is_disabled_by_packaged_build_env(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_PACKAGED_BUILD", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))

    assert development_credential_fallback_enabled() is False
    with pytest.raises(CredentialStoreError, match="disabled"):
        DevFileCredentialStore(tmp_path / "credentials.dev.json")


def test_credential_store_factory_does_not_use_dev_fallback_for_packaged_build_env(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_PACKAGED_BUILD", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))
    monkeypatch.setattr("apps.shell.credential_store.sys.platform", "linux")

    store = create_credential_store(tmp_path)
    try:
        assert isinstance(store, UnavailableCredentialStore)
    finally:
        store.close()


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_credential_store_factory_does_not_use_dev_fallback_for_release_like_build(
    monkeypatch, tmp_path, channel
):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel=channel))
    monkeypatch.setattr("apps.shell.credential_store.sys.platform", "linux")

    store = create_credential_store(tmp_path)
    try:
        assert isinstance(store, UnavailableCredentialStore)
    finally:
        store.close()


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_credential_store_factory_uses_keychain_on_macos_release_like_build(
    monkeypatch, tmp_path, channel
):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel=channel))
    monkeypatch.setattr("apps.shell.credential_store.sys.platform", "darwin")

    created: list[str] = []

    class FakeKeychainCredentialStore:
        def __init__(self) -> None:
            created.append("keychain")

        def get(self, ref: str) -> str:
            return ""

        def set(self, ref: str, secret: str) -> None:
            raise AssertionError("not used")

        def delete(self, ref: str) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "apps.shell.credential_store.KeychainCredentialStore",
        FakeKeychainCredentialStore,
    )

    store = create_credential_store(tmp_path)
    try:
        assert isinstance(store, FakeKeychainCredentialStore)
        assert created == ["keychain"]
    finally:
        store.close()


def test_dev_file_credential_store_available_only_for_development(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))

    store = DevFileCredentialStore(tmp_path / "credentials.dev.json")
    try:
        store.set("ref", "secret")
        assert store.get("ref") == "secret"
    finally:
        store.close()
