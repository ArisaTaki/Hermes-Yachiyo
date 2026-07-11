"""Credential store guard tests."""

from __future__ import annotations

import json
import threading

import pytest

from apps.shell import credential_store
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


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_dev_file_credential_store_is_disabled_by_release_channel_env(monkeypatch, tmp_path, channel):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_CHANNEL", channel)

    assert development_credential_fallback_enabled() is False
    with pytest.raises(CredentialStoreError, match="disabled"):
        DevFileCredentialStore(tmp_path / "credentials.dev.json")


@pytest.mark.parametrize("env_name", ["OHA_YACHIYO_RELEASE_BUILD", "OHA_YACHIYO_ALPHA_BUILD"])
def test_dev_file_credential_store_is_disabled_by_release_flag_env(monkeypatch, tmp_path, env_name):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv(env_name, "1")

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


class _FakeFunction:
    def __init__(self, return_value: int = 0) -> None:
        self.argtypes = None
        self.restype = None
        self.return_value = return_value
        self.side_effect = None
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        if self.side_effect is not None:
            return self.side_effect(*args)
        return self.return_value


class _FakeLibrary:
    def __init__(self) -> None:
        self._functions: dict[str, _FakeFunction] = {}

    def __getattr__(self, name: str) -> _FakeFunction:
        return self._functions.setdefault(name, _FakeFunction())


def _keychain_store(monkeypatch: pytest.MonkeyPatch, security: _FakeLibrary):
    core_foundation = _FakeLibrary()

    def load_library(path: str) -> _FakeLibrary:
        return core_foundation if "CoreFoundation" in path else security

    monkeypatch.setattr(credential_store.sys, "platform", "darwin")
    monkeypatch.setattr(credential_store.ctypes.cdll, "LoadLibrary", load_library)
    return credential_store.KeychainCredentialStore()


def _configure_noninteractive_find(security: _FakeLibrary) -> None:
    def get_policy(pointer: object) -> int:
        pointer._obj.value = 1
        return 0

    security.SecKeychainGetUserInteractionAllowed.side_effect = get_policy
    security.SecKeychainFindGenericPassword.return_value = -25300


def test_keychain_store_scopes_noninteractive_access(monkeypatch: pytest.MonkeyPatch) -> None:
    security = _FakeLibrary()
    _configure_noninteractive_find(security)
    store = _keychain_store(monkeypatch, security)

    assert store.get("profile:test:api_key") == ""

    function = security.SecKeychainSetUserInteractionAllowed
    assert function.argtypes == [credential_store.ctypes.c_ubyte]
    assert function.restype is credential_store.ctypes.c_int32
    assert function.calls == [(0,), (1,)]


def test_keychain_store_rejects_interaction_policy_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    security = _FakeLibrary()
    security.SecKeychainGetUserInteractionAllowed.return_value = -25291
    store = _keychain_store(monkeypatch, security)

    with pytest.raises(
        credential_store.CredentialStoreError,
        match="read interaction policy failed with OSStatus -25291",
    ):
        store.get("profile:test:api_key")
    assert security.SecKeychainSetUserInteractionAllowed.calls == []


def test_keychain_store_serializes_process_global_interaction_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    security = _FakeLibrary()
    _configure_noninteractive_find(security)
    first_find_started = threading.Event()
    second_find_started = threading.Event()
    release_first_find = threading.Event()
    find_count = 0
    find_count_lock = threading.Lock()

    def find(*_args: object) -> int:
        nonlocal find_count
        with find_count_lock:
            find_count += 1
            current = find_count
        if current == 1:
            first_find_started.set()
            release_first_find.wait(timeout=2)
        else:
            second_find_started.set()
        return -25300

    security.SecKeychainFindGenericPassword.side_effect = find
    first_store = _keychain_store(monkeypatch, security)
    second_store = _keychain_store(monkeypatch, security)
    first = threading.Thread(target=first_store.get, args=("first",))
    second = threading.Thread(target=second_store.get, args=("second",))

    first.start()
    assert first_find_started.wait(timeout=1)
    second.start()
    assert not second_find_started.wait(timeout=0.1)
    release_first_find.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_find_started.is_set()
    assert security.SecKeychainSetUserInteractionAllowed.calls == [
        (0,),
        (1,),
        (0,),
        (1,),
    ]
