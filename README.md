<div align="center">

# 🌸 Hermes-Yachiyo

**桌面优先的本地个人 Agent 应用**

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 构建的智能桌面助手

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest%20suite-brightgreen.svg)](#测试)

**[English](README.en.md)** | **中文** | **[日本語](README.ja.md)**

</div>

---

## ✨ 特性

- 🖥️ **桌面优先** — 本地运行的桌面应用，系统托盘常驻，无需部署服务器
- 🔄 **两种桌面显示模式** — Bubble 气泡悬浮模式 / Live2D 角色模式，主控台负责状态与全局设置
- 🤖 **智能任务系统** — 可插拔执行策略，支持模拟执行与 Hermes CLI 真实执行
- 🎨 **Live2D 资源包解耦** — 模型资源包通过 GitHub Releases 下载，导入本地用户目录后自动检测
- ⚙️ **完整设置系统** — 即时生效 / 需重启分级提示，保存即反馈
- 🔌 **QQ 桥接** — 通过 AstrBot 插件远程控制（`/y` 命令族）
- 🏗️ **严格分层** — Shell / Core / Bridge / Locald / Protocol 职责清晰

## 📸 桌面入口

| Control Center | Bubble 模式 | Live2D 模式 |
|:---:|:---:|:---:|
| 主控台 / 设置中心 | 桌面气泡 Launcher | 桌面角色 Launcher |
| Hermes 状态 · 工作区 · 集成状态 · 全局设置 | 头像悬浮 · 呼吸灯 · 点击打开 Chat Window | 模型舞台 · 回复气泡 · 快捷输入 · 动作/表情预留 |

Control Center 不是独立显示模式；它始终作为主设置与状态入口存在。真正决定桌面常驻形态的是 `display_mode`，当前支持 `bubble` 和 `live2d`。

## 🏛️ 架构

```
┌────────────────────────────────────────────────┐
│             Hermes-Yachiyo 桌面应用              │
│                                                │
│  ┌── App Shell (apps/shell) ────────────────┐  │
│  │  启动入口 · 系统托盘 · 窗口管理            │  │
│  │  显示模式: bubble / live2d                │  │
│  │  设置系统 · 生效策略 · 集成状态            │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Core Runtime (apps/core) ───────────────┐  │
│  │  Hermes Agent 封装 · 任务状态管理           │  │
│  │  TaskRunner · 执行策略 · 不暴露 HTTP       │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Local (apps/locald) ────────────────────┐  │
│  │  截图 · 活动窗口 · 本地硬件能力             │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Bridge (apps/bridge) ───────────────────┐  │
│  │  内部 FastAPI · 仅供 UI 和 AstrBot 调用    │  │
│  │  可重启 · 配置漂移检测 · 状态机            │  │
│  └───────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
           ↑ HTTP (本地，可选)
  ┌────────┴───────┐        ┌───────────┐
  │  AstrBot Plugin │  ───→  │   Hapi    │
  │  (QQ 远程桥接)   │        │  (Codex)  │
  └────────────────┘        └───────────┘
```

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js 20.19+（建议使用 nvm）
- macOS / Linux / Windows (WSL2)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)（应用内可引导安装）

### 安装与运行

```bash
# 克隆并安装
git clone <repo-url>
cd Hermes-Yachiyo
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
source ~/.nvm/nvm.sh
nvm use 20.19.0

# 启动桌面应用
hermes-yachiyo
# 仅启动 Python 后端
hermes-yachiyo-backend
```

`hermes-yachiyo` 会自动打开 Electron 桌面前端，并由 Electron 拉起 Python backend。首次运行或清理过 `apps/frontend/node_modules` 后，启动器会自动执行一次前端依赖安装；也可以提前手动运行 `npm --prefix apps/frontend install`。

