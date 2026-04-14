# Session Summary

# Session Summary

## 本轮完成内容

实现了 Hermes Agent 安装引导层，将 Hermes Agent 视为外部运行时依赖。

### Hermes Agent 作为外部依赖
- 不再将 Hermes Agent 视为项目内嵌库
- 实现安装检测、版本兼容性检查、平台支持验证
- 提供分平台安装指导和环境配置引导

### 新增模块

**apps/installer/**:
- hermes_check.py: 检测 hermes 命令、版本兼容性、平台支持
- hermes_install.py: 分平台安装指导（macOS/Linux/WSL2），不含复杂自动安装
- hermes_setup.py: HERMES_HOME 环境规划、目录结构创建、环境变量配置

**packages/protocol/install.py**:
- HermesInstallStatus, Platform 枚举
- HermesInstallInfo, HermesVersionInfo, HermesSetupRequest/Response 模型

### 集成到 Core Runtime
- apps/core/runtime.py: 启动时执行 Hermes 安装检测
- 不阻止启动，允许用户在 UI 中查看安装状态和引导
- 增强 get_status() 包含 Hermes 安装信息

### Bridge API 扩展
- apps/bridge/routes/hermes.py: Hermes 环境设置 API
- GET /hermes/install-info: 安装状态和引导信息
- POST /hermes/setup: Hermes 环境设置
- GET /hermes/environment: 当前环境信息

### 平台支持策略
- macOS: Homebrew 或二进制文件
- Linux/WSL2: 官方安装脚本或二进制文件  
- Windows: 强制要求使用 WSL2，不支持原生 Windows

### HERMES_HOME 策略
- 默认: ~/.hermes
- Yachiyo 工作空间: $HERMES_HOME/yachiyo
- 环境变量持久化到 .bashrc/.zshrc
- 目录结构自动创建（logs, memory, tasks, config）

### 文档更新
- README 更新：环境要求、Hermes Agent 安装、API 路由、目录结构
- memory 进度文件同步更新
