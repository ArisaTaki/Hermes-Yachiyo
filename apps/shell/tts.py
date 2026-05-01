"""可选 TTS 触发抽象。"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from apps.shell.config import TTSConfig

logger = logging.getLogger(__name__)


def prepare_tts_text(text: str, max_chars: int = 80) -> str:
    """Convert an assistant reply into a short, speech-friendly notification."""
    limit = max(20, min(240, int(max_chars or 80)))
    value = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", value)
    value = re.sub(r"https?://\S+", "链接", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value

    sentence_cut = -1
    for mark in ("。", "！", "？", ".", "!", "?"):
        index = value.find(mark, 0, limit + 1)
        if index >= 0 and (sentence_cut < 0 or index < sentence_cut):
            sentence_cut = index
    if sentence_cut >= 6:
        return value[: sentence_cut + 1].strip()

    punctuation_cut = max(value.rfind(mark, 0, limit + 1) for mark in ("，", "；", ",", ";"))
    if punctuation_cut >= max(12, limit // 2):
        return value[: punctuation_cut + 1].strip()
    return value[: max(1, limit - 1)].rstrip() + "…"


class TTSService:
    """非阻塞 TTS 触发器。默认无副作用，失败不影响聊天主流程。"""

    def __init__(self, config: "TTSConfig") -> None:
        self._config = config
        self._last_status: dict[str, Any] = {
            "enabled": bool(config.enabled),
            "provider": config.provider,
            "ok": True,
            "message": "TTS 未启用" if not config.enabled else "TTS 待触发",
        }

    def get_status(self) -> dict[str, Any]:
        status = dict(self._last_status)
        status["enabled"] = bool(self._config.enabled)
        status["provider"] = self._config.provider
        return status

    def speak_async(self, text: str) -> dict[str, Any]:
        """异步触发 TTS，立即返回调度状态。"""
        text = (text or "").strip()
        spoken_text = prepare_tts_text(text, getattr(self._config, "max_chars", 80))
        validation_error = self._validation_error(spoken_text)
        if validation_error:
            self._last_status = {
                "enabled": bool(self._config.enabled),
                "provider": self._config.provider,
                "ok": False,
                "skipped": True,
                "message": validation_error,
            }
            return dict(self._last_status)

        self._last_status = {
            "enabled": True,
            "provider": self._config.provider,
            "ok": True,
            "scheduled": True,
            "message": "TTS 已触发",
            "spoken_text": spoken_text,
            "original_length": len(text),
        }
        thread = threading.Thread(
            target=self._run_safely,
            args=(spoken_text,),
            daemon=True,
            name="live2d-tts",
        )
        thread.start()
        return dict(self._last_status)

    def _validation_error(self, text: str) -> str | None:
        if not self._config.enabled:
            return "TTS 未启用"
        if not text:
            return "TTS 文本为空"
        provider = self._config.provider
        if provider == "none":
            return "TTS Provider 为 none"
        if provider == "http" and not (self._config.endpoint or "").strip():
            return "TTS HTTP endpoint 未配置"
        if provider == "command" and not (self._config.command or "").strip():
            return "TTS 本地命令未配置"
        if provider not in {"http", "command"}:
            return "TTS Provider 不受支持"
        return None

    def _run_safely(self, text: str) -> None:
        try:
            if self._config.provider == "http":
                self._run_http(text)
            elif self._config.provider == "command":
                self._run_command(text)
            self._last_status = {
                "enabled": True,
                "provider": self._config.provider,
                "ok": True,
                "message": "TTS 已完成",
                "spoken_text": text,
            }
        except Exception as exc:
            logger.warning("TTS 触发失败: %s", exc)
            self._last_status = {
                "enabled": True,
                "provider": self._config.provider,
                "ok": False,
                "error": str(exc),
                "message": "TTS 触发失败",
                "spoken_text": text,
            }

    def _timeout(self) -> int:
        try:
            return max(1, min(120, int(self._config.timeout_seconds or 20)))
        except (TypeError, ValueError):
            return 20

    def _run_http(self, text: str) -> None:
        payload = json.dumps(
            {"text": text, "voice": self._config.voice or ""},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            (self._config.endpoint or "").strip(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout()) as response:
                response.read()
        except URLError as exc:
            raise RuntimeError(exc.reason if hasattr(exc, "reason") else str(exc)) from exc

    def _run_command(self, text: str) -> None:
        argv = shlex.split(self._config.command or "")
        if not argv:
            raise RuntimeError("TTS 本地命令为空")
        voice = self._config.voice or ""
        if any("{text}" in part or "{voice}" in part for part in argv):
            argv = [part.replace("{text}", text).replace("{voice}", voice) for part in argv]
        else:
            argv.append(text)
            if voice:
                argv.append(voice)

        env = dict(os.environ)
        env["HERMES_YACHIYO_TTS_TEXT"] = text
        env["HERMES_YACHIYO_TTS_VOICE"] = voice
        result = subprocess.run(
            argv,
            env=env,
            capture_output=True,
            text=True,
            timeout=self._timeout(),
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:200]
            raise RuntimeError(f"TTS 命令退出码 {result.returncode}: {detail}")