如果运行 `hermes-yachiyo` 后仍出现旧的 pywebview/Python 原生窗口，说明当前 venv 里的 console script 还是旧入口；在仓库根目录重新执行 `pip install -e .` 即可刷新到 Electron 启动器。旧窗口入口只保留在 `hermes-yachiyo-legacy-pywebview`。

### 首次启动流程

应用会自动检测 Hermes Agent 状态，引导完成初始化：

```
未安装 Hermes → 安装引导界面（一键安装）
    ↓
已安装未初始化 → 工作区初始化向导
    ↓
就绪 → 进入正常模式 → 当前显示模式
```

## ⚙️ 配置系统

配置文件位于 `~/.hermes-yachiyo/config.json`，可通过设置界面可视化编辑。

设置分为主设置和模式设置。主设置负责全局行为；Bubble / Live2D 设置只负责对应桌面形态。主设置里的文本、数字和大段文本字段会先暂存，需要点击“应用共通设置修改”后保存；显示模式切换和开关类设置仍会即时保存。保存设置后，界面会即时显示每项配置的生效状态提示：即时生效、需重启当前模式、需重启 Bridge、或需重启应用。

### 主设置

| 功能 | 配置项 | 说明 | 生效策略 |
|------|--------|------|---------|
| Hermes Agent | 安装检测 / 工作区初始化 | 显示 Hermes 安装、doctor 诊断、工作区状态，并提供安装或补全能力入口。Hermes 是 Agent 本体，Yachiyo 只负责桌面壳、状态与桥接。 | 诊断即时刷新 |
| 显示模式 | `display_mode` | 选择桌面常驻形态：`bubble` 为气泡 Launcher，`live2d` 为角色 Launcher。主控台不属于显示模式。 | 需重启应用 |
| 用户称呼 | `assistant.user_address` | 配置希望助手如何称呼用户，会随人设一起注入 Hermes 调用上下文，并对 Bubble、Live2D、Chat Window 和 AstrBot 桥接请求生效。 | 点击确认后即时生效 |
| 助手人设 Prompt | `assistant.persona_prompt` | 全局人格与语气设定，会随 Bubble、Live2D、Chat Window 和 AstrBot 桥接请求一起进入 Hermes 调用上下文。该项放在主设置里，避免同一个助手在不同模式下出现多份人设配置。 | 点击确认后即时生效 |
| Bridge 开关 | `bridge_enabled` | 启用或关闭本地 FastAPI Bridge。Bridge 只供 UI 与 AstrBot 插件调用，不是产品主体。 | 需重启 Bridge |
| Bridge 地址 | `bridge_host` / `bridge_port` | 控制本地 Bridge 监听地址。默认 `127.0.0.1:8420`，不对外网开放。 | 点击确认后需重启 Bridge |
| 集成状态 | AstrBot / Hapi | 展示 QQ 桥接和 Hapi/Codex 后端的可用性。AstrBot 只做薄桥接，Hapi 仍是外部 Codex 执行后端。 | 状态即时刷新 |
| 系统托盘 | `tray_enabled` | 控制是否常驻系统托盘，便于重新打开主控台或退出应用。 | 需重启应用 |

### Bubble 模式设置

Bubble 是轻量桌面 Launcher，不承载完整聊天 UI。点击气泡会打开统一 Chat Window；聊天窗口关闭后，后台任务不会因此取消，Bubble 会继续用呼吸灯提示 Hermes 的处理状态。

