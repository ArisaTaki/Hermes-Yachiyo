"""Importable TTS voice preset resources."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from apps.shell.assets import TTS_RELEASES_URL
from apps.shell.assets import get_user_tts_assets_dir
from apps.shell.assets import project_display_path


TTS_PRESET_KIND = "hermes-yachiyo-gpt-sovits-voice"
TTS_PRESET_MANIFEST_NAMES = ("yachiyo-tts-preset.json", "tts-preset.json")


def get_tts_voice_resource_info() -> dict[str, Any]:
    assets_root = get_user_tts_assets_dir().expanduser()
    return {
        "default_assets_root": str(assets_root),
        "default_assets_root_display": project_display_path(assets_root),
        "releases_url": TTS_RELEASES_URL,
        "help_text": "从 Releases 下载八千代 GPT-SoVITS 语音包 ZIP 后导入，Yachiyo 会把模型权重和参考音频路径填入主动关怀 TTS 设置。",
        "service_help_text": "语音包只包含音色资源；选择 GPT-SoVITS 本地服务时，还需要先启动 GPT-SoVITS API 服务。可在语音设置页填写服务目录和启动命令后打开终端。",
        "default_service_command": "python api_v2.py -a 127.0.0.1 -p 9880",
    }


def import_tts_voice_archive_draft(archive_path: Path) -> dict[str, Any]:
    """Import a GPT-SoVITS voice ZIP and return TTS config draft values."""
    try:
        imported_dir, manifest = import_tts_voice_archive(archive_path)
        settings = tts_settings_from_manifest(imported_dir, manifest)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    draft_changes = {f"tts.{key}": value for key, value in settings.items()}
    return {
        "ok": True,
        "message": "语音包已导入，等待保存 TTS 设置",
        "imported_path": str(imported_dir),
        "imported_path_display": project_display_path(imported_dir),
        "tts_settings": settings,
        "draft_changes": draft_changes,
        "resource": get_tts_voice_resource_info(),
    }


def import_tts_voice_archive(archive_path: Path, assets_root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved_archive = archive_path.expanduser().resolve()
    if not resolved_archive.exists() or not resolved_archive.is_file():
        raise FileNotFoundError("未找到要导入的语音包 ZIP")

    target_root = (assets_root or get_user_tts_assets_dir()).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hermes-tts-import-") as tmp_dir:
        try:
            shutil.unpack_archive(str(resolved_archive), tmp_dir)
        except (shutil.ReadError, ValueError) as exc:
            raise ValueError("所选文件不是可导入的语音包压缩文件") from exc

        manifest_path = find_tts_voice_manifest(Path(tmp_dir))
        if manifest_path is None:
            raise ValueError("压缩包内未找到 yachiyo-tts-preset.json")
        manifest = read_tts_voice_manifest(manifest_path)
        source_dir = manifest_path.parent
        target_dir = pick_import_target_dir(target_root, str(manifest.get("slug") or source_dir.name or "yachiyo-gpt-sovits"))
        shutil.copytree(source_dir, target_dir)
        return target_dir.resolve(), manifest


def find_tts_voice_manifest(root: Path) -> Path | None:
    for name in TTS_PRESET_MANIFEST_NAMES:
        direct = root / name
        if direct.is_file():
            return direct
    for path in sorted(root.rglob("*.json")):
        if path.name not in TTS_PRESET_MANIFEST_NAMES:
            continue
        return path
    return None


def read_tts_voice_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("语音包 manifest 解析失败") from exc
    if payload.get("kind") != TTS_PRESET_KIND:
        raise ValueError("语音包 manifest 类型不匹配")
    return payload


def tts_settings_from_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    params = manifest.get("gpt_sovits") if isinstance(manifest.get("gpt_sovits"), dict) else {}

    def rel_path(key: str, fallback_key: str = "") -> str:
        value = str(files.get(key) or manifest.get(fallback_key or key) or "").strip()
        if not value:
            return ""
        path = (root / value).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"语音包缺少文件：{value}")
        return str(path)

    settings: dict[str, Any] = {
        "enabled": True,
        "provider": "gpt-sovits",
        "gsv_base_url": str(manifest.get("base_url") or params.get("base_url") or "http://127.0.0.1:9880"),
        "gsv_service_workdir": str(manifest.get("service_workdir") or params.get("service_workdir") or ""),
        "gsv_service_command": str(
            manifest.get("service_command")
            or params.get("service_command")
            or "python api_v2.py -a 127.0.0.1 -p 9880"
        ),
        "gsv_gpt_weights_path": rel_path("gpt_weights", "gpt_weights"),
        "gsv_sovits_weights_path": rel_path("sovits_weights", "sovits_weights"),
        "gsv_ref_audio_path": rel_path("ref_audio", "ref_audio"),
        "gsv_ref_audio_text": str(params.get("ref_audio_text") or manifest.get("ref_audio_text") or ""),
        "gsv_ref_audio_language": str(params.get("ref_audio_language") or manifest.get("ref_audio_language") or "ja"),
        "gsv_aux_ref_audio_path": rel_path("aux_ref_audio", "aux_ref_audio") if (files.get("aux_ref_audio") or manifest.get("aux_ref_audio")) else "",
        "gsv_text_language": str(params.get("text_language") or manifest.get("text_language") or "zh"),
        "gsv_top_k": int(params.get("top_k", 15)),
        "gsv_top_p": float(params.get("top_p", 1.0)),
        "gsv_temperature": float(params.get("temperature", 1.0)),
        "gsv_text_split_method": str(params.get("text_split_method") or "cut1"),
        "gsv_batch_size": int(params.get("batch_size", 1)),
        "gsv_batch_threshold": float(params.get("batch_threshold", 0.75)),
        "gsv_split_bucket": bool(params.get("split_bucket", True)),
        "gsv_speed_factor": float(params.get("speed_factor", 1.0)),
        "gsv_fragment_interval": float(params.get("fragment_interval", 0.3)),
        "gsv_streaming_mode": bool(params.get("streaming_mode", False)),
        "gsv_seed": int(params.get("seed", -1)),
        "gsv_parallel_infer": bool(params.get("parallel_infer", False)),
        "gsv_repetition_penalty": float(params.get("repetition_penalty", 1.35)),
        "gsv_media_type": str(params.get("media_type") or "wav"),
    }
    return settings


def pick_import_target_dir(root: Path, name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name).strip(".-")
    safe_name = safe_name or "yachiyo-gpt-sovits"
    candidate = root / safe_name
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        next_candidate = root / f"{safe_name}-{suffix}"
        if not next_candidate.exists():
            return next_candidate
        suffix += 1
