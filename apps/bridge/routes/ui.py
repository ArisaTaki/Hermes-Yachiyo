"""HTTP UI bridge routes for the Electron/React desktop frontend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydantic import Field

from apps.bridge.deps import get_runtime
from apps.core.chat_session import MessageStatus
from apps.shell.assets import DEFAULT_BUBBLE_AVATAR_PATH
from apps.shell.assets import data_uri
from apps.shell.assets import find_live2d_preview_path
from apps.shell.chat_api import ChatAPI
from apps.shell.chat_api import allocate_chat_attachment_path
from apps.shell.chat_api import audio_mime_type_for_suffix
from apps.shell.chat_api import chat_attachment_record
from apps.shell.chat_bridge import ChatBridge
from apps.shell.gpt_sovits_service import get_gpt_sovits_service_status
from apps.shell.gpt_sovits_service import install_gpt_sovits_launch_agent
from apps.shell.gpt_sovits_service import uninstall_gpt_sovits_launch_agent
from apps.shell.launcher_notifications import LauncherNotificationTracker
from apps.shell.live2d_resources import import_live2d_archive_draft
from apps.shell.live2d_resources import prepare_live2d_model_path_draft
from apps.shell.tts_resources import get_tts_voice_resource_info
from apps.shell.tts_resources import import_tts_voice_archive_draft
from apps.shell.installer_api import InstallerWebViewAPI
from apps.shell.main_api import MainWindowAPI
from apps.shell.mode_settings import apply_settings_changes
from apps.shell.mode_settings import serialize_mode_window_data
from apps.shell.proactive import ProactiveDesktopService
from apps.shell.proactive import get_proactive_chat_session
from apps.shell.tts import TTSService

router = APIRouter(prefix="/ui", tags=["UI"])
_launcher_notifications: dict[str, LauncherNotificationTracker] = {}
_launcher_proactive_services: dict[tuple[str, int], ProactiveDesktopService] = {}
_launcher_tts_services: dict[int, TTSService] = {}
_launcher_last_tts_attention: dict[int, str] = {}
_launcher_pending_tts_attention: dict[int, str] = {}
_launcher_completed_tts_attention: dict[int, str] = {}


class SendChatMessageRequest(BaseModel):
    text: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class LauncherAckRequest(BaseModel):
    mode: str = "bubble"


class LauncherQuickMessageRequest(BaseModel):
    text: str
    mode: str = "bubble"
    session_id: str = ""


class LauncherWorkAreaRequest(BaseModel):
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class LauncherPositionRequest(BaseModel):
    mode: str = "bubble"
    x: int
    y: int
    width: int = 0
    height: int = 0
    work_area: LauncherWorkAreaRequest | None = None


class LoadChatSessionRequest(BaseModel):
    session_id: str


class SettingsUpdateRequest(BaseModel):
    changes: dict[str, Any]


class TerminalCommandRequest(BaseModel):
    command: str


class HermesConfigUpdateRequest(BaseModel):
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    image_input_mode: str | None = None
    vision_provider: str | None = None
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None


class HermesToolConfigUpdateRequest(BaseModel):
    tool_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class HermesToolConfigTestRequest(BaseModel):
    tool_id: str


class HermesUpdateRunRequest(BaseModel):
    backup: bool = False


class TtsTestRequest(BaseModel):
    text: str = "八千代语音测试成功。主动关怀播报已经可以正常调用。"


class ScreenPermissionRequest(BaseModel):
    open_settings: bool = True


class ProactiveTestRequest(BaseModel):
    mode: str = "bubble"


class BackupCreateRequest(BaseModel):
    overwrite_latest: bool = False


class BackupPathRequest(BaseModel):
    backup_path: str = ""


class UninstallRunRequest(BaseModel):
    scope: str = "yachiyo_only"
    keep_config: bool = True
    confirm_text: str = ""


class Live2DResourcePathRequest(BaseModel):
    path: str


class TtsResourcePathRequest(BaseModel):
    path: str


@router.get("/dashboard")
async def get_dashboard() -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).get_dashboard_data()


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).get_settings_data()


@router.post("/settings")
async def update_settings(request: SettingsUpdateRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).update_settings(request.changes)


@router.post("/tts/test")
async def test_proactive_tts(request: TtsTestRequest) -> dict[str, Any]:
    runtime = get_runtime()

    def _run_test() -> dict[str, Any]:
        tts_config = getattr(runtime.config, "tts", None)
        if tts_config is None:
            return {
                "ok": False,
                "success": False,
                "provider": "none",
                "message": "TTS 配置不存在",
            }
        service = TTSService(tts_config)
        status = service.speak_sync(request.text)
        return {
            "tool": "proactive_tts",
            **status,
        }

    return await asyncio.to_thread(_run_test)


@router.get("/tts/voice-resource")
async def get_tts_voice_resource() -> dict[str, Any]:
    return get_tts_voice_resource_info()


@router.post("/tts/voice-resource/import")
async def import_tts_voice_archive_path(request: TtsResourcePathRequest) -> dict[str, Any]:
    return import_tts_voice_archive_draft(Path(request.path))


@router.get("/tts/gpt-sovits/service-status")
async def get_tts_gpt_sovits_service_status() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(get_gpt_sovits_service_status, runtime.config)


@router.post("/tts/gpt-sovits/service/install")
async def install_tts_gpt_sovits_service() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(install_gpt_sovits_launch_agent, runtime.config)


@router.post("/tts/gpt-sovits/service/uninstall")
async def uninstall_tts_gpt_sovits_service() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(uninstall_gpt_sovits_launch_agent, runtime.config)


@router.post("/proactive/screen-permission/check")
async def check_proactive_screen_permission(request: ScreenPermissionRequest) -> dict[str, Any]:
    def _check() -> dict[str, Any]:
        from apps.locald.screenshot import check_screen_capture_permission

        return check_screen_capture_permission(open_settings=request.open_settings)

    return await asyncio.to_thread(_check)


@router.post("/hermes/terminal-command")
async def open_hermes_terminal_command(request: TerminalCommandRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).open_terminal_command(request.command)


@router.post("/hermes/diagnostic-command")
async def run_hermes_diagnostic_command(request: TerminalCommandRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).run_hermes_diagnostic_command,
        request.command,
    )


@router.get("/hermes/diagnostics/cache")
async def get_hermes_diagnostic_cache() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).get_hermes_diagnostic_cache
    )


@router.post("/hermes/connection-test")
async def test_hermes_connection() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).test_hermes_connection
    )


@router.post("/hermes/image-connection-test")
async def test_hermes_image_connection() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).test_hermes_image_connection
    )


@router.get("/hermes/config")
async def get_hermes_configuration() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).get_hermes_configuration
    )


@router.post("/hermes/config")
async def update_hermes_configuration(request: HermesConfigUpdateRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).update_hermes_configuration,
        request.model_dump(exclude_none=True),
    )


@router.get("/hermes/tools/config")
async def get_hermes_tool_config() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).get_hermes_tool_config
    )


@router.post("/hermes/tools/config")
async def update_hermes_tool_config(request: HermesToolConfigUpdateRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).update_hermes_tool_config,
        request.tool_id,
        request.changes,
    )


@router.post("/hermes/tools/config/test")
async def test_hermes_tool_config(request: HermesToolConfigTestRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).test_hermes_tool_config,
        request.tool_id,
    )


@router.post("/hermes/update/check")
async def check_hermes_update() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).check_hermes_update
    )


@router.post("/hermes/update/run")
async def update_hermes_agent(request: HermesUpdateRunRequest | None = None) -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).update_hermes_agent,
        bool(request.backup) if request else False,
    )


@router.post("/hermes/tools/browser-cdp/launch")
async def launch_hermes_browser_cdp() -> dict[str, Any]:
    runtime = get_runtime()
    return await asyncio.to_thread(
        MainWindowAPI(runtime, runtime.config).launch_browser_cdp
    )


@router.post("/hermes/recheck")
async def recheck_hermes() -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).recheck_hermes()


@router.post("/bridge/restart")
async def restart_bridge() -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).restart_bridge()


@router.get("/backup/status")
async def get_backup_status() -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).get_backup_status()


@router.post("/backup/create")
async def create_backup(request: BackupCreateRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).create_backup(request.overwrite_latest)


@router.post("/backup/restore")
async def restore_backup(request: BackupPathRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).restore_backup(request.backup_path)


@router.post("/backup/delete")
async def delete_backup(request: BackupPathRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).delete_backup(request.backup_path)


@router.post("/backup/open-location")
async def open_backup_location(request: BackupPathRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).open_backup_location(request.backup_path)


@router.get("/uninstall/preview")
async def get_uninstall_preview(scope: str = "yachiyo_only", keep_config: bool = True) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).get_uninstall_preview(scope, keep_config)


@router.post("/uninstall/run")
async def run_uninstall(request: UninstallRunRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return MainWindowAPI(runtime, runtime.config).run_uninstall(
        request.scope,
        request.keep_config,
        request.confirm_text,
    )


@router.post("/installer/install")
async def start_hermes_install() -> dict[str, Any]:
    return InstallerWebViewAPI().install_hermes()


@router.get("/installer/install/progress")
async def get_hermes_install_progress() -> dict[str, Any]:
    return InstallerWebViewAPI().get_install_progress()


@router.post("/installer/workspace/initialize")
async def initialize_workspace() -> dict[str, Any]:
    return InstallerWebViewAPI().initialize_workspace()


@router.get("/installer/backup/status")
async def get_installer_backup_status() -> dict[str, Any]:
    return InstallerWebViewAPI().get_backup_status()


@router.post("/installer/backup/import")
async def import_installer_backup() -> dict[str, Any]:
    return InstallerWebViewAPI().import_backup()


@router.post("/installer/hermes/setup-terminal")
async def open_installer_setup_terminal() -> dict[str, Any]:
    return InstallerWebViewAPI().open_hermes_setup_terminal()


@router.get("/installer/hermes/setup-process")
async def get_installer_setup_process() -> dict[str, Any]:
    return InstallerWebViewAPI().check_setup_process()


@router.post("/installer/status/recheck")
async def recheck_installer_status() -> dict[str, Any]:
    runtime = get_runtime()
    result = InstallerWebViewAPI().recheck_status()
    try:
        runtime.refresh_hermes_installation()
        result["executor_refresh"] = runtime.refresh_task_runner_executor()
    except Exception as exc:
        result["refresh_error"] = str(exc)
    return result


@router.post("/live2d/model-path/prepare")
async def prepare_live2d_model_path(request: Live2DResourcePathRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return prepare_live2d_model_path_draft(runtime.config, Path(request.path))


@router.post("/live2d/archive/import")
async def import_live2d_archive_path(request: Live2DResourcePathRequest) -> dict[str, Any]:
    runtime = get_runtime()
    return import_live2d_archive_draft(runtime.config, Path(request.path))


@router.get("/chat/messages")
async def get_chat_messages(limit: int = 80) -> dict[str, Any]:
    return ChatAPI(get_runtime()).get_messages(limit)


@router.post("/chat/messages")
async def send_chat_message(request: SendChatMessageRequest) -> dict[str, Any]:
    return ChatAPI(get_runtime()).send_message(request.text, request.attachments)


@router.get("/chat/attachments/{attachment_id}")
async def get_chat_attachment(attachment_id: str) -> FileResponse:
    attachment = ChatAPI(get_runtime()).get_attachment_file(attachment_id)
    if not attachment.get("ok"):
        raise HTTPException(status_code=404, detail=attachment.get("error") or "附件不存在")
    return FileResponse(
        attachment["path"],
        media_type=attachment.get("mime_type") or "image/png",
        filename=attachment.get("name") or "image",
        content_disposition_type="inline",
    )


@router.get("/chat/session")
async def get_chat_session() -> dict[str, Any]:
    return ChatAPI(get_runtime()).get_session_info()


@router.post("/chat/session/clear")
async def clear_chat_session() -> dict[str, Any]:
    return ChatAPI(get_runtime()).clear_session()


@router.post("/chat/session/cancel")
async def cancel_chat_session_tasks() -> dict[str, Any]:
    return ChatAPI(get_runtime()).cancel_current_tasks()


@router.post("/chat/session/delete")
async def delete_chat_session() -> dict[str, Any]:
    return ChatAPI(get_runtime()).delete_current_session()


@router.get("/chat/sessions")
async def list_chat_sessions(limit: int = 20) -> dict[str, Any]:
    return ChatAPI(get_runtime()).list_sessions(limit)


@router.post("/chat/sessions/load")
async def load_chat_session(request: LoadChatSessionRequest) -> dict[str, Any]:
    return ChatAPI(get_runtime()).load_session(request.session_id)


@router.get("/chat/executor")
async def get_chat_executor() -> dict[str, Any]:
    return ChatAPI(get_runtime()).get_executor_info()


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _bubble_avatar_url(config: Any) -> str:
    avatar_path = Path(str(getattr(config, "avatar_path", "") or DEFAULT_BUBBLE_AVATAR_PATH)).expanduser()
    if not avatar_path.exists():
        avatar_path = DEFAULT_BUBBLE_AVATAR_PATH
    try:
        return data_uri(avatar_path)
    except Exception:
        return data_uri(DEFAULT_BUBBLE_AVATAR_PATH)


def _launcher_proactive_service(runtime: Any, mode_id: str, mode_config: Any) -> ProactiveDesktopService:
    key = (mode_id, id(runtime))
    return _launcher_proactive_services.setdefault(
        key,
        ProactiveDesktopService(runtime, mode_config),
    )


def _launcher_proactive_state(runtime: Any, mode_id: str, mode_config: Any) -> dict[str, Any]:
    return _launcher_proactive_service(runtime, mode_id, mode_config).get_state()


def _mode_config_for_launcher(runtime: Any, mode_id: str) -> Any:
    return runtime.config.live2d_mode if mode_id == "live2d" else runtime.config.bubble_mode


def _live2d_resource_payload(config: Any) -> dict[str, Any]:
    resource_info = getattr(config, "resource_info", None)
    if not callable(resource_info):
        return {"available": False, "state": "unknown", "status_label": "Live2D 资源状态未知"}
    resource = resource_info()
    summary = getattr(resource, "summary", None)
    return {
        "available": getattr(getattr(resource, "state", None), "value", "") == "path_valid",
        "state": getattr(getattr(resource, "state", None), "value", "unknown"),
        "display_name": getattr(resource, "display_name", "Live2D 角色"),
        "source": getattr(resource, "source", ""),
        "source_label": getattr(resource, "source_label", ""),
        "status_label": getattr(resource, "status_label", ""),
        "help_text": getattr(resource, "help_text", ""),
        "effective_model_path": getattr(resource, "effective_model_path", ""),
        "default_assets_root_display": getattr(resource, "default_assets_root_display", ""),
        "releases_url": getattr(resource, "releases_url", ""),
        "renderer_entry": getattr(summary, "renderer_entry", "") if summary else "",
    }


def _live2d_preview_url(config: Any) -> str:
    try:
        resolved_path = config.resolve_model_path()
        preview_path = find_live2d_preview_path(resolved_path or "")
    except Exception:
        preview_path = DEFAULT_BUBBLE_AVATAR_PATH
    return data_uri(preview_path)


def _bridge_state() -> str:
    try:
        from apps.bridge.server import get_bridge_state

        return get_bridge_state()
    except Exception:
        return "not_started"


def _bridge_running_config(config: Any) -> dict[str, Any]:
    try:
        from apps.bridge.server import get_running_config

        return get_running_config()
    except Exception:
        return {"host": getattr(config, "bridge_host", "127.0.0.1"), "port": getattr(config, "bridge_port", 8420)}


def _live2d_model_url(app_config: Any, resource: dict[str, Any]) -> str:
    renderer_entry = str(resource.get("renderer_entry") or "")
    if not renderer_entry:
        return ""
    try:
        root = app_config.live2d_mode.resolve_model_path()
        if root is None:
            return ""
        entry = Path(renderer_entry).expanduser().resolve()
        rel_path = entry.relative_to(Path(root).expanduser().resolve()).as_posix()
    except Exception:
        return ""

    running = _bridge_running_config(app_config)
    host = running.get("host") or getattr(app_config, "bridge_host", "127.0.0.1")
    port = running.get("port") or getattr(app_config, "bridge_port", 8420)
    try:
        from apps.bridge.server import get_live2d_asset_token

        token = get_live2d_asset_token()
    except Exception:
        token = ""
    suffix = f"?{urlencode({'token': token})}" if token else ""
    return f"http://{host}:{port}/live2d/assets/{quote(rel_path, safe='/')}{suffix}"


def _live2d_renderer_payload(app_config: Any, resource: dict[str, Any]) -> dict[str, Any]:
    model_url = _live2d_model_url(app_config, resource)
    bridge_state = _bridge_state()
    resource_state = str(resource.get("state") or "")
    enabled = (
        bool(model_url)
        and bridge_state == "running"
        and bool(getattr(app_config, "bridge_enabled", True))
        and resource_state in {"path_valid", "loaded"}
    )
    if resource_state not in {"path_valid", "loaded"}:
        reason = str(resource.get("help_text") or resource.get("status_label") or "")
    elif bridge_state != "running":
        reason = "Bridge 未运行，暂时无法加载 Live2D 模型"
    elif not model_url:
        reason = "未找到可加载的 model3.json 入口"
    else:
        reason = ""
    live2d = app_config.live2d_mode
    resource_info = getattr(live2d, "resource_info", None)
    summary = getattr(resource_info(), "summary", None) if callable(resource_info) else None
    return {
        "enabled": enabled,
        "model_url": model_url,
        "reason": reason,
        "scale": getattr(live2d, "scale", 1.0),
        "mouse_follow_enabled": getattr(live2d, "mouse_follow_enabled", True),
        "idle_motion_group": getattr(live2d, "idle_motion_group", "Idle"),
        "enable_expressions": getattr(live2d, "enable_expressions", False),
        "enable_physics": getattr(live2d, "enable_physics", False),
        "expression_mappings": {
            "thinking": getattr(live2d, "thinking_expression", ""),
            "message": getattr(live2d, "message_expression", ""),
            "failed": getattr(live2d, "failed_expression", ""),
            "attention": getattr(live2d, "attention_expression", ""),
        },
        "expressions": getattr(summary, "expressions", []) if summary else [],
        "motion_groups": getattr(summary, "motion_groups", {}) if summary else {},
    }


def _maybe_trigger_proactive_tts(
    runtime: Any,
    mode_id: str,
    proactive: dict[str, Any],
) -> dict[str, Any]:
    config = runtime.config
    tts_config = getattr(config, "tts", None)
    if tts_config is None:
        return {"enabled": False, "provider": "none", "ok": True, "message": "TTS 未启用"}
    key = id(runtime)
    service = _launcher_tts_services.setdefault(key, TTSService(tts_config))
    if not getattr(tts_config, "enabled", False) or getattr(tts_config, "provider", "none") == "none":
        return service.get_status()
    if not proactive.get("has_attention"):
        return service.get_status()
    text = str(
        proactive.get("attention_text")
        or proactive.get("message")
        or proactive.get("result")
        or ""
    ).strip()
    if not text:
        return service.get_status()
    attention_key = str(proactive.get("task_id") or text)
    if attention_key == _launcher_pending_tts_attention.get(key, ""):
        return {
            **service.get_status(),
            "pending_audio": True,
            "attention_key": attention_key,
            "message": "主动关怀语音生成中",
        }
    if attention_key == _launcher_completed_tts_attention.get(key, ""):
        return {
            **service.get_status(),
            "audio_ready": True,
            "attention_key": attention_key,
        }
    if attention_key == _launcher_last_tts_attention.get(key, ""):
        return service.get_status()

    output_path, attachment_id, mime_type = _allocate_tts_audio_output(runtime, tts_config)
    task_id = str(proactive.get("task_id") or "")

    def on_complete(status: dict[str, Any]) -> None:
        if task_id:
            _attach_proactive_tts_audio(runtime, task_id, status, attachment_id, output_path, mime_type)
        _launcher_pending_tts_attention.pop(key, None)
        _launcher_completed_tts_attention[key] = attention_key

    status = service.speak_async(
        text,
        play=True,
        output_path=str(output_path) if output_path else None,
        on_complete=on_complete,
    )
    if status.get("scheduled"):
        _launcher_last_tts_attention[key] = attention_key
        _launcher_pending_tts_attention[key] = attention_key
        status["pending_audio"] = True
        status["attention_key"] = attention_key
    else:
        _launcher_completed_tts_attention[key] = attention_key
    return status


def _allocate_tts_audio_output(runtime: Any, tts_config: Any) -> tuple[Path | None, str, str]:
    provider = str(getattr(tts_config, "provider", "") or "")
    if provider not in {"gpt-sovits", "http"}:
        return None, "", ""
    media_type = str(getattr(tts_config, "gsv_media_type", "wav") or "wav").strip().lower().lstrip(".")
    suffix = f".{media_type if media_type in {'wav', 'mp3', 'ogg', 'flac'} else 'wav'}"
    chat_session = get_proactive_chat_session(runtime)
    session_id = str(getattr(chat_session, "session_id", "") or "proactive")
    attachment_id, output_path = allocate_chat_attachment_path(session_id, suffix)
    return output_path, attachment_id, audio_mime_type_for_suffix(suffix)


def _attach_proactive_tts_audio(
    runtime: Any,
    task_id: str,
    status: dict[str, Any],
    attachment_id: str,
    output_path: Path | None,
    mime_type: str,
) -> None:
    if not status.get("ok") or not status.get("audio_path") or not output_path or not attachment_id:
        return
    path = Path(str(status.get("audio_path") or output_path))
    if not path.exists():
        return
    chat_session = get_proactive_chat_session(runtime)
    if chat_session is None:
        return
    existing = chat_session.get_assistant_message_for_task(task_id)
    if existing is None:
        return
    task = runtime.state.get_task(task_id)
    content = str(getattr(task, "result", "") or existing.content or "")
    attachments = [
        item for item in list(existing.attachments or [])
        if not (isinstance(item, dict) and item.get("kind") == "audio" and item.get("source") == "proactive_tts")
    ]
    attachment = chat_attachment_record(
        attachment_id,
        path,
        kind="audio",
        name="主动关怀语音." + path.suffix.lstrip("."),
        mime_type=str(status.get("mime_type") or mime_type or "audio/wav"),
    )
    attachment["source"] = "proactive_tts"
    attachment["spoken_text"] = str(status.get("spoken_text") or "")
    attachments.append(attachment)
    chat_session.upsert_assistant_message(
        task_id=task_id,
        content=content,
        status=MessageStatus.COMPLETED,
        error=existing.error,
        attachments=attachments,
    )


@router.get("/launcher")
async def get_launcher_view(mode: str = "bubble") -> dict[str, Any]:
    runtime = get_runtime()
    mode_id = "live2d" if mode == "live2d" else "bubble"
    bridge = ChatBridge(runtime)
    tts_status: dict[str, Any] = {}
    if mode_id == "live2d":
        live2d_config = runtime.config.live2d_mode
        summary_count = 3
        proactive = _launcher_proactive_state(runtime, mode_id, live2d_config)
        resource = _live2d_resource_payload(live2d_config)
        launcher_config: dict[str, Any] = {
            "show_reply_bubble": live2d_config.show_reply_bubble,
            "enable_quick_input": live2d_config.enable_quick_input,
            "click_action": live2d_config.click_action,
            "default_open_behavior": live2d_config.default_open_behavior,
            "position_anchor": getattr(live2d_config, "position_anchor", "right_bottom"),
            "scale": getattr(live2d_config, "scale", 1.0),
            "mouse_follow_enabled": getattr(live2d_config, "mouse_follow_enabled", True),
            "preview_url": _live2d_preview_url(live2d_config),
            "resource": resource,
            "renderer": _live2d_renderer_payload(runtime.config, resource),
        }
    else:
        bubble_config = runtime.config.bubble_mode
        summary_count = bubble_config.summary_count
        proactive = _launcher_proactive_state(runtime, mode_id, bubble_config)
        launcher_config = {
            "default_display": bubble_config.default_display,
            "expand_trigger": "click",
            "show_unread_dot": bubble_config.show_unread_dot,
            "auto_hide": bubble_config.auto_hide,
            "opacity": bubble_config.opacity,
            "avatar_url": _bubble_avatar_url(bubble_config),
            "suppress_status_dot": False,
        }

    chat = bridge.get_conversation_overview(summary_count=summary_count, session_limit=3)
    tts_status = _maybe_trigger_proactive_tts(runtime, mode_id, proactive)
    visible_chat = chat
    visible_proactive = proactive
    if tts_status.get("pending_audio"):
        visible_chat = dict(chat)
        visible_chat["latest_notifiable_message"] = {}
        visible_chat["latest_reply"] = ""
        visible_chat["latest_reply_full"] = ""
        visible_proactive = {
            **proactive,
            "has_attention": False,
            "status": "tts_pending",
            "message": "主动关怀语音生成中",
            "attention_text": "",
        }
    tracker = _launcher_notifications.setdefault(mode_id, LauncherNotificationTracker())
    notification = tracker.update(visible_chat, external_attention=bool(visible_proactive.get("has_attention")))
    latest_status = "ready"
    if visible_chat.get("empty"):
        latest_status = "empty"
    elif visible_chat.get("is_processing"):
        latest_status = "processing"
    elif notification.get("has_unread"):
        latest_message = notification.get("latest_message")
        if isinstance(latest_message, dict):
            latest_status = str(latest_message.get("status") or "ready")

    return {
        "ok": True,
        "mode": mode_id,
        "chat": visible_chat,
        "proactive": visible_proactive,
        "notification": notification,
        "tts": tts_status,
        "launcher": {
            **launcher_config,
            "has_attention": bool(notification.get("has_unread")),
            "latest_status": latest_status,
            "status_label": visible_chat.get("status_label", "就绪"),
            "latest_reply": visible_chat.get("latest_reply", ""),
            "latest_reply_full": visible_chat.get("latest_reply_full", ""),
        },
    }


@router.post("/launcher/ack")
async def acknowledge_launcher(request: LauncherAckRequest) -> dict[str, Any]:
    mode_id = "live2d" if request.mode == "live2d" else "bubble"
    runtime = get_runtime()
    chat = ChatBridge(runtime).get_conversation_overview(summary_count=3, session_limit=3)
    tracker = _launcher_notifications.setdefault(mode_id, LauncherNotificationTracker())
    tracker.acknowledge(chat)
    service = _launcher_proactive_services.get((mode_id, id(runtime)))
    session_id = ""
    if service is not None:
        service.acknowledge()
        session_id = service.session_id
    else:
        chat_session = get_proactive_chat_session(runtime)
        session_id = str(getattr(chat_session, "session_id", "") or "")
    return {"ok": True, "mode": mode_id, "session_id": session_id}


@router.post("/proactive/test")
async def trigger_proactive_test(request: ProactiveTestRequest) -> dict[str, Any]:
    runtime = get_runtime()
    mode_id = "live2d" if request.mode == "live2d" else "bubble"
    service = _launcher_proactive_service(
        runtime,
        mode_id,
        _mode_config_for_launcher(runtime, mode_id),
    )
    return {"mode": mode_id, **service.trigger_now()}


@router.post("/launcher/quick-message")
async def send_launcher_quick_message(request: LauncherQuickMessageRequest) -> dict[str, Any]:
    runtime = get_runtime()
    session_id = str(request.session_id or "").strip()
    if session_id:
        loaded = ChatAPI(runtime).load_session(session_id)
        if not loaded.get("ok"):
            return loaded
        mode_id = "live2d" if request.mode == "live2d" else "bubble"
        service = _launcher_proactive_services.get((mode_id, id(runtime)))
        if service is not None and session_id == service.session_id:
            service.acknowledge()
    return ChatBridge(runtime).send_quick_message(request.text)


@router.post("/launcher/position")
async def save_launcher_position(request: LauncherPositionRequest) -> dict[str, Any]:
    runtime = get_runtime()
    mode_id = "live2d" if request.mode == "live2d" else "bubble"
    if mode_id == "live2d":
        changes: dict[str, Any] = {
            "live2d_mode.position_anchor": "custom",
            "live2d_mode.position_x": int(request.x),
            "live2d_mode.position_y": int(request.y),
        }
        if request.width > 0:
            changes["live2d_mode.width"] = int(request.width)
        if request.height > 0:
            changes["live2d_mode.height"] = int(request.height)
    else:
        area = request.work_area or LauncherWorkAreaRequest()
        width = max(1, int(request.width or runtime.config.bubble_mode.width))
        height = max(1, int(request.height or runtime.config.bubble_mode.height))
        margin = 24
        usable_width = max(1, int(area.width) - width - (margin * 2))
        usable_height = max(1, int(area.height) - height - (margin * 2))
        x_percent = _clamp_float((int(request.x) - int(area.x) - margin) / usable_width, 0.0, 1.0)
        y_percent = _clamp_float((int(request.y) - int(area.y) - margin) / usable_height, 0.0, 1.0)
        changes = {
            "bubble_mode.position_x": int(request.x),
            "bubble_mode.position_y": int(request.y),
            "bubble_mode.position_x_percent": x_percent,
            "bubble_mode.position_y_percent": y_percent,
        }
    result = apply_settings_changes(runtime.config, changes)
    return {"ok": bool(result.get("ok")), "mode": mode_id, "position": changes, **result}


@router.get("/modes/{mode_id}/settings")
async def get_mode_settings(mode_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    return serialize_mode_window_data(runtime.config, mode_id)
