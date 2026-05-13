# Phase 4: Hermes 同步与全能力接入计划

## 背景

Hermes-Yachiyo 已经完成桌面 UI 重构，并跑通了桌面壳、Bridge、聊天、图片链路、工具中心、诊断、应用更新、Bubble、Live2D、主动关怀 TTS 和首用体验闭环。

下一阶段的目标不再只是补单个功能，而是把 Yachiyo 变成 Hermes 本体能力的桌面同步层：Hermes 新增命令、toolset、配置项或官方 Dashboard 能力后，Yachiyo 能发现、展示、诊断、更新、验证，并逐步做成原生桌面体验。

本次调查基于：

- 本仓库当前 `develop` 分支代码。
- 本机 Hermes Agent `v0.13.0 (2026.5.7)`。
- `hermes update --check` 返回当前 Hermes 落后 `origin/main` 约 119 commits。
- `hermes tools list` 已出现 `computer_use` toolset。
- `hermes computer-use status` 返回 `cua-driver: not installed`。
- Hermes 官方文档和 release note 中的 Computer Use、Kanban、Profiles、MCP、Cron、Curator、Dashboard、Plugins、Sessions 等能力。

## 当前差距

### 已经接入或部分接入

- Hermes 安装检测、setup 引导、工作空间初始化。
- Hermes CLI 聊天调用和 Yachiyo 流式 Bridge。
- Hermes Doctor / config check / auth list 诊断入口。
- Hermes tools list 读取、工具中心状态展示和部分工具配置。
- Hermes update 检查与更新入口。
- 图片附件链路、Yachiyo vision 预分析和图片链路测试。
- Yachiyo 桌面形态：主控台、Chat、Bubble、Live2D、主动关怀、GPT-SoVITS。
- 应用自身 macOS DMG、应用内更新、发布包首用闭环。

### 缺口

- 没有 Hermes upstream 能力差异扫描：新增命令、toolset、配置项不会自动进入产品视野。
- Hermes 更新后没有统一适配门禁：无法自动告诉用户“更新带来了什么、Yachiyo 哪些能力已适配、哪些需要验证”。
- Tool Center 仍依赖较多静态 catalog，未知 toolset 不能自动作为“新能力待适配”出现。
- Computer Use 已在 Hermes 中可用，但 Yachiyo 还没有安装、权限、状态、风险提示和可用性测试闭环。
- Kanban、Profiles、MCP、Cron、Curator、Plugins、Sessions、Logs、Insights、官方 Dashboard/TUI 等能力缺桌面入口。
- Yachiyo 聊天链路仍部分依赖 Hermes 内部 Python API，长期需要降低对内部签名变化的耦合。
- 记忆能力已有架构文档，但尚未接入 Hermes 原生 memory provider 或做 Yachiyo 控制层。

## 总体策略

采用“官方更新 + Yachiyo 适配门禁”：

1. Hermes 本体继续通过官方 `hermes update` 更新，不 vendoring、不 fork、不把 Hermes 锁死在 Yachiyo 仓库里。
2. Yachiyo 增加同步中心，负责发现 Hermes 当前版本、commit、behind count、命令面、toolset 面、Doctor 状态和新增能力。
3. Yachiyo 更新 Hermes 后自动运行 smoke gate，并生成更新差异报告。
4. 所有 Hermes 新能力至少要在桌面端可发现、可诊断、可进入官方入口。
5. 高价值能力再逐步做成 Yachiyo 原生 UI。

## Phase 4 目标

### 1. Hermes Sync Center

新增同步中枢服务 `HermesSyncService`，负责收集：

- `hermes --version`
- `hermes version`
- `hermes update --check`
- `hermes --help`
- `hermes tools list`
- `hermes doctor`
- 本地 Hermes git 状态和 `HEAD..origin/main`
- 最近一次 Yachiyo 更新前后工具差异

输出 `HermesSyncReport`，至少包含：

- 当前 Hermes version / build date / commit / project path / Python path。
- 当前本地分支与 upstream 状态。
- behind count、remote HEAD、local HEAD。
- 顶层命令列表。
- toolset 列表、启用状态、Doctor 可用/受限状态。
- 新增、移除、未知、受限的能力。
- 更新后 smoke 结果。
- Yachiyo 适配状态：`native`、`dashboard`、`diagnostic_only`、`unknown`。

