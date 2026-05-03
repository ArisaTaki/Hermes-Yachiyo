"""可选 TTS 触发抽象。"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin
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
        if provider == "gpt-sovits" and not (self._config.gsv_base_url or "").strip():
            return "GPT-SoVITS API Base URL 未配置"
        if provider not in {"http", "command", "gpt-sovits"}:
            return "TTS Provider 不受支持"
        return None

    def _run_safely(self, text: str) -> None:
        try:
            if self._config.provider == "http":
                self._run_http(text)
            elif self._config.provider == "command":
                self._run_command(text)
            elif self._config.provider == "gpt-sovits":
                self._run_gpt_sovits(text)
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

    def _run_gpt_sovits(self, text: str) -> None:
        base_url = self._gsv_base_url()
        self._maybe_set_gsv_weights(base_url)
        payload = {
            "text": text,
            "text_lang": self._config.gsv_text_language or "zh",
            "ref_audio_path": self._config.gsv_ref_audio_path or "",
            "prompt_text": self._config.gsv_ref_audio_text or "",
            "prompt_lang": self._config.gsv_ref_audio_language or "ja",
            "top_k": self._config.gsv_top_k,
            "top_p": self._config.gsv_top_p,
            "temperature": self._config.gsv_temperature,
            "text_split_method": self._config.gsv_text_split_method or "cut1",
            "batch_size": self._config.gsv_batch_size,
            "batch_threshold": self._config.gsv_batch_threshold,
            "split_bucket": bool(self._config.gsv_split_bucket),
            "speed_factor": self._config.gsv_speed_factor,
            "fragment_interval": self._config.gsv_fragment_interval,
            "streaming_mode": bool(self._config.gsv_streaming_mode),
            "media_type": self._config.gsv_media_type or "wav",
            "parallel_infer": bool(self._config.gsv_parallel_infer),
            "repetition_penalty": self._config.gsv_repetition_penalty,
            "seed": self._config.gsv_seed,
        }
        aux_path = (self._config.gsv_aux_ref_audio_path or "").strip()
        if aux_path:
            payload["aux_ref_audio_paths"] = [aux_path]

        endpoint = self._gsv_tts_endpoint(base_url)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout()) as response:
                content_type = _response_header(response, "Content-Type")
                body = response.read()
        except URLError as exc:
            raise RuntimeError(exc.reason if hasattr(exc, "reason") else str(exc)) from exc

        self._handle_gsv_response(body, content_type)

    def _gsv_base_url(self) -> str:
        value = (self._config.gsv_base_url or "").strip().rstrip("/")
        return value or "http://127.0.0.1:9880"

    @staticmethod
    def _gsv_tts_endpoint(base_url: str) -> str:
        if base_url.rstrip("/").endswith("/tts"):
            return base_url
        return urljoin(base_url + "/", "tts")

    def _maybe_set_gsv_weights(self, base_url: str) -> None:
        mappings = (
            ("gsv_gpt_weights_path", "set_gpt_weights", "weights_path"),
            ("gsv_sovits_weights_path", "set_sovits_weights", "weights_path"),
        )
        for attr, route, parameter in mappings:
            value = (getattr(self._config, attr, "") or "").strip()
            if not value:
                continue
            url = urljoin(base_url + "/", f"{route}?{parameter}={quote(value)}")
            request = Request(url, method="GET")
            try:
                with urlopen(request, timeout=self._timeout()) as response:
                    response.read()
            except URLError as exc:
                raise RuntimeError(
                    exc.reason if hasattr(exc, "reason") else f"{route} 请求失败: {exc}"
                ) from exc

    def _handle_gsv_response(self, body: bytes, content_type: str) -> None:
        if not body:
            raise RuntimeError("GPT-SoVITS 返回空音频")
        lowered = content_type.lower()
        if "application/json" in lowered or body[:1] in {b"{", b"["}:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception as exc:
                raise RuntimeError("GPT-SoVITS 返回 JSON 解析失败") from exc
            audio_path = str(payload.get("audio_path") or payload.get("file_path") or "").strip()
            if audio_path:
                self._play_audio_file(audio_path)
                return
            if payload.get("error") or payload.get("message"):
                raise RuntimeError(str(payload.get("error") or payload.get("message")))
            raise RuntimeError("GPT-SoVITS 未返回音频路径或音频内容")

        suffix = "." + (self._config.gsv_media_type or "wav").strip().lstrip(".")
        with tempfile.NamedTemporaryFile(prefix="hermes-yachiyo-gsv-", suffix=suffix, delete=False) as tmp:
            tmp.write(body)
            audio_path = tmp.name
        try:
            self._play_audio_file(audio_path)
        finally:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                logger.debug("清理 GPT-SoVITS 临时音频失败: %s", audio_path, exc_info=True)

    def _play_audio_file(self, audio_path: str) -> None:
        path = str(Path(audio_path).expanduser())
        if not Path(path).exists():
            raise RuntimeError(f"TTS 音频文件不存在: {path}")
        system = platform.system().lower()
        if system == "darwin":
            argv = ["afplay", path]
        elif system == "windows":
            argv = [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$player = New-Object System.Media.SoundPlayer "
                    f"{json.dumps(path)}; $player.PlaySync()"
                ),
            ]
        else:
            player = (
                shutil.which("paplay")
                or shutil.which("aplay")
                or shutil.which("ffplay")
            )
            if not player:
                raise RuntimeError("未找到可用音频播放器（paplay/aplay/ffplay）")
            argv = [player, "-nodisp", "-autoexit", path] if Path(player).name == "ffplay" else [player, path]
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=self._timeout(),
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:200]
            raise RuntimeError(f"TTS 音频播放失败: {detail}")


def _response_header(response: Any, name: str) -> str:
    getter = getattr(response, "getheader", None)
    if callable(getter):
        return str(getter(name, "") or "")
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get(name, "")
        return str(value or "")
    return ""
