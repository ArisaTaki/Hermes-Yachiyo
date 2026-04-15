"""协议枚举定义"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    """任务类型"""

    STATUS_QUERY = "status_query"
    SCREENSHOT = "screenshot"
    ACTIVE_WINDOW = "active_window"
    GENERAL = "general"


class RiskLevel(StrEnum):
    """风险等级"""

    LOW = "low"  # status, task lists, screenshots, summaries
    MEDIUM = "medium"  # bounded reads, workspace scans, safe local queries
    HIGH = "high"  # arbitrary shell, destructive ops, git push, keyboard/mouse


class ErrorCode(StrEnum):
    """错误码"""

    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    TASK_NOT_CANCELLABLE = "task_not_cancellable"
    RISK_DENIED = "risk_denied"
    INTERNAL_ERROR = "internal_error"
    ADAPTER_ERROR = "adapter_error"
    HERMES_NOT_INSTALLED = "hermes_not_installed"
    HERMES_INCOMPATIBLE = "hermes_incompatible"
    PLATFORM_UNSUPPORTED = "platform_unsupported"


class AuditAction(StrEnum):
    """审计动作类型"""

    TASK_CREATED = "task_created"
    TASK_CANCELLED = "task_cancelled"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    SCREEN_CAPTURED = "screen_captured"
    WINDOW_QUERIED = "window_queried"
    RISK_DENIED = "risk_denied"
    HERMES_INSTALL_CHECK = "hermes_install_check"
    HERMES_INSTALL_ATTEMPT = "hermes_install_attempt"


class HermesInstallStatus(StrEnum):
    """Hermes Agent 安装状态"""

    NOT_CHECKED = "not_checked"              # 尚未检测
    NOT_INSTALLED = "not_installed"          # Hermes Agent 未安装
    INSTALLING = "installing"                # 正在安装中
    INSTALL_FAILED = "install_failed"        # 安装失败
    INCOMPATIBLE_VERSION = "incompatible_version"  # 版本不兼容
    PLATFORM_UNSUPPORTED = "platform_unsupported"  # 平台不支持
    WSL2_REQUIRED = "wsl2_required"          # Windows 用户需要 WSL2
    INSTALLED_NEEDS_SETUP = "installed_needs_setup"  # Hermes 已安装但未完成 setup 配置
    SETUP_IN_PROGRESS = "setup_in_progress"          # hermes setup 进程正在运行中
    INSTALLED_NOT_INITIALIZED = "installed_not_initialized"  # Hermes 已安装，但 Yachiyo 工作空间未初始化
    INITIALIZING = "initializing"            # Yachiyo 工作空间正在初始化
    READY = "ready"                          # Hermes 已安装且 Yachiyo 工作空间已初始化


class Platform(StrEnum):
    """支持的平台"""

    MACOS = "macos"
    LINUX = "linux" 
    WINDOWS_WSL2 = "windows_wsl2"
    WINDOWS_NATIVE = "windows_native"  # 不支持，需提示使用 WSL2
