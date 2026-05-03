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
from http.client import HTTPException
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import quote, urljoin, urlparse, urlunparse
from urllib.error import URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from apps.shell.config import TTSConfig

logger = logging.getLogger(__name__)
_AUDIO_MIME_BY_MEDIA = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}
_AUDIO_SUFFIX_BY_MIME = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
}
TTSCompletionCallback = Callable[[dict[str, Any]], None]
_ACTION_CUE_KEYWORDS = (
    "歪头",
    "歪了歪头",
    "眨眼",
    "眨了眨眼",
    "点头",
    "摇头",
    "抬头",
    "低头",
    "微笑",
    "笑",
    "挥手",
    "叹气",
    "托腮",
    "伸懒腰",
    "揉眼",
    "眯眼",
    "抬手",
    "转身",
    "凑近",
    "抱着",
    "抱住",
    "比划",
    "表情",
    "动作",
)
_LEADING_ACTION_CUE_RE = re.compile(r"^\s*[\(（\[\{【]([^)\]）}】]{1,80})[\)）\]\}】]\s*")


def prepare_tts_text(text: str, max_chars: int = 80) -> str:
    """Convert an assistant reply into a short, speech-friendly notification."""
    limit = max(20, min(240, int(max_chars or 80)))
    value = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", value)
    value = re.sub(r"https?://\S+", "链接", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = _strip_leading_action_cues(value)
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


def _strip_leading_action_cues(text: str) -> str:
    value = text.strip()
    while True:
        match = _LEADING_ACTION_CUE_RE.match(value)
        if not match:
            return value
        cue = match.group(1).strip()
        if not any(keyword in cue for keyword in _ACTION_CUE_KEYWORDS):
            return value
        value = value[match.end():].strip()


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

    def speak_async(
        self,
        text: str,
        *,
        play: bool = True,
        output_path: str | None = None,
        on_complete: TTSCompletionCallback | None = None,
    ) -> dict[str, Any]:
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
            if on_complete is not None:
                on_complete(dict(self._last_status))
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
            args=(spoken_text, play, output_path, on_complete),
            daemon=True,
            name="live2d-tts",
        )
        thread.start()
        return dict(self._last_status)

    def speak_sync(
        self,
        text: str,
        *,
        play: bool = True,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """同步触发 TTS，用于配置页测试并返回最终结果。"""
        text = (text or "").strip()
        spoken_text = prepare_tts_text(text, getattr(self._config, "max_chars", 80))
        validation_error = self._validation_error(spoken_text)
        if validation_error:
            self._last_status = {
                "enabled": bool(self._config.enabled),
                "provider": self._config.provider,
                "ok": False,
                "success": False,
                "skipped": True,
                "message": validation_error,
            }
            return dict(self._last_status)

        try:
            provider_result = self._run_provider(spoken_text, play=play, output_path=output_path)
            self._last_status = {
                "enabled": True,
                "provider": self._config.provider,
                "ok": True,
                "success": True,
                "message": "TTS 测试已完成",
                "spoken_text": spoken_text,
                "original_length": len(text),
                **provider_result,
            }
        except Exception as exc:
            logger.warning("TTS 测试失败: %s", exc)
            self._last_status = {
                "enabled": True,
                "provider": self._config.provider,
                "ok": False,
                "success": False,
                "error": str(exc),
                "message": "TTS 测试失败",
                "spoken_text": spoken_text,
            }
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

    def _run_safely(
        self,
        text: str,
        play: bool,
        output_path: str | None,
        on_complete: TTSCompletionCallback | None,
    ) -> None:
        try:
            provider_result = self._run_provider(text, play=play, output_path=output_path)
            self._last_status = {
                "enabled": True,
                "provider": self._config.provider,
                "ok": True,
                "message": "TTS 已完成",
                "spoken_text": text,
                **provider_result,
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
        finally:
            if on_complete is not None:
                try:
                    on_complete(dict(self._last_status))
                except Exception:
                    logger.debug("TTS 完成回调失败", exc_info=True)

    def _run_provider(
        self,
        text: str,
        *,
        play: bool = True,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        if self._config.provider == "http":
            return self._run_http(text, play=play, output_path=output_path)
        elif self._config.provider == "command":
            self._run_command(text)
            return {}
        elif self._config.provider == "gpt-sovits":
            return self._run_gpt_sovits(text, play=play, output_path=output_path)
        return {}

    def _timeout(self) -> int:
        try:
            return max(1, min(120, int(self._config.timeout_seconds or 20)))
        except (TypeError, ValueError):
            return 20

    def _run_http(self, text: str, *, play: bool, output_path: str | None) -> dict[str, Any]:
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
                content_type = _response_header(response, "Content-Type")
                body = response.read()
        except (URLError, OSError, HTTPException) as exc:
            raise RuntimeError(_network_error_message("TTS HTTP 请求", request.full_url, exc)) from exc
        if _looks_like_audio(body, content_type):
            return self._handle_audio_response(body, content_type, output_path=output_path, play=play)
        return {}

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

    def _run_gpt_sovits(self, text: str, *, play: bool, output_path: str | None) -> dict[str, Any]:
        errors: list[str] = []
        for base_url in self._gsv_base_url_candidates():
            try:
                return self._run_gpt_sovits_with_base_url(
                    text,
                    base_url,
                    play=play,
                    output_path=output_path,
                )
            except RuntimeError as exc:
                errors.append(str(exc))
                logger.info("GPT-SoVITS 请求失败，尝试下一个候选地址: %s", exc)
        if errors:
            raise RuntimeError(errors[-1])
        raise RuntimeError("GPT-SoVITS API Base URL 未配置")

    def _run_gpt_sovits_with_base_url(
        self,
        text: str,
        base_url: str,
        *,
        play: bool,
        output_path: str | None,
    ) -> dict[str, Any]:
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
        except (URLError, OSError, HTTPException) as exc:
            raise RuntimeError(_network_error_message("GPT-SoVITS /tts 请求", endpoint, exc)) from exc

        return self._handle_gsv_response(body, content_type, output_path=output_path, play=play)

    def _gsv_base_url(self) -> str:
        value = (self._config.gsv_base_url or "").strip().rstrip("/")
        return value or "http://127.0.0.1:9880"

    def _gsv_base_url_candidates(self) -> list[str]:
        primary = self._gsv_base_url()
        candidates = [primary]
        parsed = urlparse(primary)
        host = (parsed.hostname or "").lower()
        if host == "host.docker.internal":
            port = f":{parsed.port}" if parsed.port else ""
            fallback = urlunparse(parsed._replace(netloc=f"127.0.0.1{port}")).rstrip("/")
            if fallback and fallback not in candidates:
                candidates.append(fallback)
        return candidates

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
            except (URLError, OSError, HTTPException) as exc:
                raise RuntimeError(_network_error_message(f"GPT-SoVITS {route} 请求", url, exc)) from exc

    def _handle_gsv_response(
        self,
        body: bytes,
        content_type: str,
        *,
        output_path: str | None,
        play: bool,
    ) -> dict[str, Any]:
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
                path = self._copy_audio_file(audio_path, output_path) if output_path else str(Path(audio_path).expanduser())
                if play:
                    self._play_audio_file(path)
                return {
                    "audio_path": path,
                    "mime_type": _mime_type_for_audio_path(path, self._config.gsv_media_type),
                }
            if payload.get("error") or payload.get("message"):
                raise RuntimeError(str(payload.get("error") or payload.get("message")))
            raise RuntimeError("GPT-SoVITS 未返回音频路径或音频内容")

        return self._handle_audio_response(body, content_type, output_path=output_path, play=play)

    def _handle_audio_response(
        self,
        body: bytes,
        content_type: str,
        *,
        output_path: str | None,
        play: bool,
    ) -> dict[str, Any]:
        suffix = "." + (self._config.gsv_media_type or "wav").strip().lstrip(".")
        if output_path:
            audio_path = str(Path(output_path).expanduser())
            Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
            Path(audio_path).write_bytes(body)
            keep_file = True
        else:
            inferred_suffix = _suffix_for_audio_response(content_type, suffix)
            with tempfile.NamedTemporaryFile(prefix="hermes-yachiyo-gsv-", suffix=inferred_suffix, delete=False) as tmp:
                tmp.write(body)
                audio_path = tmp.name
            keep_file = False
        try:
            if play:
                self._play_audio_file(audio_path)
        finally:
            if not keep_file:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except OSError:
                    logger.debug("清理 GPT-SoVITS 临时音频失败: %s", audio_path, exc_info=True)
        result: dict[str, Any] = {
            "mime_type": _mime_type_for_audio_path(audio_path, self._config.gsv_media_type),
        }
        if keep_file:
            result["audio_path"] = audio_path
        return result

    @staticmethod
    def _copy_audio_file(source_path: str, output_path: str | None) -> str:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise RuntimeError(f"TTS 音频文件不存在: {source}")
        if not output_path:
            return str(source)
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return str(target)

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


def _looks_like_audio(body: bytes, content_type: str) -> bool:
    lowered = (content_type or "").lower()
    if lowered.startswith("audio/"):
        return True
    return body.startswith((b"RIFF", b"ID3", b"OggS", b"fLaC"))


def _suffix_for_audio_response(content_type: str, fallback: str = ".wav") -> str:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    suffix = _AUDIO_SUFFIX_BY_MIME.get(mime_type)
    if suffix:
        return suffix
    fallback = fallback if fallback.startswith(".") else f".{fallback}"
    return fallback or ".wav"


def _mime_type_for_audio_path(path: str, configured_media_type: str | None = None) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".flac":
        return "audio/flac"
    media_type = (configured_media_type or "").strip().lower().lstrip(".")
    return _AUDIO_MIME_BY_MEDIA.get(media_type, "audio/wav")


def _network_error_message(action: str, url: str, exc: BaseException) -> str:
    detail = ""
    if isinstance(exc, URLError) and getattr(exc, "reason", None):
        detail = str(exc.reason)
    if not detail:
        detail = str(exc)
    if not detail:
        detail = exc.__class__.__name__

    hint = ""
    lowered = detail.lower()
    if "remote end closed connection" in lowered or "remote disconnected" in lowered:
        hint = "；远端提前关闭连接，通常是 TTS 服务进程崩溃、接口路径不匹配，或请求参数不被当前服务版本接受"
    elif "connection refused" in lowered or "errno 61" in lowered:
        hint = "；连接被拒绝，请确认 TTS 服务已启动并监听该地址"
    elif "timed out" in lowered or "timeout" in lowered:
        hint = "；请求超时，请检查模型加载耗时、超时秒数和服务日志"
    return f"{action}失败: {url}；{detail}{hint}"
