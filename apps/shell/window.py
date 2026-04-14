"""主窗口管理

MVP 实现：使用 pywebview 展示本地状态页或安装引导页。
这只是桌面壳原型方案，后续允许迁移到更完整的桌面壳技术。
pywebview 的使用不影响 core / bridge / protocol 的长期边界。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import webview

    _HAS_WEBVIEW = True
except ImportError:
    _HAS_WEBVIEW = False

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig
    from packages.protocol.install import HermesInstallInfo

logger = logging.getLogger(__name__)

# 正常状态页 HTML
_STATUS_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo</title>
    <style>
        body {
            font-family: -apple-system, "Helvetica Neue", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        h1 { color: #6495ed; margin-bottom: 0.2em; }
        .status { color: #90ee90; font-size: 1.2em; }
        .info { color: #888; margin-top: 2em; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>Hermes-Yachiyo</h1>
    <p class="status">● 运行中</p>
    <p class="info">桌面优先本地个人 agent</p>
    <p class="info">Bridge API: http://{host}:{port}</p>
</body>
</html>
"""

# 安装引导页 HTML
_INSTALLER_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo - Hermes Agent 安装引导</title>
    <style>
        body {
            font-family: -apple-system, "Helvetica Neue", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 20px;
            margin: 0;
            line-height: 1.6;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        h1 { color: #6495ed; text-align: center; margin-bottom: 0.5em; }
        h2 { color: #ffd700; margin-top: 2em; }
        .status {
            background: #2d2d54;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #ff6b6b;
            margin: 20px 0;
        }
        .status.warning {
            border-left-color: #ffd700;
        }
        .status.info {
            border-left-color: #6495ed;
        }
        .platform { color: #90ee90; font-weight: bold; }
        .install-steps {
            background: #2d2d54;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }
        .step {
            margin: 10px 0;
            padding: 8px 0;
        }
        code {
            background: #0d1117;
            color: #58a6ff;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Monaco', 'Consolas', monospace;
        }
        .code-block {
            background: #0d1117;
            color: #58a6ff;
            padding: 15px;
            border-radius: 4px;
            font-family: 'Monaco', 'Consolas', monospace;
            white-space: pre-line;
            margin: 10px 0;
            overflow-x: auto;
        }
        .links {
            margin-top: 20px;
        }
        a {
            color: #58a6ff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .footer {
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #444;
            color: #888;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Hermes-Yachiyo</h1>
        
        <div class="status {status_class}">
            <strong>状态：</strong>{status_message}<br>
            <strong>平台：</strong><span class="platform">{platform}</span><br>
            {error_info}
        </div>

        <h2>{main_title}</h2>
        <p>Hermes-Yachiyo 需要 <a href="https://github.com/NousResearch/hermes-agent" target="_blank">Hermes Agent</a> 作为底层运行时。</p>
        
        <div class="install-steps">
            <h3>{steps_title}</h3>
            {install_steps}
        </div>

        {suggestions_section}

        <div class="links">
            <h3>相关链接：</h3>
            <ul>
                <li><a href="https://github.com/NousResearch/hermes-agent" target="_blank">Hermes Agent 官方仓库</a></li>
                <li><a href="https://github.com/NousResearch/hermes-agent/releases" target="_blank">发布页面</a></li>
                <li><a href="https://github.com/NousResearch/hermes-agent#installation" target="_blank">安装文档</a></li>
            </ul>
        </div>

        <div class="footer">
            安装完成后，重新启动 Hermes-Yachiyo 即可正常使用。
        </div>
    </div>
</body>
</html>
"""


def create_main_window(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """创建并显示主窗口（阻塞主线程）- 正常模式"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，以无窗口模式运行")
        # 无窗口模式下保持主线程活跃
        import threading

        threading.Event().wait()
        return

    html = _STATUS_HTML.format(host=config.bridge_host, port=config.bridge_port)

    webview.create_window(
        title="Hermes-Yachiyo",
        html=html,
        width=480,
        height=360,
        resizable=True,
    )
    webview.start()


def create_installer_window(install_info: "HermesInstallInfo", config: "AppConfig") -> None:
    """创建并显示安装引导窗口（阻塞主线程）- 安装引导模式"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，显示控制台安装信息")
        _print_console_install_info(install_info)
        # 无窗口模式下保持主线程活跃
        import threading

        threading.Event().wait()
        return

    html = _generate_installer_html(install_info)

    webview.create_window(
        title="Hermes-Yachiyo - Hermes Agent 安装引导",
        html=html,
        width=800,
        height=600,
        resizable=True,
    )
    webview.start()


def _generate_installer_html(install_info: "HermesInstallInfo") -> str:
    """生成安装引导页面的 HTML 内容"""
    from apps.installer.hermes_install import HermesInstallGuide
    from packages.protocol.enums import HermesInstallStatus

    # 获取安装指导
    guidance = HermesInstallGuide.get_install_instructions(install_info)
    
    # 状态样式和消息
    status_mapping = {
        HermesInstallStatus.NOT_INSTALLED: ("warning", "Hermes Agent 未安装"),
        HermesInstallStatus.INSTALLED_NOT_INITIALIZED: ("info", "Hermes Agent 已安装，需要初始化 Yachiyo 工作空间"),
        HermesInstallStatus.INCOMPATIBLE_VERSION: ("warning", "Hermes Agent 版本不兼容"),
        HermesInstallStatus.PLATFORM_UNSUPPORTED: ("", "平台不支持"),
        HermesInstallStatus.WSL2_REQUIRED: ("info", "需要 WSL2 环境"),
    }
    
    status_class, status_message = status_mapping.get(
        install_info.status, 
        ("", f"状态: {install_info.status}")
    )
    
    # 错误信息
    error_info = ""
    if install_info.error_message:
        error_info = f"<strong>详情：</strong>{install_info.error_message}"
    
    # 根据状态确定主标题和步骤内容
    if install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
        main_title = "初始化 Yachiyo 工作空间"
        steps_title = "初始化步骤："
    else:
        main_title = "安装 Hermes Agent"
        steps_title = "安装步骤："
    
    # 安装/配置步骤
    install_steps = ""
    if "actions" in guidance:
        steps_html = []
        for i, action in enumerate(guidance["actions"], 1):
            if action.startswith("  "):
                # 缩进的命令或说明
                steps_html.append(f'<div class="code-block">{action.strip()}</div>')
            elif action.strip() == "":
                # 空行
                steps_html.append('<br>')
            else:
                # 普通步骤
                steps_html.append(f'<div class="step">{action}</div>')
        install_steps = "\n".join(steps_html)
    
    # 建议部分
    suggestions_section = ""
    if install_info.suggestions:
        suggestions_html = []
        for suggestion in install_info.suggestions:
            suggestions_html.append(f'<li>{suggestion}</li>')
        suggestions_section = f"""
        <div class="install-steps">
            <h3>建议：</h3>
            <ul>{"".join(suggestions_html)}</ul>
        </div>
        """
    
    return _INSTALLER_HTML.format(
        main_title=main_title,
        steps_title=steps_title,
        status_class=status_class,
        status_message=status_message,
        platform=install_info.platform,
        error_info=error_info,
        install_steps=install_steps,
        suggestions_section=suggestions_section,
    )


def _print_console_install_info(install_info: "HermesInstallInfo") -> None:
    """在控制台显示安装信息（无 pywebview 时的备选方案）"""
    print("\n" + "="*60)
    print("Hermes-Yachiyo - Hermes Agent 安装引导")
    print("="*60)
    print(f"状态: {install_info.status}")
    print(f"平台: {install_info.platform}")
    
    if install_info.error_message:
        print(f"错误: {install_info.error_message}")
    
    if install_info.suggestions:
        print("\n建议:")
        for suggestion in install_info.suggestions:
            print(f"  - {suggestion}")
    
    print("\n相关链接:")
    print("  - Hermes Agent 官方仓库: https://github.com/NousResearch/hermes-agent")
    print("  - 发布页面: https://github.com/NousResearch/hermes-agent/releases")
    
    print("\n安装完成后，重新启动 Hermes-Yachiyo 即可正常使用。")
    print("="*60)
