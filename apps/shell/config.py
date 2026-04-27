"""用户配置读写"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from apps.shell.assets import (
    DEFAULT_BUBBLE_AVATAR_PATH,
    DEFAULT_LIVE2D_MODEL_DIR,
    LEGACY_BUNDLED_LIVE2D_MODEL_DIR,
    LIVE2D_RELEASES_URL,
    find_default_live2d_model_dir,
    get_user_live2d_assets_dir,
    project_display_path,
)

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".hermes-yachiyo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# 合法的 display_mode 值，与 DisplayMode 枚举保持同步。
# 主控台不再是 display mode；旧配置中的 "window" 会迁移到 "bubble"。
DisplayModeValue = Literal["bubble", "live2d"]
BubbleDisplayValue = Literal["icon", "summary", "recent_reply"]
BubbleExpandTriggerValue = Literal["click"]
Live2DClickActionValue = Literal["focus_stage", "open_chat", "toggle_reply"]
Live2DDefaultOpenValue = Literal["stage", "reply_bubble", "chat_input"]
TTSProviderValue = Literal["none", "http", "command"]


class ModelState(StrEnum):
    """Live2D 模型配置校验状态。

    状态迁移路径（→ 表示用户操作或系统变化可触发）：

        NOT_CONFIGURED  → 填写 model_name + model_path
        PATH_INVALID    → 创建或修正目录
        PATH_NOT_LIVE2D → 在目录内放入 .moc3 / .model3.json 文件
        PATH_VALID      → live2d_renderer.py 实现后自动升级
        LOADED          （未来，由 Live2DRenderer 设置）
    """

    NOT_CONFIGURED  = "not_configured"   # model_name 或 model_path 为空
    PATH_INVALID    = "path_invalid"     # 路径已填写但目录不存在
    PATH_NOT_LIVE2D = "path_not_live2d"  # 目录存在但不含 Live2D 模型文件
    PATH_VALID      = "path_valid"       # 目录含模型文件，渲染器尚未实现
    LOADED          = "loaded"           # 渲染器已加载模型（未来）


# Live2D Cubism 模型目录的特征文件（glob 模式）
# .moc3        — 二进制模型数据（Cubism 3/4 必须）
# .model3.json — 模型清单/描述符（Cubism 3/4 必须）
_LIVE2D_SIGNATURE_GLOBS = ("*.moc3", "*.model3.json")


def check_live2d_model_dir(path: Path) -> bool:
    """检查目录是否像一个 Live2D Cubism 模型目录。

    判断依据：在目录（含一级子目录）中找到至少一个 .moc3 或 .model3.json 文件。
    仅做文件名匹配，不解析文件内容。

    Returns:
        True  — 目录内有 Live2D 特征文件
        False — 目录为空或不含特征文件
    """
    for pattern in _LIVE2D_SIGNATURE_GLOBS:
        if any(path.glob(pattern)):
            return True
        if any(path.glob(f"*/{pattern}")):
            return True
    return False


@dataclass
class ModelSummary:
    """从模型目录扫描得到的最小摘要信息。

    仅做文件名级别的静态扫描，不加载任何数据。
    供设置页和状态条展示用，真正解析由未来 Live2DRenderer 负责。

    主候选字段（primary_*_abs）是未来 Live2DRenderer 的入口输入：
      - Live2DRenderer 通常以 .model3.json 为唯一入口
      - .moc3 路径由 model3.json 内部引用，此处仅作冗余提示
    """

    model3_json: str = ""          # 检测到的 .model3.json 文件名，无则空
    moc3_file: str = ""            # 检测到的 .moc3 文件名，无则空
    found_in_subdir: bool = False  # 特征文件是否位于子目录
    subdir_name: str = ""          # 子目录名（found_in_subdir=True 时）
    extra_moc3_count: int = 0      # 额外 .moc3 数量（多模型目录提示）

    # 主候选绝对路径 — 供未来 Live2DRenderer 直接消费
    primary_model3_json_abs: str = ""  # .model3.json 的绝对路径，渲染器首选入口
    primary_moc3_abs: str = ""         # .moc3 的绝对路径，model3.json 引用的兜底
    expressions: list[dict[str, str]] = field(default_factory=list)
    motion_groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """摘要是否为空（未找到任何特征文件）。"""
        return not self.model3_json and not self.moc3_file

    @property
    def renderer_entry(self) -> str:
        """渲染器推荐入口路径：优先 model3.json，其次 moc3，无则空字符串。"""
        return self.primary_model3_json_abs or self.primary_moc3_abs


@dataclass
class Live2DResourceInfo:
    """Live2D 资源解析结果，供设置页 / 模式壳 / 主控台统一消费。"""

    state: ModelState
    source: str
    source_label: str
    display_name: str
    configured_path: str = ""
    configured_path_display: str = ""
    effective_model_path: str = ""
    effective_model_path_display: str = ""
    default_assets_root: str = ""
    default_assets_root_display: str = ""
    releases_url: str = LIVE2D_RELEASES_URL
    status_label: str = ""
    help_text: str = ""
    summary: ModelSummary | None = None


def _resolve_scanned_model_dir(root: Path, summary: ModelSummary | None) -> Path:
    """Return the actual model directory that contains model files."""
    if summary and summary.found_in_subdir and summary.subdir_name:
        return (root / summary.subdir_name).resolve()
    return root.resolve()


def _read_live2d_manifest_metadata(model3_path: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, Any]]]]:
    """读取 model3.json 中声明的表情和动作列表，失败时返回空集合。"""
    try:
        data = json.loads(model3_path.read_text(encoding="utf-8"))
    except Exception:
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    refs = data.get("FileReferences")
    if not isinstance(refs, dict):
        return [], {}

    expressions: list[dict[str, str]] = []
    raw_expressions = refs.get("Expressions")
    if isinstance(raw_expressions, list):
        for index, item in enumerate(raw_expressions):
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("File") or "").strip()
            name = str(item.get("Name") or "").strip() or Path(file_path).stem or f"expression-{index + 1}"
            expressions.append({"name": name, "file": file_path})

    motion_groups: dict[str, list[dict[str, Any]]] = {}
    raw_motions = refs.get("Motions")
    if isinstance(raw_motions, dict):
        for group, items in raw_motions.items():
            if not isinstance(items, list):
                continue
            group_name = str(group or "").strip() or "default"
            motions: list[dict[str, Any]] = []
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                file_path = str(item.get("File") or "").strip()
                motions.append({
                    "group": group_name,
                    "index": index,
                    "file": file_path,
                    "display_name": Path(file_path).stem or f"{group_name}-{index + 1}",
                    "has_sound": bool(item.get("Sound")),
                })
            if motions:
                motion_groups[group_name] = motions
    return expressions, motion_groups


def _attach_live2d_manifest_metadata(summary: ModelSummary) -> None:
    if not summary.primary_model3_json_abs:
        return
    expressions, motion_groups = _read_live2d_manifest_metadata(Path(summary.primary_model3_json_abs))
    summary.expressions = expressions
    summary.motion_groups = motion_groups


def scan_live2d_model_dir(path: Path) -> ModelSummary:
    """扫描 Live2D 模型目录，返回最小文件摘要。

    扫描顺序：根目录优先，找不到再看一级子目录。
    每类文件只记录第一个（按文件名字母序），多余的计入 extra_moc3_count。
    主候选绝对路径（primary_*_abs）直接在此填充，供 Live2DRenderer 消费。
    """
    summary = ModelSummary()

    # 优先扫描根目录
    root_moc3 = sorted(path.glob("*.moc3"))
    root_json = sorted(path.glob("*.model3.json"))

    if root_moc3 or root_json:
        summary.found_in_subdir = False
        if root_moc3:
            summary.moc3_file = root_moc3[0].name
            summary.primary_moc3_abs = str(root_moc3[0].resolve())
            summary.extra_moc3_count = len(root_moc3) - 1
        if root_json:
            summary.model3_json = root_json[0].name
            summary.primary_model3_json_abs = str(root_json[0].resolve())
            _attach_live2d_manifest_metadata(summary)
        return summary

    # 根目录无特征文件，扫描一级子目录
    for subdir in sorted(p for p in path.iterdir() if p.is_dir()):
        sub_moc3 = sorted(subdir.glob("*.moc3"))
        sub_json = sorted(subdir.glob("*.model3.json"))
        if sub_moc3 or sub_json:
            summary.found_in_subdir = True
            summary.subdir_name = subdir.name
            if sub_moc3:
                summary.moc3_file = sub_moc3[0].name
                summary.primary_moc3_abs = str(sub_moc3[0].resolve())
                summary.extra_moc3_count = len(sub_moc3) - 1
            if sub_json:
                summary.model3_json = sub_json[0].name
                summary.primary_model3_json_abs = str(sub_json[0].resolve())
                _attach_live2d_manifest_metadata(summary)
            return summary  # 取第一个有内容的子目录即止

    return summary  # 空摘要


@dataclass
class WindowModeConfig:
    """主控台配置。

    主控台负责状态仪表盘、诊断与入口中心，因此配置聚焦在控制台视图本身，
    不直接承担完整聊天窗口的消息区配置。
    """

    width: int = 960
    height: int = 720
    recent_sessions_limit: int = 4
    recent_messages_limit: int = 3
    open_chat_on_start: bool = False
    show_runtime_panel: bool = True
    show_mode_overview: bool = True


@dataclass
class BubbleModeConfig:
    """Bubble 模式配置。"""

    width: int = 112
    height: int = 112
    position_x_percent: float = 1.0
    position_y_percent: float = 1.0
    position_x: int = 24
    position_y: int = 24
    always_on_top: bool = True
    edge_snap: bool = True
    expanded_on_start: bool = True
    # 兼容旧配置字段；hover 已废弃，加载时会统一规整为 click。
    expand_trigger: BubbleExpandTriggerValue = "click"
    default_display: BubbleDisplayValue = "summary"
    show_unread_dot: bool = True
    auto_hide: bool = False
    opacity: float = 0.92
    summary_count: int = 3
    avatar_path: str = str(DEFAULT_BUBBLE_AVATAR_PATH)
    proactive_enabled: bool = False
    proactive_desktop_watch_enabled: bool = False
    proactive_interval_seconds: int = 300


@dataclass
class AssistantConfig:
    """共享助手配置。"""

    persona_prompt: str = ""
    user_address: str = ""


@dataclass
class TTSConfig:
    """可选 TTS 配置。默认关闭，未配置时不影响聊天。"""

    enabled: bool = False
    provider: TTSProviderValue = "none"
    endpoint: str = ""
    command: str = ""
    voice: str = ""
    timeout_seconds: int = 20


@dataclass
class Live2DModeConfig:
    """Live2D 模式配置骨架。

    当前阶段仍是角色聊天壳，保留未来 renderer / moc3 / 动作系统的接入位。
    """

    model_name: str = ""  # 角色模型名，空字符串表示使用自动检测名称
    model_path: str = ""  # 显式模型目录路径；为空时自动在用户目录查找
    width: int = 420
    height: int = 680
    position_x: int = 48
    position_y: int = 48
    scale: float = 1.0                 # 角色缩放（参考 Live2DRenderer 的 SetScale）
    window_on_top: bool = True        # 角色窗口是否置顶
    show_on_all_spaces: bool = True    # macOS: 置顶时加入所有 Spaces / 全屏辅助层
    show_reply_bubble: bool = True
    default_open_behavior: Live2DDefaultOpenValue = "reply_bubble"
    click_action: Live2DClickActionValue = "open_chat"
    auto_open_chat_window: bool = False
    enable_quick_input: bool = True
    mouse_follow_enabled: bool = True
    idle_motion_group: str = "Idle"   # 待机动作组名（Live2D Cubism 约定）
    enable_expressions: bool = False  # 是否启用表情系统（等待渲染器支持）
    enable_physics: bool = False      # 是否启用物理模拟（等待渲染器支持）
    proactive_enabled: bool = False
    proactive_desktop_watch_enabled: bool = False
    proactive_interval_seconds: int = 300

    def has_explicit_model_path(self) -> bool:
        """用户是否显式填写了模型路径。"""
        return bool((self.model_path or "").strip())

    def resolve_model_path(self) -> Path | None:
        """返回当前实际要使用的模型目录。

        优先级：
          1. 用户显式填写的 model_path
          2. 用户目录 ~/.hermes/yachiyo/assets/live2d/ 下自动发现的有效模型
        """
        if self.has_explicit_model_path():
            return Path(self.model_path).expanduser()
        return find_default_live2d_model_dir(check_live2d_model_dir, get_user_live2d_assets_dir())

    def get_display_name(self, summary: "ModelSummary | None" = None, resolved_path: Path | None = None) -> str:
        """返回 UI 展示用模型名。"""
        if (self.model_name or "").strip():
            return self.model_name.strip()
        if summary and summary.found_in_subdir and summary.subdir_name:
            return summary.subdir_name
        if resolved_path is not None and resolved_path.name not in {"", "live2d"}:
            return resolved_path.name
        if summary and summary.model3_json:
            return summary.model3_json.removesuffix(".model3.json")
        return "Live2D 角色"

    def resource_info(self) -> "Live2DResourceInfo":
        """构建统一资源状态信息。"""
        assets_root = get_user_live2d_assets_dir().expanduser().resolve()
        configured_path = (self.model_path or "").strip()
        configured_display = project_display_path(configured_path) if configured_path else ""

        if configured_path:
            root = Path(configured_path).expanduser()
            if not root.exists() or not root.is_dir():
                return Live2DResourceInfo(
                    state=ModelState.PATH_INVALID,
                    source="configured",
                    source_label="用户配置路径",
                    display_name=self.get_display_name(),
                    configured_path=configured_path,
                    configured_path_display=configured_display,
                    default_assets_root=str(assets_root),
                    default_assets_root_display=project_display_path(assets_root),
                    status_label="未找到当前配置的 Live2D 模型目录",
                    help_text=(
                        f"请检查设置中的模型路径，或清空后改用默认导入目录 “{project_display_path(assets_root)}”。"
                        "资源包可从 GitHub Releases 下载。"
                    ),
                )

            summary = scan_live2d_model_dir(root)
            effective_dir = _resolve_scanned_model_dir(root, summary)
            if summary.is_empty():
                return Live2DResourceInfo(
                    state=ModelState.PATH_NOT_LIVE2D,
                    source="configured",
                    source_label="用户配置路径",
                    display_name=self.get_display_name(summary, effective_dir),
                    configured_path=configured_path,
                    configured_path_display=configured_display,
                    effective_model_path=str(root.resolve()),
                    effective_model_path_display=project_display_path(root),
                    default_assets_root=str(assets_root),
                    default_assets_root_display=project_display_path(assets_root),
                    status_label="当前目录不是有效的 Live2D 模型目录",
                    help_text=(
                        "目录内至少需要 .moc3 或 .model3.json 文件。"
                        "请确认资源包解压层级正确，或重新从 GitHub Releases 下载。"
                    ),
                )

            return Live2DResourceInfo(
                state=ModelState.PATH_VALID,
                source="configured",
                source_label="用户配置路径",
                display_name=self.get_display_name(summary, effective_dir),
                configured_path=configured_path,
                configured_path_display=configured_display,
                effective_model_path=str(effective_dir),
                effective_model_path_display=project_display_path(effective_dir),
                default_assets_root=str(assets_root),
                default_assets_root_display=project_display_path(assets_root),
                status_label="已检测到有效的 Live2D 模型资源",
                help_text="当前使用你在设置中指定的模型路径。",
                summary=summary,
            )

        resolved_path = self.resolve_model_path()
        if resolved_path is None:
            return Live2DResourceInfo(
                state=ModelState.NOT_CONFIGURED,
                source="missing",
                source_label="未导入资源",
                display_name=self.get_display_name(),
                default_assets_root=str(assets_root),
                default_assets_root_display=project_display_path(assets_root),
                status_label="未检测到有效的 Live2D 模型资源",
                help_text=(
                    f"请从 GitHub Releases 下载 Live2D 资源包，并解压到 “{project_display_path(assets_root)}”。"
                    "如果你已把模型放在其他位置，也可以在设置中手动填写模型路径。"
                ),
            )

        summary = scan_live2d_model_dir(resolved_path)
        effective_dir = _resolve_scanned_model_dir(resolved_path, summary)
        return Live2DResourceInfo(
            state=ModelState.PATH_VALID,
            source="auto_discovered",
            source_label="用户目录自动发现",
            display_name=self.get_display_name(summary, effective_dir),
            effective_model_path=str(effective_dir),
            effective_model_path_display=project_display_path(effective_dir),
            default_assets_root=str(assets_root),
            default_assets_root_display=project_display_path(assets_root),
            status_label="已在默认导入目录中检测到 Live2D 模型资源",
            help_text="当前未填写模型路径，程序正在使用默认用户目录中自动发现的资源。",
            summary=summary,
        )

    def is_model_configured(self) -> bool:
        """当前是否已有可用模型资源（显式路径或自动发现）。"""
        return self.resource_info().state in {ModelState.PATH_VALID, ModelState.LOADED}

    def validate(self) -> "ModelState":
        """校验当前配置，返回对应状态。

        校验层级（从浅到深）：
          1. 字段是否填写      → NOT_CONFIGURED
          2. 目录是否存在      → PATH_INVALID
          3. 是否含模型文件    → PATH_NOT_LIVE2D
          4. 渲染器是否可用    → PATH_VALID（渲染器实现后由其返回 LOADED）
        """
        return self.resource_info().state

    def scan(self) -> "ModelSummary | None":
        """扫描模型目录，返回摘要。目录不存在或未配置则返回 None。"""
        return self.resource_info().summary


@dataclass
class AppConfig:
    """应用配置"""

    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8420
    bridge_enabled: bool = True
    display_mode: DisplayModeValue = "bubble"   # 合法值见 DisplayMode 枚举
    tray_enabled: bool = True
    start_minimized: bool = False
    log_level: str = "INFO"
    window_mode: WindowModeConfig = field(default_factory=WindowModeConfig)
    bubble_mode: BubbleModeConfig = field(default_factory=BubbleModeConfig)
    live2d_mode: Live2DModeConfig = field(default_factory=Live2DModeConfig)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)

    @property
    def live2d(self) -> Live2DModeConfig:
        """兼容旧代码路径：config.live2d -> config.live2d_mode。"""
        return self.live2d_mode

    @live2d.setter
    def live2d(self, value: Live2DModeConfig) -> None:
        self.live2d_mode = value


def _load_nested_dataclass(
    data: dict[str, Any],
    key: str,
    cls: type[Any],
    legacy_key: str | None = None,
) -> Any:
    """从配置字典中加载嵌套 dataclass，兼容旧字段名。"""
    nested = data.pop(key, None)
    if nested is None and legacy_key is not None:
        nested = data.pop(legacy_key, None)
    if not isinstance(nested, dict):
        return cls()
    valid = {
        field_name: value
        for field_name, value in nested.items()
        if field_name in cls.__dataclass_fields__
    }
    return cls(**valid)


def _normalize_literal(value: Any, allowed: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _normalize_int_range(value: Any, lower: int, upper: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if lower <= number <= upper else default


def _normalize_float_range(value: Any, lower: float, upper: float, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if lower <= number <= upper else default


def _normalize_config_values(config: AppConfig) -> None:
    """规整配置文件中的枚举和范围值，避免旧配置/手改配置导致运行期异常。"""
    config.bubble_mode.expand_trigger = cast(BubbleExpandTriggerValue, _normalize_literal(
        config.bubble_mode.expand_trigger,
        {"click"},
        "click",
    ))
    config.bubble_mode.default_display = cast(BubbleDisplayValue, _normalize_literal(
        config.bubble_mode.default_display,
        {"icon", "summary", "recent_reply"},
        "summary",
    ))
    config.bubble_mode.position_x_percent = _normalize_float_range(
        config.bubble_mode.position_x_percent,
        0.0,
        1.0,
        1.0,
    )
    config.bubble_mode.position_y_percent = _normalize_float_range(
        config.bubble_mode.position_y_percent,
        0.0,
        1.0,
        1.0,
    )
    config.bubble_mode.opacity = _normalize_float_range(config.bubble_mode.opacity, 0.2, 1.0, 0.92)
    config.bubble_mode.proactive_interval_seconds = _normalize_int_range(
        config.bubble_mode.proactive_interval_seconds,
        60,
        3600,
        300,
    )
    config.live2d_mode.default_open_behavior = cast(Live2DDefaultOpenValue, _normalize_literal(
        config.live2d_mode.default_open_behavior,
        {"stage", "reply_bubble", "chat_input"},
        "reply_bubble",
    ))
    config.live2d_mode.click_action = cast(Live2DClickActionValue, _normalize_literal(
        config.live2d_mode.click_action,
        {"focus_stage", "open_chat", "toggle_reply"},
        "open_chat",
    ))
    config.live2d_mode.scale = _normalize_float_range(config.live2d_mode.scale, 0.4, 2.0, 1.0)
    config.live2d_mode.proactive_interval_seconds = _normalize_int_range(
        config.live2d_mode.proactive_interval_seconds,
        60,
        3600,
        300,
    )
    config.assistant.persona_prompt = str(config.assistant.persona_prompt or "")
    config.assistant.user_address = str(config.assistant.user_address or "")
    config.tts.provider = cast(TTSProviderValue, _normalize_literal(config.tts.provider, {"none", "http", "command"}, "none"))
    config.tts.timeout_seconds = _normalize_int_range(config.tts.timeout_seconds, 1, 120, 20)
    config.tts.endpoint = str(config.tts.endpoint or "")
    config.tts.command = str(config.tts.command or "")
    config.tts.voice = str(config.tts.voice or "")


def normalize_display_mode(value: Any) -> DisplayModeValue:
    """规范化 display mode，兼容旧版 window 配置。"""
    if value == "live2d":
        return "live2d"
    if value not in (None, "", "bubble", "window"):
        logger.warning("未知显示模式 %r，回退为 bubble", value)
    return "bubble"


def load_config() -> AppConfig:
    """从磁盘加载配置，不存在则返回默认值"""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            window_mode = _load_nested_dataclass(data, "window_mode", WindowModeConfig)
            bubble_mode = _load_nested_dataclass(data, "bubble_mode", BubbleModeConfig)
            live2d_mode = _load_nested_dataclass(
                data, "live2d_mode", Live2DModeConfig, legacy_key="live2d"
            )
            assistant = _load_nested_dataclass(data, "assistant", AssistantConfig)
            tts = _load_nested_dataclass(data, "tts", TTSConfig)
            if "display_mode" in data:
                data["display_mode"] = normalize_display_mode(data.get("display_mode"))
            config = AppConfig(
                **{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
            )
            config.window_mode = window_mode
            config.bubble_mode = bubble_mode
            config.live2d_mode = live2d_mode
            config.assistant = assistant
            config.tts = tts
            _apply_default_resource_paths(config)
            _normalize_config_values(config)
            return config
        except Exception:
            logger.warning("配置文件读取失败，使用默认配置")
    config = AppConfig()
    _apply_default_resource_paths(config)
    _normalize_config_values(config)
    return config


def _apply_default_resource_paths(config: AppConfig) -> None:
    """Normalize legacy bundled defaults and fill lightweight defaults."""
    if not config.bubble_mode.avatar_path:
        config.bubble_mode.avatar_path = str(DEFAULT_BUBBLE_AVATAR_PATH)
    legacy_paths = {
        str(LEGACY_BUNDLED_LIVE2D_MODEL_DIR),
        str(LEGACY_BUNDLED_LIVE2D_MODEL_DIR.resolve()) if LEGACY_BUNDLED_LIVE2D_MODEL_DIR.exists() else str(LEGACY_BUNDLED_LIVE2D_MODEL_DIR),
        str(DEFAULT_LIVE2D_MODEL_DIR),
    }
    if (config.live2d_mode.model_path or "").strip() in legacy_paths:
        config.live2d_mode.model_path = ""
    if config.live2d_mode.model_name == "八千代辉夜姬" and not config.live2d_mode.model_path:
        config.live2d_mode.model_name = ""


def save_config(config: AppConfig) -> None:
    """将配置写入磁盘"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
