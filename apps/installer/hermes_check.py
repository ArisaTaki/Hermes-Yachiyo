"""Hermes Agent 安装检测

检测 Hermes Agent 是否已安装，版本是否兼容，平台是否支持。
"""

import logging
import os
import platform
import re
import subprocess
from typing import Tuple

from packages.protocol.enums import HermesInstallStatus, HermesReadinessLevel, Platform
from packages.protocol.install import HermesInstallInfo, HermesVersionInfo

logger = logging.getLogger(__name__)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Hermes 最低要求版本（示例）
HERMES_MIN_VERSION = "0.8.0"

# 支持的平台映射
PLATFORM_MAPPING = {
    "Darwin": Platform.MACOS,
    "Linux": Platform.LINUX,
    "Windows": Platform.WINDOWS_NATIVE,  # 需要检测是否在 WSL2
}


def detect_platform() -> Platform:
    """检测当前运行平台"""
    sys_platform = platform.system()
    
    if sys_platform == "Windows":
        # 检测是否在 WSL2 环境中
        if _is_wsl2():
            return Platform.WINDOWS_WSL2
        return Platform.WINDOWS_NATIVE
    
    return PLATFORM_MAPPING.get(sys_platform, Platform.WINDOWS_NATIVE)


def _is_wsl2() -> bool:
    """检测是否在 WSL2 环境中运行"""
    try:
        # 检查 /proc/version 是否包含 WSL2 标识
        if os.path.exists("/proc/version"):
            with open("/proc/version", "r") as f:
                content = f.read()
                return "WSL2" in content or "microsoft" in content.lower()
    except Exception:
        pass
    
    # 检查环境变量
    return os.getenv("WSL_DISTRO_NAME") is not None