### 2. 动态能力目录

引入 `HermesCapability` 模型，静态 catalog 只保存中文标题、分类、风险说明、推荐入口；真实可用性来自 Hermes 动态探测。

能力分类建议：

- Core: chat、model、auth、status、config、doctor、update、logs。
- Tools: web、browser、terminal、file、code_execution、vision、video、image_gen、tts、computer_use。
- Automation: cron、delegation、kanban、hooks、webhook。
- Memory & Context: memory、session_search、sessions、skills、curator、checkpoints。
- Integrations: gateway、mcp、plugins、profile、acp、messaging platforms。
- Desktop/Yachiyo: Bubble、Live2D、主动关怀、GPT-SoVITS、桌面截图、活动窗口。

未知 Hermes toolset 必须自动出现在工具中心，标记为“新能力待适配”，避免 Yachiyo 对 Hermes 新功能失明。

### 3. Bridge API

新增或扩展以下 API：

- `GET /ui/hermes/capabilities`
- `GET /ui/hermes/capabilities/{id}`
- `POST /ui/hermes/sync/check`
- `POST /ui/hermes/sync/update`
- `GET /ui/hermes/sync/report/latest`
- `POST /ui/hermes/actions/{action_id}`

所有 `action_id` 必须后端白名单化，不能允许前端传任意 shell 命令。

### 4. Computer Use 首批产品化

Computer Use 是 Phase 4 的第一优先级能力，但不以牺牲同步体系为代价。

首批范围：

- 工具中心新增 `computer_use` 卡片。
- 展示 Hermes toolset 状态、Doctor 状态、`cua-driver` 安装状态。
- 提供 `hermes computer-use status`。
- 提供 `hermes computer-use install` 和 `hermes computer-use install --upgrade` 的受控终端入口。
- macOS 权限引导：Accessibility、Screen Recording。
- 安装后自动刷新 Doctor、tools list 和 sync report。
- 测试模式支持 `HERMES_COMPUTER_USE_BACKEND=noop`。

首批不做：

- 不自动执行真实点击、键盘输入、拖拽等 GUI 操作。
- 不把 Computer Use 作为主动关怀的默认动作工具。
- 不允许模型绕过 Hermes 自身审批直接驱动桌面。

### 5. 官方 Dashboard 嵌入

为所有尚未原生化的 Hermes 功能提供官方兜底入口：

- Yachiyo 管理 `hermes dashboard --no-open --host 127.0.0.1 --port <free>` 生命周期。
- 在 Electron 中打开独立 Dashboard 窗口。
- 默认只绑定 localhost，不使用 `--insecure`。
- 展示 Dashboard 进程状态、端口、启动日志、停止按钮。

这样 Kanban、Profiles、MCP、Cron、Curator、Plugins、Sessions、Logs、Analytics 等能力在 Yachiyo 原生 UI 完成前也能被用户访问。

### 6. 原生入口批次

第一批：

- Sync Center
- 动态能力目录
- Computer Use
- 官方 Dashboard 嵌入

第二批：

- Kanban board 浏览、任务创建、任务详情、worker/logs 入口。
- Profiles 列表、当前 profile、profile 创建/切换、gateway 状态。
- MCP server 列表、测试、启用/禁用、OAuth login 入口。

第三批：

- Cron job 列表、创建、暂停、恢复、立即运行、删除。
- Curator 状态、dry-run、run、pin、archive/restore、rollback。
- Plugins / Skills 管理入口。
- Sessions / Logs / Insights 桌面浏览。

第四批：

- Hermes memory provider 检测。
- `HermesMemoryAdapter`。
- Yachiyo 本地记忆控制层。
- 项目/目的上下文与可视化记忆管理。

## 实施文件建议

后端：

- `apps/shell/hermes_sync.py`
- `apps/shell/hermes_capability_catalog.py`
- `apps/shell/hermes_dashboard.py`
- `apps/bridge/routes/ui.py`
- `apps/shell/main_api.py`

前端：

