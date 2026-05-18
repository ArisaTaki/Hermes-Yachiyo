"""Reusable model profile storage and validation.

Model profiles are shared configuration records for Agent Studio, Workflow
Studio, and the app-level model configuration page. Secrets stay in the local
backend database; public payloads only expose configured state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4


class ModelProfileError(RuntimeError):
    """Raised when a model profile operation cannot be completed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hermes_yachiyo_home() -> Path:
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    root = Path(hermes_home) / "yachiyo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _profile_id() -> str:
    return f"profile_{uuid4().hex[:12]}"


def _source_id() -> str:
    return f"source_{uuid4().hex[:12]}"


def _normalize_capability(value: str) -> str:
    capability = (value or "chat").strip().lower()
    if capability not in {"chat", "vision", "tts"}:
        raise ModelProfileError("Profile capability 必须是 chat、vision 或 tts")
    return capability


class ModelProfileService:
    """Persistent model profile registry."""

    def __init__(self, db_path: Path | str | None = None, workspace_dir: Path | str | None = None) -> None:
        root = Path(workspace_dir) if workspace_dir is not None else _hermes_yachiyo_home()
        root.mkdir(parents=True, exist_ok=True)
        self.workspace_dir = root
        self.db_path = Path(db_path) if db_path is not None else root / "model-profiles.db"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self) -> None:
        self._conn.close()

    def _init_db(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS model_sources (
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
            CREATE TABLE IF NOT EXISTS model_profiles (
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
            CREATE TABLE IF NOT EXISTS model_profile_defaults (
                capability TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self._ensure_columns()
        self._conn.commit()

    def _ensure_columns(self) -> None:
        columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(model_profiles)").fetchall()}
        if "source_id" not in columns:
            self._conn.execute("ALTER TABLE model_profiles ADD COLUMN source_id TEXT NOT NULL DEFAULT ''")

    def _row_to_source(self, row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        source = {
            "source_id": row["source_id"],
            "name": row["name"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "api_key_configured": bool(row["api_key"]),
            "options": _json_load(row["options_json"], {}),
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "last_tested_at": row["last_tested_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_secret:
            source["api_key"] = row["api_key"]
        return source

    def _row_to_profile(self, row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        source = None
        if row["source_id"]:
            source_row = self._conn.execute(
                "SELECT * FROM model_sources WHERE source_id=?",
                (row["source_id"],),
            ).fetchone()
            if source_row is not None:
                source = self._row_to_source(source_row, include_secret=include_secret)
        profile = {
            "profile_id": row["profile_id"],
            "source_id": row["source_id"],
            "name": row["name"],
            "capability": row["capability"],
            "provider": source["provider"] if source else row["provider"],
            "base_url": source["base_url"] if source else row["base_url"],
            "model": row["model"],
            "api_key_configured": bool(source.get("api_key") or source.get("api_key_configured")) if source else bool(row["api_key"]),
            "source_name": source["name"] if source else "",
            "source_provider": source["provider"] if source else "",
            "options": _json_load(row["options_json"], {}),
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "last_tested_at": row["last_tested_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_secret:
            profile["api_key"] = source.get("api_key", "") if source else row["api_key"]
        return profile

    def list_profiles(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM model_profiles ORDER BY capability, name"
        ).fetchall()
        return {
            "ok": True,
            "sources": self.list_sources()["sources"],
            "profiles": [self._row_to_profile(row) for row in rows],
            "defaults": self.get_defaults(),
        }

    def list_sources(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM model_sources ORDER BY name"
        ).fetchall()
        sources = []
        for row in rows:
            source = self._row_to_source(row)
            source["models"] = self.list_source_profiles(source["source_id"])["profiles"]
            sources.append(source)
        return {"ok": True, "sources": sources}

    def create_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ModelProfileError("提供商源名称不能为空")
        now = _now()
        source_id = str(payload.get("source_id") or _source_id())
        self._conn.execute(
            """
            INSERT INTO model_sources (
                source_id, name, provider, base_url, api_key, options_json,
                enabled, status, last_tested_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                name,
                str(payload.get("provider") or "openai_compatible"),
                str(payload.get("base_url") or ""),
                str(payload.get("api_key") or ""),
                _json_dump(payload.get("options") or {}),
                1 if payload.get("enabled", True) else 0,
                "untested",
                "",
                "",
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM model_sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        source = self._row_to_source(row)
        source["models"] = self.list_source_profiles(source_id)["profiles"]
        return source

    def get_source_private(self, source_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM model_sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        source = self._row_to_source(row, include_secret=True)
        source["models"] = self.list_source_profiles(source_id)["profiles"]
        return source

    def update_source(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_source_private(source_id)
        next_source = {**current, **{key: value for key, value in payload.items() if key != "api_key"}}
        api_key = str(current.get("api_key") or "")
        if "api_key" in payload and str(payload.get("api_key") or "").strip():
            api_key = str(payload.get("api_key") or "").strip()
        now = _now()
        self._conn.execute(
            """
            UPDATE model_sources
               SET name=?, provider=?, base_url=?, api_key=?, options_json=?, enabled=?, updated_at=?
             WHERE source_id=?
            """,
            (
                str(next_source.get("name") or "").strip(),
                str(next_source.get("provider") or "openai_compatible"),
                str(next_source.get("base_url") or ""),
                api_key,
                _json_dump(next_source.get("options") or {}),
                1 if next_source.get("enabled", True) else 0,
                now,
                source_id,
            ),
        )
        self._conn.commit()
        return self.get_source(source_id)

    def delete_source(self, source_id: str) -> dict[str, Any]:
        model_ids = [
            str(row["profile_id"])
            for row in self._conn.execute("SELECT profile_id FROM model_profiles WHERE source_id=?", (source_id,)).fetchall()
        ]
        self._conn.execute("DELETE FROM model_sources WHERE source_id=?", (source_id,))
        self._conn.execute("DELETE FROM model_profiles WHERE source_id=?", (source_id,))
        for profile_id in model_ids:
            self._conn.execute("UPDATE model_profile_defaults SET profile_id='' WHERE profile_id=?", (profile_id,))
        self._conn.commit()
        return {"ok": True}

    def list_source_profiles(self, source_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT * FROM model_profiles WHERE source_id=? ORDER BY capability, name",
            (source_id,),
        ).fetchall()
        return {"ok": True, "profiles": [self._row_to_profile(row) for row in rows]}

    def test_source(self, source_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        source = self.get_source_private(source_id)
        provider = str(source.get("provider") or "openai_compatible")
        model = str((payload or {}).get("model") or "").strip()
        if not model:
            first = self._conn.execute(
                "SELECT model FROM model_profiles WHERE source_id=? AND capability IN ('chat', 'vision') ORDER BY capability, name LIMIT 1",
                (source_id,),
            ).fetchone()
            model = str(first["model"]) if first is not None else ""
        if provider != "openai_compatible":
            return self._record_source_test_result(
                source_id,
                ok=False,
                message="首版仅支持 OpenAI-compatible 提供商源的自动测试。",
            )
        missing = [
            key
            for key, value in (
                ("base_url", source.get("base_url")),
                ("api_key", source.get("api_key")),
                ("model", model),
            )
            if not str(value or "").strip()
        ]
        if missing:
            return self._record_source_test_result(
                source_id,
                ok=False,
                message="提供商源测试配置不完整。",
                extra={"missing": missing},
            )
        started = time.time()
        try:
            result = openai_compatible_chat(
                str(source["base_url"]).rstrip("/"),
                model,
                str(source["api_key"]),
                [{"role": "user", "content": "Reply with OK."}],
            )
        except ModelProfileError as exc:
            return self._record_source_test_result(source_id, ok=False, message=str(exc))
        return self._record_source_test_result(
            source_id,
            ok=True,
            message=result[:500] or "OK",
            extra={"latency_ms": int((time.time() - started) * 1000)},
        )

    def _record_source_test_result(
        self,
        source_id: str,
        *,
        ok: bool,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tested_at = _now()
        self._conn.execute(
            """
            UPDATE model_sources
               SET status=?, last_tested_at=?, last_error=?, updated_at=?
             WHERE source_id=?
            """,
            ("available" if ok else "failed", tested_at, "" if ok else message, tested_at, source_id),
        )
        self._conn.commit()
        payload = {"ok": ok, "success": ok, "message": message, "source": self.get_source(source_id)}
        if extra:
            payload.update(extra)
        return payload

    def get_defaults(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT capability, profile_id FROM model_profile_defaults").fetchall()
        defaults = {str(row["capability"]): str(row["profile_id"]) for row in rows}
        for capability in ("chat", "vision", "tts"):
            defaults.setdefault(capability, "")
        return defaults

    def set_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        for capability in ("chat", "vision", "tts"):
            if capability not in payload:
                continue
            profile_id = str(payload.get(capability) or "").strip()
            if profile_id:
                profile = self.get_profile(profile_id)
                if profile["capability"] != capability:
                    raise ModelProfileError(f"{capability} 默认 Profile 类型不匹配")
            self._conn.execute(
                """
                INSERT INTO model_profile_defaults (capability, profile_id)
                VALUES (?, ?)
                ON CONFLICT(capability) DO UPDATE SET profile_id=excluded.profile_id
                """,
                (capability, profile_id),
            )
        self._conn.commit()
        return {"ok": True, "defaults": self.get_defaults()}

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ModelProfileError("Profile 名称不能为空")
        capability = _normalize_capability(str(payload.get("capability") or "chat"))
        source_id = str(payload.get("source_id") or "").strip()
        if source_id:
            self.get_source(source_id)
        now = _now()
        profile_id = str(payload.get("profile_id") or _profile_id())
        self._conn.execute(
            """
            INSERT INTO model_profiles (
                profile_id, source_id, name, capability, provider, base_url, model, api_key,
                options_json, enabled, status, last_tested_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                source_id,
                name,
                capability,
                str(payload.get("provider") or "openai_compatible"),
                str(payload.get("base_url") or ""),
                str(payload.get("model") or ""),
                "" if source_id else str(payload.get("api_key") or ""),
                _json_dump(payload.get("options") or {}),
                1 if payload.get("enabled", True) else 0,
                "untested",
                "",
                "",
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_profile(profile_id)

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM model_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError(profile_id)
        return self._row_to_profile(row)

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM model_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError(profile_id)
        return self._row_to_profile(row, include_secret=True)

    def update_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_profile_private(profile_id)
        next_profile = {**current, **{key: value for key, value in payload.items() if key != "api_key"}}
        if "capability" in payload:
            next_profile["capability"] = _normalize_capability(str(payload.get("capability") or "chat"))
        if "source_id" in payload and str(payload.get("source_id") or "").strip():
            self.get_source(str(payload.get("source_id") or "").strip())
        next_source_id = str(next_profile.get("source_id") or "")
        api_key = "" if next_source_id else str(current.get("api_key") or "")
        if not next_source_id and "api_key" in payload and str(payload.get("api_key") or "").strip():
            api_key = str(payload.get("api_key") or "").strip()
        now = _now()
        self._conn.execute(
            """
            UPDATE model_profiles
               SET source_id=?, name=?, capability=?, provider=?, base_url=?, model=?, api_key=?,
                   options_json=?, enabled=?, updated_at=?
             WHERE profile_id=?
            """,
            (
                str(next_profile.get("source_id") or ""),
                str(next_profile.get("name") or "").strip(),
                str(next_profile.get("capability") or "chat"),
                str(next_profile.get("provider") or "openai_compatible"),
                str(next_profile.get("base_url") or ""),
                str(next_profile.get("model") or ""),
                api_key,
                _json_dump(next_profile.get("options") or {}),
                1 if next_profile.get("enabled", True) else 0,
                now,
                profile_id,
            ),
        )
        self._conn.commit()
        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: str) -> dict[str, Any]:
        self._conn.execute("DELETE FROM model_profiles WHERE profile_id=?", (profile_id,))
        self._conn.execute(
            "UPDATE model_profile_defaults SET profile_id='' WHERE profile_id=?",
            (profile_id,),
        )
        self._conn.commit()
        return {"ok": True}

    def test_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_profile_private(profile_id)
        capability = str(profile.get("capability") or "chat")
        provider = str(profile.get("provider") or "openai_compatible")
        if provider != "openai_compatible":
            return self._record_test_result(
                profile_id,
                ok=False,
                message="首版仅支持 OpenAI-compatible Profile 的自动测试。",
            )
        if capability == "tts":
            return self._record_test_result(
                profile_id,
                ok=False,
                message="TTS Profile 首版只做保存与复用，连接测试会在 TTS 专用链路中补齐。",
            )
        missing = [
            key
            for key in ("base_url", "model", "api_key")
            if not str(profile.get(key) or "").strip()
        ]
        if missing:
            return self._record_test_result(
                profile_id,
                ok=False,
                message="Profile 配置不完整。",
                extra={"missing": missing},
            )
        started = time.time()
        try:
            result = openai_compatible_chat(
                str(profile["base_url"]).rstrip("/"),
                str(profile["model"]),
                str(profile["api_key"]),
                [{"role": "user", "content": "Reply with OK."}],
            )
        except ModelProfileError as exc:
            return self._record_test_result(profile_id, ok=False, message=str(exc))
        return self._record_test_result(
            profile_id,
            ok=True,
            message=result[:500] or "OK",
            extra={"latency_ms": int((time.time() - started) * 1000)},
        )

    def _record_test_result(
        self,
        profile_id: str,
        *,
        ok: bool,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tested_at = _now()
        self._conn.execute(
            """
            UPDATE model_profiles
               SET status=?, last_tested_at=?, last_error=?, updated_at=?
             WHERE profile_id=?
            """,
            ("available" if ok else "failed", tested_at, "" if ok else message, tested_at, profile_id),
        )
        self._conn.commit()
        payload = {"ok": ok, "success": ok, "message": message, "profile": self.get_profile(profile_id)}
        if extra:
            payload.update(extra)
        return payload


def openai_compatible_chat(base_url: str, model: str, api_key: str, messages: list[dict[str, str]]) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8")
    request = urlrequest.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urlrequest.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ModelProfileError(f"OpenAI-compatible Profile 调用失败：{exc}") from exc
    return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")


_model_profile_service: ModelProfileService | None = None


def get_model_profile_service() -> ModelProfileService:
    global _model_profile_service
    if _model_profile_service is None:
        _model_profile_service = ModelProfileService()
    return _model_profile_service
