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
- ✅ integrations/astrbot-plugin/handlers/__init__.py — 注册 check + cancel handler
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
| `run_installer_mode(config, install_info)` | 合并原来的 _start_setup_mode + _start_installer_mode |
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
  - 根目录优先扫描 *.moc3 / *.model3.json
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