- `apps/frontend/src/views/HermesSyncView.tsx`
- `apps/frontend/src/views/ToolCenterView.tsx`
- `apps/frontend/src/views/DiagnosticsView.tsx`
- `apps/frontend/src/lib/bridge.ts`
- `apps/frontend/src/lib/view.ts`

测试：

- `tests/test_hermes_sync.py`
- `tests/test_hermes_capabilities.py`
- `tests/test_ui_bridge_routes.py`
- `tests/test_main_api_modes.py`
- 前端 build smoke。

## 验收标准

### 同步中心

- 能在不更新 Hermes 的情况下生成当前 `sync_report`。
- 能识别 Hermes 落后 upstream 的 commit 数。
- 能列出所有 Hermes 顶层命令。
- 能列出所有 Hermes toolsets，包含启用、禁用、Doctor 受限状态。
- 能把未知 toolset 显示为“新能力待适配”。

### 更新门禁

- 更新前保存 baseline。
- 更新后自动运行 `hermes --version`、`hermes config check`、`hermes doctor`、`hermes tools list`。
- 生成新增/移除/变化能力 diff。
- 更新失败时保留输出和恢复建议。
- 不覆盖用户本地 Hermes 配置和 Yachiyo 配置。

### Computer Use

- macOS 上能显示 `cua-driver` 未安装状态。
- 能通过受控入口启动安装。
- 安装后能刷新为可用或明确显示权限/依赖缺失。
- Doctor 中 `computer_use` 的受限原因能出现在工具中心。
- 非 macOS 平台显示不支持，不报错。

### Dashboard 嵌入

- 能启动、停止、重启 Hermes Dashboard。
- 自动选择空闲端口。
- 只绑定 `127.0.0.1`。
- Electron 能打开 Dashboard 窗口。
- Dashboard 不可用时有明确错误和日志。

## 测试计划

- 单元测试解析模拟输出：`--help`、`tools list`、`doctor`、`update --check`。
- API 测试覆盖 capabilities、sync check、latest report、computer-use status/install、dashboard lifecycle。
- 前端构建测试：`npm --prefix apps/frontend run build`。
- Python 测试：新增测试后跑相关 suite，最后跑全量 `python -m pytest`。
- macOS 手工 smoke：
  - `hermes computer-use status`
  - `hermes dashboard --no-open`
  - Yachiyo 内打开 Dashboard。
  - Tool Center 显示 `computer_use`。
  - 更新检查显示 behind count 和报告。

## 安全边界

- Yachiyo 不暴露任意命令执行入口；所有 Hermes action 后端白名单。
- Computer Use 首期只处理安装、权限、状态和可用性，不主动发起真实 GUI 操作。
- Dashboard 只允许 localhost。
- 诊断输出继续脱敏 API key、token、secret。
- 保留现有 Hapi/Codex 边界，不把 Codex 执行迁移进 Yachiyo。
- AstrBot 仍是桥接入口，不拥有 Hermes/Yachiyo 主运行时。

## 里程碑

### Milestone 80: Sync Foundation

- 新增 `HermesSyncService`。
- 新增 sync report 数据结构。
- Tool Center 改为动态能力目录。
- 新增 Sync Center 基础页面。
- 测试覆盖 CLI 输出解析。

### Milestone 81: Update Gate

- 更新前 baseline。
- 更新后 smoke。
- 工具差异报告。
- 更新失败输出保留与恢复建议。

### Milestone 82: Computer Use

- Computer Use 卡片。
- `cua-driver` status/install/upgrade。
- macOS 权限引导。
- noop 测试模式。

### Milestone 83: Dashboard Embed

- Dashboard 生命周期管理。
- Electron Dashboard 窗口。
- Dashboard 状态和日志。

### Milestone 84: Native Management Surfaces

- Kanban / Profiles / MCP 首批原生管理入口。
- 后续扩展 Cron / Curator / Plugins / Sessions / Logs / Insights。

## 默认假设

- Hermes-Yachiyo 不 fork Hermes Agent。
- Hermes 本体更新仍由 `hermes update` 负责。
- “功能同步”先定义为可发现、可诊断、可进入官方入口，再逐步原生化。
- 当前 OpenDesign / Electron 架构保持，不回退到旧 pywebview。
- Phase 4 不把 Computer Use 做成无审批自动桌面控制。
