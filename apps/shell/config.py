"""用户配置读写"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".hermes-yachiyo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# 合法的 display_mode 值，与 DisplayMode 枚举保持同步。
# 主控台不再是 display mode；旧配置中的 "window" 会迁移到 "bubble"。
DisplayModeValue = Literal["bubble", "live2d"]
BubbleDisplayValue = Literal["icon", "summary", "recent_reply"]
BubbleExpandTriggerValue = Literal["click", "hover"]
Live2DClickActionValue = Literal["focus_stage", "open_chat", "toggle_reply"]
Live2DDefaultOpenValue = Literal["stage", "reply_bubble", "chat_input"]


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

    def is_empty(self) -> bool:
        """摘要是否为空（未找到任何特征文件）。"""
        return not self.model3_json and not self.moc3_file

    @property
    def renderer_entry(self) -> str:
        """渲染器推荐入口路径：优先 model3.json，其次 moc3，无则空字符串。"""
        return self.primary_model3_json_abs or self.primary_moc3_abs


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
    position_x: int = 24
    position_y: int = 24
    always_on_top: bool = True
    edge_snap: bool = True
    expanded_on_start: bool = True
    expand_trigger: BubbleExpandTriggerValue = "click"
    default_display: BubbleDisplayValue = "summary"
    show_unread_dot: bool = True
    auto_hide: bool = False
    opacity: float = 0.92
    summary_count: int = 3


@dataclass
class Live2DModeConfig:
    """Live2D 模式配置骨架。

    当前阶段仍是角色聊天壳，保留未来 renderer / moc3 / 动作系统的接入位。
    """

    model_name: str = ""              # 角色模型名（如 "hiyori"），空字符串表示未配置
    model_path: str = ""              # 模型目录路径（含 .moc3 文件），空字符串表示未配置
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
    idle_motion_group: str = "Idle"   # 待机动作组名（Live2D Cubism 约定）
    enable_expressions: bool = False  # 是否启用表情系统（等待渲染器支持）
    enable_physics: bool = False      # 是否启用物理模拟（等待渲染器支持）

    def is_model_configured(self) -> bool:
        """是否已填写了模型名和路径（不检查路径是否存在）。"""
        return bool(self.model_name and self.model_path)

    def validate(self) -> "ModelState":
        """校验当前配置，返回对应状态。

        校验层级（从浅到深）：
          1. 字段是否填写      → NOT_CONFIGURED
          2. 目录是否存在      → PATH_INVALID
          3. 是否含模型文件    → PATH_NOT_LIVE2D
          4. 渲染器是否可用    → PATH_VALID（渲染器实现后由其返回 LOADED）
        """
        if not self.is_model_configured():
            return ModelState.NOT_CONFIGURED
        p = Path(self.model_path).expanduser()
        if not p.exists() or not p.is_dir():
            return ModelState.PATH_INVALID
        if not check_live2d_model_dir(p):
            return ModelState.PATH_NOT_LIVE2D
        return ModelState.PATH_VALID

    def scan(self) -> "ModelSummary | None":
        """扫描模型目录，返回摘要。目录不存在或未配置则返回 None。"""
        if not self.is_model_configured():
            return None
        p = Path(self.model_path).expanduser()
        if not p.exists() or not p.is_dir():
            return None
        return scan_live2d_model_dir(p)


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
    cls: type,
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
            if "display_mode" in data:
                data["display_mode"] = normalize_display_mode(data.get("display_mode"))
            config = AppConfig(
                **{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
            )
            config.window_mode = window_mode
            config.bubble_mode = bubble_mode
            config.live2d_mode = live2d_mode
            return config
        except Exception:
            logger.warning("配置文件读取失败，使用默认配置")
    return AppConfig()


def save_config(config: AppConfig) -> None:
    """将配置写入磁盘"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