| 功能 | 配置项 | 说明 | 生效策略 |
|------|--------|------|---------|
| 气泡尺寸 | `bubble_mode.width` / `bubble_mode.height` | 控制 Launcher 窗口尺寸，范围 80-192。实际气泡使用宽高中的较小值，保持圆形。 | 需重启当前模式 |
| 默认位置设置 | `bubble_mode.position_x_percent` / `bubble_mode.position_y_percent` | 使用屏幕百分比定位默认启动位置。`0%` 表示左/上边，`100%` 表示右/下边；默认 `100% / 100%`，即右下角。百分比定位可以适配不同显示器尺寸。旧的 `position_x` / `position_y` 像素字段保留用于兼容已有配置，但新设置页使用百分比。 | 需重启当前模式 |
| 窗口置顶 | `bubble_mode.always_on_top` | 让 Bubble 常驻在普通窗口之上，适合把它当作桌面入口。 | 需重启当前模式 |
| 靠边吸附 | `bubble_mode.edge_snap` | 开启后拖动 Bubble 并松开鼠标，会自动吸附到最近的屏幕边缘，并保留当前纵向或横向位置。关闭后拖动位置由窗口系统保持。 | 即时生效 |
| 头像资源 | `bubble_mode.avatar_path` | 指定气泡头像图片。为空或路径不可用时使用内置默认头像；可指向用户目录中的 Release 头像资源。 | 需重启当前模式 |
| 默认展示 | `bubble_mode.default_display` | 控制气泡标题和状态文案的默认含义：`icon` 更接近纯头像入口，`summary` 显示会话摘要语义，`recent_reply` 偏向最近回复语义。当前 Bubble 本体不展开聊天内容，完整内容仍在 Chat Window 中查看。 | 即时生效 |
| 新消息呼吸灯 | `bubble_mode.show_unread_dot` | 控制是否显示状态点。黄色表示 Hermes 正在处理；绿色表示有未读成功结果；红色表示有未读失败结果；点击打开并确认结果后，绿色或红色会消失。处理中关闭 Chat Window 时，黄色会继续保留，直到后台任务完成或失败。 | 即时生效 |
| 自动淡出 | `bubble_mode.auto_hide` | 空闲、无未读、无主动观察结果时降低气泡透明度，减少桌面干扰。 | 即时生效 |
| 透明度 | `bubble_mode.opacity` | 控制 Bubble 正常状态透明度，范围 0.2-1.0。自动淡出会在该基础上再降低。 | 即时生效 |
| 点击打开聊天 | `bubble_mode.expand_trigger` | 固定为点击打开 Chat Window。旧的 hover 触发已废弃，避免鼠标经过时误打开对话。 | 固定行为 |
| 最近会话数量 | `bubble_mode.recent_sessions_limit` | 控制 Bubble 摘要层读取多少个最近会话，用于判断当前状态和通知。 | 即时生效 |
| 最近消息数量 | `bubble_mode.recent_messages_limit` | 控制摘要层读取当前会话中多少条消息。 | 即时生效 |
| 摘要条数 | `bubble_mode.summary_count` | 控制 Bubble 获取会话摘要时最多取几条消息，范围 1-3。 | 即时生效 |
| 主动对话 | `bubble_mode.proactive_enabled` | 允许 Bubble 侧主动桌面观察服务产生提醒。默认关闭，避免未授权的后台行为。 | 即时生效 |
| 定期桌面观察 | `bubble_mode.proactive_desktop_watch_enabled` | 开启后会按间隔读取桌面上下文。该能力属于本地观察，默认关闭。 | 即时生效 |
| 观察间隔秒 | `bubble_mode.proactive_interval_seconds` | 主动桌面观察的间隔，范围 60-3600 秒。 | 即时生效 |

### Live2D 模式设置

Live2D 是角色桌面 Launcher。模型资源可为空；资源未导入时仍会显示可操作的桌面入口和设置提示，不会阻塞 Bubble、Chat Window 或 Control Center。

