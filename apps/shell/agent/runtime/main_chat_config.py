"""Main chat runtime config helpers for the legacy engine entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS = """
你是 Oha-Yachiyo 的日常桌面执行型 Agent，也是 Chat / Bubble / Live2D 的默认行动入口。
当用户提出可以由已授权工具完成的请求时，优先调用工具尝试执行，而不是只解释做法或要求用户自己操作。
常见意图映射：播放具体歌曲用 media.apple_music_play；打开/启动 Apple Music 并播放或泛化播放音乐用 media.apple_music_open_and_play；打开/启动非 Apple 的常见音乐 App 并泛化播放用 media.music_app_open_and_play；指定非 Apple 音乐 App 的暂停、继续、下一首、上一首用 media.music_app_control；泛化当前媒体的暂停、继续、下一首、上一首用 media.system_control；明确 Apple Music 的暂停、继续、下一首、上一首用 media.apple_music_control；询问 Apple Music 当前播放、播放状态或现在播放什么用 media.apple_music_status；打开 macOS 系统设置面板或权限页面用 system.settings_open；查询、调高、调低、设置、静音或取消静音系统音量用 system.volume；相对调亮或调暗屏幕亮度用 system.brightness；让显示器睡眠或关闭屏幕用 system.display_sleep；启动屏幕保护程序用 system.screen_saver_start；把用户明确给出的文本写入剪贴板用 clipboard.write；明确询问剪贴板内容用 clipboard.read；明确读取当前选中文本时先用 desktop.safe_shortcut(copy) 再用 clipboard.read；明确带正文的新建/创建备忘录或笔记用 notes.create；截图/看看屏幕用 screen.capture；检查或诊断桌面权限、询问为什么不能控制/打开/点击/播放时用 desktop.permissions；询问当前窗口用 desktop.active_window；询问正在运行/打开的应用列表用 desktop.running_apps；询问窗口列表或某应用窗口用 desktop.windows；询问当前界面控件、按钮、输入框或可点击元素用 desktop.ui_elements；询问单个应用是否运行用 app.status；打开或聚焦应用用 app.open/app.focus；打开/聚焦应用后输入用户明确文本用 app.open_and_safe_type_text/app.focus_and_safe_type_text；打开/聚焦应用后执行白名单快捷动作用 app.open_and_safe_shortcut/app.focus_and_safe_shortcut；打开/聚焦应用后按安全导航键用 app.open_and_safe_key/app.focus_and_safe_key；打开/聚焦应用后发送任意明确快捷键用 app.open_and_hotkey/app.focus_and_hotkey（需要审批）；打开/聚焦应用后滚动用 app.open_and_safe_scroll/app.focus_and_safe_scroll；打开/聚焦应用后点击用户明确坐标用 app.open_and_safe_click/app.focus_and_safe_click；打开/聚焦应用后按可见名称点击控件或按钮用 app.open_and_click_ui_element/app.focus_and_click_ui_element（需要审批）；打开/聚焦应用后按可见输入框名称输入文字用 app.open_and_type_into_ui_element/app.focus_and_type_into_ui_element（需要审批）；打开常见网站名或搜索查询、URL 用 browser.open_url；打开网页后读取正文用 browser.open_url_and_extract_text；读取当前网页正文用 browser.extract_text；打开网页后截图用 browser.open_url_and_screenshot；点击当前网页元素用 browser.click，搜索结果可用 selector search-result=N（需要审批）；在 Finder/访达中显示文件或文件夹用 desktop.reveal_path，打开安全本地路径用 desktop.open_path；聚焦指定应用标题匹配窗口用 app.focus_window；显示/还原指定应用用 app.show；隐藏指定应用用 app.hide；最小化指定应用窗口用 app.minimize；退出或关闭应用用 app.quit（需要审批）；隐藏当前/前台应用用 desktop.hide_app；显示所有隐藏应用用 desktop.show_all_apps；最小化当前/前台窗口用 desktop.minimize_window；关闭当前/前台窗口用 desktop.close_window（需要审批）；复制、复制当前网页链接、粘贴、全选、撤销、重做、查找、新建标签页、关闭标签页、切换上/下一个标签页、切换当前应用上/下一个窗口、切换当前窗口全屏、打开 Mission Control、显示当前应用窗口、打开 Spotlight、打开 Emoji 面板、锁屏、打开强制退出窗口、新建窗口、新建文档、新建笔记、新建提醒、新建日程、刷新、返回/前进网页、重新打开关闭的标签页等白名单快捷动作用 desktop.safe_shortcut；明确的 Escape、Tab、Shift+Tab、方向键、Home、End、Page Up、Page Down 前台导航按键和显示桌面用 desktop.safe_key；用户明确给出的前台输入文本用 desktop.safe_type_text；用户明确要求提交搜索/查找时用 desktop.search_submit；用户明确给出的单击坐标用 desktop.safe_click；明确的当前/前台向上或向下滚动、Page Up/Page Down 用 desktop.safe_scroll；按可见名称点击当前/前台控件或按钮用 desktop.click_ui_element（需要审批）；按可见输入框名称聚焦并输入文字用 desktop.type_into_ui_element（需要审批）；明确发送、提交或确认当前前台内容用 desktop.submit_foreground（高风险，需要审批）；明确的终端命令用 terminal.run（高风险，需要审批）；任意前台快捷键、删除、退格仍用 desktop.hotkey；非明确文本输入、坐标双击或模型推断坐标点击用 desktop.type_text/desktop.click。
低风险桌面动作默认直接执行，并把结果、失败、fallback 和 artifact 通过 Run Timeline 留痕；不要把低风险动作改成让用户手动操作。
当用户把多个明确低风险桌面动作串在一句话里时，可以按顺序执行这些工具并逐步留痕；如果序列中遇到需要审批的动作，交给 Runtime 生成审批卡后暂停。
前台点击、输入、快捷键、网页点击和网页输入属于中风险动作；要直接发起对应工具调用，让 Runtime 生成审批卡并在批准后继续执行，不要改成让用户手动操作。
如果系统权限缺失，明确说明缺少的权限和用户需要打开的系统设置入口；不要假装已经完成动作。
高风险动作仍必须遵守 approval/policy gate，尤其是删除或覆盖用户文件、发送消息、支付、系统设置、裸 shell、凭据相关操作。
""".strip()


class MainChatRuntimeConfigBuilder:
    """Builds the runtime agent config used by the daily Chat entrypoint."""

    def __init__(
        self,
        *,
        main_chat_agent_id: str,
        agent_workspaces_dir: Path,
        workspace_status: Callable[[], dict[str, Any]],
        compile_tool_policy: Callable[[str, Any], dict[str, Any]],
        compile_workspace_policy: Callable[[Any], dict[str, Any]],
        trust_workspace_from_policy: Callable[..., None],
        memory_tool_names: Sequence[str],
        future_task_tool_names: Sequence[str],
        desktop_tool_names: Sequence[str] = (),
        default_workspace_name: str = "builtin-yachiyo-main",
    ) -> None:
        self._main_chat_agent_id = main_chat_agent_id
        self._agent_workspaces_dir = agent_workspaces_dir
        self._workspace_status = workspace_status
        self._compile_tool_policy = compile_tool_policy
        self._compile_workspace_policy = compile_workspace_policy
        self._trust_workspace_from_policy = trust_workspace_from_policy
        self._memory_tool_names = list(memory_tool_names)
        self._future_task_tool_names = list(future_task_tool_names)
        self._desktop_tool_names = list(desktop_tool_names)
        self._default_workspace_name = default_workspace_name

    def _default_workspace_dir(self) -> Path:
        return self._agent_workspaces_dir / self._default_workspace_name

    def workspace_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(policy, dict):
            compiled = self._compile_workspace_policy(policy)
        else:
            workspace = self._workspace_status()
            dirs = workspace.get("dirs") if isinstance(workspace.get("dirs"), dict) else {}
            if workspace.get("initialized") and dirs.get("projects"):
                workdir = Path(str(dirs["projects"]))
            else:
                workdir = self._default_workspace_dir()
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = self._compile_workspace_policy(
                {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                }
            )
        if not str(compiled.get("default_workdir") or "").strip():
            workdir = self._default_workspace_dir()
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = {**compiled, "default_workdir": str(workdir)}
        self._trust_workspace_from_policy(compiled, source="main_chat", commit=True)
        return compiled

    def virtual_workspace_policy(self) -> dict[str, Any]:
        return self._compile_workspace_policy(
            {
                "default_workdir": str(self._default_workspace_dir()),
                "readable_scopes": ["."],
                "writable_scopes": [],
            }
        )

    def tool_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        base_allowed = [
            "workspace.list",
            "workspace.read",
            *self._desktop_tool_names,
            "terminal.run",
            *self._memory_tool_names,
            *self._future_task_tool_names,
            "artifact.write",
        ]
        if isinstance(policy, Mapping):
            raw = dict(policy)
            raw["allowed_tools"] = _unique_tools([
                *base_allowed,
                *_raw_allowed_tools(policy),
            ])
        else:
            raw = {"allowed_tools": base_allowed}
        return self._compile_tool_policy("custom", raw)

    def agent_config(
        self,
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self._main_chat_agent_id,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "category": "orchestrator",
            "instructions": MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS,
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": str(model_profile_id or "").strip(),
            "vision_model_profile_id": "",
            "model_config": {},
            "tool_policy": self.tool_policy(tool_policy),
            "workspace_policy": self.workspace_policy(workspace_policy),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
        }

    def virtual_agent(self, *, default_profile_id: str = "") -> dict[str, Any]:
        clean_profile_id = str(default_profile_id or "").strip()
        return {
            "agent_id": self._main_chat_agent_id,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "description": "Oha-Yachiyo main chat system agent.",
            "avatar_url": "",
            "category": "orchestrator",
            "instructions": MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS,
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": clean_profile_id,
            "vision_model_profile_id": "",
            "model_config": {
                "provider": "model_profile",
                "base_url": "",
                "model": "",
                "api_key_configured": bool(clean_profile_id),
            },
            "tool_policy": self.tool_policy(),
            "workspace_policy": self.virtual_workspace_policy(),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
            "virtual": True,
            "system": True,
            "builtin": True,
            "editable": False,
            "deletable": False,
            "created_at": "",
            "updated_at": "",
        }


class MainChatVirtualAgentProjector:
    """Projects the built-in daily chat Agent with the current default profile."""

    def __init__(
        self,
        *,
        main_chat_config: MainChatRuntimeConfigBuilder,
        default_profile_id: Callable[[], str],
    ) -> None:
        self._main_chat_config = main_chat_config
        self._default_profile_id = default_profile_id

    def virtual_agent(self) -> dict[str, Any]:
        try:
            default_profile_id = str(self._default_profile_id() or "").strip()
        except Exception:
            default_profile_id = ""
        return self._main_chat_config.virtual_agent(default_profile_id=default_profile_id)


def _raw_allowed_tools(policy: Mapping[str, Any]) -> list[str]:
    raw_allowed = policy.get("allowed_tools")
    if isinstance(raw_allowed, str):
        raw_allowed = [raw_allowed]
    if not isinstance(raw_allowed, Sequence):
        return []
    return [str(tool or "").strip() for tool in raw_allowed if str(tool or "").strip()]


def _unique_tools(tools: Sequence[str]) -> list[str]:
    result: list[str] = []
    for tool in tools:
        clean = str(tool or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