def check_hermes_command(hermes_path: str = "hermes") -> Tuple[bool, str | None]:
    """检查 hermes 命令是否存在且可执行。

    Args:
        hermes_path: hermes 可执行文件路径，默认依赖 PATH 查找。
                     安装后检测时可传入绝对路径（避免 PATH 未刷新的误判）。

    Returns:
        (exists, error_message)
    """
    try:
        result = subprocess.run(
            [hermes_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True, None
        else:
            return False, f"hermes 命令执行失败: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "hermes 命令未找到，请确认已安装 Hermes Agent"
    except subprocess.TimeoutExpired:
        return False, "hermes 命令执行超时"
    except Exception as e:
        return False, f"检查 hermes 命令时出错: {str(e)}"


def get_hermes_version(hermes_path: str = "hermes") -> HermesVersionInfo | None:
    """获取 Hermes Agent 版本信息

    ``hermes --version`` 第一行格式为：
    ``Hermes Agent v0.9.0 (2026.4.13)``
    使用正则从第一行提取 ``vX.Y.Z``，避免与后续 Python/SDK 版本混淆。
    """
    try:
        result = subprocess.run(
            [hermes_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None

        # 只解析第一行（"Hermes Agent v0.9.0 (2026.4.13)"）
        first_line = (result.stdout.strip().splitlines() or [""])[0]
        version_info = HermesVersionInfo()

        # 优先匹配 vX.Y.Z 格式（Hermes 自身版本）
        m = re.search(r'v(\d+\.\d+(?:\.\d+)?)', first_line)
        if m:
            version_info.version = m.group(1)
        else:
            # 降级：从第一行找任意 digit.digit 形式（不跨行，避免拾取 Python 版本）
            for part in first_line.split():
                clean = part.strip("v().,")
                if clean and clean[0].isdigit() and "." in clean:
                    version_info.version = clean
                    break

        # 提取构建日期 "(YYYY.M.D)"
        bd = re.search(r'\((\d{4}\.\d+\.\d+)\)', first_line)
        if bd:
            version_info.build_date = bd.group(1)

        return version_info
    except Exception as e:
        logger.warning("获取 Hermes 版本信息失败: %s", e)
        return None


def is_version_compatible(version: str) -> bool:
    """检查版本是否兼容。

    Hermes 版本形如 ``0.10.0``。不能使用字符串比较，否则 ``0.10.0``
    会被错误判断为小于 ``0.8.0``。
    """
    current = _parse_version_parts(version)
    minimum = _parse_version_parts(HERMES_MIN_VERSION)
    if current is None or minimum is None:
        return False
    width = max(len(current), len(minimum))
    current = current + (0,) * (width - len(current))
    minimum = minimum + (0,) * (width - len(minimum))
    return current >= minimum


def _parse_version_parts(version: str) -> tuple[int, ...] | None:
    """从版本字符串中提取可比较的数字分段。"""
    if not version:
        return None

    match = re.search(r"\d+(?:\.\d+)*", version)
    if not match:
        return None

    parts = tuple(int(part) for part in match.group(0).split("."))
    target_len = max(3, len(parts))
    return parts + (0,) * (target_len - len(parts))


def check_hermes_setup(hermes_path: str = "hermes") -> Tuple[bool, str]:
    """检查 Hermes Agent 是否已完成 setup（交互式配置）。

    检测策略（按优先级）：
    1. ``hermes status`` 返回 0 → setup 已完成
    2. HERMES_HOME 下存在 config.yaml / config.yml / config.json → setup 已完成
    3. 以上均不满足 → 需要 setup

    Returns:
        (setup_done, error_message)
    """
    # 策略 1: hermes status 退出码
    try:
        result = subprocess.run(
            [hermes_path, "status"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as exc:
        logger.debug("hermes status 执行异常: %s", exc)

    # 策略 2: 配置文件存在性
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    config_candidates = [
        os.path.join(hermes_home, "config.yaml"),
        os.path.join(hermes_home, "config.yml"),
        os.path.join(hermes_home, "config.json"),
    ]
    for cfg_path in config_candidates:
        if os.path.isfile(cfg_path):
            return True, ""

    return False, "Hermes Agent 已安装但尚未完成初始配置（hermes setup）"


def is_hermes_setup_running() -> bool:
    """检测 hermes setup 进程是否正在运行。

    macOS/Linux: 通过 pgrep 或 /proc 检测包含 "hermes" 且参数含 "setup" 的进程。
    """
    import platform as _platform

    system = _platform.system()

    try:
        if system in ("Darwin", "Linux"):
            # 使用 ps aux 查找 hermes setup 进程（排除自身 grep）
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    # 匹配 "hermes setup" 但排除 grep 自身和 Python 进程
                    if "hermes" in line and "setup" in line:
                        if "grep" not in line and "python" not in line.lower():
                            logger.debug("检测到 hermes setup 进程: %s", line.strip())
                            return True
    except Exception as exc:
        logger.debug("检测 hermes setup 进程失败: %s", exc)

    return False


def check_yachiyo_workspace() -> Tuple[bool, str]:
    """检查 Yachiyo 工作空间初始化状态
    
    检查 Yachiyo 特定的工作空间目录和配置，不检查 Hermes 官方配置。
    
    Returns:
        Tuple[bool, str]: (是否已初始化, 错误信息)
    """
    try:
        # 1. 确定 Hermes Home（优先环境变量，否则默认）
        hermes_home = os.getenv("HERMES_HOME")
        if not hermes_home:
            hermes_home = os.path.expanduser("~/.hermes")
        
        # 2. 检查 Yachiyo 工作空间目录
        yachiyo_workspace = os.path.join(hermes_home, "yachiyo")
        if not os.path.exists(yachiyo_workspace):
            return False, f"Yachiyo 工作空间目录不存在: {yachiyo_workspace}"
        
        # 3. 检查 Yachiyo 基本配置文件（如果需要的话）
        # 这里可以检查 Yachiyo 特定的配置文件或标识文件
        yachiyo_init_file = os.path.join(yachiyo_workspace, ".yachiyo_init")
        if not os.path.exists(yachiyo_init_file):
            return False, "Yachiyo 工作空间未完成初始化"
        
        return True, ""
        
    except Exception as e:
        logger.error("Yachiyo 工作空间检查失败: %s", e)
        return False, f"工作空间检查失败: {e}"


def check_hermes_basic_readiness(hermes_path: str = "hermes") -> Tuple[bool, str]:
    """检查 Hermes Agent 基本可用性
    
    只检查 Hermes 本身是否安装且可用，不涉及 Yachiyo 特定配置。
    
    Returns:
        Tuple[bool, str]: (是否可用, 错误信息)  
    """
    try:
        # 1. 检查命令可用性（已包含版本检查）
        command_exists, error_message = check_hermes_command(hermes_path)
        if not command_exists:
            return False, error_message or "Hermes 命令不可用"
        
        # 2. 简单验证 Hermes 工作状态
        # 这里不检查复杂配置，只确保 Hermes 基本可用
        try:
            result = subprocess.run(
                [hermes_path, "--version"],
                capture_output=True, 
                text=True, 
                timeout=5,
                check=False
            )
            if result.returncode != 0:
                return False, "Hermes 命令执行异常"
        except Exception as e:
            return False, f"Hermes 验证失败: {e}"
        
        return True, ""
        
    except Exception as e:
        logger.error("Hermes 基本可用性检查失败: %s", e)
        return False, f"Hermes 检查失败: {e}"


def get_hermes_home() -> str:
    """获取 HERMES_HOME 路径（当前或推荐）"""
    # 1. 检查环境变量
    hermes_home = os.getenv("HERMES_HOME")
    if hermes_home and os.path.exists(hermes_home):
        return hermes_home
    
    # 2. 默认路径策略
    home_dir = os.path.expanduser("~")
    default_hermes_home = os.path.join(home_dir, ".hermes")
    
    return default_hermes_home


def parse_hermes_doctor_output(output: str) -> dict[str, object]:
    """Parse the Hermes doctor output into stable tool availability fields."""
    text = _ANSI_RE.sub("", output or "")
    m = re.search(r"Found\s+(\d+)\s+issue", text)
    issues_count = int(m.group(1)) if m else 0
    available_tools: list[str] = []
    limited_tools: list[str] = []
    limited_tool_details: dict[str, str] = {}
    in_tools_section = False

    for line in text.splitlines():
        stripped = line.strip()
        if "Tool Availability" in stripped or (stripped.startswith("◆") and "Tool" in stripped):
            in_tools_section = True
            continue
        if in_tools_section and stripped.startswith("◆"):
            in_tools_section = False
            continue
        if not in_tools_section:
            continue

        ok_match = re.match(r"\s*(?:✓|✔|✅)\s+([A-Za-z0-9_.-]+)", line)
        if ok_match:
            available_tools.append(ok_match.group(1))
            continue

        limited_match = re.match(
            r"\s*(?:⚠️?|✗|❌)\s+([A-Za-z0-9_.-]+)(?:\s+\((.*?)\))?",
            line,
        )
        if limited_match:
            name = limited_match.group(1)
            detail = (limited_match.group(2) or "").strip()
            limited_tools.append(name)
            if detail:
                limited_tool_details[name] = detail

    readiness_level = (
        HermesReadinessLevel.FULL_READY.value
        if issues_count == 0 and not limited_tools
        else HermesReadinessLevel.BASIC_READY.value
    )
    return {
        "readiness_level": readiness_level,
        "available_tools": available_tools,
        "limited_tools": limited_tools,
        "limited_tool_details": limited_tool_details,
        "doctor_issues_count": issues_count,
    }


def check_hermes_doctor_readiness(
    timeout: float = 5.0,
    hermes_path: str = "hermes",
) -> Tuple[HermesReadinessLevel, list[str], int]:
    """通过 ``hermes doctor`` 检测 Hermes 能力就绪程度。

    解析策略：
    - 扫描 ``◆ Tool Availability`` 节的警告/失败行，提取受限工具名
    - 解析末尾摘要 ``Found N issue(s)`` 获取 issue 计数
    - 若解析失败（超时/命令不存在），静默返回 ``UNKNOWN``，不阻塞启动

    Returns:
        (readiness_level, limited_tool_names, issues_count)
    """
    try:
        result = subprocess.run(
            [hermes_path, "doctor"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr

        summary = parse_hermes_doctor_output(output)
        check_hermes_doctor_readiness.last_summary = summary  # type: ignore[attr-defined]
        readiness_level = HermesReadinessLevel(str(summary["readiness_level"]))
        limited_tools = list(summary["limited_tools"])
        issues_count = int(summary["doctor_issues_count"])
        return readiness_level, limited_tools, issues_count

    except FileNotFoundError:
        # hermes 命令不存在（理论上不应到达此处，安装检测已先行）
        check_hermes_doctor_readiness.last_summary = {}  # type: ignore[attr-defined]
        return HermesReadinessLevel.UNKNOWN, [], 0
    except subprocess.TimeoutExpired:
        logger.debug("hermes doctor 超时（%.1fs），跳过就绪分级", timeout)
        check_hermes_doctor_readiness.last_summary = {}  # type: ignore[attr-defined]
        return HermesReadinessLevel.UNKNOWN, [], 0
    except Exception as exc:
        logger.debug("hermes doctor 检测失败，跳过就绪分级: %s", exc)
        check_hermes_doctor_readiness.last_summary = {}  # type: ignore[attr-defined]
        return HermesReadinessLevel.UNKNOWN, [], 0


def check_hermes_installation() -> HermesInstallInfo:
    """完整的 Hermes Agent 安装检测
    
    分层检测：
    1. Hermes Agent 本身的安装状态
    2. Yachiyo 工作空间的初始化状态
    
    Returns:
        HermesInstallInfo: 详细的检测结果
    """
    install_info = HermesInstallInfo(
        status=HermesInstallStatus.NOT_CHECKED,
        platform=detect_platform()
    )
    
    # 1. 平台支持检查
    if install_info.platform == Platform.WINDOWS_NATIVE:
        install_info.status = HermesInstallStatus.WSL2_REQUIRED
        install_info.suggestions = [
            "Windows 用户需要使用 WSL2 运行 Hermes Agent",
            "请安装 WSL2 并在 Linux 环境中运行 Hermes-Yachiyo"
        ]
        return install_info
    
    if install_info.platform not in [Platform.MACOS, Platform.LINUX, Platform.WINDOWS_WSL2]:
        install_info.status = HermesInstallStatus.PLATFORM_UNSUPPORTED
        install_info.error_message = f"不支持的平台: {install_info.platform}"
        return install_info
    
    # 2. Hermes Agent 安装检查
    hermes_path, _needs_env_refresh = locate_hermes_binary()
    if hermes_path is None:
        hermes_path = "hermes"

    command_exists, error_message = check_hermes_command(hermes_path)
    install_info.command_exists = command_exists
    
    if not command_exists:
        install_info.status = HermesInstallStatus.NOT_INSTALLED
        install_info.error_message = error_message
        install_info.suggestions = [
            "请安装 Hermes Agent: https://github.com/NousResearch/hermes-agent",
            "macOS: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup",
            "Linux: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup",
            "确保 hermes 命令在 PATH 环境变量中"
        ]
        return install_info
    
    # 3. Hermes Agent 版本兼容性检查
    version_info = get_hermes_version(hermes_path)
    install_info.version_info = version_info
    
    if not version_info or not version_info.version:
        install_info.status = HermesInstallStatus.INCOMPATIBLE_VERSION
        install_info.error_message = "无法获取 Hermes 版本信息"
        install_info.suggestions = [
            "请检查 Hermes Agent 安装是否完整",
            f"建议使用 Hermes Agent {HERMES_MIN_VERSION}+ 版本"
        ]
        return install_info
    
    if not is_version_compatible(version_info.version):
        install_info.status = HermesInstallStatus.INCOMPATIBLE_VERSION
        install_info.error_message = f"Hermes 版本 {version_info.version} 不兼容，需要 {HERMES_MIN_VERSION}+"
        install_info.suggestions = [
            f"请升级 Hermes Agent 到 {HERMES_MIN_VERSION}+ 版本",
            "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup"
        ]
        return install_info
    
    # 4. Hermes setup（交互式配置）检查
    # 上面的版本读取已经执行并解析过 `hermes --version`，这里不再重复调用
    # check_hermes_basic_readiness()，避免正常启动时多跑两次子进程。
    setup_done, setup_error = check_hermes_setup(hermes_path)
    if not setup_done:
        # 检测 setup 进程是否正在运行
        if is_hermes_setup_running():
            install_info.status = HermesInstallStatus.SETUP_IN_PROGRESS
            install_info.error_message = "hermes setup 正在终端中运行"
            install_info.suggestions = [
                "Hermes Agent 配置正在进行中",
                "请在终端中完成 hermes setup 交互式配置",
                "完成后回到此应用点击「重新检测」"
            ]
            return install_info

        install_info.status = HermesInstallStatus.INSTALLED_NEEDS_SETUP
        install_info.error_message = setup_error
        install_info.suggestions = [
            "Hermes Agent 已安装，但需要完成初始配置",
            "请在终端中运行 hermes setup 完成交互式配置",
            "配置完成后回到此应用点击「重新检测」"
        ]
        return install_info

    # 5. Yachiyo 工作空间初始化检查
    hermes_home = get_hermes_home()
    install_info.hermes_home = hermes_home
    
    workspace_ok, workspace_error = check_yachiyo_workspace()
    if not workspace_ok:
        install_info.status = HermesInstallStatus.INSTALLED_NOT_INITIALIZED
        install_info.error_message = workspace_error
        install_info.suggestions = [
            "Hermes Agent 已安装，需要初始化 Yachiyo 工作空间",
            f"工作空间位置: {hermes_home}/yachiyo",
            "请运行初始化向导完成设置"
        ]
        return install_info
    
    # 6. 一切就绪 — 检测能力等级
    readiness_level, limited_tools, issues_count = check_hermes_doctor_readiness(
        hermes_path=hermes_path,
    )
    doctor_summary = getattr(check_hermes_doctor_readiness, "last_summary", {})
    install_info.readiness_level = readiness_level
    install_info.limited_tools = limited_tools
    if isinstance(doctor_summary, dict):
        install_info.available_tools = [
            str(tool) for tool in doctor_summary.get("available_tools", []) if tool
        ]
        details = doctor_summary.get("limited_tool_details", {})
        if isinstance(details, dict):
            install_info.limited_tool_details = {
                str(key): str(value) for key, value in details.items() if key and value
            }
    install_info.doctor_issues_count = issues_count

    install_info.status = HermesInstallStatus.READY
    return install_info


# ── 安装后环境刷新感知检测 ─────────────────────────────────────────────────────

# Hermes 官方安装脚本常见写入路径（按优先级排列）
HERMES_COMMON_INSTALL_PATHS: list[str] = [
    "~/.local/bin/hermes",
    "~/.hermes/bin/hermes",
    "/usr/local/bin/hermes",
    "/usr/bin/hermes",
    "~/bin/hermes",
    "~/.cargo/bin/hermes",   # Rust 工具链常见位置
    "/opt/homebrew/bin/hermes",  # macOS Homebrew (Apple Silicon)
    "/usr/local/homebrew/bin/hermes",  # macOS Homebrew (Intel)
]


def find_hermes_in_common_paths() -> str | None:
    """在常见安装路径中寻找 hermes 二进制。

    安装脚本执行完毕后，当前进程 PATH 尚未刷新，但二进制文件已落盘，
    可通过直接路径探测绕过 PATH 问题。

    Returns:
        找到时返回绝对路径字符串；未找到返回 None。
    """
    for path_template in HERMES_COMMON_INSTALL_PATHS:
        path = os.path.expanduser(path_template)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            logger.debug("在常见路径找到 hermes: %s", path)
            return path
    return None


def probe_hermes_via_login_shell() -> str | None:
    """通过登录 Shell 定位 hermes 可执行文件。

    登录 Shell 会 source ~/.bashrc / ~/.zshrc 等初始化脚本，
    能感知安装脚本写入的新 PATH 条目。

    Returns:
        找到时返回绝对路径；未找到或超时返回 None。
    """
    shells = []

    # 优先使用用户的默认 shell
    user_shell = os.environ.get("SHELL", "")
    if user_shell and os.path.isfile(user_shell):
        shells.append(user_shell)

    # 备用 shell
    for s in ["/bin/bash", "/bin/zsh", "/bin/sh"]:
        if s not in shells and os.path.isfile(s):
            shells.append(s)

    for shell in shells:
        try:
            result = subprocess.run(
                [shell, "-lc", "command -v hermes"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode == 0:
                found = result.stdout.strip()
                if found and os.path.isfile(found):
                    logger.debug("通过登录 Shell (%s) 找到 hermes: %s", shell, found)
                    return found
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    return None


def _inject_hermes_bin_dir(hermes_bin_path: str) -> None:
    """将 hermes 所在目录注入当前进程 PATH 环境变量。

    安装脚本执行完毕后二进制已落盘，但 Python 进程的 PATH 快照未更新。
    通过修改 os.environ["PATH"] 使后续的子进程调用（subprocess.run）也能找到 hermes。
    """
    bin_dir = os.path.dirname(os.path.abspath(hermes_bin_path))
    current_path = os.environ.get("PATH", "")
    if bin_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + current_path
        logger.info("已将 %s 注入当前进程 PATH（安装后环境修复）", bin_dir)


def locate_hermes_binary() -> tuple[str | None, bool]:
    """定位 hermes 可执行文件，感知当前进程 PATH 是否过期。

    检测顺序：
    1. 当前进程 PATH（最快，正常模式）
    2. 常见安装路径扫描（安装后 PATH 未刷新时的快速回退）
    3. 登录 Shell 探测（最可靠，但稍慢）

    找到备用路径时会自动调用 ``_inject_hermes_bin_dir()``，
    使当前进程及子进程后续均可通过 "hermes" 命令直接调用。

    Returns:
        Tuple:
            - path: hermes 可用路径（已在 PATH 中时为命令名，否则为绝对路径）
            - needs_env_refresh: True 表示通过备用途径找到并已注入 PATH，
              用户的 Shell 会话仍需 ``source ~/.bashrc`` 才能使用 hermes 命令。
    """
    import shutil

    # 策略 1：当前 PATH
    if shutil.which("hermes"):
        return "hermes", False

    # 策略 2：常见路径直接扫描
    common_path = find_hermes_in_common_paths()
    if common_path:
        _inject_hermes_bin_dir(common_path)
        return common_path, True

    # 策略 3：登录 Shell（source rc 文件后重新 which）
    login_path = probe_hermes_via_login_shell()
    if login_path:
        _inject_hermes_bin_dir(login_path)
        return login_path, True

    return None, False


def check_hermes_installation_post_install() -> tuple["HermesInstallInfo", bool]:
    """安装完成后的 Hermes 状态检测。

    与 ``check_hermes_installation()`` 的区别：
    - 先调用 ``locate_hermes_binary()``，若发现 PATH 过期则自动注入修复
    - 修复后直接复用 ``check_hermes_installation()`` 标准流程
    - 返回额外的 ``needs_env_refresh`` 布尔值（提示用户 Shell 仍需手动刷新）

    Returns:
        Tuple:
            - HermesInstallInfo: 安装状态（注入 PATH 后已准确）
            - needs_env_refresh: True 表示本次通过备用途径找到 hermes 并已注入 PATH，
              用户的 Shell 环境仍需手动刷新（不影响应用本身的继续运行）。
    """
    hermes_path, needs_env_refresh = locate_hermes_binary()

    if hermes_path is None:
        # 完全找不到：走标准检测，返回 NOT_INSTALLED
        return check_hermes_installation(), False

    if needs_env_refresh:
        logger.info(
            "安装后检测：通过备用路径找到 hermes（%s），PATH 已注入，继续标准检测",
            hermes_path,
        )

    # PATH 已更新（注入或本来就有），走标准检测流程即可
    return check_hermes_installation(), needs_env_refresh
