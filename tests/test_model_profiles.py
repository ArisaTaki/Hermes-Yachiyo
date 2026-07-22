"""Model profile registry tests."""

from __future__ import annotations

import json
import queue
import sqlite3
import ssl
import threading

import pytest

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import CredentialStoreError, MemoryCredentialStore
from apps.shell.model_profiles import (
    OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS,
    ModelProfileError,
    ModelProfileService,
    openai_compatible_chat,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
)
from scripts.verify_secret_redaction import verify_secret_redaction


def make_profile_service(tmp_path) -> ModelProfileService:
    return ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )


class _BlockingCredentialStore(MemoryCredentialStore):
    def __init__(self) -> None:
        super().__init__()
        self.block_reads = False
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def get(self, ref: str) -> str:
        if self.block_reads:
            self.read_started.set()
            self.release_read.wait(timeout=5)
        return super().get(ref)


class _FailingReadCredentialStore(MemoryCredentialStore):
    def get(self, ref: str) -> str:
        raise CredentialStoreError(
            "Keychain find failed with OSStatus -25293 sk-read-secret123456"
        )


class _CredentialRotationStore(MemoryCredentialStore):
    """Deterministic Keychain double; never talks to the host Keychain."""

    def __init__(self) -> None:
        super().__init__()
        self.locked_refs: set[str] = set()
        self.fail_new_writes = False
        self.set_attempts: list[tuple[str, str]] = []
        self.delete_attempts: list[str] = []

    def set(self, ref: str, secret: str) -> None:
        self.set_attempts.append((ref, secret))
        if ref in self.locked_refs:
            raise CredentialStoreError(
                f"Keychain update failed with OSStatus -25293 {secret}"
            )
        if self.fail_new_writes and self.locked_refs:
            # Model an ambiguous native failure where the item was created
            # before Security.framework reported the error.
            super().set(ref, secret)
            raise CredentialStoreError(
                f"Keychain add failed with OSStatus -25293 {secret}"
            )
        super().set(ref, secret)

    def delete(self, ref: str) -> None:
        self.delete_attempts.append(ref)
        if ref in self.locked_refs:
            raise CredentialStoreError(
                "Keychain delete failed with OSStatus -25293"
            )
        super().delete(ref)

    def value_for_test(self, ref: str) -> str:
        return self._values.get(ref, "")


class _LockOrderCredentialStore(MemoryCredentialStore):
    def __init__(self, order: queue.Queue[str], main_thread_id: int) -> None:
        super().__init__()
        self._order = order
        self._main_thread_id = main_thread_id

    def _record_worker_effect(self) -> None:
        if threading.get_ident() != self._main_thread_id:
            self._order.put("credential")

    def set(self, ref: str, secret: str) -> None:
        self._record_worker_effect()
        super().set(ref, secret)

    def delete(self, ref: str) -> None:
        self._record_worker_effect()
        super().delete(ref)


class _ObservedServiceLock:
    def __init__(
        self,
        lock: threading.RLock,
        order: queue.Queue[str],
        main_thread_id: int,
    ) -> None:
        self._lock = lock
        self._order = order
        self._main_thread_id = main_thread_id

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if threading.get_ident() != self._main_thread_id:
            self._order.put("lock")
        if timeout == -1:
            return self._lock.acquire(blocking)
        return self._lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args) -> None:
        self.release()