| 功能 | 配置项 | 说明 | 生效策略 |
|------|--------|------|---------|
| 资源操作 | 选择模型目录 / 导入资源包 ZIP / 打开导入目录 / 打开 Releases | 选择本地模型目录会校验 `.model3.json` 或 `.moc3`；导入 ZIP 会解压到用户资源目录；打开导入目录用于手动管理资源；打开 Releases 用于下载官方资源包。 | 选择或导入后需应用修改 |
| 角色缩放 | `live2d_mode.scale` | 控制角色渲染缩放，范围 0.40-2.00。用于适配不同模型尺寸和屏幕密度。 | 即时生效 |
| 模型名称 | `live2d_mode.model_name` | 给当前模型设置展示名称；为空时尝试从目录名或资源元数据推断。 | 即时生效 |
| 模型路径 | `live2d_mode.model_path` | 指向 Live2D 模型目录。为空时自动扫描 `~/.hermes/yachiyo/assets/live2d/` 及一级子目录。 | 需重启当前模式 |
| 资源状态 | 当前配置路径 / 当前生效路径 / 模型可用表情 / 模型可用动作 | 设置页会展示配置路径、实际检测到的模型路径、可用表情和动作组，帮助确认资源包是否完整。 | 信息即时刷新 |
| 窗口尺寸 | `live2d_mode.width` / `live2d_mode.height` | 控制 Live2D 舞台窗口大小。该窗口负责承载模型、回复气泡和快捷输入入口。 | 需重启当前模式 |
| 窗口位置 | `live2d_mode.position_x` / `live2d_mode.position_y` | 控制 Live2D 舞台启动位置，当前为像素坐标。 | 需重启当前模式 |
| 窗口置顶 | `live2d_mode.window_on_top` | 让角色窗口保持在普通窗口之上。 | 需重启当前模式 |
| macOS 所有桌面可见 | `live2d_mode.show_on_all_spaces` | 在 macOS 上让角色跨 Space 可见，适合长期桌面陪伴。 | 需重启当前模式 |
| 显示回复气泡 | `live2d_mode.show_reply_bubble` | 控制角色旁边是否显示最近回复气泡。关闭后可只保留角色与快捷输入。 | 即时生效 |
| 启动初始表现 | `live2d_mode.default_open_behavior` | `stage` 仅显示角色舞台；`reply_bubble` 启动时显示回复气泡；`chat_input` 启动时显示快捷输入。该设置不会自动打开 Chat Window。 | 即时生效 |
| 点击角色行为 | `live2d_mode.click_action` | `open_chat` 打开或切换 Chat Window；`toggle_reply` 切换回复气泡；`focus_stage` 仅聚焦角色窗口。 | 即时生效 |
| 显示快捷输入入口 | `live2d_mode.enable_quick_input` | 在角色窗口中显示轻量输入入口，适合快速发一句话；完整上下文仍在 Chat Window 中查看。 | 即时生效 |
| 启动时打开聊天窗口 | `live2d_mode.auto_open_chat_window` | 应用启动进入 Live2D 模式时自动打开 Chat Window。默认关闭，避免打断桌面。 | 需重启当前模式 |
| 鼠标跟随 | `live2d_mode.mouse_follow_enabled` | 启用后角色会根据全局鼠标位置更新注视方向；关闭后保持默认朝向。 | 即时生效 |
| 待机动作组 | `live2d_mode.idle_motion_group` | 指定模型中用于待机的 motion group，默认 `Idle`。模型没有对应动作时会静默跳过。 | 即时生效 |
| 表情系统 | `live2d_mode.enable_expressions` | 允许后续根据模型可用表情触发表情切换。当前作为能力开关保留。 | 即时生效 |
| 物理模拟 | `live2d_mode.enable_physics` | 启用模型物理配置，例如头发、衣物等物理效果。模型缺少物理文件时不会阻塞启动。 | 即时生效 |
| 主动对话 | `live2d_mode.proactive_enabled` | 允许 Live2D 侧主动观察服务产生提醒。默认关闭。 | 即时生效 |
| 定期桌面观察 | `live2d_mode.proactive_desktop_watch_enabled` | 开启后按间隔读取桌面上下文。该能力默认关闭。 | 即时生效 |
| 观察间隔秒 | `live2d_mode.proactive_interval_seconds` | 主动桌面观察的间隔，范围 60-3600 秒。 | 即时生效 |
| Live2D TTS | `tts.enabled` | 控制是否为 Live2D 回复播放语音。TTS 默认关闭，失败不会影响聊天。 | 即时生效 |
| TTS Provider | `tts.provider` | `none` 表示关闭；`http` 使用 HTTP POST；`command` 调用本地命令。 | 即时生效 |
| TTS HTTP Endpoint | `tts.endpoint` | 当 provider 为 `http` 时使用的接口地址。 | 即时生效 |
| TTS 本地命令 | `tts.command` | 当 provider 为 `command` 时执行的命令模板，可按实现约定传入文本。 | 即时生效 |
| TTS 音色 | `tts.voice` | 传给 TTS 后端的音色名。具体可用值取决于外部 TTS 服务或命令。 | 即时生效 |
| TTS 超时秒 | `tts.timeout_seconds` | 限制 TTS 调用等待时间，避免外部服务卡住桌面交互。 | 即时生效 |

