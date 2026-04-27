# Current State

## 已完成

### Milestone 63/64 — 下午桌面交互、设置与记忆规划收敛

- ✅ Hermes 执行体验
  - 默认执行超时从 60 秒提升为 30 分钟，并支持 `HERMES_YACHIYO_EXEC_TIMEOUT_SECONDS` 覆盖。
  - Hermes CLI / streaming bridge 增加首事件、首 token、完成、进程结束和超时耗时日志，用于诊断冷启动与响应延迟。
  - 每轮 Hermes 请求注入当前本地时间、星期和时段，避免下午仍按早晨语境回应。
  - 助手 prompt 包装顺序扩展为环境上下文 → 人设 → 用户称呼 → 用户请求。
- ✅ 共享助手资料与主设置
  - 新增 `assistant.user_address`，Bridge `GET/PATCH /assistant/profile`、协议 schema、配置加载保存和 Hermes 调用链已贯通。
  - 助手人设 Prompt 与用户称呼从模式设置收敛到 Control Center 主设置，避免 Bubble / Live2D 出现多份人设。
  - Control Center 的文本/数字/大段文本共通设置改为待确认保存，点击“应用共通设置修改”后统一提交。
  - 共通设置 dirty 判断改为与当前已提交值比较；用户改动后再改回原值会自动清除 pending。
  - 工作空间创建时间在 Control Center 和设置页中改为本地可读格式。
- ✅ Bubble / Live2D 桌面入口体验
  - Bubble 默认位置使用屏幕百分比定位，默认右下角；设置页暴露 0-100% 输入。
  - Bubble 靠边吸附正式实现，拖动释放后吸附最近屏幕边缘。
  - Bubble 呼吸灯语义调整：处理中为黄色，未读成功为绿色，未读失败为红色；Chat Window 打开时抑制状态点并确认可见结果。
  - Bubble / Live2D 点击聊天入口时改为打开或置前 Chat Window，不再因窗口已存在而关闭。
- ✅ Chat Window 交互
  - 消息文本可选择复制，消息右上角提供传统复制图标。
  - 复制成功后图标短暂变为对勾，复制链路优先走 pywebview 后端系统剪贴板，再回退浏览器剪贴板和 textarea。
  - 移除“重新编辑/重编”入口，避免当前历史链与 Hermes resume 语义不完整时产生误导。
  - Chat Window 已存在时使用 restore/show/bring_to_front/focus + macOS native focus 置前。
  - 若 WebView 初始化期 focus/show 某一步失败，不再把单例判坏并新建第二个白屏窗口；只有明确关闭/销毁才重建。
- ✅ 记忆架构文档
  - 新增 `docs/memory-architecture.md`，明确 SQLite 聊天记录只是原始会话存档，不等同长期记忆。
  - 记忆设计优先复用 Hermes 原生记忆；Yachiyo 作为本地桌面侧控制层，负责授权、项目归类、UI 管理、Bridge 边界和 prompt 注入策略。

### 当前验证结果

- ✅ 全量测试：`python -m pytest` → 360 passed。
- ✅ 相关 diagnostics：Chat Window、Control Center、Bubble/Live2D 入口和测试文件无 VS Code 错误。

### Milestone 65 — Chat Window 单例竞态隔离

- ✅ Chat Window 已存在时，macOS 置前改为只走原生标题聚焦，不再调用 pywebview 的 `restore/show/bring_to_front/focus` 组合，避免这些方法在初始化期或跨入口调用时触发空白副本。
- ✅ 新增 `_chat_window_creating` 防重入保护；创建窗口期间再次点击 Bubble/Live2D 会直接返回并尝试原生聚焦，不会嵌套创建第二个窗口。
- ✅ `events.closed` 回调改为只清理自己对应的 window，旧窗口延迟触发 closed 事件时不会误把当前活窗口单例置空。
- ✅ 回归测试覆盖原生聚焦路径、创建中重入、旧 closed 事件不清当前窗口。
- ✅ 全量测试：`python -m pytest` → 362 passed。

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
- **已安装未配置**: Hermes Agent 可用，但 `hermes setup` 未完成
- **配置进行中**: `hermes setup` 进程正在终端中运行
- **已安装未初始化**: Hermes Agent 可用且已配置，但 Yachiyo 工作空间未初始化  
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
- ✅ 启动流程五状态联动（安装引导 vs Setup 配置 vs Setup 进行中 vs 工作空间初始化 vs 正常模式）
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

完整可运行的桌面助手骨架。当前产品结构是 `Bubble / Live2D` 两种显示模式 + 按需打开的 `Control Center` 主控台；Control Center 不再参与 display mode 切换。旧 `display_mode="window"` 配置会在读取时迁移为 `bubble`。

> 下面 Milestone 55/56 保留历史改造记录；当前最终结构以 Milestone 57 和“当前产品职责确认”为准。

### Milestone 55 — 三模式统一架构重构

- ✅ `apps/shell/config.py`
  - 新增 `WindowModeConfig` / `BubbleModeConfig` / `Live2DModeConfig`
  - `AppConfig` 改为“通用配置 + 模式配置”结构
  - 兼容旧 `live2d` 配置块读取，统一落到 `live2d_mode`
- ✅ `apps/shell/mode_catalog.py`
  - 定义三模式并列元数据：Window / Bubble / Live2D
- ✅ `apps/shell/mode_settings.py`
  - 集中处理模式设置序列化、校验、保存
  - 支持 `window_mode.*` / `bubble_mode.*` / `live2d_mode.*`
  - 兼容旧 `live2d.*` 更新键
- ✅ `apps/shell/settings.py`
  - 改为“单模式设置窗口”而非混合设置页
  - Bubble / Live2D / Window 均可打开各自设置窗口
- ✅ `apps/shell/window.py`
  - Window Mode 明确为总控台
  - 主窗口展示状态、模式入口、最近消息概览、最近会话概览
  - 不再承载完整聊天 UI，只保留打开 Chat Window 入口
- ✅ `apps/shell/modes/bubble.py`
  - Bubble 从基础壳升级为完整轻量模式
  - 支持展开/收起、最近摘要、短输入、状态标签、打开完整聊天、打开模式设置
- ✅ `apps/shell/modes/live2d.py`
  - Live2D 从配置壳升级为角色聊天壳
  - 支持角色舞台、最近回复泡泡、最小输入入口、打开完整聊天、打开模式设置
  - 继续保留 renderer 接入位，不实现真实 Live2D 渲染
- ✅ `apps/shell/chat_bridge.py`
  - 新增统一会话概览接口 `get_conversation_overview()` / `get_recent_sessions()`
  - 供 Window / Bubble / Live2D 共享读取当前会话摘要

### 现在的四个入口职责

- **Window Mode**：总控台 / 仪表盘 / 模式入口 / 设置入口 / 最近会话与消息概览
- **Chat Window**：完整会话空间，承载完整消息流和历史会话切换
- **Bubble Mode**：常驻桌面轻量聊天模式，短输入 + 摘要 + 打开完整会话
- **Live2D Mode**：角色聊天壳，角色舞台 + 回复气泡 + 最小输入入口

### 统一聊天来源确认

- Window / Bubble / Live2D / Chat Window 全部继续共享 `runtime.chat_session`
- 摘要层统一经过 `ChatBridge → ChatAPI → ChatSession → ChatStore`
- 未引入新的 assistant message / task 映射逻辑副本

### 当前仍是后续精装修项

- 真正 Live2D renderer / moc3 渲染接入
- Bubble / Live2D 原生窗口位置恢复和更细 UI 打磨
- 更精细的未读态与模式动画表现

### Milestone 56 — Bubble / Live2D launcher 形态修正

- ✅ `apps/shell/modes/bubble.py`
  - Bubble 不再是完整聊天窗口壳，改为透明无边框圆形桌面 launcher
  - 单击气泡展开 / 收起统一 `Chat Window`
  - 右键菜单保留打开对话、主控台、设置、退出入口
  - Bubble 尺寸运行时夹在 96–128px，避免旧配置把 launcher 撑成窗口
- ✅ `apps/shell/modes/live2d.py`
  - Live2D 不再显示状态面板和输入区，改为透明无边框角色 launcher
  - 单击角色展开 / 收起统一 `Chat Window`
  - 保留 Live2D renderer / model3.json 接入位，当前仍是 CSS 占位角色舞台
- ✅ `apps/shell/config.py` / `apps/shell/mode_settings.py`
  - Live2D 新增 `scale` 配置，可在设置里控制角色缩放
  - Live2D 新增 `show_on_all_spaces`，用于 macOS 跨 Spaces / Mission Control 行为
- ✅ `apps/shell/native_window.py`
  - macOS 下 best-effort 设置 NSWindow level 与 collection behavior
  - `window_on_top=True` 时可作为浮动窗口；关闭后回到普通窗口层级，可被其他窗口覆盖
- ✅ `apps/shell/chat_window.py`
  - 新增 `toggle_chat_window()`，Bubble / Live2D 共用同一展开逻辑
- ✅ `apps/shell/main_api.py` / `apps/shell/window.py`
  - 主设置中切换 `display_mode` 保存后自动调度应用重启
  - `display_mode` 生效策略从“重启显示模式”升级为“重启应用”
- ✅ `apps/shell/settings.py`
  - 当时独立设置窗口改为 `Common + 当前模式设置`，不再只显示单模式字段
  - 后续 Milestone 58 已再次收敛：Common / 全局设置只放在 Control Center，模式窗口只展示对应模式专属设置

### 当前交互确认

- **Control Center**：独立主控台 / 设置 / 诊断入口，不再作为 display mode
- **Bubble Mode**：桌面圆形 launcher，点击展开 Chat Window
- **Live2D Mode**：桌面角色 launcher，点击展开 Chat Window
- **Chat Window**：Bubble / Live2D 共享的完整对话框

### Milestone 57 — Window Mode 移出显示模式体系

- ✅ `apps/shell/config.py`
  - `display_mode` 收敛为 `bubble | live2d`
  - 默认启动模式改为 `bubble`
  - 旧配置 `display_mode="window"` 读取时迁移为 `bubble`
- ✅ `apps/shell/modes/__init__.py`
  - 删除 Window 分发分支，未知 display mode 统一回退 Bubble
  - `apps/shell/modes/window.py` 已移除，避免继续把主控台当显示模式
- ✅ `apps/shell/mode_catalog.py` / `apps/shell/mode_settings.py`
  - 模式列表只返回 Bubble / Live2D
  - `mode_settings` 不再暴露 Window mode 分区
- ✅ `apps/shell/window.py`
  - 原 Window 页面改为 `Hermes-Yachiyo Control Center`
  - 主控台保留 Hermes / Workspace / Bridge / Integration / Task / 会话概览
  - 主控台操作区只提供打开对话、Bubble 设置、Live2D 设置、应用设置
- ✅ Bubble / Live2D 右键菜单
  - “主窗口”文案改为“主控台”
  - 仍可从 launcher 打开 Control Center，不丢失诊断和配置能力

### 当前产品职责确认

- **Bubble**：默认桌面入口，圆形 launcher，点击展开 / 收起 Chat Window
- **Live2D**：角色桌面入口，点击展开 / 收起 Chat Window
- **Control Center**：按需打开的主控台，不参与 display mode 切换
- **Chat Window**：统一完整对话窗口，Bubble / Live2D / Control Center 共用同一 `ChatSession`

### Milestone 58 — Launcher 菜单、设置归属与退出兜底

- ✅ Bubble / Live2D 右键菜单
  - 右键打开设置菜单后，点击 launcher 外部、按 Esc、窗口失焦都会关闭菜单
  - 菜单打开时再次左键点击 launcher 只关闭菜单，不误触发 Chat Window 展开
  - 右键菜单按点击点定位，并 best-effort 聚焦原生窗口 / 菜单首项
  - 拖动 launcher 超过阈值后吞掉随后的 click，避免拖动结束误展开对话框
- ✅ `apps/shell/settings.py` / `apps/shell/mode_settings.py`
  - 模式设置窗口不再返回或渲染 Common / display / bridge 全局配置
  - Bubble 设置窗口只展示 Bubble 专属项，Live2D 设置窗口只展示 Live2D 专属项
  - 全局应用设置继续由 Control Center 承担
- ✅ `apps/shell/window.py`
  - Control Center 的 Hermes 诊断同时展示受限工具列表和 doctor issue 数
  - doctor 发现问题或受限工具时显示补全能力入口，不再只依赖 `basic_ready`
  - Hermes 已就绪但 readiness 仍未知时，显示检测 / 补全入口并自动触发一次重检
  - 退出应用增加强制退出兜底，避免 pywebview 销毁卡住后留下白屏窗口
- ✅ `apps/installer/hermes_check.py`
  - `hermes doctor` 的 Tool Availability 解析支持 warning / failure 行
  - 工具名支持 `image_gen`、`agent-browser` 等包含 `_` / `-` / `.` 的名称
- ✅ `apps/shell/assets/`
  - 新增项目内默认头像 `avatars/yachiyo-default.jpg`
  - 新增默认 Live2D 模型目录 `live2d/yachiyo`
  - `AppConfig` 默认 Live2D 模型指向该内置模型，旧空配置读取时自动补默认路径
- ✅ Bubble 主动对话设置
  - 新增主动对话总开关、定期桌面观察开关和观察间隔设置
  - Bubble 红色呼吸灯只用于主动观察结果，不再因普通 assistant 回复点亮
  - 定期桌面观察会检查 Hermes 执行器 / vision 工具能力，不满足时给出阻塞提示
  - 能力满足时按间隔创建低风险桌面观察任务，用户打开 Chat Window 后确认并清除红点

### Milestone 6 — 显示模式切换骨架

