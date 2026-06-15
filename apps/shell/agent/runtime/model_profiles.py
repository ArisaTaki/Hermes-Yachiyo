"""Runtime model profile resolution helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeModelProfileResolver:
    """Resolves Agent model configuration without owning execution state."""

    def __init__(
        self,
        *,
        profile_service_factory: Callable[[], Any],
        supports_openai_compatible_api: Callable[[str], bool],
        default_agent_ids: set[str] | frozenset[str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._profile_service_factory = profile_service_factory
        self._supports_openai_compatible_api = supports_openai_compatible_api
        self._default_agent_ids = set(default_agent_ids)
        self._error_type = error_type

    def model_profile_config_private(
        self,
        profile_id: str,
        *,
        capability: str,
    ) -> dict[str, Any]:
        try:
            profile = self._profile_service_factory().get_profile_private(profile_id)
        except KeyError as exc:
            raise self._error_type("Agent 引用的模型 Profile 不存在") from exc
        if not profile.get("enabled", True):
            raise self._error_type("Agent 引用的模型 Profile 已停用")
        if str(profile.get("status") or "") != "available":
            raise self._error_type("Agent 引用的模型 Profile 尚未通过连接测试")
        if not self._supports_openai_compatible_api(
            str(profile.get("provider") or "openai_compatible")
        ):
            raise self._error_type("Agent Runtime 首版仅支持 OpenAI-compatible 模型 Profile")
        if str(profile.get("capability") or "chat") != capability:
            raise self._error_type(f"Agent 推理需要 {capability} 模型 Profile")
        return {
            "provider": profile.get("provider") or "openai_compatible",
            "base_url": profile.get("base_url") or "",
            "model": profile.get("model") or "",
            "api_key": profile.get("api_key") or "",
        }

    def chat_profile_model_config_private(self, profile_id: str) -> dict[str, Any]:
        return self.model_profile_config_private(profile_id, capability="chat")

    def validate_available_profile(self, profile_id: str, capability: str) -> dict[str, Any]:
        profile_service = self._profile_service_factory()
        get_profile = getattr(profile_service, "get_profile", None)
        try:
            profile = (
                get_profile(profile_id)
                if callable(get_profile)
                else profile_service.get_profile_private(profile_id)
            )
        except KeyError as exc:
            raise self._error_type("Agent 引用的模型 Profile 不存在") from exc
        if str(profile.get("capability") or "") != capability:
            raise self._error_type(f"Agent 引用的 {capability} 模型 Profile 类型不匹配")
        if str(profile.get("status") or "") != "available":
            raise self._error_type("Agent 只能引用已通过连接测试的模型 Profile")
        if not profile.get("enabled", True):
            raise self._error_type("Agent 引用的模型 Profile 已停用")
        return profile

    def validate_agent_profile_refs(self, payload: dict[str, Any]) -> None:
        model_mode = str(payload.get("model_mode") or "profile")
        if model_mode == "profile":
            profile_id = str(payload.get("model_profile_id") or "").strip()
            if profile_id:
                self.validate_available_profile(profile_id, "chat")
        vision_profile_id = str(payload.get("vision_model_profile_id") or "").strip()
        if vision_profile_id:
            self.validate_available_profile(vision_profile_id, "vision")

    def agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
            return self.chat_profile_model_config_private(profile_id)
        model_mode = str(agent.get("model_mode") or "profile")
        agent_id = str(agent.get("agent_id") or "")
        if model_mode == "follow_main" or agent_id in self._default_agent_ids:
            default_profile_id = str(
                self._profile_service_factory().get_defaults().get("chat") or ""
            ).strip()
            if default_profile_id:
                return self.chat_profile_model_config_private(default_profile_id)
        model_config = agent.get("model_config") or {}
        if any(
            str(model_config.get(key) or "").strip()
            for key in ("base_url", "model", "api_key")
        ):
            return model_config
        raise self._error_type(
            "Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。"
        )


class RuntimeAgentModelTester:
    """Tests Agent model settings without owning Agent persistence."""

    def __init__(
        self,
        *,
        profile_service_factory: Callable[[], Any],
        default_agent_ids: set[str] | frozenset[str],
        call_custom_api: Callable[[str, str, str, list[dict[str, str]]], str],
        now_seconds: Callable[[], float],
        redact_error: Callable[[Any], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._profile_service_factory = profile_service_factory
        self._default_agent_ids = set(default_agent_ids)
        self._call_custom_api = call_custom_api
        self._now_seconds = now_seconds
        self._redact_error = redact_error
        self._error_type = error_type

    def test_agent_model(self, agent: dict[str, Any]) -> dict[str, Any]:
        profile_service = self._profile_service_factory()
        vision_profile_id = str(agent.get("vision_model_profile_id") or "").strip()
        vision_result: dict[str, Any] | None = None
        if vision_profile_id:
            try:
                vision_result = profile_service.test_profile(vision_profile_id)
            except KeyError as exc:
                raise self._error_type("Agent 引用的图片识别 Profile 不存在") from exc
            if not vision_result.get("ok"):
                vision_result["mode"] = "vision_profile"
                return vision_result

        profile_id = str(agent.get("model_profile_id") or "").strip()
        if profile_id:
            try:
                result = profile_service.test_profile(profile_id)
            except KeyError as exc:
                raise self._error_type("Agent 引用的模型 Profile 不存在") from exc
            result["mode"] = "profile"
            self._append_vision_success(result, vision_result)
            return result

        if agent.get("model_mode") == "follow_main" or str(agent.get("agent_id") or "") in self._default_agent_ids:
            default_profile_id = str(profile_service.get_defaults().get("chat") or "").strip()
            if default_profile_id:
                try:
                    result = profile_service.test_profile(default_profile_id)
                except KeyError as exc:
                    raise self._error_type("默认 Chat Profile 不存在") from exc
                result["mode"] = "follow_main"
                self._append_vision_success(result, vision_result)
                return result

        if agent.get("model_mode") != "custom_api":
            return {
                "ok": False,
                "mode": "profile",
                "missing": ["model_profile_id"],
                "message": "请选择已通过测试的 Agent 文本模型 Profile。",
            }

        model_config = agent.get("model_config") or {}
        missing = [
            key
            for key in ("base_url", "model", "api_key")
            if not str(model_config.get(key) or "").strip()
        ]
        if missing:
            return {"ok": False, "missing": missing, "message": "custom_api 配置不完整。"}

        started = self._now_seconds()
        try:
            result = self._call_custom_api(
                str(model_config["base_url"]).rstrip("/"),
                str(model_config["model"]),
                str(model_config["api_key"]),
                [{"role": "user", "content": "Reply with OK."}],
            )
        except self._error_type as exc:
            return {"ok": False, "message": self._redact_error(exc)}
        return {
            "ok": True,
            "latency_ms": int((self._now_seconds() - started) * 1000),
            "message": result[:500] or "OK",
        }

    @staticmethod
    def _append_vision_success(
        result: dict[str, Any],
        vision_result: dict[str, Any] | None,
    ) -> None:
        if result.get("ok") and vision_result:
            result["message"] = f"{result.get('message') or '文本模型测试通过'}；图片识别 Profile 测试通过。"