### 记忆规划

当前对话记录通过 SQLite 保存在本地 `chat.db` 中，它是原始会话存档，不等于长期可召回记忆。长期记忆、项目/目的记忆、共享偏好和检索注入链路见 [docs/memory-architecture.md](docs/memory-architecture.md)。

## 🤖 任务系统

任务生命周期：`PENDING → RUNNING → COMPLETED / CANCELLED / FAILED`

**执行策略：**

- **SimulatedExecutor** — 模拟执行，用于 MVP 测试
- **HermesExecutor** — 真实调用 `hermes chat -q <prompt> -Q --source tool`，自动检测可用性

```bash
# 通过 Bridge API
curl http://127.0.0.1:8420/tasks -X POST \
  -H "Content-Type: application/json" \
  -d '{"description": "分析当前目录结构"}'

# 通过 QQ
/y do 分析当前目录结构
/y check abc123
/y cancel abc123
```

## 🔌 QQ 桥接（AstrBot 插件）

通过 AstrBot 插件接入 QQ，所有命令以 `/y` 开头：

| 命令 | 说明 |
|------|------|
| `/y status` | 查看系统状态 |
| `/y tasks` | 任务列表 |
| `/y do <描述>` | 创建任务 |
| `/y check <id>` | 查询任务详情 |
| `/y cancel <id>` | 取消任务 |
| `/y screen` | 截图信息 |
| `/y window` | 当前活动窗口 |
| `/y codex <描述>` | Codex 执行（Hapi，即将推出） |
| `/y help` | 命令帮助 |

插件只做路由桥接，不实现本地逻辑。错误提示已覆盖连接失败、超时、服务未就绪等场景。

## 🎨 桌面资源包（Bubble / Live2D）

Hermes-Yachiyo 将运行代码和大体积角色资源分开管理：

- **Bubble 头像资源**：体积小，可作为独立 Release 资源包下载，也保留一个默认头像随主仓库发布。
- **Live2D 模型资源**：体积较大，不直接提交到主仓库；请从单独的 L2D Release 下载后导入到用户目录。

### GitHub Releases

资源包按用途拆分为两个 Release / Tag：

| 资源类型 | Release / Tag | 用途 |
|---|---|---|
| Bubble 头像 | `bubble-assets-20260423` | 气泡模式头像、备用头像素材 |
| Live2D 模型 | `l2d-assets-20260423` / `live2d-assets-20260423` | Live2D Cubism 模型、纹理、表情、物理配置 |

发布页：<https://github.com/ArisaTaki/Hermes-Yachiyo/releases>

### 推荐用户目录结构

```text
~/.hermes/yachiyo/assets/
├── bubble/
│   └── avatars/
│       └── yachiyo-default.jpg
└── live2d/
    └── yachiyo/
        ├── 八千代辉夜姬.model3.json
        ├── 八千代辉夜姬.moc3
        ├── 八千代辉夜姬.physics3.json
        └── 八千代辉夜姬.8192/
            ├── texture_00.png
            └── texture_01.png
```

