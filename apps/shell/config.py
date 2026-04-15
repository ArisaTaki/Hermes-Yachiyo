"""用户配置读写"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".hermes-yachiyo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# 合法的 display_mode 值，与 DisplayMode 枚举保持同步
DisplayModeValue = Literal["window", "bubble", "live2d"]


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
    """

    model3_json: str = ""       # 检测到的 .model3.json 文件名（如 "hiyori.model3.json"），无则空
    moc3_file: str = ""         # 检测到的 .moc3 文件名（如 "hiyori.moc3"），无则空
    found_in_subdir: bool = False  # 特征文件是否位于子目录（而非根目录）
    subdir_name: str = ""       # 若 found_in_subdir=True，记录子目录名（如 "hiyori"）
    extra_moc3_count: int = 0   # 除第一个外额外检测到的 .moc3 数量（多模型目录提示）

    def is_empty(self) -> bool:
        """摘要是否为空（未找到任何特征文件）。"""
        return not self.model3_json and not self.moc3_file


def scan_live2d_model_dir(path: Path) -> ModelSummary:
    """扫描 Live2D 模型目录，返回最小文件摘要。

    扫描顺序：根目录优先，找不到再看一级子目录。
    每类文件只记录第一个（按文件名字母序），多余的计入 extra_moc3_count。
    """
    summary = ModelSummary()

    # 优先扫描根目录
    root_moc3  = sorted(path.glob("*.moc3"))
    root_json  = sorted(path.glob("*.model3.json"))

    if root_moc3 or root_json:
        summary.found_in_subdir = False
        if root_moc3:
            summary.moc3_file = root_moc3[0].name
            summary.extra_moc3_count = len(root_moc3) - 1
        if root_json:
            summary.model3_json = root_json[0].name
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
                summary.extra_moc3_count = len(sub_moc3) - 1
            if sub_json:
                summary.model3_json = sub_json[0].name
            return summary  # 取第一个有内容的子目录即止

    return summary  # 空摘要


@dataclass
class Live2DConfig:
    """Live2D 模式配置骨架。

    当前字段为占位，等待 Live2DRenderer 实现后逐步填充。
    """

    model_name: str = ""              # 角色模型名（如 "hiyori"），空字符串表示未配置
    model_path: str = ""              # 模型目录路径（含 .moc3 文件），空字符串表示未配置
    idle_motion_group: str = "Idle"   # 待机动作组名（Live2D Cubism 约定）
    enable_expressions: bool = False  # 是否启用表情系统（等待渲染器支持）
    enable_physics: bool = False      # 是否启用物理模拟（等待渲染器支持）
    window_on_top: bool = True        # 角色窗口是否置顶

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
    display_mode: DisplayModeValue = "window"   # 合法值见 DisplayMode 枚举
    tray_enabled: bool = True
    start_minimized: bool = False
    log_level: str = "INFO"
    live2d: Live2DConfig = field(default_factory=Live2DConfig)


def load_config() -> AppConfig:
    """从磁盘加载配置，不存在则返回默认值"""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            # 处理嵌套的 live2d 配置
            live2d_data = data.pop("live2d", {})
            live2d = Live2DConfig(**{
                k: v for k, v in live2d_data.items()
                if k in Live2DConfig.__dataclass_fields__
            }) if live2d_data else Live2DConfig()
            config = AppConfig(
                **{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
            )
            config.live2d = live2d
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
