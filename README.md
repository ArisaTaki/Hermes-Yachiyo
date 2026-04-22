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
- 🔄 **三种显示模式** — 窗口模式 / 气泡悬浮模式 / Live2D 角色模式
- 🤖 **智能任务系统** — 可插拔执行策略，支持模拟执行与 Hermes CLI 真实执行
- 🎨 **Live2D 资源包解耦** — 模型资源包通过 GitHub Releases 下载，导入本地用户目录后自动检测
- ⚙️ **完整设置系统** — 即时生效 / 需重启分级提示，保存即反馈
- 🔌 **QQ 桥接** — 通过 AstrBot 插件远程控制（`/y` 命令族）
- 🏗️ **严格分层** — Shell / Core / Bridge / Locald / Protocol 职责清晰

## 📸 显示模式

| 窗口模式 | 气泡模式 | Live2D 模式 |
|:---:|:---:|:---:|
| 560×520 完整仪表盘 | 320×280 悬浮状态 | 380×560 角色骨架 |
| 任务统计 · 设置面板 | 自动刷新 · 一键展开 | 动作占位 · 配置入口 |

## 🏛️ 架构

```
┌────────────────────────────────────────────────┐
│             Hermes-Yachiyo 桌面应用              │
│                                                │
│  ┌── App Shell (apps/shell) ────────────────┐  │
│  │  启动入口 · 系统托盘 · 窗口管理            │  │
│  │  显示模式: window / bubble / live2d       │  │
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

# 启动桌面应用
hermes-yachiyo
# 或
python -m apps.shell.app
```

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

| 配置项 | 默认值 | 生效策略 |
|--------|--------|---------|
| `display_mode` | `bubble` | 需重启模式 |
| `bridge_enabled` | `true` | 需重启 Bridge |
| `bridge_host` | `127.0.0.1` | 需重启 Bridge |
| `bridge_port` | `8420` | 需重启 Bridge |
| `tray_enabled` | `true` | 需重启应用 |
| `live2d_mode.model_name` | 自动检测 | 即时生效 |
| `live2d_mode.model_path` | 空（自动在用户目录查找） | 即时生效 |
| `live2d_mode.enable_expressions` | `false` | 即时生效 |
| `live2d_mode.enable_physics` | `false` | 即时生效 |
| `live2d_mode.window_on_top` | `true` | 需重启模式 |

保存设置后，界面会即时显示每项配置的生效状态提示。

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

## 🎨 Live2D 资源包

Hermes-Yachiyo 不再把大型 Live2D 二进制资源作为主仓库默认依赖。

### 下载位置

Live2D 资源包请从 GitHub Releases 下载：

- 发布页：<https://github.com/ArisaTaki/Hermes-Yachiyo/releases>

### 默认导入目录

将资源包解压到本机用户目录：

```text
~/.hermes/yachiyo/assets/live2d/
```

如果你在设置页里手动填写了模型路径，程序会优先使用手动路径；如果没有填写，程序会默认在上面的用户目录中自动查找可用模型。设置页也支持直接“选择模型目录”或“导入资源包 ZIP”，不需要手动去拼完整路径。

### 推荐目录结构

```text
~/.hermes/yachiyo/assets/live2d/
└── yachiyo/
  ├── yachiyo.model3.json
  ├── yachiyo.moc3
  ├── yachiyo.physics3.json
  └── textures/
    ├── texture_00.png
    └── texture_01.png
```

只要目录中能检测到 `.moc3` 或 `.model3.json`，Hermes-Yachiyo 就会把它识别为有效的 Live2D 模型目录。

### 在设置里启用

1. 打开 Control Center。
2. 打开 “Live2D 设置”。
3. 如果你已经下载了 Releases 资源包，可以直接点击“导入资源包 ZIP”。
4. 如果模型已经在本地某个目录里，可以点击“选择模型目录”。
5. 如果你已经把资源包解压到默认目录，也可以保持“模型路径”为空，让程序自动检测。

### 未导入资源时会发生什么

- 应用仍然可以正常启动。
- Live2D 模式仍然可以作为角色聊天壳 / 桌面入口存在。
- 设置页会提示你去 Releases 下载资源包，并显示默认导入目录。
- Live2D 模式会明确提示“未检测到有效 Live2D 模型资源”，但不会导致整个模式崩溃。

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
  shell/              # 桌面应用壳
    app.py              # 主入口
    startup.py          # 启动决策
    window.py           # 主窗口 (pywebview)
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
tests/                # 测试套件（105 tests）
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
3. **新显示模式** → `apps/shell/modes/` 实现 → `startup.py` 集成

## 📋 后续规划

- [ ] Live2D Cubism SDK 渲染器接入
- [ ] HermesExecutor 真机 CLI 联调
- [ ] Hapi Codex 后端对接
- [ ] 任务持久化（当前为内存存储）
- [ ] 跨平台适配（Windows / Linux）
- [ ] AstrBot 真实 QQ 环境联调
- [ ] Bridge HTTPS + 认证
- [ ] 桌面壳技术升级（替换 pywebview）

## 📄 许可证

MIT
