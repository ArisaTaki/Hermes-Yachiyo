# Current State

## 已完成

### Milestone 0 — 仓库骨架（desktop-first）

- ✅ pyproject.toml（桌面应用依赖：pywebview, pystray, Pillow, fastapi, uvicorn）
- ✅ apps/shell/ — 桌面壳入口（app.py, tray.py, window.py, config.py, modes/）
- ✅ apps/core/ — Runtime + State 骨架（runtime.py, state.py），不暴露 HTTP
- ✅ apps/bridge/ — 内部 FastAPI 桥梁（server.py + routes/），非产品本体
- ✅ apps/locald/ — 截图 + 活动窗口适配器（macOS 实现）
- ✅ packages/protocol/ — 枚举、请求/响应模型、错误模型、审计事件
- ✅ packages/tasking/ — 占位
- ✅ packages/security/ — 占位
- ✅ integrations/astrbot-plugin/ — QQ 命令路由骨架

### Milestone 1 — Protocol Schema

- ✅ TaskStatus, TaskType, RiskLevel, ErrorCode, AuditAction 枚举
- ✅ StatusResponse, TaskCreateRequest, TaskInfo, TaskListResponse 等请求/响应模型
- ✅ ErrorResponse 错误模型
- ✅ AuditEvent 审计事件模型

### Milestone 2 — Hermes 安装引导层

- ✅ packages/protocol/install.py — Hermes 安装状态模型
- ✅ packages/protocol/enums.py — 新增 HermesInstallStatus, Platform 枚举
- ✅ apps/installer/ — Hermes Agent 安装引导层
  - hermes_check.py: 命令检测、版本检查、平台支持检测
  - hermes_install.py: 分平台安装指导（不含复杂自动安装）
  - hermes_setup.py: HERMES_HOME 规划与环境变量设置
- ✅ apps/core/runtime.py — 集成安装检测到启动流程
- ✅ apps/bridge/routes/hermes.py — Hermes 环境设置 API
- ✅ apps/bridge/routes/status.py — 暴露 Hermes 安装状态

### Milestone 4 — Yachiyo 工作空间初始化流程

- ✅ apps/installer/workspace_init.py — 完整工作空间初始化器
- ✅ apps/shell/installer_api.py — WebView API 支持自动初始化
- ✅ apps/shell/window.py — 初始化界面和按钮支持
- ✅ apps/installer/hermes_install.py — 初始化指导内容更新
- ✅ 工作空间结构：
  - ~/.hermes/yachiyo/ 主目录
  - projects/, configs/, logs/, cache/, templates/ 子目录
  - .yachiyo_init 标记文件
  - yachiyo.json, environments.json, default.json 配置文件
- ✅ 初始化流程：
  - WebView 界面显示"自动初始化"按钮
  - 点击后调用 JavaScript → WebView API → Python 初始化器
  - 创建完整工作空间结构和配置
  - 自动重启进入正常模式

### Milestone 3 — 启动流程三状态联动（已修正）

- ✅ packages/protocol/enums.py — 修正 HermesInstallStatus 三状态模型
  - NOT_INSTALLED: Hermes Agent 未安装
  - INSTALLED_NOT_INITIALIZED: Hermes Agent 已安装，但 Yachiyo 工作空间未初始化
  - READY: Hermes Agent 已安装且 Yachiyo 工作空间已初始化
- ✅ apps/installer/hermes_check.py — 修正检测逻辑
  - 区分 Hermes installation/readiness 和 Yachiyo workspace initialization
  - check_hermes_basic_readiness(): 仅检查 Hermes 本身可用性
  - check_yachiyo_workspace(): 检查 Yachiyo 工作空间初始化状态
  - 不把 HERMES_HOME 可选项等同于配置状态
- ✅ apps/shell/app.py — 三状态启动流程分离
- ✅ apps/shell/window.py — 工作空间初始化界面内容
- ✅ apps/installer/hermes_install.py — 工作空间初始化指导
- ✅ 三状态分流:
  - NOT_INSTALLED: 安装引导模式
  - INSTALLED_NOT_INITIALIZED: 工作空间初始化引导模式
  - READY: 正常启动模式

## 初始化流程完整性

### 创建的目录结构

```
~/.hermes/yachiyo/
├── .yachiyo_init          # 初始化标记文件
├── projects/              # 项目配置和数据
├── configs/               # Yachiyo 应用配置
│   ├── yachiyo.json      # 主配置文件
│   └── environments.json # 环境配置
├── logs/                  # Yachiyo 应用日志
├── cache/                 # 临时缓存
└── templates/             # 配置模板
    └── default.json      # 默认项目模板
```

### 完整用户流程

1. **新用户**: 安装 Hermes Agent → 初始化 Yachiyo 工作空间 → 正常使用
2. **Hermes 老用户**: 直接初始化 Yachiyo 工作空间 → 正常使用
3. **完整用户**: 直接正常使用

## 状态检测逻辑确认

### 分层检测设计

1. **Hermes Agent 层**:
   - 平台支持检查
   - 命令存在性检查
   - 版本兼容性检查  
   - 基本可用性验证
2. **Yachiyo 工作空间层**:
   - 检查 yachiyo/ 目录是否存在
   - 检查 .yachiyo_init 标识文件
   - 不依赖 HERMES_HOME 环境变量（可选覆盖项）

