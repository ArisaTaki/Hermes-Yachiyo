"""Reusable model profile storage and validation.

Model profiles are shared configuration records for Agent Studio, Workflow
Studio, and the app-level model configuration page. Secrets stay in the local
backend database; public payloads only expose configured state.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

from apps.shell.model_provider_adapters import resolve_provider_adapter


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


_OPENAI_COMPATIBLE_PROVIDER_IDS = {
    "openai",
    "openai-compatible",
    "openai_compatible",
    "alibaba",
    "alibaba-coding-plan",
    "google_gemini",
    "gemini",
    "qwen_dashscope",
    "dashscope",
    "custom",
    "minimax",
    "minimax-cn",
    "moonshot",
    "kimi",
    "kimi-coding",
    "kimi-coding-cn",
    "kimi_coding_plan",
    "openrouter",
    "xai",
    "deepseek",
    "zhipu",
    "volcengine_doubao",
    "doubao",
    "tencent_hunyuan",
    "hunyuan",
    "baidu_qianfan",
    "qianfan",
    "baichuan",
    "stepfun",
    "tencent-tokenhub",
    "siliconflow",
    "modelscope",
    "sensenova",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "mistral",
    "nvidia",
    "302ai",
    "ollama",
    "lm_studio",
    "lmstudio",
    "aihubmix",
    "ppio",
    "tokenpony",
    "compshare",
    "fastgpt",
    "xiaomi",
    "xiaomi_mimo",
    "mimo",
}


def _supports_openai_compatible_api(provider: str) -> bool:
    provider_id = (provider or "openai_compatible").strip().lower()
    return not provider_id or provider_id in _OPENAI_COMPATIBLE_PROVIDER_IDS


def supports_openai_compatible_api(provider: str) -> bool:
    return _supports_openai_compatible_api(provider)


def _remote_model_provider_key(model_id: str, owned_by: str, fallback_provider: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lstrip("~")
    if owned_by:
        return owned_by.strip().lstrip("~")
    return str(fallback_provider or "openai_compatible").strip().lstrip("~")


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _pricing_is_free(pricing: dict[str, Any]) -> bool:
    if not pricing:
        return False
    try:
        return float(str(pricing.get("prompt", "0") or "0")) == 0 and float(str(pricing.get("completion", "0") or "0")) == 0
    except ValueError:
        return False


_VISION_TEST_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP8z8AARQAFAAH/AS7x7fqQAAAAAElFTkSuQmCC"
)


def _remote_model_from_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    remote_model = options.get("remote_model")
    return remote_model if isinstance(remote_model, dict) else {}


def _remote_model_supports_vision(remote_model: dict[str, Any], model_id: str) -> bool:
    if not remote_model:
        return False
    remote_id = str(remote_model.get("id") or remote_model.get("model") or "").strip()
    if remote_id and remote_id != model_id:
        return False
    input_modalities = {
        str(item).strip().lower()
        for item in remote_model.get("input_modalities", [])
        if str(item).strip()
    }
    modality = str(remote_model.get("modality") or "").strip().lower()
    return "image" in input_modalities or bool(re.search(r"\bimage\b|vision|multimodal", modality))


def _vision_test_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What color is the solid square in this image? Reply with exactly one English color word."},
                {"type": "image_url", "image_url": {"url": _VISION_TEST_IMAGE_DATA_URL}},
            ],
        }
    ]


def _vision_test_passed(response: str) -> bool:
    text = str(response or "").strip().lower()
    return bool(re.search(r"\bred\b|红色|红", text))


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
                name TEXT NOT NULL,
                capability TEXT NOT NULL DEFAULT 'chat',
                provider TEXT NOT NULL DEFAULT 'openai_compatible',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'untested',
                last_tested_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(capability, name)
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
        self._ensure_source_schema()

    def _ensure_source_schema(self) -> None:
        columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(model_sources)").fetchall()}
        table = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='model_sources'"
        ).fetchone()
        table_sql = str(table["sql"] if table is not None else "")
        if "capability" in columns and "name TEXT NOT NULL UNIQUE" not in table_sql:
            return

        legacy_table = f"model_sources_legacy_{uuid4().hex[:8]}"
        self._conn.execute(f"ALTER TABLE model_sources RENAME TO {legacy_table}")
        self._conn.execute(
            """
            CREATE TABLE model_sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                capability TEXT NOT NULL DEFAULT 'chat',
                provider TEXT NOT NULL DEFAULT 'openai_compatible',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                options_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'untested',
                last_tested_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(capability, name)
            );
            """
        )

        legacy_rows = self._conn.execute(f"SELECT * FROM {legacy_table} ORDER BY name").fetchall()
        used_names: set[tuple[str, str]] = set()
        legacy_columns = {str(row["name"]) for row in self._conn.execute(f"PRAGMA table_info({legacy_table})").fetchall()}
        for row in legacy_rows:
            source_id = str(row["source_id"])
            profile_caps = [
                str(item["capability"])
                for item in self._conn.execute(
                    """
                    SELECT DISTINCT capability
                      FROM model_profiles
                     WHERE source_id=?
                     ORDER BY CASE capability WHEN 'chat' THEN 0 WHEN 'vision' THEN 1 WHEN 'tts' THEN 2 ELSE 3 END
                    """,
                    (source_id,),
                ).fetchall()
            ]
            has_legacy_capability = "capability" in legacy_columns
            legacy_capability = _normalize_capability(str(row["capability"])) if has_legacy_capability else "chat"
            capabilities = profile_caps or [legacy_capability]
            if has_legacy_capability and legacy_capability not in capabilities:
                capabilities.insert(0, legacy_capability)
            for index, capability in enumerate(capabilities):
                next_source_id = source_id if index == 0 else f"{source_id}_{capability}"
                while self._conn.execute("SELECT 1 FROM model_sources WHERE source_id=?", (next_source_id,)).fetchone():
                    next_source_id = _source_id()
                name = self._unique_source_name(str(row["name"]), capability, used_names)
                self._conn.execute(
                    """
                    INSERT INTO model_sources (
                        source_id, name, capability, provider, base_url, api_key, options_json,
                        enabled, status, last_tested_at, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        next_source_id,
                        name,
                        capability,
                        str(row["provider"]),
                        str(row["base_url"]),
                        str(row["api_key"]),
                        str(row["options_json"]),
                        int(row["enabled"]),
                        str(row["status"]),
                        str(row["last_tested_at"]),
                        str(row["last_error"]),
                        str(row["created_at"]),
                        str(row["updated_at"]),
                    ),
                )
                if next_source_id != source_id:
                    self._conn.execute(
                        "UPDATE model_profiles SET source_id=? WHERE source_id=? AND capability=?",
                        (next_source_id, source_id, capability),
                    )
        self._conn.execute(f"DROP TABLE {legacy_table}")

    @staticmethod
    def _unique_source_name(name: str, capability: str, used_names: set[tuple[str, str]]) -> str:
        base = (name or capability).strip() or capability
        candidate = base
        index = 2
        key = (capability, candidate.lower())
        while key in used_names:
            candidate = f"{base} {index}"
            key = (capability, candidate.lower())
            index += 1
        used_names.add(key)
        return candidate

    def _row_to_source(self, row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        adapter = resolve_provider_adapter(row["provider"], row["base_url"])
        source = {
            "source_id": row["source_id"],
            "name": row["name"],
            "capability": row["capability"],
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
            "runtime": adapter,
            "runtime_scope": adapter["runtime_scope"],
            "hermes_provider": adapter["hermes_provider"],
            "can_use_as_hermes": adapter["can_use_as_hermes"],
            "api_key_name": adapter["api_key_name"],
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
        profile_enabled = bool(row["enabled"])
        source_enabled = bool(source.get("enabled", True)) if source else True
        adapter = resolve_provider_adapter(
            source["provider"] if source else row["provider"],
            source["base_url"] if source else row["base_url"],
            row["model"],
        )
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
            "enabled": profile_enabled and source_enabled,
            "profile_enabled": profile_enabled,
            "source_enabled": source_enabled,
            "status": row["status"],
            "last_tested_at": row["last_tested_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "runtime": adapter,
            "runtime_scope": adapter["runtime_scope"],
            "hermes_provider": adapter["hermes_provider"],
            "can_use_as_hermes": adapter["can_use_as_hermes"],
            "api_key_name": adapter["api_key_name"],
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
            "SELECT * FROM model_sources ORDER BY capability, name"
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
        capability = _normalize_capability(str(payload.get("capability") or "chat"))
        now = _now()
        source_id = str(payload.get("source_id") or _source_id())
        self._conn.execute(
            """
            INSERT INTO model_sources (
                source_id, name, capability, provider, base_url, api_key, options_json,
                enabled, status, last_tested_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                name,
                capability,
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
        if "capability" in payload:
            next_source["capability"] = _normalize_capability(str(payload.get("capability") or "chat"))
        next_capability = str(next_source.get("capability") or "chat")
        mismatched = self._conn.execute(
            "SELECT 1 FROM model_profiles WHERE source_id=? AND capability<>? LIMIT 1",
            (source_id, next_capability),
        ).fetchone()
        if mismatched is not None:
            raise ModelProfileError("提供商源类型不能与已登记模型类型不一致")
        api_key = str(current.get("api_key") or "")
        if "api_key" in payload and str(payload.get("api_key") or "").strip():
            api_key = str(payload.get("api_key") or "").strip()
        now = _now()
        self._conn.execute(
            """
            UPDATE model_sources
               SET name=?, capability=?, provider=?, base_url=?, api_key=?, options_json=?, enabled=?, updated_at=?
             WHERE source_id=?
            """,
            (
                str(next_source.get("name") or "").strip(),
                next_capability,
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
            "SELECT * FROM model_profiles WHERE source_id=? ORDER BY name",
            (source_id,),
        ).fetchall()
        return {"ok": True, "profiles": [self._row_to_profile(row) for row in rows]}

    def test_source(self, source_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        source = self.get_source_private(source_id)
        source_capability = str(source.get("capability") or "chat")
        if source_capability == "tts":
            return self._record_source_test_result(
                source_id,
                ok=False,
                message="TTS 提供商源使用语音专用链路测试，不走 OpenAI-compatible 模型测试。",
            )
        provider = str(source.get("provider") or "openai_compatible")
        model = str((payload or {}).get("model") or "").strip()
        if not model:
            first = self._conn.execute(
                "SELECT model FROM model_profiles WHERE source_id=? AND capability=? ORDER BY name LIMIT 1",
                (source_id, source_capability),
            ).fetchone()
            model = str(first["model"]) if first is not None else ""
        if not _supports_openai_compatible_api(provider):
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

    def fetch_source_models(self, source_id: str) -> dict[str, Any]:
        source = self.get_source_private(source_id)
        if str(source.get("capability") or "chat") == "tts":
            raise ModelProfileError("TTS 提供商源不支持从 /models 获取模型列表。")
        provider = str(source.get("provider") or "openai_compatible")
        if not _supports_openai_compatible_api(provider):
            raise ModelProfileError("当前提供商源暂不支持自动获取模型列表。")
        base_url = str(source.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise ModelProfileError("提供商源 Base URL 为空，无法获取模型列表。")
        models_url = f"{base_url}/models"
        headers = {"Accept": "application/json"}
        api_key = str(source.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urlrequest.Request(models_url, method="GET", headers=headers)
        try:
            with urlrequest.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelProfileError(f"获取模型列表失败：{exc}") from exc

        if isinstance(payload, dict):
            raw_models = payload.get("data")
            if raw_models is None:
                raw_models = payload.get("models")
        else:
            raw_models = payload
        if not isinstance(raw_models, list):
            raise ModelProfileError("模型列表响应格式无法识别。")

        models: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_models:
            if isinstance(item, str):
                model_id = item.strip()
                owned_by = ""
                display_name = ""
                model_info: dict[str, Any] = {}
            elif isinstance(item, dict):
                display_name = str(item.get("name") or "").strip()
                model_id = str(item.get("id") or item.get("model") or display_name or "").strip()
                owned_by = str(item.get("owned_by") or item.get("owner") or "").strip()
                architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
                top_provider = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
                pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
                context_length = _as_int(item.get("context_length")) or _as_int(top_provider.get("context_length"))
                max_completion_tokens = _as_int(top_provider.get("max_completion_tokens"))
                model_info = {
                    "canonical_slug": str(item.get("canonical_slug") or "").strip(),
                    "context_length": context_length,
                    "default_parameters": item.get("default_parameters") if isinstance(item.get("default_parameters"), dict) else {},
                    "description": str(item.get("description") or "").strip(),
                    "input_modalities": _as_string_list(architecture.get("input_modalities")),
                    "is_free": _pricing_is_free(pricing) if pricing else None,
                    "is_moderated": bool(top_provider.get("is_moderated")) if "is_moderated" in top_provider else None,
                    "max_completion_tokens": max_completion_tokens,
                    "modality": str(architecture.get("modality") or "").strip(),
                    "name": display_name,
                    "output_modalities": _as_string_list(architecture.get("output_modalities")),
                    "pricing": pricing,
                    "supported_parameters": _as_string_list(item.get("supported_parameters")),
                }
            else:
                continue
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            model = {
                "id": model_id,
                "owned_by": owned_by,
                "provider_key": _remote_model_provider_key(model_id, owned_by, provider),
            }
            for key, value in model_info.items():
                if value not in ("", None, [], {}):
                    model[key] = value
            models.append(model)

        return {
            "ok": True,
            "models": models,
            "count": len(models),
            "source": self.get_source(source_id),
        }

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
                if not profile.get("enabled", True):
                    raise ModelProfileError(f"{capability} 默认 Profile 已暂停")
                if not profile.get("can_use_as_hermes", True):
                    raise ModelProfileError(f"{capability} 默认 Profile 不能映射到 Hermes Provider")
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
            source = self.get_source(source_id)
            if str(source.get("capability") or "chat") != capability:
                raise ModelProfileError("模型类型必须与提供商源类型一致")
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

    def test_and_save_profile(self, source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        source = self.get_source_private(source_id)
        capability = _normalize_capability(str(payload.get("capability") or source.get("capability") or "chat"))
        if str(source.get("capability") or "chat") != capability:
            raise ModelProfileError("模型类型必须与提供商源类型一致")
        payload = {**payload, "capability": capability}
        test_result = self._test_profile_payload(source, payload)
        if not test_result.get("ok"):
            return self._record_source_test_result(
                source_id,
                ok=False,
                message=str(test_result.get("message") or "模型测试失败"),
                extra={
                    key: value
                    for key, value in test_result.items()
                    if key not in {"ok", "success", "message"}
                },
            )

        profile_payload = {
            **payload,
            "source_id": source_id,
            "provider": source.get("provider") or payload.get("provider") or "openai_compatible",
            "base_url": source.get("base_url") or payload.get("base_url") or "",
        }
        try:
            if str(payload.get("profile_id") or "").strip():
                profile = self.update_profile(str(payload["profile_id"]), profile_payload)
            else:
                profile = self.create_profile(profile_payload)
        except sqlite3.IntegrityError as exc:
            raise ModelProfileError("Profile 名称必须唯一") from exc
        result = self._record_test_result(
            profile["profile_id"],
            ok=True,
            message=str(test_result.get("message") or "OK"),
            extra={"latency_ms": test_result.get("latency_ms")},
        )
        result["created"] = not bool(str(payload.get("profile_id") or "").strip())
        return result

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
        if next_source_id:
            source = self.get_source(next_source_id)
            if str(source.get("capability") or "chat") != str(next_profile.get("capability") or "chat"):
                raise ModelProfileError("模型类型必须与提供商源类型一致")
        api_key = "" if next_source_id else str(current.get("api_key") or "")
        if not next_source_id and "api_key" in payload and str(payload.get("api_key") or "").strip():
            api_key = str(payload.get("api_key") or "").strip()
        profile_enabled = next_profile.get("enabled", True)
        if "enabled" not in payload and "profile_enabled" in current:
            profile_enabled = current.get("profile_enabled", True)
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
                1 if profile_enabled else 0,
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
        result = self._test_profile_payload(
            {
                "provider": profile.get("provider"),
                "base_url": profile.get("base_url"),
                "api_key": profile.get("api_key"),
            },
            profile,
        )
        return self._record_test_result(
            profile_id,
            ok=bool(result.get("ok")),
            message=str(result.get("message") or ""),
            extra={
                key: value
                for key, value in result.items()
                if key not in {"ok", "success", "message"}
            },
        )

    def _test_profile_payload(self, source: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        capability = _normalize_capability(str(payload.get("capability") or "chat"))
        provider = str(source.get("provider") or payload.get("provider") or "openai_compatible")
        base_url = str(source.get("base_url") or payload.get("base_url") or "").strip()
        api_key = str(source.get("api_key") or payload.get("api_key") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not _supports_openai_compatible_api(provider):
            return {"ok": False, "success": False, "message": "首版仅支持 OpenAI-compatible Profile 的自动测试。"}
        if capability == "tts":
            return {"ok": False, "success": False, "message": "TTS Profile 首版只做保存与复用，连接测试会在 TTS 专用链路中补齐。"}
        missing = [
            key
            for key, value in (("base_url", base_url), ("model", model), ("api_key", api_key))
            if not value
        ]
        if missing:
            return {"ok": False, "success": False, "message": "Profile 配置不完整。", "missing": missing}
        messages: list[dict[str, Any]] = [{"role": "user", "content": "Reply with OK."}]
        if capability == "vision":
            messages = _vision_test_messages()
        started = time.time()
        try:
            result = openai_compatible_chat(
                base_url.rstrip("/"),
                model,
                api_key,
                messages,
            )
        except ModelProfileError as exc:
            return {"ok": False, "success": False, "message": str(exc)}
        if capability == "vision" and not _vision_test_passed(result):
            return {
                "ok": False,
                "success": False,
                "message": "图片识别模型没有通过真实图片测试，请选择能够读取图片内容的多模态模型。",
                "vision_test_response": result[:500],
            }
        return {
            "ok": True,
            "success": True,
            "message": result[:500] or "OK",
            "latency_ms": int((time.time() - started) * 1000),
        }

    def _record_test_result(
        self,
        profile_id: str,
        *,
        ok: bool,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tested_at = _now()
        profile = self.get_profile(profile_id)
        self._conn.execute(
            """
            UPDATE model_profiles
               SET status=?, last_tested_at=?, last_error=?, updated_at=?
             WHERE profile_id=?
            """,
            ("available" if ok else "failed", tested_at, "" if ok else message, tested_at, profile_id),
        )
        source_id = str(profile.get("source_id") or "")
        if source_id:
            self._conn.execute(
                """
                UPDATE model_sources
                   SET status=?, last_tested_at=?, last_error=?, updated_at=?
                 WHERE source_id=?
                """,
                ("available" if ok else "failed", tested_at, "" if ok else message, tested_at, source_id),
            )
        self._conn.commit()
        payload = {"ok": ok, "success": ok, "message": message, "profile": self.get_profile(profile_id)}
        if extra:
            payload.update(extra)
        return payload


def openai_compatible_chat(base_url: str, model: str, api_key: str, messages: list[dict[str, Any]]) -> str:
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