### 从 Release ZIP 导入

下载资源包后，可用下面命令导入。

#### Bubble 头像

```bash
mkdir -p ~/.hermes/yachiyo/assets/bubble
unzip hermes-yachiyo-bubble-avatar-20260423.zip -d ~/.hermes/yachiyo/assets/bubble/
```

如果你只是从本地开发仓库复制默认头像：

```bash
mkdir -p ~/.hermes/yachiyo/assets/bubble/avatars
cp apps/shell/assets/avatars/yachiyo-default.jpg \
  ~/.hermes/yachiyo/assets/bubble/avatars/yachiyo-default.jpg
```

Bubble 模式默认会使用主仓库内置头像；如果你希望改用用户目录头像，可在设置页把 `bubble_mode.avatar_path` 指向：

```text
~/.hermes/yachiyo/assets/bubble/avatars/yachiyo-default.jpg
```

#### Live2D 模型

```bash
mkdir -p ~/.hermes/yachiyo/assets/live2d
unzip hermes-yachiyo-live2d-yachiyo-20260423.zip -d ~/.hermes/yachiyo/assets/live2d/
```

如果你已经在本地开发仓库中有未提交的 Live2D 资源，也可以直接复制：

```bash
mkdir -p ~/.hermes/yachiyo/assets/live2d
cp -R apps/shell/assets/live2d/yachiyo \
  ~/.hermes/yachiyo/assets/live2d/
```

### Live2D 自动检测和手动路径

默认情况下，`live2d_mode.model_path` 为空，Hermes-Yachiyo 会自动扫描：

```text
~/.hermes/yachiyo/assets/live2d/
```

只要该目录或其一级子目录中存在 `.model3.json` 或 `.moc3`，就会被识别为有效 Live2D 模型。

你也可以在 Control Center → “Live2D 设置”中：

1. 点击“导入资源包 ZIP”；或
2. 点击“选择模型目录”；或
3. 手动填写 `live2d_mode.model_path`。

### 未导入资源时会发生什么

- 应用仍然可以正常启动。
- Bubble / Chat Window / Control Center 不受影响。
- Live2D 模式仍然可以作为角色聊天壳 / 桌面入口存在。
- 设置页会提示你从 Releases 下载资源包，并显示默认导入目录。
- Live2D 模式会明确提示“未检测到有效 Live2D 模型资源”，不会导致整个模式崩溃。

更多说明见 [docs/live2d-assets.md](docs/live2d-assets.md)。

## 🔗 Bridge API

内部 FastAPI 服务，供 UI 和 AstrBot 调用：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/status` | GET | 运行状态与任务统计 |
| `/tasks` | GET | 任务列表 |
| `/tasks` | POST | 创建任务 |
| `/tasks/{id}` | GET | 任务详情 |
| `/tasks/{id}/cancel` | POST | 取消任务 |
| `/screen/current` | GET | 截图（base64） |
| `/system/active-window` | GET | 活动窗口信息 |
| `/hermes/install-info` | GET | Hermes 安装状态 |

Bridge 支持运行时重启、配置漂移检测、状态机管理（disabled / enabled_not_started / running / failed）。

## 🧪 测试

```bash
# 安装测试依赖
pip install -e ".[dev]"

# 运行全部测试
.venv/bin/python -m pytest tests/ -v

