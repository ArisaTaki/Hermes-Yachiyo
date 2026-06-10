"""Local credential storage for model profile secrets.

Production macOS builds use Keychain. Tests should inject MemoryCredentialStore.
Development file fallback is intentionally gated by OHA_YACHIYO_DEV=1.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
from pathlib import Path
from typing import Protocol

from apps.core.build_metadata import development_features_enabled


class CredentialStoreError(RuntimeError):
    """Raised when a credential cannot be stored or retrieved."""


class CredentialStore(Protocol):
    def get(self, ref: str) -> str:
        ...

    def set(self, ref: str, secret: str) -> None:
        ...

    def delete(self, ref: str) -> None:
        ...

    def close(self) -> None:
        ...


class MemoryCredentialStore:
    """In-memory credential store for tests."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.RLock()

    def get(self, ref: str) -> str:
        with self._lock:
            return self._values.get(ref, "")

    def set(self, ref: str, secret: str) -> None:
        with self._lock:
            self._values[ref] = secret

    def delete(self, ref: str) -> None:
        with self._lock:
            self._values.pop(ref, None)

    def close(self) -> None:
        with self._lock:
            self._values.clear()


class UnavailableCredentialStore:
    """Startup-safe store used when no production/dev credential backend exists."""

    def get(self, ref: str) -> str:
        return ""

    def set(self, ref: str, secret: str) -> None:
        raise CredentialStoreError(
            "Credential store unavailable. On macOS production builds use Keychain; "
            "for local development set OHA_YACHIYO_DEV=1."
        )

    def delete(self, ref: str) -> None:
        return None

    def close(self) -> None:
        return None


class DevFileCredentialStore:
    """Development-only local credential store.

    This is intentionally not selected unless OHA_YACHIYO_DEV=1 and the build
    channel is not release/alpha.
    """

    def __init__(self, path: Path) -> None:
        if not development_credential_fallback_enabled():
            raise CredentialStoreError("Development credential fallback is disabled")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}

    def _write(self, payload: dict[str, str]) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, ref: str) -> str:
        with self._lock:
            return self._read().get(ref, "")

    def set(self, ref: str, secret: str) -> None:
        with self._lock:
            payload = self._read()
            payload[ref] = secret
            self._write(payload)

    def delete(self, ref: str) -> None:
        with self._lock:
            payload = self._read()
            if ref in payload:
                del payload[ref]
                self._write(payload)

    def close(self) -> None:
        return None


class KeychainCredentialStore:
    """macOS Keychain-backed credential store using Security.framework."""

    _ERR_SEC_SUCCESS = 0
    _ERR_SEC_ITEM_NOT_FOUND = -25300

    def __init__(self, service_name: str = "oha-yachiyo.model-profiles") -> None:
        if sys.platform != "darwin":
            raise CredentialStoreError("KeychainCredentialStore is only available on macOS")
        self.service_name = service_name
        try:
            self._security = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
            self._core_foundation = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
        except OSError as exc:
            raise CredentialStoreError("Unable to load macOS Security.framework") from exc
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        self._security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self._security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        self._security.SecKeychainItemDelete.restype = ctypes.c_int32
        self._security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        self._core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFRelease.restype = None

    def _status_error(self, operation: str, status: int) -> CredentialStoreError:
        return CredentialStoreError(f"Keychain {operation} failed with OSStatus {status}")

    def _find(self, ref: str) -> tuple[str, ctypes.c_void_p | None]:
        service = self.service_name.encode("utf-8")
        account = ref.encode("utf-8")
        password_length = ctypes.c_uint32(0)
        password_data = ctypes.c_void_p()
        item_ref = ctypes.c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            ctypes.byref(password_length),
            ctypes.byref(password_data),
            ctypes.byref(item_ref),
        )
        if status == self._ERR_SEC_ITEM_NOT_FOUND:
            return "", None
        if status != self._ERR_SEC_SUCCESS:
            raise self._status_error("find", status)
        try:
            secret = ""
            if password_data.value and password_length.value:
                secret = ctypes.string_at(password_data, password_length.value).decode("utf-8")
            return secret, item_ref if item_ref.value else None
        finally:
            if password_data.value:
                self._security.SecKeychainItemFreeContent(None, password_data)

    def get(self, ref: str) -> str:
        secret, item_ref = self._find(ref)
        if item_ref is not None:
            self._core_foundation.CFRelease(item_ref)
        return secret

    def set(self, ref: str, secret: str) -> None:
        existing_secret, item_ref = self._find(ref)
        del existing_secret
        secret_bytes = secret.encode("utf-8")
        if item_ref is not None:
            try:
                status = self._security.SecKeychainItemModifyAttributesAndData(
                    item_ref,
                    None,
                    len(secret_bytes),
                    ctypes.c_char_p(secret_bytes),
                )
            finally:
                self._core_foundation.CFRelease(item_ref)
            if status != self._ERR_SEC_SUCCESS:
                raise self._status_error("update", status)
            return

        service = self.service_name.encode("utf-8")
        account = ref.encode("utf-8")
        new_item_ref = ctypes.c_void_p()
        status = self._security.SecKeychainAddGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            len(secret_bytes),
            ctypes.c_char_p(secret_bytes),
            ctypes.byref(new_item_ref),
        )
        if new_item_ref.value:
            self._core_foundation.CFRelease(new_item_ref)
        if status != self._ERR_SEC_SUCCESS:
            raise self._status_error("add", status)

    def delete(self, ref: str) -> None:
        secret, item_ref = self._find(ref)
        del secret
        if item_ref is None:
            return
        try:
            status = self._security.SecKeychainItemDelete(item_ref)
        finally:
            self._core_foundation.CFRelease(item_ref)
        if status not in {self._ERR_SEC_SUCCESS, self._ERR_SEC_ITEM_NOT_FOUND}:
            raise self._status_error("delete", status)

    def close(self) -> None:
        return None


def development_credential_fallback_enabled() -> bool:
    return development_features_enabled()


def create_credential_store(root: Path) -> CredentialStore:
    if sys.platform == "darwin":
        return KeychainCredentialStore()
    if development_credential_fallback_enabled():
        return DevFileCredentialStore(root / "credentials.dev.json")
    return UnavailableCredentialStore()
