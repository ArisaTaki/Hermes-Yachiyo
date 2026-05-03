"""Hermes Agent 安装相关 Schema 定义"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import HermesInstallStatus, HermesReadinessLevel, Platform


class HermesVersionInfo(BaseModel):
    """Hermes Agent 版本信息"""

    version: str | None = None
    """版本号字符串，如 '1.2.3'"""
    
    commit: str | None = None
    """Git commit hash（如果可用）"""
    
    build_date: str | None = None
    """构建日期（如果可用）"""


class HermesInstallInfo(BaseModel):
    """Hermes Agent 安装检测结果"""

    status: HermesInstallStatus
    """安装状态"""
    
    platform: Platform
    """检测到的平台"""
    
    command_exists: bool = False
    """hermes 命令是否存在于 PATH"""
    
    version_info: HermesVersionInfo | None = None
    """版本信息（如果可获取）"""
    
    hermes_home: str | None = None
    """HERMES_HOME 路径（当前或推荐）"""
    
    error_message: str | None = None
    """检测过程中的错误信息"""
    
    checked_at: datetime = Field(default_factory=datetime.now)
    """检测时间"""
    
    suggestions: list[str] = Field(default_factory=list)
    """安装建议"""

    readiness_level: HermesReadinessLevel = HermesReadinessLevel.UNKNOWN
    """能力就绪等级（仅在 status=READY 时有意义）"""

    limited_tools: list[str] = Field(default_factory=list)
    """受限工具名称列表（hermes doctor 检测到的 ⚠ 工具）"""

    available_tools: list[str] = Field(default_factory=list)
    """可用工具名称列表（hermes doctor 检测到的 ✓ 工具）"""

    limited_tool_details: dict[str, str] = Field(default_factory=dict)
    """受限工具的原因摘要，key 为工具名称"""

    doctor_issues_count: int = 0
    """hermes doctor 报告的 issue 数（0 表示完整就绪）"""


class HermesSetupRequest(BaseModel):
    """Hermes 环境设置请求"""

    hermes_home: str | None = None
    """自定义 HERMES_HOME 路径"""
    
    auto_setup: bool = True
    """是否自动设置环境变量"""


class HermesSetupResponse(BaseModel):
    """Hermes 环境设置响应"""

    success: bool
    """设置是否成功"""
    
    hermes_home: str
    """实际设置的 HERMES_HOME 路径"""
    
    message: str
    """设置结果信息"""
    
    restart_required: bool = False
    """是否需要重启应用"""