# 测试数量以当前 pytest 收集结果为准
```

| 测试模块 | 覆盖范围 |
|---------|---------|
| `test_protocol` | 枚举、数据模型、请求/响应 |
| `test_state` | 任务生命周期、终态保护 |
| `test_executor` | 执行器模型、模拟执行 |
| `test_chat_store` | SQLite 会话/消息 CRUD |
| `test_chat_session` | 会话恢复、清空后持久化、孤立任务消息恢复、assistant 幂等更新 |
| `test_chat_api` | 消息发送、任务状态同步、取消/失败闭环、清空会话取消旧任务 |
| `test_runtime` | TaskRunner 执行器热切换 |
| `test_effect_policy` | 设置生效策略 |
| `test_integration_status` | Bridge/AstrBot/Hapi 状态 |
| `test_astrbot_handlers` | 全 handler 输出与错误格式 |
| `test_startup` | 启动决策树 |

## 📁 目录结构

```
apps/
  frontend/           # Electron + React/Vite/TypeScript 前端
    electron/           # Electron main/preload
    src/                # React renderer
  desktop_backend/    # 无窗口 Python runtime + Bridge 后端入口
  desktop_launcher.py # 桌面开发启动器
  shell/              # 桌面应用壳
    app.py              # legacy pywebview 入口
    startup.py          # 启动决策
    window.py           # legacy 主窗口 (pywebview)
    config.py           # 配置管理 + Live2D 校验
    effect_policy.py    # 设置生效策略
    integration_status.py  # 集成状态统一来源
    main_api.py         # 窗口 API
    settings.py         # 设置页构建
    tray.py             # 系统托盘
    modes/              # 显示模式
      bubble.py           # 气泡悬浮模式
      live2d.py           # Live2D 角色模式
  core/               # 核心运行时（不暴露 HTTP）
    runtime.py          # Hermes 运行时封装
    state.py            # 任务状态管理
    executor.py         # 执行策略（模拟 / Hermes CLI）
    task_runner.py      # 任务调度轮询
  bridge/             # 内部通信桥
    server.py           # FastAPI 服务（可重启）
    deps.py             # 依赖注入
    routes/             # API 路由
  locald/             # 本地能力适配
    screenshot.py       # 截图（macOS）
    active_window.py    # 活动窗口（macOS）
  installer/          # Hermes 安装引导
    hermes_check.py     # 安装检测
    hermes_install.py   # 安装执行
    workspace_init.py   # 工作区初始化
packages/
  protocol/           # 跨层数据定义
    enums.py            # 枚举
    schemas.py          # 请求/响应模型
    install.py          # 安装模型
integrations/
  astrbot-plugin/     # QQ 桥接插件
    main.py             # 入口与 ACL
    command_router.py   # 命令路由
    api_client.py       # HTTP 客户端
    handlers/           # 各命令 handler
tests/                # 测试套件（pytest）
```

## 🔧 开发指南

### 严格边界

| 模块 | 允许 | 禁止 |
|------|------|------|
| `apps/core` | 运行时、状态、执行器 | 暴露 HTTP |
| `apps/bridge` | 内部 API、依赖注入 | 实现业务逻辑 |
| `apps/shell` | 产品入口、UI、配置 | 直接访问 Bridge 以外的状态 |
| `apps/locald` | 平台能力适配 | 处理业务逻辑 |
| `astrbot-plugin` | 命令路由、格式化 | 实现本地机器控制 |

### 添加新功能

1. **新本地能力** → `apps/locald/` 添加适配器 → `apps/bridge/routes/` 暴露端点
2. **新任务类型** → `packages/protocol/enums.py` 添加枚举 → `apps/core/state.py` 处理
3. **新显示模式** → 优先在 `apps/frontend/src/views/` 设计前端入口 → 通过 `apps/bridge/routes/` 调用 Python 能力

## 📋 后续规划

- [ ] Live2D Cubism SDK 渲染器接入
- [ ] HermesExecutor 真机 CLI 联调
- [ ] Hapi Codex 后端对接
- [ ] 任务持久化（当前为内存存储）
- [ ] 跨平台适配（Windows / Linux）
- [ ] AstrBot 真实 QQ 环境联调
- [ ] Bridge HTTPS + 认证
- [x] 桌面壳技术升级第一阶段（Electron + React 固定入口，pywebview 转 legacy）

## 📄 许可证

MIT