### 状态判定规则

- **未安装**: Hermes Agent 命令不存在或版本不兼容
- **已安装未初始化**: Hermes Agent 可用，但 Yachiyo 工作空间未初始化  
- **已就绪**: Hermes Agent 可用且 Yachiyo 工作空间已初始化

## 架构边界确认

- apps/shell: 桌面壳（pywebview 仅为 MVP 原型，不影响长期边界），支持三状态启动分离和自动初始化
- apps/core: runtime + state + task orchestration + Hermes 安装检测，不直接暴露 HTTP
- apps/bridge: FastAPI 内部通信桥梁，仅供 UI 和 AstrBot 调用
- apps/locald: 本地能力适配器
- apps/installer: Hermes Agent 视为外部运行时依赖，提供分层检测、引导和工作空间初始化
- integrations/astrbot-plugin: QQ 桥接，路由到 Hermes 或 Hapi

## 当前状态

完整可运行的桌面应用骨架，具备：

- ✅ 正确架构分层和职责边界
- ✅ Hermes Agent 外部依赖管理和分层状态检测
- ✅ 启动流程三状态联动（正常 vs 工作空间初始化 vs 安装引导）
- ✅ 完整的工作空间初始化流程（自动 + 手动）
- ✅ shell → core → bridge 完整连通
- ✅ 跨平台支持策略
- ✅ 分层检测和动态界面引导

### Milestone 5 — 正常模式主界面与仪表盘

- ✅ apps/shell/main_api.py — 主窗口 WebView API（MainWindowAPI）
  - get_dashboard_data(): 汇聚 runtime 状态、Hermes 状态、工作空间状态、任务统计
  - get_settings_data(): 提供设置页完整数据（Hermes、工作空间、显示模式、Bridge、集成服务、应用配置）
  - update_settings(changes): 修改白名单内配置项并持久化（display_mode, bridge_enabled, bridge_host, bridge_port, tray_enabled）
- ✅ apps/shell/window.py — 正常模式主界面
  - 完整仪表盘 HTML 模板（_STATUS_HTML）：Hermes 状态、工作空间状态、运行信息、任务统计、显示模式切换入口
  - 设置面板：可编辑配置项
    - 显示模式：select 下拉选择
    - Bridge 开关：toggle 开关
    - Bridge 地址/端口：input 输入框
    - 系统托盘开关：toggle 开关
    - 保存状态提示（自动保存，3秒后消失）
  - create_main_window() 集成 MainWindowAPI（api= 参数传入 webview.start()）
  - 模板渲染改用 .replace() 避免 CSS 花括号与 .format() 冲突
  - 控制台备选方案 _print_console_dashboard()
  - 窗口尺寸扩大至 560x520
- ✅ apps/shell/config.py — 应用配置
  - 新增 bridge_enabled（默认 True）
  - 新增 tray_enabled（默认 True）
  - load_config() / save_config() 支持持久化
- ✅ apps/shell/app.py — Bridge 和 Tray 受配置开关控制
- ✅ 产品状态流定义：
  1. NOT_INSTALLED → 安装引导模式
  2. INSTALLED_NOT_INITIALIZED → 工作空间初始化引导模式
  3. READY → 正常模式主界面（仪表盘 + 可编辑设置 + 模式切换占位）
- ✅ 主界面仪表盘内容：
  - Hermes Agent 状态/版本/平台
  - Yachiyo 工作空间状态/路径/创建时间
  - 运行时间/版本
  - 任务统计（等待/运行/完成）
  - 显示模式切换按钮占位（窗口/气泡/Live2D）
  - 设置入口占位

## 当前状态

完整可运行的桌面应用骨架，具备正常模式主界面、可编辑设置面板、配置持久化、完整启动状态流和显示模式切换骨架。

### Milestone 6 — 显示模式切换骨架

- ✅ apps/shell/modes/__init__.py — 模式分发器 `launch_mode(runtime, config)`
  - 根据 config.display_mode 分发到对应模式 runner
  - 未知模式自动回退为 window
  - 每个模式模块导出 `run(runtime, config)` 函数
- ✅ apps/shell/modes/window.py — 窗口模式 runner（真正实现）
  - 委托 apps/shell/window.create_main_window()
- ✅ apps/shell/modes/bubble.py — 气泡模式 runner（占位实现）
  - 显示专属占位窗口（360×300），提示"即将推出"
  - 预留 run() 接口，后续完整实现时只需修改此文件
- ✅ apps/shell/modes/live2d.py — Live2D 模式 runner（占位实现）
  - 显示专属占位窗口（400×320），提示"即将推出"
  - 预留 run() 接口，后续完整实现时只需修改此文件
- ✅ apps/shell/app.py — _start_normal_mode() 改用 launch_mode(runtime, config)
  - 模式分支逻辑收敛到 modes/ 下，app.py 不再有模式分支

### display_mode 生效方式
1. 用户在设置面板修改 display_mode → update_settings() 写入 ~/.hermes-yachiyo/config.json
2. 下次启动时 load_config() 读取新值
3. _start_normal_mode() 调用 launch_mode(runtime, config)
4. launch_mode() 根据 config.display_mode 选择对应 runner

## 下一步

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。