class _ObservedConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        order: queue.Queue[str],
        main_thread_id: int,
    ) -> None:
        self._connection = connection
        self._order = order
        self._main_thread_id = main_thread_id

    def execute(self, *args, **kwargs):
        if threading.get_ident() != self._main_thread_id:
            self._order.put("database")
        return self._connection.execute(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


class _CommitFaultConnection:
    """SQLite proxy that fails the next commit before or after durability."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        persist_before_error: bool,
    ) -> None:
        self._connection = connection
        self._persist_before_error = persist_before_error
        self._armed = True

    def commit(self) -> None:
        if not self._armed:
            self._connection.commit()
            return
        self._armed = False
        if self._persist_before_error:
            self._connection.commit()
        raise sqlite3.OperationalError("forced commit outcome unknown")

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


class _CredentialRefRotatingReadStore(MemoryCredentialStore):
    def __init__(self) -> None:
        super().__init__()
        self.blocked_ref = ""
        self.first_read_started = threading.Event()
        self.release_first_read = threading.Event()
        self.get_refs: list[str] = []
        self._first_read_claimed = False
        self._claim_lock = threading.Lock()

    def arm(self, ref: str) -> None:
        self.blocked_ref = ref

    def get(self, ref: str) -> str:
        self.get_refs.append(ref)
        should_block = False
        with self._claim_lock:
            if ref == self.blocked_ref and not self._first_read_claimed:
                self._first_read_claimed = True
                should_block = True
        if should_block:
            self.first_read_started.set()
            self.release_first_read.wait(timeout=5)
        return super().get(ref)


class _OwnershipTrackingLock:
    """RLock proxy exposing whether the current thread owns the service lock."""

    def __init__(self, lock: threading.RLock) -> None:
        self._lock = lock
        self._state_lock = threading.Lock()
        self._owner: int | None = None
        self._depth = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if timeout == -1:
            acquired = self._lock.acquire(blocking)
        else:
            acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            thread_id = threading.get_ident()
            with self._state_lock:
                if self._owner == thread_id:
                    self._depth += 1
                else:
                    self._owner = thread_id
                    self._depth = 1
        return acquired

    def release(self) -> None:
        thread_id = threading.get_ident()
        with self._state_lock:
            assert self._owner == thread_id
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()

    def owned_by_current_thread(self) -> bool:
        with self._state_lock:
            return self._owner == threading.get_ident() and self._depth > 0

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args) -> None:
        self.release()


class _WriteOwnershipObservedConnection:
    """SQLite proxy recording lock ownership at each write and commit."""

    _WRITE_PREFIXES = ("DELETE", "INSERT", "REPLACE", "UPDATE")

    def __init__(
        self,
        connection: sqlite3.Connection,
        service_lock: _OwnershipTrackingLock,
        armed: threading.Event,
    ) -> None:
        self._connection = connection
        self._service_lock = service_lock
        self._armed = armed
        self.observations: list[tuple[str, bool]] = []

    def execute(self, sql: str, *args, **kwargs):
        statement = str(sql or "").lstrip().upper()
        if self._armed.is_set() and statement.startswith(self._WRITE_PREFIXES):
            self.observations.append(
                ("execute", self._service_lock.owned_by_current_thread())
            )
        return self._connection.execute(sql, *args, **kwargs)

    def commit(self) -> None:
        if self._armed.is_set():
            self.observations.append(
                ("commit", self._service_lock.owned_by_current_thread())
            )
        self._connection.commit()

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


class _BlockingModelCall:
    """Network-free model double that lets a credential rotate mid-request."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.api_keys: list[str] = []

    def __call__(
        self,
        _base_url: str,
        _model: str,
        api_key: str,
        _messages: list[dict],
    ) -> str:
        self.api_keys.append(api_key)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("test did not release the fake model request")
        return "OK"


def _credential_row(db_path, table: str, id_column: str, row_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT api_key, credential_ref FROM {table} WHERE {id_column}=?",
            (row_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row


def _vision_challenge():
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "left/right color test"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ], ("red", "blue")


def test_model_profile_crud_redacts_and_preserves_api_key(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Work Gateway",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )

        assert profile["api_key_configured"] is True
        assert "api_key" not in profile

        updated = service.update_profile(
            profile["profile_id"],
            {"base_url": "https://gateway.example.test/v1", "api_key": ""},
        )
        private = service.get_profile_private(profile["profile_id"])

        assert updated["base_url"] == "https://gateway.example.test/v1"
        assert updated["api_key_configured"] is True
        assert private["api_key"] == "sk-secret"

        conn = sqlite3.connect(tmp_path / "model-profiles.db")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                (profile["profile_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["api_key"] == ""
        assert row["credential_ref"] == f"model_profile:{profile['profile_id']}:api_key"
    finally:
        service.close()


def test_update_standalone_profile_rotates_inaccessible_credential_ref(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    credentials = _CredentialRotationStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    replacement = "sk-profile-replacement-secret123456"
    try:
        profile = service.create_profile(
            {
                "name": "Standalone",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-profile-original-secret123456",
            }
        )
        original_row = _credential_row(
            db_path,
            "model_profiles",
            "profile_id",
            profile["profile_id"],
        )
        original_ref = str(original_row["credential_ref"])
        credentials.locked_refs.add(original_ref)

        updated = service.update_profile(
            profile["profile_id"],
            {"api_key": replacement},
        )
        rotated_row = _credential_row(
            db_path,
            "model_profiles",
            "profile_id",
            profile["profile_id"],
        )
        rotated_ref = str(rotated_row["credential_ref"])

        assert rotated_ref
        assert rotated_ref != original_ref
        assert rotated_row["api_key"] == ""
        assert credentials.value_for_test(rotated_ref) == replacement
        assert updated["api_key_configured"] is True
        assert "api_key" not in updated
        assert replacement not in repr(updated)
        assert replacement not in repr(tuple(rotated_row))
    finally:
        service.close()


def test_update_source_rotates_inaccessible_credential_ref(tmp_path):
    db_path = tmp_path / "model-sources.db"
    credentials = _CredentialRotationStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / "sources",
        credential_store=credentials,
    )
    replacement = "sk-source-replacement-secret123456"
    try:
        source = service.create_source(
            {
                "name": "Gateway",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-original-secret123456",
            }
        )
        original_row = _credential_row(
            db_path,
            "model_sources",
            "source_id",
            source["source_id"],
        )
        original_ref = str(original_row["credential_ref"])
        credentials.locked_refs.add(original_ref)

        updated = service.update_source(
            source["source_id"],
            {"api_key": replacement},
        )
        rotated_row = _credential_row(
            db_path,
            "model_sources",
            "source_id",
            source["source_id"],
        )
        rotated_ref = str(rotated_row["credential_ref"])

        assert rotated_ref
        assert rotated_ref != original_ref
        assert rotated_row["api_key"] == ""
        assert credentials.value_for_test(rotated_ref) == replacement
        assert updated["api_key_configured"] is True
        assert "api_key" not in updated
        assert replacement not in repr(updated)
        assert replacement not in repr(tuple(rotated_row))
    finally:
        service.close()


def test_update_source_preserves_old_ref_when_rotated_credential_write_fails(tmp_path):
    db_path = tmp_path / "model-sources.db"
    credentials = _CredentialRotationStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / "sources",
        credential_store=credentials,
    )
    replacement = "sk-source-write-failure-secret123456"
    try:
        source = service.create_source(
            {
                "name": "Gateway",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-original-secret123456",
            }
        )
        original_row = _credential_row(
            db_path,
            "model_sources",
            "source_id",
            source["source_id"],
        )
        original_ref = str(original_row["credential_ref"])
        original_secret = credentials.value_for_test(original_ref)
        credentials.locked_refs.add(original_ref)
        credentials.fail_new_writes = True

        with pytest.raises(ModelProfileError) as error:
            service.update_source(source["source_id"], {"api_key": replacement})

        persisted_row = _credential_row(
            db_path,
            "model_sources",
            "source_id",
            source["source_id"],
        )
        attempted_rotated_refs = {
            ref for ref, _secret in credentials.set_attempts if ref != original_ref
        }

        assert attempted_rotated_refs
        assert persisted_row["credential_ref"] == original_ref
        assert persisted_row["api_key"] == ""
        assert credentials.value_for_test(original_ref) == original_secret
        assert original_ref not in credentials.delete_attempts
        assert all(
            credentials.value_for_test(ref) == ""
            for ref in attempted_rotated_refs
        )
        assert attempted_rotated_refs.issubset(credentials.delete_attempts)
        assert replacement not in str(error.value)
    finally:
        service.close()


def test_update_standalone_profile_cleans_rotated_ref_when_db_write_fails(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    credentials = _CredentialRotationStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    replacement = "sk-profile-db-failure-secret123456"
    try:
        profile = service.create_profile(
            {
                "name": "Standalone",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-profile-original-secret123456",
            }
        )
        original_row = _credential_row(
            db_path,
            "model_profiles",
            "profile_id",
            profile["profile_id"],
        )
        original_ref = str(original_row["credential_ref"])
        original_secret = credentials.value_for_test(original_ref)
        credentials.locked_refs.add(original_ref)
        service._conn.execute(
            """
            CREATE TRIGGER fail_profile_credential_rotation
            BEFORE UPDATE OF credential_ref ON model_profiles
            WHEN NEW.credential_ref <> OLD.credential_ref
            BEGIN
                SELECT RAISE(ABORT, 'forced credential-ref DB failure');
            END
            """
        )
        service._conn.commit()

        with pytest.raises((sqlite3.DatabaseError, ModelProfileError)):
            service.update_profile(profile["profile_id"], {"api_key": replacement})

        persisted_row = _credential_row(
            db_path,
            "model_profiles",
            "profile_id",
            profile["profile_id"],
        )
        attempted_rotated_refs = {
            ref for ref, _secret in credentials.set_attempts if ref != original_ref
        }

        assert len(attempted_rotated_refs) == 1
        rotated_ref = attempted_rotated_refs.pop()
        assert persisted_row["credential_ref"] == original_ref
        assert persisted_row["api_key"] == ""
        assert credentials.value_for_test(original_ref) == original_secret
        assert original_ref not in credentials.delete_attempts
        assert rotated_ref in credentials.delete_attempts
        assert credentials.value_for_test(rotated_ref) == ""
    finally:
        service.close()


@pytest.mark.parametrize("record_kind", ["source", "profile"])
@pytest.mark.parametrize("persist_before_error", [False, True])
def test_credential_rotation_cleanup_respects_commit_outcome_unknown(
    tmp_path,
    record_kind: str,
    persist_before_error: bool,
):
    """Never delete a staged secret that an outcome-unknown commit references."""

    db_path = tmp_path / f"model-{record_kind}-commit-fault.db"
    credentials = _CredentialRotationStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / f"{record_kind}-commit-fault",
        credential_store=credentials,
    )
    original_secret = f"{record_kind}-original-test-secret"
    replacement_secret = f"{record_kind}-replacement-test-secret"
    if record_kind == "source":
        table = "model_sources"
        id_column = "source_id"
        record = service.create_source(
            {
                "name": "Commit Fault Source",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "api_key": original_secret,
            }
        )
        update = service.update_source
    else:
        table = "model_profiles"
        id_column = "profile_id"
        record = service.create_profile(
            {
                "name": "Commit Fault Profile",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": original_secret,
            }
        )
        update = service.update_profile

    record_id = str(record[id_column])
    original_row = _credential_row(db_path, table, id_column, record_id)
    original_ref = str(original_row["credential_ref"])
    service._conn = _CommitFaultConnection(
        service._conn,
        persist_before_error=persist_before_error,
    )

    try:
        with pytest.raises(sqlite3.OperationalError, match="commit outcome unknown"):
            update(record_id, {"api_key": replacement_secret})

        persisted_row = _credential_row(db_path, table, id_column, record_id)
        staged_refs = {
            ref for ref, _secret in credentials.set_attempts if ref != original_ref
        }
        assert len(staged_refs) == 1
        staged_ref = staged_refs.pop()
        assert credentials.value_for_test(original_ref) == original_secret
        assert original_ref not in credentials.delete_attempts

        if persist_before_error:
            assert persisted_row["credential_ref"] == staged_ref
            assert credentials.value_for_test(staged_ref) == replacement_secret
            assert staged_ref not in credentials.delete_attempts
        else:
            assert persisted_row["credential_ref"] == original_ref
            assert credentials.value_for_test(staged_ref) == ""
            assert staged_ref in credentials.delete_attempts
    finally:
        service.close()


@pytest.mark.parametrize(
    "operation",
    ["create_source", "create_profile", "delete_profile"],
)
def test_model_profile_mutations_acquire_service_lock_before_effects(
    tmp_path,
    operation: str,
):
    order: queue.Queue[str] = queue.Queue()
    main_thread_id = threading.get_ident()
    credentials = _LockOrderCredentialStore(order, main_thread_id)
    service = ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    profile_to_delete = None
    if operation == "delete_profile":
        profile_to_delete = service.create_profile(
            {
                "name": "Delete Me",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-delete-lock-secret123456",
            }
        )

    service._conn = _ObservedConnection(service._conn, order, main_thread_id)
    service._lock = _ObservedServiceLock(service._lock, order, main_thread_id)
    worker_started = threading.Event()
    worker_done = threading.Event()
    worker_errors: list[BaseException] = []

    def mutate() -> None:
        worker_started.set()
        try:
            if operation == "create_source":
                service.create_source(
                    {
                        "name": "Locked Source",
                        "capability": "chat",
                        "base_url": "https://api.example.test/v1",
                        "api_key": "sk-source-lock-secret123456",
                    }
                )
            elif operation == "create_profile":
                service.create_profile(
                    {
                        "name": "Locked Profile",
                        "capability": "chat",
                        "base_url": "https://api.example.test/v1",
                        "model": "demo-model",
                        "api_key": "sk-profile-lock-secret123456",
                    }
                )
            else:
                assert profile_to_delete is not None
                service.delete_profile(profile_to_delete["profile_id"])
        except BaseException as exc:  # surfaced on the main test thread below
            worker_errors.append(exc)
        finally:
            worker_done.set()

    worker = threading.Thread(target=mutate)
    first_event = ""
    started = False
    try:
        with service._lock:
            worker.start()
            started = worker_started.wait(timeout=1)
            try:
                first_event = order.get(timeout=1)
            except queue.Empty:
                first_event = "timeout"
        assert worker_done.wait(timeout=2)
        worker.join(timeout=1)

        assert started is True
        assert not worker.is_alive()
        assert worker_errors == []
        assert first_event == "lock"
    finally:
        if worker.is_alive():
            worker.join(timeout=2)
        service.close()


@pytest.mark.parametrize("private_reader", ["source", "profile"])
def test_private_reads_retry_when_source_credential_ref_rotates(
    tmp_path,
    private_reader: str,
):
    db_path = tmp_path / "model-profiles.db"
    credentials = _CredentialRefRotatingReadStore()
    service = ModelProfileService(
        db_path=db_path,
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    source = service.create_source(
        {
            "name": "Rotating Source",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-old-secret123456",
        }
    )
    profile = service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "Rotating Profile",
            "capability": "chat",
            "model": "demo-model",
        }
    )
    original_ref = str(
        _credential_row(
            db_path,
            "model_sources",
            "source_id",
            source["source_id"],
        )["credential_ref"]
    )
    credentials.arm(original_ref)
    private_result: list[dict] = []
    private_errors: list[BaseException] = []
    private_done = threading.Event()
    public_done = threading.Event()

    def read_private() -> None:
        try:
            if private_reader == "source":
                private_result.append(service.get_source_private(source["source_id"]))
            else:
                private_result.append(service.get_profile_private(profile["profile_id"]))
        except BaseException as exc:
            private_errors.append(exc)
        finally:
            private_done.set()

    def read_public() -> None:
        if private_reader == "source":
            service.get_source(source["source_id"])
        else:
            service.get_profile(profile["profile_id"])
        public_done.set()

    private_thread = threading.Thread(target=read_private)
    public_thread = threading.Thread(target=read_public)
    public_started = False
    replacement = "sk-source-new-secret123456"
    public_completed_while_keychain_blocked = False
    try:
        private_thread.start()
        assert credentials.first_read_started.wait(timeout=1)
        public_thread.start()
        public_started = True
        public_completed_while_keychain_blocked = public_done.wait(timeout=1)
        service.update_source(source["source_id"], {"api_key": replacement})
    finally:
        credentials.release_first_read.set()
        private_thread.join(timeout=2)
        if public_started:
            public_thread.join(timeout=2)

    try:
        rotated_ref = str(
            _credential_row(
                db_path,
                "model_sources",
                "source_id",
                source["source_id"],
            )["credential_ref"]
        )
        assert public_completed_while_keychain_blocked is True
        assert private_done.is_set()
        assert not private_thread.is_alive()
        assert not public_thread.is_alive()
        assert private_errors == []
        assert len(private_result) == 1
        assert rotated_ref != original_ref
        assert private_result[0]["api_key"] == replacement
        result_ref_key = (
            "credential_ref" if private_reader == "source" else "source_credential_ref"
        )
        assert private_result[0][result_ref_key] == rotated_ref
        assert credentials.get_refs[0] == original_ref
        assert rotated_ref in credentials.get_refs[1:]
    finally:
        service.close()


def test_explicit_source_api_key_update_resets_source_and_child_profiles(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Reset Source",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-old-secret123456",
            }
        )
        profiles = [
            service.create_profile(
                {
                    "source_id": source["source_id"],
                    "name": f"Child {index}",
                    "capability": "chat",
                    "model": f"demo-model-{index}",
                }
            )
            for index in range(2)
        ]
        service._conn.execute(
            "UPDATE model_sources SET status='failed', last_error='stale source error', last_tested_at='old' WHERE source_id=?",
            (source["source_id"],),
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_error='stale profile error', last_tested_at='old' WHERE source_id=?",
            (source["source_id"],),
        )
        service._conn.commit()

        service.update_source(
            source["source_id"],
            {"api_key": "sk-source-new-secret123456"},
        )

        reset_source = service.get_source(source["source_id"])
        reset_profiles = [
            service.get_profile(profile["profile_id"])
            for profile in profiles
        ]
        assert reset_source["status"] == "untested"
        assert reset_source["last_error"] == ""
        assert all(profile["status"] == "untested" for profile in reset_profiles)
        assert all(profile["last_error"] == "" for profile in reset_profiles)
    finally:
        service.close()


def test_explicit_standalone_profile_api_key_update_resets_only_that_profile(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        target = service.create_profile(
            {
                "name": "Reset Target",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-target",
                "api_key": "sk-target-old-secret123456",
            }
        )
        unrelated = service.create_profile(
            {
                "name": "Unrelated",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-unrelated",
                "api_key": "sk-unrelated-secret123456",
            }
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='failed', last_error='stale target error', last_tested_at='old' WHERE profile_id=?",
            (target["profile_id"],),
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_error='unrelated error', last_tested_at='old' WHERE profile_id=?",
            (unrelated["profile_id"],),
        )
        service._conn.commit()

        service.update_profile(
            target["profile_id"],
            {"api_key": "sk-target-new-secret123456"},
        )

        reset_target = service.get_profile(target["profile_id"])
        unchanged = service.get_profile(unrelated["profile_id"])
        assert reset_target["status"] == "untested"
        assert reset_target["last_error"] == ""
        assert unchanged["status"] == "available"
        assert unchanged["last_error"] == "unrelated error"
    finally:
        service.close()


@pytest.mark.parametrize("record_kind", ["source", "profile"])
def test_connection_test_result_writes_hold_service_lock(
    monkeypatch,
    tmp_path,
    record_kind: str,
):
    """A completed network test must join the credential-rotation transaction lock."""

    service = make_profile_service(tmp_path)
    if record_kind == "source":
        record = service.create_source(
            {
                "name": "Lock Source",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-lock-secret123456",
            }
        )
        run_test = lambda: service.test_source(
            record["source_id"],
            {"model": "demo-model"},
        )
    else:
        record = service.create_profile(
            {
                "name": "Lock Profile",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-profile-lock-secret123456",
            }
        )
        run_test = lambda: service.test_profile(record["profile_id"])

    armed = threading.Event()
    tracked_lock = _OwnershipTrackingLock(service._lock)
    observed_connection = _WriteOwnershipObservedConnection(
        service._conn,
        tracked_lock,
        armed,
    )
    service._lock = tracked_lock
    service._conn = observed_connection

    def model_call(*_args, **_kwargs) -> str:
        armed.set()
        return "OK"

    monkeypatch.setattr(
        "apps.shell.model_profiles.openai_compatible_chat",
        model_call,
    )
    try:
        result = run_test()

        assert result["ok"] is True
        assert observed_connection.observations
        assert all(
            lock_owned
            for _operation, lock_owned in observed_connection.observations
        ), observed_connection.observations
    finally:
        service.close()


def test_source_test_discards_success_from_rotated_credential_generation(
    monkeypatch,
    tmp_path,
):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Stale Source Test",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-old-generation123456",
        }
    )
    model_call = _BlockingModelCall()
    monkeypatch.setattr(
        "apps.shell.model_profiles.openai_compatible_chat",
        model_call,
    )
    results: list[dict] = []
    errors: list[BaseException] = []

    def test_connection() -> None:
        try:
            results.append(
                service.test_source(
                    source["source_id"],
                    {"model": "demo-model"},
                )
            )
        except BaseException as exc:  # surfaced on the main test thread below
            errors.append(exc)

    worker = threading.Thread(target=test_connection)
    try:
        worker.start()
        assert model_call.started.wait(timeout=1)
        service.update_source(
            source["source_id"],
            {"api_key": "sk-source-new-generation123456"},
        )
    finally:
        model_call.release.set()
        worker.join(timeout=2)

    try:
        assert not worker.is_alive()
        assert errors == []
        assert len(results) == 1
        assert model_call.api_keys == ["sk-source-old-generation123456"]
        assert results[0]["ok"] is False
        assert "配置" in results[0]["message"]
        assert "变化" in results[0]["message"]
        assert (
            "重测" in results[0]["message"]
            or "重新测试" in results[0]["message"]
        )
        assert results[0]["source"]["status"] == "untested"
        assert service.get_source(source["source_id"])["status"] == "untested"
    finally:
        service.close()


def test_profile_test_discards_success_from_rotated_credential_generation(
    monkeypatch,
    tmp_path,
):
    service = make_profile_service(tmp_path)
    profile = service.create_profile(
        {
            "name": "Stale Profile Test",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-profile-old-generation123456",
        }
    )
    model_call = _BlockingModelCall()
    monkeypatch.setattr(
        "apps.shell.model_profiles.openai_compatible_chat",
        model_call,
    )
    results: list[dict] = []
    errors: list[BaseException] = []

    def test_connection() -> None:
        try:
            results.append(service.test_profile(profile["profile_id"]))
        except BaseException as exc:  # surfaced on the main test thread below
            errors.append(exc)

    worker = threading.Thread(target=test_connection)
    try:
        worker.start()
        assert model_call.started.wait(timeout=1)
        service.update_profile(
            profile["profile_id"],
            {"api_key": "sk-profile-new-generation123456"},
        )
    finally:
        model_call.release.set()
        worker.join(timeout=2)

    try:
        assert not worker.is_alive()
        assert errors == []
        assert len(results) == 1
        assert model_call.api_keys == ["sk-profile-old-generation123456"]
        assert results[0]["ok"] is False
        assert "配置" in results[0]["message"]
        assert "变化" in results[0]["message"]
        assert (
            "重测" in results[0]["message"]
            or "重新测试" in results[0]["message"]
        )
        assert results[0]["profile"]["status"] == "untested"
        assert service.get_profile(profile["profile_id"])["status"] == "untested"
    finally:
        service.close()


def test_profile_credential_failure_does_not_mark_reentered_key_failed(tmp_path):
    credentials = _FailingReadCredentialStore()
    service = ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    profile = service.create_profile(
        {
            "name": "Credential Recovery Race",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-profile-old-read-failure123456",
        }
    )
    record_started = threading.Event()
    release_record = threading.Event()
    original_record = service._record_test_result
    results: list[dict] = []

    def blocking_record(*args, **kwargs):
        record_started.set()
        assert release_record.wait(timeout=5)
        return original_record(*args, **kwargs)

    service._record_test_result = blocking_record  # type: ignore[method-assign]
    worker = threading.Thread(
        target=lambda: results.append(service.test_profile(profile["profile_id"]))
    )
    try:
        worker.start()
        assert record_started.wait(timeout=1)
        service.update_profile(
            profile["profile_id"],
            {"api_key": "sk-profile-new-read-recovery123456"},
        )
    finally:
        release_record.set()
        worker.join(timeout=2)

    try:
        assert not worker.is_alive()
        assert len(results) == 1
        assert results[0]["ok"] is False
        assert results[0]["stale_result"] is True
        assert service.get_profile(profile["profile_id"])["status"] == "untested"
    finally:
        service.close()


def test_private_profile_keychain_read_does_not_block_public_profile_reads(tmp_path):
    credentials = _BlockingCredentialStore()
    service = ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=credentials,
    )
    profile = service.create_profile(
        {
            "name": "Blocking Keychain",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    credentials.block_reads = True
    private_done = threading.Event()
    public_done = threading.Event()

    def read_private() -> None:
        service.get_profile_private(profile["profile_id"])
        private_done.set()

    def read_public() -> None:
        service.get_profile(profile["profile_id"])
        public_done.set()

    private_thread = threading.Thread(target=read_private)
    public_thread = threading.Thread(target=read_public)
    try:
        private_thread.start()
        assert credentials.read_started.wait(timeout=1)
        public_thread.start()
        assert public_done.wait(timeout=1)
    finally:
        credentials.release_read.set()
        private_thread.join(timeout=2)
        public_thread.join(timeout=2)
        service.close()

    assert private_done.is_set()


def test_private_source_keychain_read_does_not_block_public_source_reads(tmp_path):
    credentials = _BlockingCredentialStore()
    service = ModelProfileService(
        db_path=tmp_path / "model-sources.db",
        workspace_dir=tmp_path / "sources",
        credential_store=credentials,
    )
    source = service.create_source(
        {
            "name": "Blocking Source Keychain",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-secret",
        }
    )
    credentials.block_reads = True
    private_done = threading.Event()
    public_done = threading.Event()

    def read_private() -> None:
        service.get_source_private(source["source_id"])
        private_done.set()

    def read_public() -> None:
        service.get_source(source["source_id"])
        public_done.set()

    private_thread = threading.Thread(target=read_private)
    public_thread = threading.Thread(target=read_public)
    try:
        private_thread.start()
        assert credentials.read_started.wait(timeout=1)
        public_thread.start()
        assert public_done.wait(timeout=1)
    finally:
        credentials.release_read.set()
        private_thread.join(timeout=2)
        public_thread.join(timeout=2)
        service.close()

    assert private_done.is_set()


def test_model_profile_defaults_validate_capability(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile({"name": "Vision", "capability": "vision"})

        with pytest.raises(ModelProfileError):
            service.set_defaults({"chat": profile["profile_id"]})

        result = service.set_defaults({"vision": profile["profile_id"]})
        assert result["defaults"]["vision"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_test_sets_default_when_missing(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Chat",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )

        result = service._record_test_result(profile["profile_id"], ok=True, message="OK")

        assert result["defaults"]["chat"] == profile["profile_id"]
        assert service.get_defaults()["chat"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_defaults_repair_single_available_profile(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Chat",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_tested_at='now', updated_at='now' WHERE profile_id=?",
            (profile["profile_id"],),
        )
        service._conn.commit()

        assert service.get_defaults()["chat"] == profile["profile_id"]
    finally:
        service.close()


def test_model_profile_defaults_do_not_guess_between_multiple_available_profiles(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        first = service.create_profile(
            {
                "name": "Chat One",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-a",
                "api_key": "sk-secret-a",
            }
        )
        second = service.create_profile(
            {
                "name": "Chat Two",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model-b",
                "api_key": "sk-secret-b",
            }
        )
        service._conn.execute(
            "UPDATE model_profiles SET status='available', last_tested_at='now', updated_at='now' WHERE profile_id IN (?, ?)",
            (first["profile_id"], second["profile_id"]),
        )
        service._conn.commit()

        assert service.get_defaults()["chat"] == ""
    finally:
        service.close()


def test_model_source_owns_credentials_and_models_reference_it(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "MiniMax",
                "provider": "openai_compatible",
                "base_url": "https://api.minimax.chat/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiniMax Chat",
                "capability": "chat",
                "model": "MiniMax-M2.7",
                "api_key": "sk-ignored",
            }
        )
        public_profile = service.get_profile(profile["profile_id"])
        private_profile = service.get_profile_private(profile["profile_id"])
        updated = service.update_profile(profile["profile_id"], {"model": "MiniMax-M2.8"})

        assert public_profile["source_name"] == "MiniMax"
        assert public_profile["base_url"] == "https://api.minimax.chat/v1"
        assert public_profile["api_key_configured"] is True
        assert private_profile["api_key"] == "sk-source-secret"
        assert service.get_profile_private(profile["profile_id"])["api_key"] == "sk-source-secret"
        assert updated["model"] == "MiniMax-M2.8"

        conn = sqlite3.connect(tmp_path / "model-profiles.db")
        conn.row_factory = sqlite3.Row
        try:
            source_row = conn.execute(
                "SELECT api_key, credential_ref FROM model_sources WHERE source_id=?",
                (source["source_id"],),
            ).fetchone()
            profile_row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                (profile["profile_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert source_row is not None
        assert profile_row is not None
        assert source_row["api_key"] == ""
        assert source_row["credential_ref"] == f"model_source:{source['source_id']}:api_key"
        assert profile_row["api_key"] == ""
        assert profile_row["credential_ref"] == ""
    finally:
        service.close()


def test_model_sources_are_scoped_by_capability(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        chat_source = service.create_source(
            {
                "name": "Gateway",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-chat",
            }
        )
        vision_source = service.create_source(
            {
                "name": "Gateway",
                "capability": "vision",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-vision",
            }
        )

        assert chat_source["capability"] == "chat"
        assert vision_source["capability"] == "vision"
        with pytest.raises(ModelProfileError, match="ID 在当前类型下必须唯一"):
            service.create_source(
                {
                    "name": "Gateway",
                    "capability": "vision",
                    "provider": "openai_compatible",
                    "base_url": "https://api.example.test/v1",
                }
            )
        with pytest.raises(ModelProfileError):
            service.create_profile(
                {
                    "source_id": chat_source["source_id"],
                    "name": "Wrong Vision",
                    "capability": "vision",
                    "model": "vision-model",
                }
            )
    finally:
        service.close()


def test_sync_tts_provider_registers_available_gsv_source_and_default(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        result = service.sync_tts_provider(
            {
                "enabled": True,
                "provider": "gpt-sovits",
                "base_url": "http://127.0.0.1:9880",
                "voice": "yachiyo",
                "options": {"gsv_text_language": "zh"},
            }
        )

        assert result["ok"] is True
        assert result["source"]["capability"] == "tts"
        assert result["source"]["provider"] == "gsv_tts_local"
        assert result["source"]["status"] == "available"
        assert result["profile"]["capability"] == "tts"
        assert result["profile"]["model"] == "yachiyo"
        assert result["profile"]["status"] == "available"
        assert result["defaults"]["tts"] == result["profile"]["profile_id"]

        second = service.sync_tts_provider(
            {
                "enabled": True,
                "provider": "gpt-sovits",
                "base_url": "http://127.0.0.1:9880",
                "voice": "yachiyo",
            }
        )

        assert second["source"]["source_id"] == result["source"]["source_id"]
        assert second["profile"]["profile_id"] == result["profile"]["profile_id"]
        assert len([source for source in service.list_sources()["sources"] if source["capability"] == "tts"]) == 1
    finally:
        service.close()


def test_legacy_shared_source_is_split_by_profile_capability(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE model_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profiles (
            profile_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL UNIQUE,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profile_defaults (
            capability TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO model_sources VALUES (
            'source_shared', 'Gateway', 'openai_compatible', 'https://api.example.test/v1',
            'sk-source-secret123456', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        INSERT INTO model_profiles VALUES (
            'profile_chat', 'source_shared', 'Gateway Chat', 'chat', 'openai_compatible',
            '', 'chat-model', '', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        INSERT INTO model_profiles VALUES (
            'profile_vision', 'source_shared', 'Gateway Vision', 'vision', 'openai_compatible',
            '', 'vision-model', '', '{}', 1, 'available', 'now', '', 'now', 'now'
        );
        """
    )
    conn.close()

    service = make_profile_service(tmp_path)
    try:
        sources = service.list_sources()["sources"]
        by_capability = {source["capability"]: source for source in sources}

        assert set(by_capability) == {"chat", "vision"}
        assert by_capability["chat"]["name"] == "Gateway"
        assert by_capability["vision"]["name"] == "Gateway"
        assert service.get_profile("profile_chat")["source_id"] == by_capability["chat"]["source_id"]
        assert service.get_profile("profile_vision")["source_id"] == by_capability["vision"]["source_id"]
        assert service.get_source_private(by_capability["chat"]["source_id"])["api_key"] == "sk-source-secret123456"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT api_key, credential_ref FROM model_sources ORDER BY capability").fetchall()
        finally:
            conn.close()
        assert [row["api_key"] for row in rows] == ["", ""]
        assert all(row["credential_ref"] for row in rows)
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_legacy_model_profile_api_key_migration_vacuums_plaintext_secret(tmp_path):
    db_path = tmp_path / "model-profiles.db"
    legacy_secret = "sk-legacy-profile-secret123456"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        f"""
        CREATE TABLE model_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{{}}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(capability, name)
        );
        CREATE TABLE model_profiles (
            profile_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL UNIQUE,
            capability TEXT NOT NULL DEFAULT 'chat',
            provider TEXT NOT NULL DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            options_json TEXT NOT NULL DEFAULT '{{}}',
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'untested',
            last_tested_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE model_profile_defaults (
            capability TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO model_profiles VALUES (
            'profile_legacy_secret', '', 'Legacy Chat', 'chat', 'openai_compatible',
            'https://api.example.test/v1', 'demo-model', '{legacy_secret}', '{{}}',
            1, 'available', 'now', '', 'now', 'now'
        );
        """
    )
    conn.close()

    service = make_profile_service(tmp_path)
    try:
        profile = service.get_profile_private("profile_legacy_secret")
        assert profile["api_key"] == legacy_secret

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
                ("profile_legacy_secret",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["api_key"] == ""
        assert row["credential_ref"] == "model_profile:profile_legacy_secret:api_key"
        assert verify_secret_redaction(paths=[tmp_path]) == []
    finally:
        service.close()


def test_model_source_reports_native_provider_adapter(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Xiaomi MiMo",
                "provider": "xiaomi_mimo",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiMo",
                "capability": "chat",
                "model": "mimo-v2-pro",
            }
        )
        public_source = service.get_source(source["source_id"])
        public_profile = service.get_profile(profile["profile_id"])

        assert public_source["native_provider"] == "xiaomi"
        assert public_source["api_key_name"] == "XIAOMI_API_KEY"
        assert public_source["can_use_as_native"] is True
        assert public_profile["native_provider"] == "xiaomi"
        assert public_profile["runtime_scope"] == "native"
    finally:
        service.close()


def test_openrouter_profile_keeps_openrouter_as_runtime_provider(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "OpenRouter",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "DeepSeek via OpenRouter",
                "capability": "chat",
                "model": "deepseek/deepseek-chat",
            }
        )

        public_profile = service.get_profile(profile["profile_id"])

        assert public_profile["native_provider"] == "openrouter"
        assert public_profile["api_key_name"] == "OPENROUTER_API_KEY"
    finally:
        service.close()


def test_paused_source_marks_child_profiles_unavailable(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Gateway",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "Gateway Chat",
                "capability": "chat",
                "model": "demo-model",
            }
        )

        service.update_source(source["source_id"], {"enabled": False})
        paused_profile = service.get_profile(profile["profile_id"])

        assert paused_profile["enabled"] is False
        assert paused_profile["profile_enabled"] is True
        assert paused_profile["source_enabled"] is False

        service.update_source(source["source_id"], {"enabled": True})
        assert service.get_profile(profile["profile_id"])["enabled"] is True
    finally:
        service.close()


def test_model_profile_test_updates_status(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    profile = service.create_profile(
        {
            "name": "Runnable",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *_args, **_kwargs: "OK")
    try:
        result = service.test_profile(profile["profile_id"])
        tested = service.get_profile(profile["profile_id"])

        assert result["ok"] is True
        assert tested["status"] == "available"
        assert tested["last_tested_at"]
    finally:
        service.close()


def test_model_profile_test_records_credential_access_failure(tmp_path):
    service = ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=_FailingReadCredentialStore(),
    )
    source = service.create_source(
        {
            "name": "Unavailable Keychain",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-secret",
        }
    )
    profile = service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "Unavailable Keychain Chat",
            "capability": "chat",
            "model": "demo-model",
        }
    )
    try:
        result = service.test_profile(profile["profile_id"])
        tested_profile = service.get_profile(profile["profile_id"])
        tested_source = service.get_source(source["source_id"])

        assert result["ok"] is False
        assert result["success"] is False
        assert result["failure_stage"] == "credential_access"
        assert "模型凭据不可访问" in result["message"]
        assert "OSStatus -25293" in result["message"]
        assert tested_profile["status"] == "failed"
        assert tested_profile["last_error"] == result["message"]
        assert tested_source["status"] == "failed"
        assert tested_source["last_error"] == result["message"]
        assert "sk-secret" not in repr(result)
        assert "sk-read-secret123456" not in repr(result)
    finally:
        service.close()


def test_openai_compatible_chat_reads_reasoning_content_and_xiaomi_api_key_header(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "", "reasoning_content": "red, blue"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer sk-xiaomi"
        assert request.get_header("Api-key") == "sk-xiaomi"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    result = openai_compatible_chat(
        "https://token-plan-cn.xiaomimimo.com/v1",
        "mimo-v2-omni",
        "sk-xiaomi",
        [{"role": "user", "content": "hello"}],
    )

    assert result == "red, blue"


def test_openai_compatible_chat_skips_reasoning_content_parts(monkeypatch):
    private_reasoning = "private non-stream reasoning"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "reasoning", "text": {"value": private_reasoning}},
                                    {"type": "text", "text": {"value": "visible answer"}},
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", lambda *_args, **_kwargs: FakeResponse())

    result = openai_compatible_chat(
        "https://api.example.test/v1",
        "demo-model",
        "sk-demo",
        [{"role": "user", "content": "hello"}],
    )

    assert result == "visible answer"
    assert private_reasoning not in result


def test_openai_compatible_chat_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", raising=False)
    assert OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS == 180
    assert read_openai_compatible_chat_timeout() == 180

    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "240.5")
    assert read_openai_compatible_chat_timeout() == 240.5

    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "invalid")
    assert read_openai_compatible_chat_timeout() == 180


def test_openai_compatible_chat_timeout_error_reports_limit(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_MODEL_TIMEOUT_SECONDS", "12")
    monkeypatch.setattr(
        "apps.shell.model_profiles.urlrequest.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("read operation timed out")),
    )

    with pytest.raises(ModelProfileError, match="等待响应超过 12 秒"):
        openai_compatible_chat(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
        )


def test_openai_compatible_chat_message_returns_tool_calls(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "workspace_read", "arguments": "{\"path\":\"README.md\"}"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert body["tools"][0]["function"]["name"] == "workspace_read"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    message = openai_compatible_chat_message(
        "https://api.example.test/v1",
        "demo-model",
        "sk-demo",
        [{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "workspace_read", "parameters": {"type": "object"}}}],
    )

    assert message["tool_calls"][0]["function"]["name"] == "workspace_read"


def test_openai_compatible_chat_message_streams_sse_chunks(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                b'"type":"function","function":{"name":"workspace_read","arguments":"{}"}}]}}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert body["stream"] is True
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert chunks[0]["choices"][0]["delta"]["content"] == "hello "
    assert chunks[1]["choices"][0]["delta"]["content"] == "world"
    assert chunks[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "workspace_read"


def test_openai_compatible_chat_message_streams_legacy_function_call_sse(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"checking "}}]}\n\n'
            yield (
                b'data: {"choices":[{"delta":{"function_call":'
                b'{"name":"workspace_","arguments":"{\\"path\\":\\"READ"}}}]}\n\n'
            )
            yield (
                b'data: {"choices":[{"delta":{"function_call":'
                b'{"name":"read","arguments":"ME.md\\"}"}},'
                b'"finish_reason":"function_call"}]}\n\n'
            )
            yield b"data: [DONE]\n\n"

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert chunks[0]["choices"][0]["delta"]["content"] == "checking "
    assert chunks[1]["choices"][0]["delta"]["function_call"]["name"] == "workspace_"
    assert chunks[1]["choices"][0]["delta"]["function_call"]["arguments"] == '{"path":"READ'
    assert chunks[2]["choices"][0]["delta"]["function_call"]["name"] == "read"
    assert chunks[2]["choices"][0]["delta"]["function_call"]["arguments"] == 'ME.md"}'
    assert chunks[2]["choices"][0]["finish_reason"] == "function_call"


def test_openai_compatible_chat_message_streams_coalesced_sse_frames(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"choices": [{"delta": {"content": "hello "}}]})
            second = json.dumps({"choices": [{"delta": {"content": "world"}}]})
            yield f": keepalive\n\ndata: {first}\n\ndata: {second}\n\ndata: [DONE]\n\n".encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["hello ", "world"]


def test_openai_compatible_chat_message_stream_ignores_control_events(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"choices": [{"delta": {"content": "control "}}]})
            second = json.dumps({"choices": [{"delta": {"content": "ignored"}}]})
            yield (
                b"event: ping\n"
                b'data: {"type":"ping"}\n\n'
                b'data: {"type":"heartbeat","created":123}\n\n'
                b'data: {"object":"keepalive"}\n\n'
                + f"data: {first}\n\n".encode("utf-8")
                + b'event: heartbeat\n'
                + f"data: {second}\n\n".encode("utf-8")
                + b"data: [DONE]\n\n"
            )

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["control ", "ignored"]


def test_openai_compatible_chat_message_streams_multiline_sse_data_event(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield (
                b"id: chunk-1\r\n"
                b"event: completion.chunk\r\n"
                b'data: {"choices":[{"delta":{"content":"multi line"}\r\n'
                b'data: ,"finish_reason":"stop"}]}\r\n\r\n'
                b"data: [DONE]\r\n\r\n"
            )

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert len(chunks) == 1
    assert chunks[0]["choices"][0]["delta"]["content"] == "multi line"
    assert chunks[0]["choices"][0]["finish_reason"] == "stop"


def test_openai_compatible_chat_message_streams_split_sse_frame_chunks(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            payload = json.dumps({"choices": [{"delta": {"content": "split frame"}}]})
            frame = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
            yield frame[:9]
            yield frame[9:31]
            yield frame[31:52]
            yield frame[52:]

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["split frame"]


def test_openai_compatible_chat_message_streams_split_utf8_sse_frame_chunks(monkeypatch):
    expected = "跨块文本"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            payload = json.dumps({"choices": [{"delta": {"content": expected}}]}, ensure_ascii=False)
            frame = f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
            split_at = frame.index("跨".encode("utf-8")) + 1
            yield frame[:split_at]
            yield frame[split_at : split_at + 2]
            yield frame[split_at + 2 :]

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    chunks = list(
        openai_compatible_chat_message(
            "https://api.example.test/v1",
            "demo-model",
            "sk-demo",
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == [expected]
    assert "\ufffd" not in json.dumps(chunks, ensure_ascii=False)


def test_openai_compatible_chat_message_stream_raises_provider_error(monkeypatch):
    leaked_secret = "sk-stream-provider-error123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield (
                "data: "
                + json.dumps(
                    {
                        "error": {
                            "message": f"upstream rejected api_key={leaked_secret}",
                            "type": "invalid_request_error",
                            "code": "bad_api_key",
                        }
                    }
                )
                + "\n\n"
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    with pytest.raises(ModelProfileError) as excinfo:
        list(
            openai_compatible_chat_message(
                "https://api.example.test/v1",
                "demo-model",
                "sk-demo",
                [{"role": "user", "content": "hello"}],
                stream=True,
            )
        )

    error_text = str(excinfo.value)
    assert "OpenAI-compatible Profile 调用失败" in error_text
    assert "invalid_request_error" in error_text
    assert "bad_api_key" in error_text
    assert leaked_secret not in error_text
    assert "[redacted]" in error_text


@pytest.mark.parametrize(
    "error_frame",
    [
        "event: error\n"
        'data: {"message":"gateway rejected api_key=sk-stream-event-error123456","code":"bad_api_key"}\n\n',
        'data: {"type":"error","message":"gateway rejected api_key=sk-stream-event-error123456","code":"bad_api_key"}\n\n',
    ],
)
def test_openai_compatible_chat_message_stream_raises_provider_error_event(monkeypatch, error_frame):
    leaked_secret = "sk-stream-event-error123456"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield error_frame.encode("utf-8")

    def fake_urlopen(request, timeout, context):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert timeout == OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS
        assert isinstance(context, ssl.SSLContext)
        assert request.get_header("Accept") == "text/event-stream"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)

    with pytest.raises(ModelProfileError) as excinfo:
        list(
            openai_compatible_chat_message(
                "https://api.example.test/v1",
                "demo-model",
                "sk-demo",
                [{"role": "user", "content": "hello"}],
                stream=True,
            )
        )

    error_text = str(excinfo.value)
    assert "OpenAI-compatible Profile 调用失败" in error_text
    assert "bad_api_key" in error_text
    assert leaked_secret not in error_text
    assert "[redacted]" in error_text


def test_test_and_save_profile_failure_does_not_persist(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Gateway",
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-secret",
        }
    )

    def fail_chat(*_args, **_kwargs):
        raise ModelProfileError("network failed")

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fail_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {"name": "Draft", "capability": "chat", "model": "demo-model"},
        )

        assert result["ok"] is False
        assert result["source"]["status"] == "failed"
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


@pytest.mark.parametrize("model_succeeds", [True, False], ids=["success", "failure"])
def test_test_and_save_profile_discards_stale_result_after_source_key_rotation(
    monkeypatch,
    tmp_path,
    model_succeeds: bool,
):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Rotating Gateway",
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-old-draft-generation123456",
        }
    )
    profile = service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "Existing Draft",
            "capability": "chat",
            "model": "current-model",
        }
    )
    request_started = threading.Event()
    release_request = threading.Event()
    used_api_keys: list[str] = []
    results: list[dict] = []
    errors: list[BaseException] = []

    def blocking_chat(
        _base_url: str,
        _model: str,
        api_key: str,
        _messages: list[dict],
    ) -> str:
        used_api_keys.append(api_key)
        request_started.set()
        if not release_request.wait(timeout=5):
            raise AssertionError("test did not release the fake model request")
        if not model_succeeds:
            raise ModelProfileError("network failed")
        return "OK"

    monkeypatch.setattr(
        "apps.shell.model_profiles.openai_compatible_chat",
        blocking_chat,
    )

    def test_and_save() -> None:
        try:
            results.append(
                service.test_and_save_profile(
                    source["source_id"],
                    {
                        "profile_id": profile["profile_id"],
                        "name": "Existing Draft",
                        "capability": "chat",
                        "model": "stale-draft-model",
                    },
                )
            )
        except BaseException as exc:  # surfaced on the main test thread below
            errors.append(exc)

    worker = threading.Thread(target=test_and_save)
    try:
        worker.start()
        assert request_started.wait(timeout=1)
        service.update_source(
            source["source_id"],
            {"api_key": "sk-source-new-draft-generation123456"},
        )
    finally:
        release_request.set()
        worker.join(timeout=2)

    try:
        assert not worker.is_alive()
        assert errors == []
        assert used_api_keys == ["sk-source-old-draft-generation123456"]
        assert len(results) == 1
        assert results[0]["ok"] is False
        assert results[0]["stale_result"] is True
        assert "配置" in results[0]["message"]
        assert "变化" in results[0]["message"]
        assert (
            "重测" in results[0]["message"]
            or "重新测试" in results[0]["message"]
        )

        current_source = service.get_source(source["source_id"])
        current_profile = service.get_profile(profile["profile_id"])
        assert current_source["status"] == "untested"
        assert current_profile["status"] == "untested"
        assert current_profile["model"] == "current-model"
    finally:
        service.close()


def test_vision_profile_rejects_model_that_fails_real_image_test(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "capability": "vision",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "OK")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Text Only",
                "capability": "vision",
                "model": "qwen/qwen3-coder",
                "options": {"remote_model": {"id": "qwen/qwen3-coder", "input_modalities": ["text"]}},
            },
        )

        assert result["ok"] is False
        assert "真实图片测试" in result["message"]
        assert calls
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_vision_profile_test_uses_image_payload_and_saves(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "capability": "vision",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []

    def fake_chat(base_url, model, api_key, messages):
        calls.append((base_url, model, api_key, messages))
        return "red, blue"

    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fake_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Vision",
                "capability": "vision",
                "model": "openai/gpt-4.1-mini",
                "options": {
                    "remote_model": {
                        "id": "openai/gpt-4.1-mini",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    }
                },
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert service.get_source(source["source_id"])["status"] == "available"
        assert result["profile"]["options"]["remote_model"]["input_modalities"] == ["text", "image"]
        assert calls[0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_vision_profile_can_pass_without_remote_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles._vision_test_challenge", _vision_challenge)
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "left red, right blue")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "MiMo Vision",
                "capability": "vision",
                "model": "mimo-v2.5",
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert result["profile"]["capability"] == "vision"
        assert calls[0][0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_xiaomi_text_reasoning_model_is_not_saved_as_vision(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://api.mimo-v2.com/v1",
            "api_key": "sk-source-secret",
        }
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("known text-only Xiaomi model should be rejected before HTTP probing")

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fail_if_called)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "MiMo Pro Vision",
                "capability": "vision",
                "model": "mimo-v2.5-pro",
            },
        )

        assert result["ok"] is False
        assert "文本/推理模型" in result["message"]
        assert result["vision_capability"]["recommended_vision_models"] == ["mimo-v2.5", "mimo-v2-omni"]
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_fetch_source_models_reads_openai_compatible_list(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "DeepSeek",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-source-secret",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-reasoner"},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://api.deepseek.com/models"
        assert request.get_header("Authorization") == "Bearer sk-source-secret"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])

        assert result["ok"] is True
        assert result["count"] == 2
        assert result["models"] == [
            {"id": "deepseek-chat", "owned_by": "deepseek", "provider_key": "deepseek"},
            {"id": "deepseek-reasoner", "owned_by": "", "provider_key": "deepseek"},
        ]
        assert "api_key" not in result["source"]
    finally:
        service.close()


def test_fetch_xiaomi_models_marks_known_vision_capabilities(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "capability": "vision",
            "provider": "xiaomi",
            "base_url": "https://api.mimo-v2.com/v1",
            "api_key": "sk-source-secret",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "mimo-v2.5-pro"},
                        {"id": "mimo-v2.5"},
                        {"id": "mimo-v2-omni"},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://api.mimo-v2.com/v1/models"
        assert request.get_header("Authorization") == "Bearer sk-source-secret"
        assert request.get_header("Api-key") == "sk-source-secret"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])
        by_id = {model["id"]: model for model in result["models"]}

        assert by_id["mimo-v2.5-pro"]["known_capability"] == "text"
        assert by_id["mimo-v2.5-pro"]["not_recommended_for"] == ["vision"]
        assert by_id["mimo-v2.5"]["known_capability"] == "vision"
        assert by_id["mimo-v2.5"]["recommended_for"] == ["vision"]
        assert by_id["mimo-v2-omni"]["known_capability"] == "vision"
    finally:
        service.close()


def test_fetch_source_models_preserves_openrouter_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {
                            "id": "qwen/qwen3-coder",
                            "canonical_slug": "qwen/qwen3-coder",
                            "name": "Qwen: Qwen3 Coder",
                            "context_length": 262144,
                            "architecture": {
                                "modality": "text->text",
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                            },
                            "pricing": {"prompt": "0", "completion": "0"},
                            "top_provider": {"max_completion_tokens": 65536, "is_moderated": False},
                            "supported_parameters": ["tools", "structured_outputs"],
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://openrouter.ai/api/v1/models"
        assert request.get_header("Authorization") is None
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])
        model = result["models"][0]

        assert model["provider_key"] == "qwen"
        assert model["name"] == "Qwen: Qwen3 Coder"
        assert model["context_length"] == 262144
        assert model["max_completion_tokens"] == 65536
        assert model["input_modalities"] == ["text"]
        assert model["supported_parameters"] == ["tools", "structured_outputs"]
        assert model["is_free"] is True
    finally:
        service.close()


def test_agent_runtime_uses_model_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    profile = profile_service.create_profile(
        {
            "name": "Agent Profile",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Profile result"})
    try:
        agent = runtime.create_agent(
            {
                "name": "Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "Profile result"
    finally:
        runtime.close()
        profile_service.close()


def test_agent_runtime_uses_openai_compatible_provider_source_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    source = profile_service.create_source(
        {
            "name": "Xiaomi MiMo",
            "provider": "xiaomi_mimo",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-secret",
        }
    )
    profile = profile_service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "MiMo Agent",
            "capability": "chat",
            "model": "mimo-v2.5-pro",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "MiMo result"})
    try:
        agent = runtime.create_agent(
            {
                "name": "MiMo Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "MiMo result"
    finally:
        runtime.close()
        profile_service.close()