- ✅ apps/shell/modes/**init**.py — 模式分发器 `launch_mode(runtime, config)`
  - 根据 config.display_mode 分发到对应模式 runner
  - 未知模式自动回退为 window
  - 每个模式模块导出 `run(runtime, config)` 函数
- ✅ apps/shell/modes/window.py — 窗口模式 runner（真正实现）
  - 委托 apps/shell/window.create_main_window()
- ✅ apps/shell/modes/bubble.py — 气泡模式 runner（最小可用实现）
  - 320×280 轻量悬浮窗口（on_top=True）
  - 显示 Hermes 状态、工作空间状态、运行时间
  - BubbleWindowAPI: get_bubble_data() / open_main_window() / close_bubble()
  - open_main_window(): 在当前 webview 会话中创建第二个完整仪表盘窗口
  - 15 秒自动刷新 + 手动刷新按钮
- ✅ apps/shell/main_api.py — bubble available 改为 True
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

### Milestone 7 — Bridge 状态接入主界面与 Bubble

- ✅ apps/shell/main_api.py — `get_dashboard_data()` 新增
  - `bridge`: enabled / host / port / url / running(占位)
  - `integrations`: astrbot / hapi 占位状态（not_connected）
- ✅ apps/shell/window.py — 主界面仪表盘更新
  - card3 “运行信息”：新增 Bridge 启用状态 + Bridge 地址行
  - 新增全宽“集成服务”卡（span 2）：AstrBot / Hapi 占位状态
  - `refreshDashboard()` JS 同步填充这些元素
- ✅ apps/shell/modes/bubble.py — 气泡模式增加
  - `get_bubble_data()` 新增 `bridge` (enabled+addr) 和 `astrbot` 状态字段
  - HTML 增加 Bridge / AstrBot 两行精简展示
  - JS 填充 bridge-status 和 astrbot-status

### Milestone 9 — AstrBot 插件最小桥接骨架

- ✅ integrations/astrbot-plugin/config.py — `PluginConfig` 数据类
  - `hermes_url` / `hapi_url` / `allowed_senders` / `timeout`
- ✅ integrations/astrbot-plugin/api_client.py — HTTP 客户端封装（依赖 `httpx`）
  - `HermesClient`: get_status / list_tasks / create_task / get_screen / get_active_window
  - `HapiClient`: run_codex（占位，Hapi /codex 端点待确认）
- ✅ integrations/astrbot-plugin/command_router.py — 命令路由分发
  - `HERMES_COMMANDS`: status / tasks / screen / window / do → Hermes Bridge
  - `HAPI_COMMANDS`: codex → Hapi
  - `route()`: 未知命令返回帮助文本，捕获异常返回错误提示
- ✅ integrations/astrbot-plugin/handlers/ — 各命令 handler 模块
  - `__init__.py`: 注册表 + `dispatch()` 统一入口
  - `status.py`: GET /status → 格式化运行状态摘要
  - `tasks.py`: GET /tasks → 格式化任务列表（最多显示 10 条）
  - `screen.py`: GET /screen/current → 元信息摘要（图片发送待联调）
  - `window.py`: GET /system/active-window → 活动窗口信息
  - `do.py`: POST /tasks → 创建任务并返回 ID/状态
  - `codex.py`: POST Hapi /codex → 占位实现
- ✅ integrations/astrbot-plugin/main.py — 重写为插件入口
  - `parse_y_command()`: 拆分 '/y sub args'
  - `on_y_command()`: 权限校验 + 路由（AstrBot 宿主调用此函数）

## 当前占位状态

- `codex.py` handler：Hapi /codex 端点 schema 待确认后完整实现
- `screen.py` handler：图片 base64 → AstrBot 图片消息转换待联调后启用
- `allowed_senders` 权限校验：逻辑已就位，AstrBot 宿主传入 sender_id 后生效
- AstrBot 宿主绑定：`on_y_command()` 入口已定义，与 AstrBot 事件系统的挂钩待联调

## 下一步

**AstrBot 宿主绑定**：在 AstrBot 插件框架中注册 /y 命令监听，调用 `on_y_command()`。

### Milestone 10 — AstrBot Handler 输出格式完善

- ✅ packages/protocol/schemas.py — `StatusResponse` 新增 `hermes_ready: bool`
- ✅ apps/bridge/routes/status.py — `/status` 端点填充 `hermes_ready`
- ✅ integrations/astrbot-plugin/api_client.py — `_raise_readable()` 提取 JSON 错误详情
- ✅ integrations/astrbot-plugin/handlers/utils.py（新建）— `fmt_status / fmt_status_icon / fmt_uptime / fmt_dt`
- ✅ handlers/status.py: 新增 Hermes Agent 就绪状态行，任务统计用图标精简格式
- ✅ handlers/tasks.py: 每条任务显示短 ID + 创建时间
- ✅ handlers/window.py: 新增查询时间行
- ✅ handlers/screen.py: 格式大写化，时间格式化，文案整洁
- ✅ handlers/do.py: 状态显示为中文标签，ID 截短为 8 位

### Milestone 11 — 统一 AstrBot 错误与不可用状态反馈

- ✅ handlers/utils.py — 新增 `fmt_error(exc, command)` + `_fmt_http_error()`
  - 连接失败 → "⚠️ 无法连接到 Hermes-Yachiyo，请确认桌面应用运行"
  - 连接超时 → "⚠️ 连接超时"
  - 读取超时 → "⚠️ 请求超时，请稍后重试"
  - HTTP 503 → "⚠️ Hermes Agent 未就绪（含桌面应用指引）"
  - HTTP 5xx → "⚠️ Bridge 内部错误 [状态码]"
  - HTTP 422/404/4xx → 对应可读提示
  - RuntimeError（来自 _raise_readable）→ 解析 [状态码] 后分类
  - 其他 → "⚠️ 未知错误"
- ✅ command_router.py — catch 块统一改用 `fmt_error(exc, command)`
- ✅ handlers/codex.py — 不发起 HTTP 请求，直接返回清晰占位消息
- ✅ handlers/status.py — `hermes_ready=False` 时新增桌面应用指引行

## 当前占位状态

- `/y codex`：直接返回"即将推出"（Hapi 端点待确认）
- `/y screen` 图片发送：base64 → AstrBot 图片消息待联调
- AstrBot 宿主绑定：`on_y_command()` 入口已定义，与 AstrBot 事件系统挂钩待联调

## Bridge 状态模型（Milestone 8）

- `apps/bridge/server.py`：`_state` 取值 `not_started | running | failed`
- `apps/shell/main_api.py`：四状态 `disabled / enabled_not_started / running / failed`
- `apps/shell/modes/bubble.py`：四状态标签展示
- `apps/shell/window.py`：bridge 行四状态标签展示

### Milestone 12 — 最小任务闭环

- ✅ apps/core/state.py — 新增 `update_task_status(task_id, status, result, error)`
  - 合法状态流转保护：终态（completed/cancelled/failed）不可再变更
  - 供未来执行器模块调用，当前不自动触发
- ✅ packages/protocol/schemas.py — 新增 `TaskGetResponse`
- ✅ apps/bridge/routes/tasks.py — 新增 `GET /tasks/{task_id}` 端点（404 if not found）
- ✅ integrations/astrbot-plugin/api_client.py — 新增 `get_task(task_id)` + `cancel_task(task_id)`
- ✅ integrations/astrbot-plugin/handlers/check.py（新建）— `/y check <id>` 查询任务详情
- ✅ integrations/astrbot-plugin/handlers/cancel.py（新建）— `/y cancel <id>` 取消任务
- ✅ integrations/astrbot-plugin/handlers/**init**.py — 注册 check + cancel handler
- ✅ integrations/astrbot-plugin/command_router.py — HERMES_COMMANDS 加入 check/cancel，帮助文本更新
- ✅ integrations/astrbot-plugin/handlers/do.py — 输出完整 task_id，提示 `/y check <id> 查询进度`

### 任务链路完整性

- `/y do <描述>` → POST /tasks → 返回完整 task_id + `/y check <id>` 使用提示
- `/y tasks` → GET /tasks → 列出全部任务（含短 ID + 时间）
- `/y check <id>` → GET /tasks/{id} → 任务详情（描述/状态/创建时间/结果/错误）
- `/y cancel <id>` → POST /tasks/{id}/cancel → 取消任务
- 任务当前保持 PENDING 状态（无执行引擎），是真实状态而非 bug

## 当前占位状态

- `/y codex`：直接返回"即将推出"（Hapi 端点待确认）
- `/y screen` 图片发送：base64 → AstrBot 图片消息待联调
- AstrBot 宿主绑定：`on_y_command()` 入口已定义，与 AstrBot 事件系统挂钩待联调
- 任务执行引擎：任务状态保持 PENDING，`update_task_status()` 已备好接口

## 下一步

**AstrBot 宿主绑定**：在 AstrBot 插件框架中注册 /y 命令，调用 `on_y_command()`。

### Milestone 13 — 任务状态最小推进

- ✅ apps/core/task_runner.py（新建）— 最小 asyncio 任务执行器
  - TaskRunner: 轮询 PENDING 任务，分派到独立协程
  - PENDING → RUNNING（2 秒延迟）
  - RUNNING → COMPLETED（再 5 秒，result 写入占位说明）
  - 异常时置 FAILED，cancelled_error 静默退出
  - stop() 优雅取消所有子协程
- ✅ apps/bridge/server.py — 新增 `_lifespan` FastAPI 生命周期
  - 启动时创建 TaskRunner 并调用 runner.start()
  - 停止时调用 runner.stop()
  - Runtime 未注入时优雅降级（跳过启动，不崩溃）
- ✅ integrations/astrbot-plugin/handlers/tasks.py — 状态展示升级
  - 每条任务显示完整状态标签（⏳ 等待中 / 🔄 运行中 / ✅ 已完成 / …）
  - 时间戳改为 updated_at（体现最新状态变更时间）

### 任务状态链路

1. `/y do <描述>` → 创建 PENDING 任务
2. ~2 秒后 → TaskRunner 推进至 RUNNING
3. ~再 5 秒后 → TaskRunner 推进至 COMPLETED（result 为占位说明）
4. `/y tasks` → 实时显示当前状态（含图标+文字标签）
5. `/y check <id>` → 详情含 result/error 字段
6. `/y cancel <id>` → 直接置 CANCELLED（TaskRunner 遇到终态冲突静默跳过）

真实 Hermes 集成时，只需替换 `TaskRunner._execute()` 中的模拟逻辑。

### Milestone 14 — TaskRunner 执行策略抽象

- ✅ apps/core/executor.py（新建）— 执行策略模块
  - `ExecutionStrategy`（ABC）: 抽象接口，`run(task) → str`
  - `SimulatedExecutor`: MVP 模拟实现（sleep 占位，不调用外部服务）
  - `HermesExecutor`: Hermes Agent 接入存根，带详细 TODO 注释，当前抛出 NotImplementedError
- ✅ apps/core/task_runner.py — 重构为策略注入模式
  - `TaskRunner(state, executor=None)`: executor 默认为 SimulatedExecutor
  - 内部拆分为 `_dispatch_pending()` 调度 + `_execute_with_state()` 状态机包装
  - 日志中记录当前 executor 类名，便于区分运行模式
  - 具体执行逻辑全部移入 executor.run()，TaskRunner 只管状态推进

### 接入 Hermes 的路径

后续真正接 Hermes 只需两步：

1. 补全 `apps/core/executor.py` 中 `HermesExecutor.run()`
2. 在 Bridge lifespan 构造 TaskRunner 时传入 `HermesExecutor()`

其余链路（状态机、Bridge API、AstrBot 展示）**无需改动**。

### Milestone 15 — HermesExecutor 最小接入骨架

- ✅ apps/core/executor.py — 大幅扩展
  - `ExecutionStrategy` 新增 `name` property（日志/状态展示用）
  - `SimulatedExecutor` 无逻辑变化，仅注释更新
  - `HermesExecutor` 完整骨架：
    - `is_available()`: 同步探测（subprocess hermes --version，超时 5s）
    - `run()`: 状态日志 + 委托 `_call_hermes()`
    - `_call_hermes()`: 详细注释两种接入方式（subprocess CLI / HTTP API），当前抛 NotImplementedError
    - 失败回退策略：`is_available()` 失败 → select_executor 回退 Simulated；run() 失败 → TaskRunner 标记 FAILED
  - `select_executor(runtime)` 工厂函数：
    - runtime.is_hermes_ready() 且 HermesExecutor.is_available() → HermesExecutor
    - 其他 → SimulatedExecutor（安全回退）
- ✅ apps/bridge/server.py — lifespan 改用 select_executor(rt) 选择执行器
  - 导入整理，去除重复 import

### 接入 Hermes 还差什么

| 步骤 | 状态 |
|------|------|
| 确认 Hermes Agent 接口形式（CLI / HTTP） | ❌ 待确认 |
| 实现 `HermesExecutor._call_hermes()` | ❌ 待实现 |
| `runtime.is_hermes_ready()` 在真机上返回 True | ❌ 依赖 Hermes 安装 |
| `select_executor()` 自动切换生效 | ✅ 逻辑已就位 |

### Milestone 16 — HermesExecutor 最小真实调用路径

- apps/core/executor.py — HermesExecutor 完整 subprocess 实现
  - 新增 HermesCallError(RuntimeError): 携带 returncode + stderr
  - _HERMES_CMD = [hermes, run, --prompt]: CLI 接口假设，集中管理
  - HermesExecutor(fallback_to_simulated=False): 可选降级开关
  - _call_hermes(description): asyncio.create_subprocess_exec 真实调用
    - FileNotFoundError → HermesCallError
    - asyncio.TimeoutError(60s) → 终止进程 + 抛出
    - returncode != 0 → HermesCallError(stderr[:200])
    - stdout 空 → 返回占位说明
  - run(task): 捕获失败，按 fallback 开关决定降级或抛出

### 回退策略

- Bridge 启动：is_available()=False → 全局使用 SimulatedExecutor
- 单次执行（fallback=False，默认）：失败 → 任务 FAILED，错误可见
- 单次执行（fallback=True，调试）：失败 → 降级 Simulated，任务 COMPLETED

### 真正完整接入还差什么

- 确认 hermes run --prompt 是正确 CLI 接口（或切换 HTTP API）
- 在测试机安装 Hermes Agent，验证 select_executor 自动切换
- 处理 Hermes 流式输出（当前收集全部 stdout）

### Milestone 17 — HermesExecutor 最小真实验证闭环

- apps/core/executor.py — 重构为职责分离三层
  - `HermesInvokeResult`（dataclass）: 结构化调用结果
    - success / stdout / stderr / returncode / error_message
    - output property: 成功时返回 stdout，失败时返回空串
    - to_task_error(): 格式化为可写入 TaskInfo.error 的字符串
  - `invoke_hermes_cli(description)`: 独立异步函数，最小调用单元
    - 构造 cmd → create_subprocess_exec → wait_for(communicate, 60s)
    - 所有失败路径均返回 HermesInvokeResult（不抛出），调用方决定如何处理
    - FileNotFoundError / asyncio.TimeoutError / returncode!=0 → success=False
  - `probe_hermes_available()`: 独立同步函数，hermes --version 探测
  - `HermesCallError.to_error_string()`: 结构化错误 → 可写入 error 字段的字符串
  - `HermesExecutor._call_hermes()`: 调用 invoke_hermes_cli()，映射结果/异常
  - `HermesExecutor.is_available()`: 委托 probe_hermes_available()
  - `select_executor()`: 改用 probe_hermes_available() 直接探测
- apps/core/task_runner.py — FAILED 时使用 HermesCallError.to_error_string()

### 当前 HermesExecutor 实际调用链

1. `invoke_hermes_cli(description)` → `hermes run --prompt "<description>"`
2. 等待 stdout/stderr，最多 60 秒
3. 返回 `HermesInvokeResult`（结构化）
4. `_call_hermes()` 映射：success=True → 返回 output；success=False → 抛 HermesCallError
5. `run()` 捕获 → fallback 或 重抛
6. `TaskRunner._execute_with_state()` 捕获 → update_task_status(FAILED, error=to_error_string())

### 调用成功 / 失败路径

| 场景 | HermesInvokeResult | TaskInfo |
|------|-------------------|----------|
| 正常输出 | success=True, stdout=... | status=COMPLETED, result=stdout |
| hermes 命令未找到 | success=False, error_message=... | status=FAILED, error="hermes 命令未找到..." |
| 超时（60s） | success=False, error_message=... | status=FAILED, error="Hermes 执行超时..." |
| returncode != 0 | success=False, stderr=... | status=FAILED, error="exit=N | stderr: ..." |
| stdout 为空 | success=True, stdout="[完毕无输出]" | status=COMPLETED, result="[完毕无输出]" |

### Milestone 18 — 真实 Hermes 安装流程

- packages/protocol/enums.py — HermesInstallStatus 新增两个状态
  - INSTALLING: 安装正在进行中
  - INSTALL_FAILED: 安装失败（此状态由前端记录，后端不持久化）
- apps/installer/hermes_install.py — 新增真实安装执行函数
  - InstallResult dataclass: 结构化安装结果（success/message/stdout/stderr/returncode）
  - run_hermes_install(on_output, timeout): 运行官方安装脚本
    - 命令: bash -c "curl -fsSL <官方脚本URL> | bash"
    - 实时输出回调 on_output(line)
    - 默认超时 300s（5分钟）
    - Windows 原生环境直接拒绝
    - 所有失败路径返回 InstallResult（不抛出）
- apps/shell/installer_api.py — InstallerWebViewAPI 新增三个方法
  - install_hermes(): 在后台线程启动安装，立即返回 {started: bool}
  - get_install_progress(): 前端轮询，返回 {running, lines[-50:], success, message}
  - recheck_status(): 安装完成后重新检测，返回 {status, ready, needs_init}
- apps/shell/window.py — 安装界面新增安装 UI 区域
  - NOT_INSTALLED 状态显示"一键安装"按钮
  - 安装进行中显示实时日志滚动（pre 元素）
  - 安装完成后调用 recheck_status() 决定下一步
  - 成功 → 重启进入正常模式；需初始化 → 重启进入初始化向导；失败 → 显示错误可重试

### 完整安装流程

1. 启动 → check_hermes_installation() → NOT_INSTALLED
2. 进入 installer 界面，显示"安装 Hermes Agent"按钮
3. 用户点击 → install_hermes() → 后台线程运行脚本
4. 前端 1.5s 轮询 get_install_progress() → 实时显示日志
5. 安装完成 → recheck_status()
   - READY → 重启进入正常模式
   - INSTALLED_NOT_INITIALIZED → 重启进入初始化向导
   - 其他 → 显示错误，允许重试

### Milestone 19 — 安装后环境刷新感知检测

**问题根因**：Hermes 官方安装脚本把二进制写入 `~/.local/bin` 等目录后，
当前 Python 进程的 PATH 不会自动刷新，导致 `recheck_status()`
调用 `subprocess.run(["hermes", "--version"])` 时仍然 `FileNotFoundError`，
误判为 Hermes 仍未安装。

**修复方案**：新增 `locate_hermes_binary()` 三级探测策略：

1. **当前 PATH**（`shutil.which("hermes")`）— 正常启动场景，最快
2. **常见安装路径扫描** — 直接检查 `~/.local/bin/hermes`、`~/.hermes/bin/hermes` 等 8 个路径
3. **登录 Shell 探测** — `bash/zsh -lc "command -v hermes"`，会 source 用户 rc 文件

**返回值区分**：

- `(path, needs_env_refresh=False)` — 在当前 PATH 找到，环境正常
- `(path, needs_env_refresh=True)` — 通过备用途径找到，当前进程需重启
- `(None, False)` — 完全未找到

**新增函数**（`apps/installer/hermes_check.py`）：

- `find_hermes_in_common_paths()` → `str | None`
- `probe_hermes_via_login_shell()` → `str | None`
- `locate_hermes_binary()` → `tuple[str | None, bool]`
- `check_hermes_installation_post_install()` → `tuple[HermesInstallInfo, bool]`
- `_check_hermes_installation_with_cmd(hermes_cmd)` — 使用指定路径执行完整检测

**`recheck_status()`**（`apps/shell/installer_api.py`）：

- 改用 `check_hermes_installation_post_install()`
- 新增返回字段 `needs_env_refresh: bool`

**前端处理**（`apps/shell/window.py` JS）：

- `needs_env_refresh=True` → 显示"已安装，环境待刷新，5秒后自动重启"
- 不再将此情况误报为"安装失败"

### Milestone 20 — 安装成功后自动过渡闭环

**修复三处问题：**

1. **PATH 注入**（hermes_check.py）
   - 新增 `_inject_hermes_bin_dir(path)` 函数
   - `locate_hermes_binary()` 找到备用路径时自动注入 `os.environ["PATH"]`
   - 后续子进程（subprocess.run）同样能找到 hermes，无需绝对路径
   - 删除了不再需要的 `_check_hermes_installation_with_cmd()`
   - `check_hermes_installation_post_install()` 简化为：注入PATH → 调用标准流程

2. **真正重启**（installer_api.py）
   - `restart_app()` 改为先 `subprocess.Popen([sys.executable] + sys.argv)`，再 `os._exit(0)`
   - 应用会自动重新拉起，不再停留在"安装成功应用已关闭"的中间态

3. **JS 过渡逻辑**（window.py）
   - `recheckAfterInstall()` 优先判断 `ready` / `needs_init`，再检查 `needs_env_refresh`
   - `ready=True`（含 `needs_env_refresh=True`）→ 1.5s 后重启进入主界面
   - `needs_init=True` → 1.5s 后重启进入初始化向导
   - `needs_env_refresh=True` 但状态仍未通过 → 2s 后重启重新检测
   - `needs_env_refresh` 现在仅作 Shell 提示，不再阻塞正常流程

**安装后完整状态流：**
安装脚本执行 → `recheck_status()` → PATH注入 → 标准检测：
  → READY → restart → 主界面
  → INSTALLED_NOT_INITIALIZED → restart → 初始化向导
  → needs_env_refresh=True（边缘情况）→ restart → 重新检测

### Milestone 21 — 初始化向导完整闭环

**修复三处问题：**

1. **WebView API 始终挂载**（window.py）
   - 原来只有 INSTALLED_NOT_INITIALIZED 才传 `api`，NOT_INSTALLED 时 `api=None`
   - 安装按钮 JS 调用 `window.pywebview.api.install_hermes()` 会静默失败
   - 修复：`create_installer_window` 始终创建并传入 `InstallerWebViewAPI()`
   - 窗口标题按状态区分："初始化工作空间" vs "安装 Hermes Agent"

2. **INITIALIZING 枚举状态**（enums.py）
   - 新增 `INITIALIZING = "initializing"`，完善首次启动状态机

3. **init section 进度反馈**（window.py）
   - 新增 `<pre id="init-log">` 进度日志区域
   - JS 按步骤追加日志：创建目录 → 创建项目 → 完成
   - created_items 逐条展示
   - 成功 → "正在进入主界面..." → 1.5s 后 restart_app()
   - 失败 → 显示错误，允许重试

**完整首次启动状态流（已闭环）：**

```
not_installed
  → 安装引导页（含安装按钮，API 已挂载）
  → install_hermes() [后台线程]
  → 轮询进度 → 安装完成
  → recheck_status()（PATH 注入）
  → installed_not_initialized → restart
  或 → ready → restart

installed_not_initialized
  → 初始化向导页（含初始化按钮，API 已挂载）
  → initialize_workspace()（同步）
  → 逐步展示 created_items
  → 初始化完成 → restart_app()（Popen 重新拉起）
  → 新进程 check_hermes_installation() → READY
  → _start_normal_mode → 主界面

ready
  → 直接进入主界面
```

### Milestone 22 — 统一启动决策层

**新文件 `apps/shell/startup.py`**

| 组件 | 职责 |
|------|------|
| `StartupMode` (StrEnum) | `NORMAL` / `INIT_WIZARD` / `INSTALLER` |
| `_INSTALL_STATUS_TO_MODE` | 状态 → 模式的唯一映射表 |
| `resolve_startup_mode(install_info)` | 纯映射函数，无副作用，易测试 |
| `run_normal_mode(config)` | 启动 Runtime + Bridge + 主窗口 |
| `run_installer_mode(config, install_info)` | 合并原来的 _start_setup_mode +_start_installer_mode |
| `launch(config)` | 统一入口：check → resolve → dispatch |

**`apps/shell/app.py` 精简为 3 行逻辑：**

```python
config = load_config()
launch(config)  # 所有状态判断在 startup.py
```

**扩展方式（后续新增状态只需）：**

1. 在 `_INSTALL_STATUS_TO_MODE` 加一行映射
2. 如需新模式，加对应的 `run_xxx_mode()` 并在 `launch()` 里分发

### Milestone 23 — startup 决策层与显示模式系统衔接

**`apps/shell/modes/__init__.py`**

- 新增 `DisplayMode` StrEnum：WINDOW / BUBBLE / LIVE2D
- 新增 `resolve_display_mode(config) -> DisplayMode`：解析配置，未知值回退为 WINDOW
- `launch_mode()` 内部改用 `DisplayMode` 枚举分发，不再比较字符串

**`apps/shell/startup.py`**

- `run_normal_mode()` 第一步显式调用 `resolve_display_mode(config)` 并记录日志
- 日志格式：`startup_mode=NORMAL, display_mode=window/bubble/live2d`
- `launch()` 在 NORMAL 分支也先解析 display_mode 并输出完整决策日志

**`apps/shell/config.py`**

- `display_mode` 字段改用 `Literal["window", "bubble", "live2d"]` 类型注解
- 新增 `DisplayModeValue` 类型别名

**两个维度在 startup.py 中的表达：**

```
launch()
  → resolve_startup_mode(install_info)  → NORMAL / INIT_WIZARD / INSTALLER
  → resolve_display_mode(config)        → WINDOW / BUBBLE / LIVE2D（仅 NORMAL 时）
  → logger.info("startup_mode=NORMAL, display_mode=window")
  → run_normal_mode() → launch_mode() → run()
```

### Milestone 24 — Live2D 模式骨架

**`apps/shell/modes/live2d.py`** 从纯占位提升为可接入骨架：

| 组件 | 内容 |
|------|------|
| `Live2DWindowAPI` | 独立 API 类，方法：`get_live2d_status()` / `open_main_window()` / `open_settings()` |
| `get_live2d_status()` | 返回 hermes / tasks / workspace / model / bridge 五组状态数据 |
| `model` 字段 | `loaded=False`, `name=""`, `available_motions=[]`，带 TODO 注释指向 `Live2DRenderer` |
| HTML 骨架 | 角色舞台区（占位动画）+ 状态条（hermes/任务状态）+ 工具栏（主窗口/设置/刷新） |
| 角色图标 | 根据任务运行状态切换 🎤 / ⚡（未来由 Live2D 动作系统替换） |
| 窗口 | 380×560，竖版，可缩放，挂载 `Live2DWindowAPI` |

**与 bubble 模式的边界：**

- bubble：180×280 横版，最小化状态摘要，主窗口入口
- live2d：380×560 竖版，角色舞台区占主体，状态条在底部，设置入口

**未来接入 Live2D 还差：**

1. `apps/shell/modes/live2d_renderer.py` — 封装 Live2D SDK（moc3 加载、动作系统）
2. `Live2DWindowAPI.load_model()` / `play_motion()` / `set_expression()` 方法实现
3. HTML 中的 `<canvas id="live2d">` 替换 `.character-placeholder`
4. pywebview 透明窗口支持（角色贴屏显示）

### Milestone 25 — Live2D 模型配置入口骨架

**`apps/shell/config.py`**

- 新增 `Live2DConfig` dataclass，字段：
  - `model_name: str = ""`            — 角色模型显示名
  - `model_path: str = ""`            — .moc3 模型目录路径
  - `idle_motion_group: str = "Idle"` — 待机动作组（Cubism 约定）
  - `enable_expressions: bool = False`— 表情系统开关（等待渲染器）
  - `enable_physics: bool = False`    — 物理模拟开关（等待渲染器）
  - `window_on_top: bool = True`      — 角色窗口置顶
  - `is_model_configured()` 方法：name 和 path 都不为空则返回 True
- `AppConfig` 新增 `live2d: Live2DConfig` 字段（`field(default_factory=Live2DConfig)`）
- `load_config()` 更新：特殊处理嵌套 live2d 配置的反序列化

**`apps/shell/settings.py`** ← 新文件

- `build_settings_html(config: AppConfig) -> str`：独立设置页 HTML，供 live2d 模式的 `open_settings()` 使用
- 包含区块：显示模式 / Live2D 配置（含状态、模型名、路径、动作/表情/物理开关）/ Bridge 配置 / AstrBot 集成占位

**`apps/shell/window.py`** — 主窗口设置面板

- 在"显示模式"section 之后新增"Live2D 模式配置"section（含 badge `骨架`）
- 7 个展示字段：model_configured / model_name / model_path / idle_motion_group / enable_expressions / enable_physics / 渲染器状态（只读占位）
- `refreshSettings()` JS 新增 Live2D 字段填充逻辑（读取 `d.live2d`）

**`apps/shell/main_api.py`** — get_settings_data()

- 返回值新增 `"live2d"` 键，包含所有 `Live2DConfig` 字段 + `renderer_available: False`

**`apps/shell/modes/live2d.py`** — get_live2d_status()

- `model` 字段从全硬编码更新为读取 `config.live2d`：
  - `configured`: 是否已配置模型（`is_model_configured()`）
  - `name`: 模型显示名
  - `path`: 模型路径
  - `idle_motion_group`, `expressions_enabled`, `physics_enabled`
- 前端 JS `label.textContent` 逻辑分三态：
  - 已加载（未来渲染器）→ 显示模型名
  - 已配置未加载 → "已配置模型: hiyori · 渲染器待实现"
  - 未配置 → "角色模型未配置"

**真正接入 Live2D 还差：**

1. `apps/shell/modes/live2d_renderer.py` — Live2D Cubism SDK 封装
2. `Live2DWindowAPI.load_model()` / `play_motion()` / `set_expression()` 实现
3. HTML canvas 替换占位 div
4. pywebview 透明窗口支持

### Milestone 26 — Live2D 配置最小校验与状态闭环

**`apps/shell/config.py`**

- 新增 `ModelState(StrEnum)` 枚举：
  - `NOT_CONFIGURED` — model_name 或 model_path 为空
  - `PATH_INVALID`   — 路径已填写但目录不存在
  - `PATH_VALID`     — 路径存在，渲染器未实现
  - `LOADED`         — 渲染器已加载（未来，不由 validate() 返回）
- `Live2DConfig.validate() -> ModelState`：调用 `Path.expanduser().exists()` 校验路径

**`apps/shell/modes/live2d.py`**

- `get_live2d_status()` model 字段新增 `state` 键（`validate().value`）
- 前端 JS label 改用 4 条 stateLabels 字典映射，覆盖全部状态

**`apps/shell/window.py`**

- 设置面板 Live2D 区块：`s-l2d-configured` → `s-l2d-state`（四态文本 + CSS 类）
- JS `refreshSettings()` 改用 stateMap 字典填充颜色和文字

**`apps/shell/main_api.py`**

- `get_settings_data()` live2d 键新增 `model_state` 字段

**`apps/shell/settings.py`**

- HTML 模板：`模型已配置` → `配置状态`，占位改为 `{model_state_label}`
- `build_settings_html()` 用 `_MODEL_STATE_LABELS` 字典映射四态文本和 CSS 类

### Milestone 27 — Live2D 配置资源目录结构检查

**`apps/shell/config.py`**

- `ModelState` 枚举新增 `PATH_NOT_LIVE2D`（目录存在但无模型文件），完整五态：
  `NOT_CONFIGURED → PATH_INVALID → PATH_NOT_LIVE2D → PATH_VALID → LOADED`
- 新增 `check_live2d_model_dir(path: Path) -> bool`：
  - 检查目录（及一级子目录）中是否存在 `*.moc3` 或 `*.model3.json`
  - 这是 Live2D Cubism 3/4 模型的两个特征文件
- `Live2DConfig.validate()` 新增第三层：路径存在 + 无特征文件 → `PATH_NOT_LIVE2D`

**`apps/shell/modes/live2d.py`**

- 前端 stateLabels 新增 `path_not_live2d` 条目

**`apps/shell/window.py`**

- 设置面板 JS stateMap 新增 `path_not_live2d` 条目（⚠️ 黄色 warn）

**`apps/shell/settings.py`**

- `_MODEL_STATE_LABELS` 新增 `path_not_live2d` 条目（含特征文件说明）

**校验层级（validate() 实现）：**

1. name/path 是否填写    → NOT_CONFIGURED
2. 目录是否存在且为目录  → PATH_INVALID
3. 是否含模型特征文件    → PATH_NOT_LIVE2D
4. 渲染器是否可用        → PATH_VALID（渲染器返回 LOADED）

### Milestone 28 — Live2D 配置最小模型信息摘要

**`apps/shell/config.py`**

- 新增 `ModelSummary` dataclass（纯静态文件名摘要）：
  - `model3_json: str`       — 检测到的 .model3.json 文件名
  - `moc3_file: str`         — 检测到的 .moc3 文件名
  - `found_in_subdir: bool`  — 文件是否在子目录
  - `subdir_name: str`       — 子目录名（found_in_subdir=True 时）
  - `extra_moc3_count: int`  — 额外 .moc3 文件数量（多模型目录提示）
  - `is_empty()` 方法
- 新增 `scan_live2d_model_dir(path: Path) -> ModelSummary`：
  - 根目录优先扫描 *.moc3 /*.model3.json
  - 找不到再扫一级子目录，取第一个有内容的子目录
- `Live2DConfig.scan() -> ModelSummary | None`：目录不存在或未配置返回 None

**`apps/shell/main_api.py`**

- 新增 `_serialize_summary(summary)` 辅助函数（ModelSummary → dict）
- `get_settings_data()` live2d 键新增 `summary` 字段
- 导入 `ModelSummary`

**`apps/shell/modes/live2d.py`**

- `get_live2d_status()` model 字段新增 `summary` 键
- 导入 `_serialize_summary`

**`apps/shell/window.py`**

- 设置面板 Live2D 区块新增三行：检测到 .model3.json / 检测到 .moc3 / 文件位置
- JS `refreshSettings()` 新增摘要字段填充逻辑（extra_moc3_count 拼接提示）

**`apps/shell/settings.py`**

- HTML 模板新增三行摘要展示
- `build_settings_html()` 新增摘要格式化逻辑（含子目录名 / extra_moc3_count）

### Milestone 29 — Live2D 摘要补主候选入口整理

**`apps/shell/config.py`** — ModelSummary + scan_live2d_model_dir()

- `ModelSummary` 新增两个绝对路径字段：
  - `primary_model3_json_abs: str` — .model3.json 的绝对路径（渲染器首选入口）
  - `primary_moc3_abs: str`        — .moc3 的绝对路径（兜底）
- 新增 `renderer_entry` property：优先返回 model3.json 路径，其次 moc3，无则空
- `scan_live2d_model_dir()` 在扫描时同步填充 `primary_*_abs` 字段（`.resolve()`）

**`apps/shell/main_api.py`** — _serialize_summary()

- 返回 dict 新增三个字段：
  - `primary_model3_json_abs`
  - `primary_moc3_abs`
  - `renderer_entry`（推荐入口，model3.json 优先）

**`apps/shell/window.py`**

- 设置面板 Live2D 区块新增"渲染器入口候选"行（显示绝对路径，小字）
- JS `refreshSettings()` 填充 `s.renderer_entry`，有值绿色，无值暗灰

**`apps/shell/settings.py`**

- HTML 模板新增"渲染器入口候选"行
- `build_settings_html()` 新增 `s_entry` / `s_entry_cls` 格式化

**renderer 接入时的消费方式（文档化）：**

```python
summary = config.live2d.scan()
if summary and summary.renderer_entry:
    renderer.load(summary.renderer_entry)  # 唯一入口
```

### Milestone 30 — Live2D 配置最小可编辑能力

**`apps/shell/main_api.py`**

- `update_settings()` 新增 `live2d.*` 前缀嵌套字段支持
  - `_EDITABLE_LIVE2D_FIELDS` 白名单：model_name / model_path / idle_motion_group / enable_expressions / enable_physics / window_on_top
  - 字段名以 `live2d.` 开头 → 写入 `config.live2d.*`，同步保存配置

**`apps/shell/window.py`**（主窗口内嵌设置面板）

- Live2D 设置区域 HTML 改为可编辑控件：
  - model_name / model_path / idle_motion_group → `<input class="s-input">`
  - enable_expressions / enable_physics / window_on_top → `<label class="s-toggle">` + checkbox
- JS `onSettingChange(key, value)` 支持 `live2d.*` 前缀写入
- JS `refreshSettings()` 填充 `.value` / `.checked`，加 active-element 守护（防止用户输入被覆盖）

**`apps/shell/settings.py`**（Live2D 模式独立设置窗口）

- HTML 模板 `_SETTINGS_HTML` 重构为带输入控件版本：
  - model_name / model_path / idle_motion_group → `<input class="s-input">` with `onchange="saveLive2D(...)"`
  - enable_expressions / enable_physics / window_on_top → `<label class="s-toggle">`
  - 新增 `save-hint` 显示区（3秒后消失）
  - 新增 JS `saveLive2D(field, value)` → `window.pywebview.api.update_settings({'live2d.<field>': value})`
- `build_settings_html()` 参数改为输入控件初始值（`model_name_val` / `expr_checked` 等）

**`apps/shell/modes/live2d.py`**（Live2DWindowAPI）

- 新增 `update_settings(changes: dict) -> dict` 方法
  - 独立处理 `live2d.*` 前缀字段，不依赖 main_api
  - 应用变更后调用 `save_config()`
  - 返回 `{ok, applied, errors?}`
- `open_settings()` 传入 `js_api=self`，让设置窗口可调用 `update_settings`

**可编辑字段一览：**

| 字段 | 控件类型 | 默认值 |
|------|---------|--------|
| model_name | text input | 空 |
| model_path | text input | 空 |
| idle_motion_group | text input | Idle |
| enable_expressions | toggle | False |
| enable_physics | toggle | False |
| window_on_top | toggle | False |

### Milestone 31 — 保存后重新校验与即时状态刷新

**`apps/shell/modes/live2d.py`**

- 新增 `get_live2d_state() -> dict`：调用 `validate()` + `scan()` + `_serialize_summary()`，返回完整当前状态
- `update_settings()` 保存成功后调用 `get_live2d_state()` 并将结果作为 `live2d_state` 字段一并返回

**`apps/shell/main_api.py`**

- `update_settings()` 当 `applied` 中包含 `live2d.*` 字段时，将最新校验结果（validate + scan）作为 `live2d_state` 字段返回

**`apps/shell/settings.py`**（独立设置窗口）

- read-only span 元素补 ID：`sw-summary-json` / `sw-summary-moc3` / `sw-summary-loc` / `sw-summary-entry`
- 新增 JS `_STATE_LABELS` 字典和 `updateLive2DState(state)` 函数：
  - 更新 `sw-l2d-state` 文本与颜色
  - 更新 4 个摘要字段（model3_json / moc3_file / 文件位置 / renderer_entry）
- `saveLive2D()` 保存成功后，若 `res.live2d_state` 存在则立即调用 `updateLive2DState(res.live2d_state)`

**刷新闭环：**

- 独立设置窗口：`onchange` → `saveLive2D()` → `update_settings()` → 返回 `live2d_state` → `updateLive2DState()` → DOM 即时更新
- 主窗口设置面板：`onSettingChange()` → `update_settings()` → `refreshSettings()` → `get_settings_data()` → 重新渲染（已有）
- Live2D 模式窗口：`refreshStatus()` 每 10 秒轮询 `get_live2d_status()`（已有）

### Milestone 32 — 通用配置保存后即时刷新闭环

**`apps/shell/main_api.py`**

- 新增 `_current_app_state() -> dict` 方法：返回当前可编辑配置快照
  - 包含：`display_mode` / `bridge`（enabled/host/port/url/running）/ `tray_enabled`
- `update_settings()` 在成功保存后始终附带 `app_state`（所有保存操作都带）

**`apps/shell/window.py`**

- 新增 JS `applyAppState(state)` 函数：直接更新 DOM，无需额外 API 调用
  - 设置面板：display_mode 下拉 / bridge toggle+host+port+url / tray toggle
  - 仪表盘 Bridge 卡：bridge-enabled 状态标签 + bridge-addr（即时同步）
- `onSettingChange()` 重构：
  - 保存成功 → `applyAppState(res.app_state)` 直接更新（1 次 API 调用）
  - display_mode 或 live2d.* 变更时，额外调用 `refreshSettings()` 重新渲染标签列表

**刷新策略对照表：**

| 配置字段 | 触发方式 | 刷新路径 | API 调用数 |
|---------|---------|---------|----------|
| bridge_enabled | toggle | applyAppState → 设置面板+仪表盘同步 | 1 |
| bridge_host | input | applyAppState → 设置面板+仪表盘同步 | 1 |
| bridge_port | input | applyAppState → 设置面板+仪表盘同步 | 1 |
| tray_enabled | toggle | applyAppState → 设置面板同步 | 1 |
| display_mode | select | applyAppState + refreshSettings（标签列表重渲染） | 2 |
| live2d.* | input/toggle | applyAppState + refreshSettings（live2d 只读区刷新） | 2 |

### Milestone 33 — 设置生效策略 + 运行时反馈 + 控制入口

**新增 `apps/shell/effect_policy.py`**

- `EffectType` 枚举：`IMMEDIATE` / `REQUIRES_MODE_RESTART` / `REQUIRES_BRIDGE_RESTART` / `REQUIRES_APP_RESTART`
- `_FIELD_POLICIES` 集中注册表：11 个可编辑字段 → (效果类型, 用户友好文案)
- `get_effect(key)` → 查询单字段策略
- `build_effects_summary(applied_keys)` → 生成统一 effects 摘要，含分级提示

**策略分配：**

| 字段 | 生效策略 |
|------|---------|
| live2d.model_name | immediate |
| live2d.model_path | immediate |
| live2d.idle_motion_group | immediate |
| live2d.enable_expressions | immediate |
| live2d.enable_physics | immediate |
| live2d.window_on_top | requires_mode_restart |
| display_mode | requires_mode_restart |
| bridge_enabled | requires_bridge_restart |
| bridge_host | requires_bridge_restart |
| bridge_port | requires_bridge_restart |
| tray_enabled | requires_app_restart |

**`apps/shell/main_api.py` 变更**

- 新增 `_bridge_boot_config` 快照：记录 bridge 启动时的配置
- `_current_app_state()` 新增 `bridge.config_dirty` 字段：检测已保存配置与运行配置差异
- `update_settings()` 返回新增 `effects` 字段：来自 `build_effects_summary()`

**`apps/shell/modes/live2d.py` 变更**

- `update_settings()` 返回新增 `effects` 字段（与 main_api 一致的格式）

**`apps/shell/window.py` 变更**

- 新增 CSS：`effect-hints` / `effect-hint-row` / 四级颜色分类 / `bridge-dirty-hint`
- Bridge 设置区新增 `bridge-dirty-hint` 提示条：当 bridge.config_dirty 时显示
- `applyAppState()` 增加 bridge config_dirty 联动
- 新增 JS `showEffectHints(effects)` 函数：根据 effects 数据渲染分级提示
- `onSettingChange()` 保存成功后调用 `showEffectHints(res.effects)`

**`apps/shell/settings.py` 变更**

- 新增 CSS：`effect-hints` 分级提示样式
- 新增 `effect-hints` DOM 容器
- 新增 JS `showEffectHints(effects)` 函数
- `saveLive2D()` 保存成功后调用 `showEffectHints(res.effects)`

**用户体验流程：**

1. 修改 bridge_host → 保存 → 提示 "🔌 Bridge 地址变更需重启 Bridge 后生效"
2. 修改 display_mode → 保存 → 提示 "🔄 显示模式将在下次启动时生效"
3. 修改 live2d.model_path → 保存 → 提示 "✓ 模型路径已更新，已重新校验"
4. 修改 tray_enabled → 保存 → 提示 "⚡ 托盘设置将在下次启动时生效"
5. Bridge 区域：当已保存配置与运行配置不一致时，显示黄色漂移提示条

### Milestone 34 — Bridge 运行控制 + AstrBot 接入可观测性

**新增 `apps/shell/integration_status.py`**

- 集中产出 Bridge / AstrBot / Hapi 运行时状态
- `BridgeStatus` dataclass：四状态(disabled/enabled_not_started/running/failed) + config_dirty + drift_details + boot_config
- `AstrBotStatus` dataclass：四状态(not_configured/configured_not_connected/connected/unknown) + bridge_ready + blockers
- `HapiStatus` dataclass：四状态(not_configured/configured_not_connected/connected/unknown)
- `get_integration_snapshot()` 一次性获取全部集成状态
- `to_dict()` / `to_dashboard_dict()` 供前端消费

**Bridge 状态模型**

| 状态 | 条件 | 展示 |
|------|------|------|
| disabled | bridge_enabled=False | ⛔ 已禁用 |
| enabled_not_started | enabled 但进程未完成启动 | ⏳ 启动中 |
| running | uvicorn 正常运行 | ✅ 运行中 |
| failed | 启动后异常退出 | ❌ 异常退出 |

**Bridge 配置漂移展示**

- `_bridge_boot_config` 记录启动时快照
- `drift_details` 列出每个差异字段（如 "地址: 127.0.0.1 → 0.0.0.0"）
- 设置页新增"运行地址"行（仅 dirty 时显示）+ 差异明细区
- 仪表盘 bridge 卡即时同步

**AstrBot 接入状态**

| 状态 | 条件 | 展示 |
|------|------|------|
| not_configured | bridge 运行但用户未配置 AstrBot 插件 | ⚪ 未配置 |
| configured_not_connected | bridge 异常/未启动 | ⏳ 已配置但未连接 |
| connected | 未来真实接入 | ✅ 已连接 |
| unknown | 无法判定 | ❓ 状态未知 |

**状态来源统一**

- `main_api.py` 的 `get_dashboard_data()` / `get_settings_data()` / `_current_app_state()` 全部消费 `get_integration_snapshot()`
- `bubble.py` 的 `get_bubble_data()` 消费 `get_integration_snapshot()`
- `settings.py` 的 `build_settings_html()` 通过辅助函数获取 bridge/astrbot 状态
- 不再各自硬编码 "not_connected"

**UI 变更**

- 仪表盘集成服务卡：AstrBot 行增加说明行 + blockers 行
- 设置页 Bridge 区：新增"运行状态"行 + "运行地址"行 + drift_details 差异明细
- 设置页集成服务区：AstrBot 行增加说明/blocker + "AstrBot 是什么？" 依赖说明
- Bubble 模式：bridge 状态增加 ⚠️ dirty 标记，AstrBot 显示 label 而非硬编码文案
- 独立设置窗口：Bridge 运行状态行 + AstrBot 接入状态 + 依赖说明

**文件变更**

| 文件 | 变更 |
|------|------|
| apps/shell/integration_status.py | **新增** — 统一状态产出源 |
| apps/shell/main_api.py | 消费 integration_status，移除硬编码 |
| apps/shell/modes/bubble.py | 消费 integration_status，增强展示 |
| apps/shell/window.py | 仪表盘+设置页 bridge/astrbot 展示增强 |
| apps/shell/settings.py | bridge 运行状态 + AstrBot 接入状态 + 依赖说明 |

### Milestone 35 — Bridge 最小控制闭环

**Bridge 控制动作**

- `apps/bridge/server.py` 新增 `restart_bridge(host, port)` — 停止旧 uvicorn 实例 → 等待旧线程退出(最多5s) → 新后台线程启动
- `start_bridge()` 正常退出（被 should_exit 停止）时自动归零为 `not_started`
- 新增 `get_running_config()` 返回当前实际使用的 host/port
- 失败路径覆盖：bridge 未启用 / 停止超时 / 端口无效 / 启动异常

**MainWindowAPI.restart_bridge()**

- 检查 bridge_enabled
- 调用 server.restart_bridge() 停止 + 重启
- 成功后刷新 `_bridge_boot_config` → config_dirty 归零
- 返回最新 app_state 供前端刷新

**设置页 UI**

- bridge 区新增"🔄 应用配置并重启 Bridge"按钮（仅 config_dirty + bridge 已启用时显示）
- JS `restartBridge()` 函数：调用 API → 显示结果 → 刷新 dashboard → 自动隐藏按钮
- 成功: "✅ Bridge 已重启" / 失败: "❌ ..." 提示

**AstrBot 漂移警告**

- `get_astrbot_status()` 新增：bridge running + config_dirty 时增加 blocker "Bridge 配置已修改但尚未重启，AstrBot 可能使用旧地址"
- bridge 重启成功后 blocker 自动消除

**Bubble 模式**

- `BubbleWindowAPI` 新增 `restart_bridge()` API，共享同一 server 层实现

**文件变更**

| 文件 | 变更 |
|------|------|
| apps/bridge/server.py | 新增 restart_bridge / get_running_config / 停止后归零 |
| apps/shell/main_api.py | 新增 restart_bridge() API |
| apps/shell/integration_status.py | AstrBot config_dirty 漂移 blocker |
| apps/shell/window.py | 重启按钮 + restartBridge() JS |
| apps/shell/modes/bubble.py | 新增 restart_bridge() |

### Milestone 36 — 冲刺到可运行测试

**测试套件**
建立了完整测试基础设施，7 个测试文件、105 个测试用例，全部通过。

| 测试文件 | 测试用例数 | 覆盖范围 |
|---------|-----------|---------|
| test_protocol.py | 14 | Enum 值、TaskInfo、Request/Response 模型、ScreenshotResponse、ActiveWindowResponse |
| test_state.py | 11 | AppState 任务创建/取消/状态推进/终态保护/完整生命周期 |
| test_executor.py | 7 | HermesCallError、HermesInvokeResult、SimulatedExecutor |
| test_effect_policy.py | 9 | get_effect 策略查询、build_effects_summary 混合效果 |
| test_integration_status.py | 11 | BridgeStatus/AstrBotStatus/HapiStatus/IntegrationSnapshot + config_dirty 漂移 |
| test_astrbot_handlers.py | 32 | 命令解析、ACL、帮助/未知命令、8 个 handler 输出格式、错误格式化、状态工具函数 |
| test_startup.py | 6 | resolve_startup_mode 决策树全路径 |

**测试基础设施**

- `tests/conftest.py` — Bridge mock 注入（避免真实 uvicorn/fastapi 依赖）+ fixtures
- `importlib.util.spec_from_file_location` 解决 astrbot-plugin 连字符目录导入问题
- pytest + pytest-asyncio 异步 handler 测试

**如何运行测试**

```bash
cd /path/to/Hermes-Yachiyo
.venv/bin/python -m pytest tests/ -v
```

**文件变更**

| 文件 | 变更 |
|------|------|
| tests/**init**.py | 新增 — 包标记 |
| tests/conftest.py | 新增 — mock 注入 + fixtures |
| tests/test_protocol.py | 新增 — protocol schema 测试 |
| tests/test_state.py | 新增 — AppState 生命周期测试 |
| tests/test_executor.py | 新增 — executor 模型测试 |
| tests/test_effect_policy.py | 新增 — 设置生效策略测试 |
| tests/test_integration_status.py | 新增 — 集成状态统一来源测试 |
| tests/test_astrbot_handlers.py | 新增 — AstrBot 全 handler 输出/错误/ACL 测试 |
| tests/test_startup.py | 新增 — startup 决策路径测试 |
| apps/**init**.py | 新增 — 包标记 |
| packages/**init**.py | 新增 — 包标记 |
| integrations/**init**.py | 新增 — 包标记 |

### Milestone 37 — Hermes Setup 阶段纳入状态流

将 Hermes 安装后的 `hermes setup` 交互式配置阶段纳入正式产品流，解决用户安装完成后"卡在 setup"的体验问题。

**状态流更新（五状态）**：

```
NOT_INSTALLED → 安装引导
INSTALLED_NEEDS_SETUP → Setup 配置引导
SETUP_IN_PROGRESS → Setup 进行中（终端已打开）
INSTALLED_NOT_INITIALIZED → Yachiyo 工作空间初始化向导
READY → 正常主界面
```

**变更**：

- ✅ packages/protocol/enums.py — 新增 `INSTALLED_NEEDS_SETUP` + `SETUP_IN_PROGRESS` 枚举值
- ✅ apps/installer/hermes_check.py
  - 新增 `check_hermes_setup()` 检测函数（`hermes status` 退出码 + 配置文件存在性）
  - 新增 `is_hermes_setup_running()` 进程检测（`ps aux` 匹配 hermes setup 进程）
  - `check_hermes_installation()` setup 检查时先检测进程在运行 → `SETUP_IN_PROGRESS`
- ✅ apps/installer/hermes_install.py — `get_install_instructions()` 新增 `INSTALLED_NEEDS_SETUP` + `SETUP_IN_PROGRESS` 分支
- ✅ apps/shell/startup.py — `_INSTALL_STATUS_TO_MODE` 显式映射两个 setup 状态 → INSTALLER
- ✅ apps/shell/installer_api.py
  - `open_hermes_setup_terminal()` 增加防重复检测（`is_hermes_setup_running()` 前置检查）
  - 返回值新增 `already_running` 字段
  - 新增 `check_setup_process()` 方法供前端轮询进程状态
- ✅ apps/shell/window.py
  - `status_mapping` + 标题逻辑处理 `SETUP_IN_PROGRESS`
  - setup 引导 UI 增强：
    - 进程正在运行时隐藏「开始配置」按钮，显示「配置终端已打开」提示
    - 打开终端后自动轮询进程状态（3 秒间隔）
    - 进程结束后恢复按钮，提供「重新打开配置终端」选项
    - 已有进程运行时点击「开始配置」不会重复启动
  - `recheckAfterInstall()` 支持 `setup_in_progress` 状态跳转
  - `create_installer_window()` 窗口标题适配 setup 进行中
- ✅ tests/test_startup.py — 新增 `test_setup_in_progress_to_installer`

**Setup 检测策略**：

1. `hermes status` 退出码为 0 → setup 已完成
2. HERMES_HOME 下存在 config.yaml / config.yml / config.json → setup 已完成
3. 以上均不满足 → 检测是否有 setup 进程 → `SETUP_IN_PROGRESS` 或 `INSTALLED_NEEDS_SETUP`

**进程检测策略**：

- `ps aux` 匹配含 "hermes" 和 "setup" 的行（排除 grep 和 python 自身）

### Milestone 38 — macOS 托盘主线程修复

**问题**：normal mode 进入后 `system-tray` 子线程调用 `create_tray()` → `pystray.Icon.__init__()` → `AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_()` 等 AppKit UI 对象创建在非主线程 → `NSWindow should only be instantiated on the main thread!` 崩溃。

**根因**：pystray 0.19.5 darwin 后端在构造函数中直接创建 NSStatusItem，必须在主线程执行。当前代码通过 `threading.Thread` 在子线程调用，违反 macOS AppKit 线程要求。

**解决方案**：GCD `dispatch_async_f` + pystray `run_detached()`

| 关键点 | 说明 |
|--------|------|
| GCD 主队列与主线程 run loop 绑定 | 在 `webview.start()` 之前入队，NSApp 启动后自动在主线程执行 |
| `pystray._darwin._run_detached()` 只调用 `_mark_ready()` | 不启动第二个 `NSApp.run()`，图标挂载到 pywebview 的 NSApp 循环 |
| `ctypes.CDLL(None)` + `dispatch_async_f` | 跨平台安全，不依赖 PyObjC 私有 API |

**变更**：

- ✅ `apps/shell/tray.py`
  - 保留原 `create_tray()` 供非 macOS 使用
  - 新增 `_GCD_CALLBACKS` — 防止 ctypes CFUNCTYPE 被 GC
  - 新增 `_dispatch_to_main_queue(fn)` — GCD dispatch_async_f 封装
  - 新增 `create_tray_macos(runtime)` — macOS 入口，GCD 调度，非阻塞
  - 新增 `_create_tray_main_thread(runtime)` — 在主线程构造 Icon + run_detached()
- ✅ `apps/shell/startup.py`
  - `run_normal_mode()` platform 分支：macOS 调 `create_tray_macos()`，其余平台保持线程方式
  - 更新注释说明托盘线程模型差异

**修复后行为**：

1. startup.py 在主线程调用 `create_tray_macos(runtime)` → GCD 入队（非阻塞）
2. `launch_mode()` → `webview.start()` → macOS NSApp.run() 开始
3. GCD 主队列处理：`pystray.Icon(...)` 在主线程构造，`icon.run_detached()` 激活
4. 托盘图标正常显示，事件由 pywebview 的 NSApp 分发

### Milestone 39 — 修复 GCD dispatch_get_main_queue 符号不可用

**问题**：Milestone 38 的 GCD 方案在启动时报 `AttributeError: dlsym(RTLD_DEFAULT, dispatch_get_main_queue): symbol not found`。

**根因**：`dispatch_get_main_queue()` 在 macOS libdispatch 中是 `DISPATCH_INLINE DISPATCH_ALWAYS_INLINE` 内联函数，**不作为符号导出**，`dlsym` 查找失败。底层真正的主队列对象是 `_dispatch_main_q`，`dispatch_get_main_queue()` C 实现就是 `return &_dispatch_main_q`。

**修复**（一行改动）：

```python
# 旧（失败）:
lib.dispatch_get_main_queue.restype = ctypes.c_void_p
queue = lib.dispatch_get_main_queue()

# 新（正确）:
main_q_obj = ctypes.c_void_p.in_dll(lib, "_dispatch_main_q")
queue = ctypes.addressof(main_q_obj)
```

`_dispatch_main_q` 是 libdispatch 的稳定导出符号，macOS 10.6+ 全版本可用。

**同时新增受控降级**：`create_tray_macos()` 包裹 try/except，GCD 整体失败时只 log warning，不崩溃，不影响主窗口/bridge/bubble/live2d。

**变更**：

- ✅ `apps/shell/tray.py`
  - `_dispatch_to_main_queue()` — 替换取主队列句柄的方式：`dispatch_get_main_queue()` → `ctypes.c_void_p.in_dll(lib, "_dispatch_main_q")` + `ctypes.addressof()`
  - `create_tray_macos()` — 新增 try/except 受控降级
  - 更新模块/函数注释，说明内联函数不可 dlsym 的原因

**验证**：

- `_dispatch_main_q` 在 system Python 3.13 和 venv Python（Anaconda 3.13.12）均验证可用
- `dispatch_async_f` 可正常调用
- `py_compile` 语法检查通过

### Milestone 40 — Hermes 就绪状态细化分级

**问题**：

1. 版本显示错误：`get_hermes_version()` 从 `hermes --version` 多行输出中匹配到 `3.11.12`（Python 版本），而非 `v0.9.0`（Hermes 版本）
2. 就绪状态二元：`is_hermes_ready()` 只有 True/False，无法区分"基础可用"与"完整就绪"
3. `hermes doctor` 的工具受限信息未被 UI 消费

**解决方案**：

新增独立 `HermesReadinessLevel` 枚举（与 `HermesInstallStatus` 正交，仅在 READY 时有意义）：

| 值 | 含义 |
|----|------|
| `unknown` | 未检测或检测失败 |
| `basic_ready` | 至少一个 auth 可用，部分工具受限 |
| `full_ready` | 无遗留 issue |

**修复：版本解析**

- 旧：遍历全部 split token，命中 `3.11.12`（Python 版本，在后续行）
- 新：只解析第一行，正则匹配 `v(\d+\.\d+(?:\.\d+)?)` → `0.9.0`

**新函数：`check_hermes_doctor_readiness()`**

- 运行 `hermes doctor`（30s 超时），失败静默返回 `UNKNOWN`
- 解析 `◆ Tool Availability` 节的 `⚠ toolname` 行，提取受限工具名
- 解析 `Found N issue(s)` 行获取 issue 数
- 返回 `(HermesReadinessLevel, limited_tools, issues_count)`

**实测结果（当前环境）**：

```
readiness_level: basic_ready
limited_tools: ['homeassistant', 'image_gen', 'moa', 'rl', 'messaging', 'vision', 'web']
doctor_issues_count: 1
```

**变更**：

- ✅ `packages/protocol/enums.py` — 新增 `HermesReadinessLevel` 枚举（3 值）
- ✅ `packages/protocol/install.py` — `HermesInstallInfo` 新增 `readiness_level`, `limited_tools`, `doctor_issues_count` 字段
- ✅ `apps/installer/hermes_check.py`
  - `get_hermes_version()` 修复：前导行正则匹配 `v\d+.\d+` + 捕获 build_date
  - 新增 `check_hermes_doctor_readiness()` 函数
  - `check_hermes_installation()` READY 分支调用 doctor 检测
- ✅ `apps/core/runtime.py` — `get_status()` 包含 `readiness_level`, `limited_tools`, `doctor_issues_count`
- ✅ `apps/shell/main_api.py` — `get_dashboard_data()` + `get_settings_data()` 传递 readiness 数据
- ✅ `apps/shell/window.py`
  - 仪表盘 Hermes 卡：新增 `hermes-limited-row`（受限工具）
  - 设置面板 Hermes 节：新增 `s-hermes-readiness`（能力就绪）+ `s-hermes-limited-row`（受限工具）
  - `refreshDashboard()` JS：按 readiness_level 显示"完整就绪 / 基础可用 · 部分工具受限"
  - `refreshSettings()` JS：按 readiness_level 分级显示，受限工具提示"运行 hermes setup 可补全"

### Milestone 41 — Hermes Setup 交互性修复

**问题**：
Hermes 官方安装脚本（`curl ... | bash`）在安装完二进制后，自动在末尾调用 `hermes setup` 作为
post-install 步骤。由于 `run_hermes_install()` 未设置 `stdin=DEVNULL`，`hermes setup` 的 TUI
菜单输出被 PIPE 到 GUI 安装日志区域，用户能看到 setup 菜单但 stdin 无 PTY，无法通过方向键/
回车进行交互。

**根因**：

- `asyncio.create_subprocess_exec()` 未指定 stdin，默认继承父进程 stdin（pywebview 进程中无真实 TTY）
- 安装脚本非零退出（因 `hermes setup` 被 EOF 中断）导致 `success=False`，但 hermes 二进制已安装

**修复**：

1. `run_hermes_install()` 加 `stdin=asyncio.subprocess.DEVNULL`：
   - 安装脚本中的 `hermes setup` 立即获得 stdin EOF 而退出（不阻塞、不显示 TUI）
   - 安装日志只包含脚本的非交互输出
2. 非零退出时回退检查：若 `hermes --version` 可用，视为"安装成功，等待 setup"并返回 `success=True`
3. `open_hermes_setup_terminal()` osascript 改用 `make new document`：
   - 强制打开新 Terminal.app 窗口（不复用已有 Tab）
   - 确保用户能清楚看到并聚焦到配置终端

**正确用户流程（修复后）**：

1. 用户点击"安装 Hermes" → 安装脚本在后台运行，GUI 显示安装日志
2. 安装脚本完成（含 setup 自动失败/退出）→ `recheck_status()` 检测到 `INSTALLED_NEEDS_SETUP`
3. App 重启 → 显示"⚙️ 配置 Hermes Agent"引导页
4. 用户点击"开始配置 Hermes" → **真实 Terminal.app 新窗口打开，运行 `hermes setup`**
5. 用户在 Terminal.app 中完成交互式配置（完整 PTY，方向键/回车均可用）
6. 回到 GUI，点击"我已完成配置，重新检测" → 进入正常模式

**变更文件**：

- ✅ `apps/installer/hermes_install.py`
  - `asyncio.create_subprocess_exec()` 新增 `stdin=asyncio.subprocess.DEVNULL`
  - 非零退出时增加 hermes 可用性回退检查（`hermes --version`）
- ✅ `apps/shell/installer_api.py`
  - `open_hermes_setup_terminal()` osascript：`do script "hermes setup"` → `do script "hermes setup" in (make new document)`

**验证**：107 tests passed

### Milestone 42 — Hermes 能力补全入口

**背景**：
主界面已能展示 `basic_ready` + 受限工具列表，但只有只读文字，用户没有操作入口。

**新增功能**：

#### 1. 仪表盘 Hermes Agent 卡

- `basic_ready` 时自动显示 **[🔧 补全 Hermes 能力]** 按钮
- 点击展开 inline 操作面板，包含：
  - **▶ hermes setup** — 在 Terminal.app 新窗口中运行（配置模型/API 密钥/工具开关）
  - **🔍 hermes doctor** — 在 Terminal.app 新窗口中运行（查看诊断详情）
  - **🔄 重新检测 Hermes 状态** — 调用后端重检，立即刷新仪表盘状态
- `full_ready` 后面板自动收起，状态行更新为"✅ 完整就绪"

#### 2. 设置页 Hermes Agent 节

- `basic_ready` 时自动显示同款操作区（`s-hermes-enhance-section`）
- 三个操作按钮与仪表盘面板共用同一套逻辑

#### 3. 新增 main_api.py 方法

- `open_terminal_command(cmd)` — 通用终端启动方法，macOS 用 osascript `make new document`，Linux 尝试 gnome-terminal 等
- `recheck_hermes()` — 触发 `check_hermes_installation()` 重检，返回最新 `get_dashboard_data()`

**文案设计**（面向产品）：
> 当前处于**基础可用**状态，部分高级工具（如消息平台、图像生成等）尚未配置。
> 完成以下操作可解锁更多能力。

**变更文件**：

- ✅ `apps/shell/main_api.py` — 新增 `open_terminal_command()` / `recheck_hermes()`
- ✅ `apps/shell/window.py`
  - 仪表盘 Hermes 卡：`hermes-enhance-row`（按钮） + `hermes-enhance-panel`（inline 面板）
  - 设置页 Hermes 节：`s-hermes-enhance-section`（操作区）
  - JS：`toggleHermesEnhancePanel()` / `openHermesCmd(cmd)` / `recheckHermes()`
  - `refreshDashboard()` 中控制 `hermes-enhance-row` 显隐
  - `refreshSettings()` 中控制 `s-hermes-enhance-section` 显隐

**验证**：107 tests passed

### Milestone 43 — Installer 安装后 Setup 阶段内联展示修复

**背景**：
即使修复了 `stdin=DEVNULL`，`hermes setup` 在 stdin EOF 前仍会把 TUI 菜单文字（ANSI 转义码 + 菜单字符）输出到 stdout，这些文字被 `run_hermes_install()` 捕获并传给 `install-log` pre 元素，用户看到不可交互的假 setup 菜单界面。

原 `recheckAfterInstall()` 检测到 `installed_needs_setup` 时调用 `restart_app()`（1500ms），过渡不明确。

**修复内容**：

1. `apps/installer/hermes_install.py` — `_read_output()` 新增 TUI 输出过滤
   - 检测 ANSI 转义码（`\x1b[`、`\x1b(`）和 TUI 字符（`❯`、`◆`、`✔` 等）
   - 首次检测到 TUI 行时替换为单行中文通知，后续 TUI 行全部跳过
   - 使用 `_tui_flag` 列表实现可变闭包

2. `apps/shell/window.py` — 安装后配置引导内联展示
   - `recheckAfterInstall()` 中 `installed_needs_setup`/`setup_in_progress` 分支不再调用 `restart_app()`
   - 改为调用 `showPostInstallSetupUI()` 直接内联渲染配置引导区块
   - 新增 3 个 JS 函数：`showPostInstallSetupUI()`、`openPostInstallSetup()`、`recheckAfterPostInstallSetup()`

**正确用户流**：
安装完成 → `recheckAfterInstall()` → `installed_needs_setup` → `showPostInstallSetupUI()` 内联渲染
→ [▶ 开始配置 Hermes] → Terminal.app 新窗口 → hermes setup
→ [🔄 已完成配置，重新检测] → `recheck_status()` → ready → `restart_app()`

**变更文件**：

- ✅ `apps/installer/hermes_install.py`
- ✅ `apps/shell/window.py`

**验证**：68 同步测试通过

### Milestone 44 — 主窗口最小可用聊天界面

**目标**：建立统一 chat/session state，主窗口支持消息发送与接收。

**新增/修改文件**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `apps/shell/chat_api.py` | 新建 | ChatAPI 类：send_message、get_messages、clear_session |
| `apps/core/runtime.py` | 修改 | 集成 TaskRunner 启动/停止（独立线程事件循环） |
| `apps/shell/main_api.py` | 修改 | 组合 ChatAPI 方法暴露给 WebView |
| `apps/shell/window.py` | 修改 | _STATUS_HTML 新增聊天面板 |

**架构设计**：

1. **统一消息状态**：
   - `ChatSession`（`apps/core/chat_session.py`）是三种模式共享的消息状态容器
   - 消息通过 `task_id` 与任务关联
   - window/bubble/live2d 都从同一个 ChatSession 读写

2. **消息发送链路**：

   ```
   用户输入 → sendMessage() [JS]
     → ChatAPI.send_message() [Python]
       → ChatSession.add_user_message()
       → AppState.create_task()
       → ChatSession.link_message_to_task()
     → TaskRunner 轮询 PENDING 任务
     → ExecutionStrategy.run() （Simulated 或 Hermes）
     → AppState.update_task_status(COMPLETED)
     → UI 轮询 get_messages()
       → ChatAPI._sync_task_status_to_messages()
       → ChatSession.add_assistant_message()
     → 渲染 assistant 回复
   ```

3. **执行器选择**：
   - `select_executor(runtime)` 根据 Hermes 就绪状态自动选择
   - Hermes 就绪 → `HermesExecutor`（调用 `hermes run --prompt`）
   - Hermes 未就绪 → `SimulatedExecutor`（模拟响应）

4. **UI 功能**：
   - 输入框 + 发送按钮
   - 消息列表（用户消息/assistant回复/系统消息）
   - 发送中状态指示（pending/processing）
   - 错误提示（failed 状态）
   - 执行器类型显示（Hermes / 模拟）
   - 清空会话按钮

**当前执行器**：取决于 Hermes 安装状态

- `HermesExecutor`：Hermes 就绪时使用
- `SimulatedExecutor`：Hermes 未就绪时使用模拟

**验证**：imports 测试通过

### Milestone 45 — Bubble/Live2D 模式聊天入口

**目标**：在已完成的共享 chat/session state 基础上，为 bubble 和 live2d 模式添加聊天功能。

**修改文件**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `apps/shell/modes/bubble.py` | 修改 | 集成 ChatAPI，添加聊天输入框和消息预览 |
| `apps/shell/modes/live2d.py` | 修改 | 集成 ChatAPI，添加聊天界面（角色区 + 消息区） |

**架构设计**：

1. **ChatAPI 复用**：
   - BubbleWindowAPI 和 Live2DWindowAPI 都持有 `ChatAPI(runtime)` 实例
   - 委托 `send_message()`、`get_messages()`、`clear_session()` 方法
   - 通过同一个 `ChatSession` 单例共享消息状态

2. **消息共享验证**：

   ```
   window 发送消息 → ChatSession 更新
     ↓
   切换到 bubble → get_messages() → 看到相同消息
     ↓
   切换到 live2d → get_messages() → 看到相同消息
   ```

3. **UI 差异化**：
   - **window 模式**：完整仪表盘 + 聊天面板（560×620）
   - **bubble 模式**：精简聊天 + 状态栏（320×380，置顶悬浮）
   - **live2d 模式**：角色占位区 + 聊天区 + 工具栏（400×640）

4. **执行器信息**：
   - 三模式都暴露 `get_executor_info()` 方法
   - UI 显示当前使用的执行器（🚀 Hermes / 🔬 模拟）

**验证**：imports 测试通过

### Milestone 46 — HermesExecutor CLI 修复 + 聊天窗口独立化 + SQLite 持久化

**目标**：修复 `hermes run --prompt` CLI 调用错误，将聊天 UI 从主窗口拆分为独立窗口，添加 SQLite 持久化。

**修改文件**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `apps/core/executor.py` | 修改 | CLI 命令修复：`hermes run --prompt` → `hermes chat -q` + `-Q --source tool` |
| `apps/core/chat_store.py` | 新建 | SQLite 持久化层（sessions + messages 表） |
| `apps/core/chat_session.py` | 修改 | 集成 ChatStore，消息自动持久化 |
| `apps/shell/chat_window.py` | 新建 | 独立聊天窗口（pywebview），单例管理 |
| `apps/shell/main_api.py` | 修改 | 新增 `open_chat()` 方法 |
| `apps/shell/window.py` | 修改 | 嵌入式聊天 → 「打开聊天窗口」按钮 |
| `apps/shell/modes/bubble.py` | 修改 | 嵌入式聊天 → 打开独立聊天窗口 |
| `apps/shell/modes/live2d.py` | 修改 | 嵌入式聊天 → 打开独立聊天窗口 |
| `tests/test_executor.py` | 修改 | CLI 命令常量验证测试 |
| `tests/test_chat_store.py` | 新建 | ChatStore CRUD 测试（6 cases） |

**关键变更**：

1. **CLI 修复**：`_HERMES_CMD = ["hermes", "chat", "-q"]` + `_HERMES_FLAGS = ["-Q", "--source", "tool"]`
2. **SQLite 持久化**：`~/.hermes/yachiyo/chat.db`，ChatSession 自动绑定
3. **独立聊天窗口**：三模式统一通过 `open_chat_window(runtime)` 打开
4. **exit=2 友好处理**：不再暴露 argparse 原始 usage 错误

**验证**：14 测试全通过

### Milestone 47 — 运行时所有权收敛 + 聊天持久化修复

**目标**：修复 Milestone 46 后暴露的运行时和持久化边界问题。

**修改内容**：

| 文件 | 说明 |
|------|------|
| `apps/bridge/server.py` | 移除 Bridge lifespan 内的第二个 TaskRunner，Bridge 只做 HTTP 转发 |
| `apps/core/runtime.py` | 新增 `refresh_hermes_installation()`，统一刷新 Hermes 检测缓存 |
| `apps/shell/main_api.py` | `recheck_hermes()` 改为调用 Runtime 刷新方法，修复写错 `_install_info` 字段的问题 |
| `apps/core/chat_store.py` | SQLite 连接改为 `check_same_thread=False`，并用 `RLock` 保护 CRUD |
| `apps/core/chat_session.py` | 启动时恢复最近会话；清空后创建新 session 记录；重启后孤立的 pending/processing 消息标记为 failed |
| `apps/core/state.py` | `AppState` 增加 `RLock`，保护任务 dict 的读写 |
| `tests/test_chat_session.py` | 新增会话恢复、清空后持久化、孤立处理中消息恢复测试 |
| `README*.md` | 同步 Hermes CLI 命令、Hermes 安装状态端点、测试依赖说明和测试表 |

**验证**：

- `python3 -m pytest tests/ -q` → 117 passed
- `.venv/bin/python -m compileall apps packages integrations tests` → passed
- `.venv/bin/python -m pytest tests/ -q` 当前失败原因：`.venv` 未安装 pytest；README 已补充 `pip install -e ".[dev]"`

### Milestone 48 — Copilot Review 修复闭环

**目标**：处理 PR #1 中 Copilot 两次 review 后仍成立的问题。

**处理结果**：

| Review 点 | 处理 |
|-----------|------|
| 主窗口 / bubble / live2d HTML 中未渲染的 `{{` / `}}` | 正常模式、bubble、live2d 中不经过模板渲染的 CSS/JS 已改回单花括号；保留 `{{HOST}}` / `{{PORT}}` 占位 |
| bubble/live2d 打开主窗口未传 `js_api` | `open_main_window()` 改为挂载 `MainWindowAPI(runtime, config)` |
| ChatSession 多窗口并发读写 | `ChatSession` 增加内部 `RLock`，公开读写方法加锁，ChatAPI 不再直接遍历裸 `messages` |
| `_pending_message_id` 过早清空 | `is_processing()` 改为根据仍处于 pending/processing 的 user 消息计算；assistant 回复完成单个任务后不会影响其他待处理消息 |
| `link_message_to_task()` 过早切换 PROCESSING | link 阶段仅建立 task_id 关联，保持 PENDING；任务 RUNNING 后再切 PROCESSING |
| TaskRunner 跨线程停止方式脆弱 | 改用 `asyncio.run_coroutine_threadsafe()` 等待 stop 结果，再停止 loop 并检查线程是否退出 |
| ChatAPI 缺少单测 | 新增 `tests/test_chat_api.py`，覆盖 send、RUNNING、COMPLETED 去重、FAILED、多个 pending |
| 未使用导入 | 清理 `chat_api.py` 和 `test_chat_store.py` 中未使用的导入 |

**验证**：

- `python3 -m pytest tests/ -q` → 122 passed
- `.venv/bin/python -m compileall apps packages integrations tests` → passed
- `git diff --check` → passed

### Milestone 49 — 最新 Copilot Review 修复闭环

**目标**：处理 PR #1 中 Copilot 对 `6481e1f` 新增的 review 记录。

**处理结果**：

| Review 点 | 处理 |
|-----------|------|
| 主窗口 JS 仍调用未定义的 `refreshMessages()` | 移除主窗口 `DOMContentLoaded` / `pywebviewready` 中的无效调用 |
| TaskRunner loop 在线程内初始化，停止时可能尚未 ready | 增加 `_task_runner_loop_ready` 事件，并在事件循环进入 `run_forever()` 后才标记可停止 |
| `TaskStatus.CANCELLED` 未同步到聊天消息 | 取消任务会把 user 消息标记为 failed，并补一条 assistant 取消提示 |
| HermesExecutor 超时注释仍写 `hermes run` | 更新为当前实际命令 `hermes chat -q` |
| Live2D API docstring 仍描述旧的内嵌聊天接口 | 改为说明 Live2D 只负责打开独立聊天窗口，不直接提供聊天读写 API |

**验证**：

- `python3 -m pytest tests/ -q` → 123 passed
- `python3 -m compileall apps packages integrations tests` → passed
- `git diff --check` → passed

### Milestone 50 — 最新 Copilot Review 第二轮修复

**目标**：处理 PR #1 中 Copilot 对 `2ecdc69` 新增的 5 条 review 记录。

**处理结果**：

| Review 点 | 处理 |
|-----------|------|
| `recheck_hermes()` 重检后 TaskRunner 仍使用旧 executor | 新增 TaskRunner executor 热切换；重检 Hermes 后替换后续任务使用的执行器，不重启、不打断已有任务 |
| `clear_session()` 清空旧会话但不取消 pending/running 任务 | 清空前同步任务状态，取消旧会话活动任务，取消 TaskRunner in-flight 协程，并持久化取消提示 |
| `get_chat_store()` 全局单例初始化无锁 | 增加模块级 `RLock` 和 double-checked locking |
| `open_chat_window()` 窗口单例无锁 | 增加模块级 `RLock`，将检查、复用、创建、关闭回调状态更新放入同一临界区 |
| `add_assistant_message(error=...)` 不同步 user error | 关联 user 消息在失败时同步写入 `error` 并持久化 |

**验证**：

- `python3 -m pytest tests/test_chat_api.py tests/test_chat_session.py tests/test_chat_store.py tests/test_runtime.py -q` → 26 passed
- `python3 -m pytest tests/ -q` → 134 passed
- `python3 -m compileall apps packages integrations tests` → passed
- `git diff --check` → passed

### Milestone 53 — _init_agent() 参数兼容性修复

**根因**：Milestone 52 将 `route["label"]` 改为 `route.get("label")` 后，`route_label=None` 仍然被传给 `cli._init_agent()`。当前安装的 Hermes 版本（Nous Portal 路径）`_init_agent()` 不接受 `route_label` 参数，引发 `TypeError: got an unexpected keyword argument 'route_label'`。

上轮的 `except TypeError` 块捕获了异常但直接 emit error 并 return 1，任务仍失败。

**修复**：

| 变更 | 处理 |
|------|------|
| `hermes_stream_bridge.py` | 新增 `_build_init_agent_kwargs(init_agent_fn, ...)` — 用 `inspect.signature()` 检查 `_init_agent` 实际接受的参数，只传支持的 kwargs |
| `hermes_stream_bridge.py` | 支持三种情况：① 签名含 `route_label` → 传；② 签名不含 → 不传；③ 函数接受 `**kwargs` → 传所有非 None 值；④ `inspect.signature` 失败 → 只传 `model_override` / `runtime_override` |
| `hermes_stream_bridge.py` | `_run()` 改用 `_build_init_agent_kwargs()` 构建 `init_kwargs`，再用 `cli._init_agent(**init_kwargs)` 调用 |
| `hermes_stream_bridge.py` | 保留 `TypeError` 兜底路径：若 `_build_init_agent_kwargs` 结果仍引发 TypeError，自动去掉 `route_label` 后再试一次 |
| `tests/test_executor.py` | 新增 `TestBuildInitAgentKwargs`（7 用例）：签名无 route_label → 排除、签名有 → 包含、**kwargs → 全传非 None、inspect 失败 → 保守降级、None 值不传 |

**测试结果**：200 passed（+7 新增，0 失败）

**三种路径的实际行为**：

| provider 路径 | route keys | _init_agent 签名 | 实际传入 kwargs |
|---|---|---|---|
| DeepSeek/OpenAI | 含 label | 含 route_label | model, runtime, route_label, request_overrides |
| Nous Portal/MiMo | 无 label | 不含 route_label | model, runtime（route_label 被过滤） |
| 未来新版 | 不确定 | **kwargs | 所有非 None 值 |

**根因**：`apps/core/hermes_stream_bridge.py` 中 `_run()` 对 `_resolve_turn_agent_config()` 返回值使用硬字典访问（`route["label"]`、`route["model"]`、`route["runtime"]`、`route["signature"]`）。Nous Portal / MiMo / 其他非 OpenAI-compatible provider 路径下，Hermes 返回的 route dict 可能不包含 `"label"` 键，导致 `KeyError: 'label'`，整个任务失败。

**修复**：

| 变更 | 处理 |
|------|------|
| `hermes_stream_bridge.py` | 新增 `_debug_route()` 打印 route 结构到 stderr（供诊断不同 provider 路径差异） |
| `hermes_stream_bridge.py` | `route["signature"]` / `route["model"]` / `route["runtime"]` / `route["label"]` 全部改为 `route.get("key")` 防御式访问 |
| `hermes_stream_bridge.py` | 对 `_init_agent()` 包裹 try/except `TypeError` / `Exception`，捕获 Hermes 版本不兼容的参数异常 |
| `hermes_stream_bridge.py` | 若 route 不是 dict，emit 结构化 error 而非引发 KeyError |
| `executor.py` | 新增 `_BRIDGE_RAW_EXCEPTION_TO_FRIENDLY` 映射表：`KeyError:`/`AttributeError:`/`TypeError:` 等 → 用户可读描述 |
| `executor.py` | 新增 `_humanize_bridge_error(message)` 函数：检测原始异常前缀，转换为可读提示 |
| `executor.py` | `_consume_stream_bridge` 中 error 事件调用 `_humanize_bridge_error()`，`boundary` 事件静默忽略，未知事件类型 debug log 跳过 |
| `tests/test_executor.py` | 新增 `TestHumanizeBridgeError`（6 个用例）：KeyError/AttributeError/TypeError/普通消息/空串 |
| `tests/test_executor.py` | 新增 `TestConsumeStreamBridgeRobustness`（5 个用例）：KeyError label 被人性化、未知事件不崩溃、boundary 不影响结果、仅 done 无 delta 降级为完整回复、done failed=True |

**测试结果**：193 passed（+11 新增，0 失败）

**诊断方式（不同 provider 路径对比）**：

启动后聊天，`stderr` 中 `[yachiyo-debug] route keys=...` 行会记录 Hermes 的 route dict 结构。

- DeepSeek/OpenAI-compatible 路径会包含 `label`、`model`、`runtime`、`signature`
- Nous Portal / MiMo 路径可能缺少 `label`，需对比 keys 列表

**后续增强项**：

- 若 `route_label=None` 导致 Hermes 某些功能降级，可在 bridge 中用 `route.get("model", "")` 派生 label 兜底
- `_debug_route()` 为临时诊断日志，问题稳定后可按 provider 路径整理文档后移除

### Milestone 54 — Bubble + Live2D 接入统一聊天入口

- ✅ apps/shell/chat_bridge.py（新建）— 统一聊天摘要桥接层
  - `ChatBridge(runtime)` 内部持有 `ChatAPI`，供 bubble/live2d 使用
  - `send_quick_message(text)` — 委托 ChatAPI.send_message()
  - `get_recent_summary(count=3)` — 获取最近 N 条消息摘要，内容截断至 80 字符
  - `_normalize_count(count)` — 规整外部传入的摘要条数，避免 `count=0` 因 `-0` 语义返回全部消息
  - `get_session_status()` — 会话状态（无消息/处理中/就绪），错误时也返回 `{ok: false, error: ...}`
  - `_truncate(text, max_len)` — 通用截断函数
- ✅ apps/shell/modes/bubble.py — 从状态面板改造为轻量聊天入口
  - 移除旧 `get_bubble_data()` / `get_executor_info()` / `_bridge_status()` 等方法
  - 新增 `ChatBridge` 集成，API 暴露 `send_quick_message` / `get_recent_summary` / `get_session_status`
  - HTML 改为：状态标签 + 最近 3 条消息摘要 + 输入行 + "完整对话"/"主窗口"/"关闭" 操作栏
  - JS 活跃轮询 1200ms / 空闲轮询 5000ms，避免跨模式消息在空闲时不可见
  - `pywebviewready` 触发即时刷新；思考态使用真实 span 点动画，不再依赖 CSS content 动画
  - 窗口 320×380，on_top=True
- ✅ apps/shell/modes/live2d.py — 角色舞台增加聊天能力
  - 新增 `ChatBridge` 实例及 `send_quick_message` / `get_recent_summary` 方法
  - HTML chat-area 从单按钮改为消息列表 + 输入行
  - JS 增加 `sendMsg()` / `refreshMessages()` / 活跃-空闲轮询
  - `pywebviewready` 触发即时刷新；思考态使用真实 span 点动画
  - 角色图标交互：处理中 ⚡ / 空闲 🎤
  - 保留全部原有非聊天方法
- ✅ tests/test_chat_bridge.py（新建）— 19 个测试用例
  - 截断函数、空会话、快捷发送、摘要内容、处理中/就绪状态标签
  - 摘要条数边界：`count=0` / 非法 count 稳定返回空摘要
  - 三模式共享状态验证：bubble 发送 → live2d 可见，反之亦然
  - 失败任务在摘要中正确显示
  - 错误状态 API 契约、空闲轮询、WebView ready 启动和真实点动画

### 三模式聊天角色定义

| 模式 | 角色 | 聊天能力 | 轮询间隔 |
|------|------|----------|----------|
| Window | 完整聊天窗口 | 全功能（ChatAPI 直接） | 800ms |
| Bubble | 轻量浮窗入口 | 摘要 + 快捷发送（ChatBridge） | 活跃 1200ms / 空闲 5000ms |
| Live2D | 角色舞台入口 | 摘要 + 快捷发送（ChatBridge） | 活跃 1200ms / 空闲 5000ms |

### 消息共享链路

```
Bubble / Live2D → ChatBridge → ChatAPI → ChatSession → ChatStore (SQLite)
Window          → ChatAPI    → ChatSession → ChatStore (SQLite)
```

所有模式共享同一个 `runtime.chat_session` 单例，任一入口发送的消息对其他入口即时可见。

**测试结果**：222 passed（+19 新增，0 回归）

### Milestone 59 — Live2D 资源包解耦（Release 下载 + 本地导入路径 + UI 提示）

- ✅ apps/shell/assets.py
  - 区分程序内轻量资源与用户本地 Live2D 资源目录
  - 新增 `get_hermes_home_dir()` / `get_yachiyo_workspace_dir()` / `get_user_live2d_assets_dir()`
  - 默认 Live2D 自动发现目录改为 `~/.hermes/yachiyo/assets/live2d/`
  - 新增 `LIVE2D_RELEASES_URL`
  - 预览兜底改为 bubble 头像，不再依赖仓库内的大型 Live2D 贴图
- ✅ apps/shell/config.py
  - 新增 `Live2DResourceInfo`
  - `Live2DModeConfig` 支持“显式路径优先 + 用户目录自动发现”
  - 空 `model_path` 不再表示错误，而是表示走默认自动发现逻辑
  - 兼容清理旧的仓库内默认 Live2D 路径配置
- ✅ apps/shell/mode_settings.py
  - Live2D 模式摘要改为产品化资源状态文案
  - 暴露 `resource.source` / `status_label` / `help_text` / `effective_model_path` / `releases_url`
- ✅ apps/shell/settings.py
  - Live2D 设置页新增：资源来源、当前生效路径、默认导入目录、Releases 地址、状态提示
  - 区分“当前配置路径”与“当前生效路径”
- ✅ apps/shell/modes/live2d.py
  - Live2D 模式根据 `resource_info()` 展示资源提示
  - 缺少资源时明确提示去 Releases 下载，但模式本身不崩溃
  - 资源路径解析统一走“生效路径”而不是原始配置字符串
- ✅ apps/bridge/routes/live2d.py
  - bridge 读取 Live2D 模型资源时统一走 resolved path
- ✅ 文档同步
  - README 增补 Releases 下载、默认导入目录、未导入资源时的行为
  - 新增 `docs/live2d-assets.md`
  - `docs/knowledge-base.md` / `docs/implementation-plan.md` 增补资源包解耦约束
  - `apps/shell/assets/live2d/README.md` 改为占位说明
  - `.gitignore` 增补 Live2D 大型资源忽略规则

### 当前读取规则

1. 若 `live2d_mode.model_path` 有值，优先使用用户手动填写路径。
2. 若 `live2d_mode.model_path` 为空，自动扫描 `~/.hermes/yachiyo/assets/live2d/`。
3. 只有检测到 `.moc3` 或 `.model3.json` 的目录才视为有效模型目录。
4. 资源缺失或路径无效时，设置页和 Live2D 模式给出明确提示，但应用与模式都继续可用。

### 手工测试基线

- 未导入资源：设置页与 Live2D 模式都应提示去 Releases 下载资源，应用不崩溃。
- 导入到默认目录：不填写模型路径时，设置页应显示已自动检测到模型资源。
- 填写自定义路径：应优先使用用户配置路径，错误路径要给出明确错误提示。

**测试结果**：

- `tests/test_mode_settings.py`
- `tests/test_main_api_modes.py`
- `tests/test_chat_bridge.py`
- 合计：44 passed

### Milestone 60 — Live2D assistant settings / Bubble 设置闭环 / AstrBot intent bridge

- ✅ 设置生效闭环
  - Bubble 运行视图实际消费 `show_unread_dot` / `opacity` / `default_display` / `auto_hide`，`expand_trigger` 保留为兼容字段
  - Bubble 聊天窗口最终策略已在 Milestone 61 收敛为 click-only；旧 `hover` 配置会被规整为 `click`
  - Bubble `edge_snap` 尚未真实吸边，设置页已标记为待实现/禁用，避免误导用户
  - Live2D `click_action` 不再硬编码为 `open_chat`，视图返回并执行配置值
  - Live2D 支持 `open_chat` / `toggle_reply` / `focus_stage`
  - Live2D `show_reply_bubble`、`enable_quick_input`、`default_open_behavior` 已被运行视图消费
  - `window_on_top` / `show_on_all_spaces` 设置页明确提示需重启当前模式生效
- ✅ 共享助手与 TTS 配置
  - 新增共享 `assistant.persona_prompt`，不绑定到 Live2D 私有配置
  - 新增 `tts.enabled` / `provider` / `endpoint` / `command` / `voice` / `timeout_seconds`
  - 设置加载、保存、序列化、校验、设置页表单、effect policy 已同步
  - Hermes 调用前按 `[人设设定] ... [用户请求] ...` 包装任务描述；空 prompt 保持原行为
  - 新增 `apps/shell/tts.py`，默认关闭；支持 `none` / `http` / `command`，失败不阻塞聊天
- ✅ Bubble + Live2D 主动桌面观察
  - 新增 `apps/shell/proactive.py` 的 `ProactiveDesktopService`
  - Bubble / Live2D 共享主动观察状态机与 blocker 检查
  - 检查 Hermes ready、TaskRunner、`HermesExecutor`、vision 限制
  - 满足条件时创建 `TaskType.SCREENSHOT` / `RiskLevel.LOW` 任务
  - 维护 last task、ack、attention 状态；Live2D 视图返回 proactive 状态并触发视觉提示
- ✅ Bridge / AstrBot 低风险自然语言入口
  - 新增 `POST /assistant/intent`
  - 响应状态、截图、活动窗口摘要；其他自然语言请求只创建低风险 Hermes 任务
  - AstrBot 新增 `/y ask <内容>` 与 `/y chat <内容>`，调用 Bridge intent 端点
  - 保留 `/y status/tasks/screen/window/do/check/cancel/codex` 命令族兼容
  - AstrBot 仍只做 QQ bridge，不直接执行本机控制，不成为第二 runtime
- ✅ 测试覆盖
  - 更新 `tests/test_mode_settings.py`：新增字段默认值、序列化、保存和非法值拒绝
  - 更新 `tests/test_chat_bridge.py`：Bubble / Live2D 运行视图消费配置
  - 新增 `tests/test_proactive.py`：disabled、Hermes 未就绪、vision 受限、成功创建低风险截图任务
  - 新增 `tests/test_tts.py`：disabled、missing config、command/http validation
  - 新增 `tests/test_assistant_intent_route.py`：Bridge assistant intent 路由
  - 更新 `tests/test_astrbot_handlers.py`：`/y ask` / `/y chat` 与权限校验

**测试结果**：

- 验收集：`tests/test_mode_settings.py tests/test_chat_bridge.py tests/test_native_window.py tests/test_astrbot_handlers.py tests/test_proactive.py tests/test_assistant_intent_route.py` → 106 passed
- 完整套件：`python -m pytest` → 304 passed

### Milestone 61 — Chat auto-open 修复 / Bubble 设置认知澄清 / Assistant profile 基础

- ✅ Bubble / Live2D 聊天窗口打开策略收敛
  - Bubble 移除 `pointerenter` / hover 打开 Chat Window 逻辑，运行视图固定返回 `expand_trigger=click`
  - 旧配置中的 `bubble_mode.expand_trigger=hover` 在加载时统一规整为 `click`
  - Bubble / Live2D 均不再通过 hover 或 pointerenter 聚焦入口打开/切换 Chat Window；聊天窗口只允许点击触发
  - Live2D `default_open_behavior` 只控制回复泡泡/快捷输入初始表现，不打开 Chat Window
  - `live2d_mode.auto_open_chat_window` 保留为“启动时打开”偏好，并标记为需重启当前模式后生效
- ✅ Bubble 设置生效认知
  - Bubble 尺寸范围扩展为 `80-192`
  - launcher CSS 与 native hit-test 改为随窗口尺寸缩放，不再被固定 `108px` 视觉尺寸误导
  - 设置页移除 hover 展开选项，明确显示“点击打开聊天（固定）”
  - Bubble 尺寸、位置、置顶、头像字段明确标注“需重启当前模式”
  - 设置页新增“应用并重启应用 / 重启应用”入口，作为当前模式重启能力未拆出前的安全兜底
  - `edge_snap` 继续保持禁用/待实现，不伪装为已生效功能
- ✅ Chat Window 单例一致性
  - `open_chat_window()` / `is_chat_window_open()` / `close_chat_window()` 增加 closed/destroyed/event 状态清理
  - stale singleton 不再导致关闭后状态误判；关闭事件会清理 `_chat_window`
- ✅ AstrBot 记忆/人设共享基础
  - canonical 人设仍是桌面端 `assistant.persona_prompt`
  - 新增 Bridge `GET /assistant/profile` 与 `PATCH /assistant/profile`，用于读取/更新共享人设
  - profile 响应声明 prompt 注入顺序：`persona` → `relevant_memory` → `current_session` → `request`
  - 记忆同步保持本地端设计占位：不默认同步 QQ 原始聊天文本，后续只接收显式摘要/事实并由 Hermes-Yachiyo 管理注入

**测试结果**：

- 验收集：`tests/test_mode_settings.py tests/test_chat_bridge.py tests/test_native_window.py tests/test_astrbot_handlers.py tests/test_executor.py tests/test_proactive.py tests/test_assistant_intent_route.py tests/test_assistant_profile_route.py tests/test_chat_window_singleton.py` → 161 passed
- 完整套件：`python -m pytest` → 320 passed

### Milestone 62 — PR #4 review 修复：主动观察重试 / Live2D TTS 全量回复 / Bubble 状态点

- ✅ 主动桌面观察失败态重试
  - `ProactiveDesktopService.get_state()` 在 failed 后会先暴露错误状态
  - 到达 `proactive_interval_seconds` 后自动重新安排低风险 `TaskType.SCREENSHOT` 任务
  - 未到间隔时不会重复创建任务，避免错误态刷屏
- ✅ Live2D TTS 使用完整回复
  - `ChatBridge.get_recent_summary()` / `get_conversation_overview()` 新增 `latest_reply_full`
  - UI 继续使用截断后的 `latest_reply`，TTS 优先朗读 `latest_reply_full`
  - `_maybe_trigger_tts()` 的去重基于完整文本，避免长回复只播摘要
- ✅ Bubble 状态点可见性恢复
  - `renderBubble()` 明确输出 `visible attention` / `visible processing` / `visible failed`
  - idle / empty / ready 且无未读时继续隐藏状态点
  - `show_unread_dot=false` 会抑制可见状态点
- ✅ 测试覆盖
  - `tests/test_proactive.py`：failed 间隔前暴露错误、间隔后重试
  - `tests/test_chat_bridge.py`：`latest_reply_full` 保留完整内容、Bubble dot class 逻辑
  - `tests/test_tts.py`：Live2D TTS 朗读完整长回复

**测试结果**：

- PR review 验收集：`python -m pytest tests/test_proactive.py tests/test_chat_bridge.py tests/test_tts.py tests/test_mode_settings.py tests/test_native_window.py` → 87 passed
