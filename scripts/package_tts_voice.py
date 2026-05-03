"""Package the current Yachiyo GPT-SoVITS voice preset for GitHub Releases."""

from __future__ import annotations

import argparse
import json
import shutil
import time
import zipfile
from pathlib import Path

from apps.shell.config import load_config
from apps.shell.tts_resources import TTS_PRESET_KIND


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "release-assets"


def _copy_required_file(source: str, target: Path, label: str) -> str:
    path = Path(source).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} 不存在: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return str(target)


def build_voice_package(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    config = load_config().tts
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = "yachiyo-gpt-sovits-v4"
    staging = output_dir / f".{slug}-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    gpt_target = staging / "GPT_weights_v4" / Path(config.gsv_gpt_weights_path).name
    sovits_target = staging / "SoVITS_weights_v4" / Path(config.gsv_sovits_weights_path).name
    ref_target = staging / "refs" / Path(config.gsv_ref_audio_path).name

    _copy_required_file(config.gsv_gpt_weights_path, gpt_target, "GPT 权重")
    _copy_required_file(config.gsv_sovits_weights_path, sovits_target, "SoVITS 权重")
    _copy_required_file(config.gsv_ref_audio_path, ref_target, "参考音频")

    aux_rel = ""
    if config.gsv_aux_ref_audio_path:
        aux_target = staging / "refs" / Path(config.gsv_aux_ref_audio_path).name
        _copy_required_file(config.gsv_aux_ref_audio_path, aux_target, "辅助参考音频")
        aux_rel = str(aux_target.relative_to(staging))

    manifest = {
        "kind": TTS_PRESET_KIND,
        "schema_version": 1,
        "name": "八千代 GPT-SoVITS v4",
        "slug": slug,
        "provider": "gpt-sovits",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            "gpt_weights": str(gpt_target.relative_to(staging)),
            "sovits_weights": str(sovits_target.relative_to(staging)),
            "ref_audio": str(ref_target.relative_to(staging)),
            "aux_ref_audio": aux_rel,
        },
        "gpt_sovits": {
            "ref_audio_text": config.gsv_ref_audio_text,
            "ref_audio_language": config.gsv_ref_audio_language,
            "text_language": config.gsv_text_language,
            "top_k": config.gsv_top_k,
            "top_p": config.gsv_top_p,
            "temperature": config.gsv_temperature,
            "text_split_method": config.gsv_text_split_method,
            "batch_size": config.gsv_batch_size,
            "batch_threshold": config.gsv_batch_threshold,
            "split_bucket": config.gsv_split_bucket,
            "speed_factor": config.gsv_speed_factor,
            "fragment_interval": config.gsv_fragment_interval,
            "streaming_mode": config.gsv_streaming_mode,
            "seed": config.gsv_seed,
            "parallel_infer": config.gsv_parallel_infer,
            "repetition_penalty": config.gsv_repetition_penalty,
            "media_type": config.gsv_media_type,
        },
    }
    (staging / "yachiyo-tts-preset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (staging / "README.md").write_text(
        "# 八千代 GPT-SoVITS 语音包\n\n"
        "在 Hermes-Yachiyo 的“主动关怀语音”页面导入此 ZIP，保存后即可填入 GPT-SoVITS 权重和参考音频路径。\n"
        "此包只包含八千代音色资源，不包含 GPT-SoVITS 服务本体；仍需用户本机启动 GPT-SoVITS API 服务。\n",
        encoding="utf-8",
    )

    archive = output_dir / f"Hermes-Yachiyo-{slug}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(staging))
    shutil.rmtree(staging, ignore_errors=True)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the Yachiyo GPT-SoVITS voice preset ZIP.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for the release ZIP.")
    args = parser.parse_args()
    archive = build_voice_package(Path(args.output_dir).expanduser())
    print(archive)


if __name__ == "__main__":
    main()
