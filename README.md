# Hermes-Yachiyo

Hermes-Yachiyo 是一个**桌面优先的本地个人 agent 应用**，基于 Hermes Agent 构建。

## 产品形态

- 🖥️ **桌面优先**：本地运行的桌面应用，系统托盘常驻
- 🔄 **多显示模式**：窗口模式 / 气泡模式 / Live2D 模式（预留）
- 🏠 **本地优先**：无需网络连接即可运行核心功能
- 🔌 **可选桥接**：可通过 AstrBot 插件接入 QQ

## 架构分层

```
┌─────────────────────────────────────────────┐
│          Hermes-Yachiyo 桌面应用             │
│                                             │
│  ┌─── App Shell ──────────────────────────┐ │
│  │  启动入口 → 托盘 + 窗口管理              │ │
│  │  显示模式: window / bubble / live2d    │ │
│  │  设置界面 (pywebview)                  │ │
│  └────────────────────────────────────────┘ │
│                    │                        │
│  ┌─── Core Runtime ──────────────────────┐ │
│  │  Hermes Agent 封装                     │ │
│  │  任务管理 / 状态管理                    │ │
│  │  不暴露 HTTP（纯本地运行时）            │ │
│  └────────────────────────────────────────┘ │
│                    │                        │
│  ┌─── Local Capabilities ────────────────┐ │
│  │  截图 / 活动窗口 / 本地硬件能力         │ │
│  └────────────────────────────────────────┘ │
│                    │                        │
│  ┌─── Bridge API (内部，可选) ────────────┐ │
│  │  FastAPI，仅供 UI 和 AstrBot 调用       │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
         ↑ HTTP (可选)
┌────────┴──────┐      ┌──────────┐
│ AstrBot Plugin │ ──→  │   Hapi   │
│ (QQ 桥接)      │      │ (Codex)  │
└───────────────┘      └──────────┘
```

### 模块职责

| 模块 | 路径 | 职责 | 边界 |
|------|------|------|------|
| **App Shell** | `apps/shell/` | 桌面壳入口、托盘、窗口、配置 | pywebview 只是 MVP 方案，可替换 |
| **Core Runtime** | `apps/core/` | Hermes 封装、任务/状态管理 | 不暴露 HTTP，纯本地运行时 |
| **Local Capabilities** | `apps/locald/` | 截图、活动窗口、本地硬件能力 | 平台适配层 |
| **Bridge API** | `apps/bridge/` | 内部 FastAPI | 仅作通信桥梁，非产品本体 |
| **Protocol** | `packages/protocol/` | Schema、枚举、请求/响应模型 | 跨层数据定义 |
| **AstrBot Plugin** | `integrations/astrbot-plugin/` | QQ 命令路由桥接 | 薄桥层，不实现本地逻辑 |

## 快速开始

## 环境要求

- Python 3.11+
- macOS、Linux 或 Windows (WSL2)
- **Hermes Agent**: 外部运行时依赖，需单独安装

### Hermes Agent 安装

Hermes-Yachiyo 依赖 [Hermes Agent](https://github.com/hermesagent/hermes) 作为底层运行时，需要先安装：

**macOS:**
```bash
# 使用 Homebrew (推荐)
brew install hermesagent/tap/hermes

# 或下载二进制文件
# 访问 https://github.com/hermesagent/hermes/releases
```

**Linux / WSL2:**
```bash
# 使用官方安装脚本
curl -fsSL https://get.hermesagent.io | sudo bash

# 或下载二进制文件
# 访问 https://github.com/hermesagent/hermes/releases
```

**Windows:**
```bash
# Windows 用户需要使用 WSL2
# 1. 安装 WSL2: https://docs.microsoft.com/zh-cn/windows/wsl/install
# 2. 在 WSL2 中按 Linux 步骤安装 Hermes Agent
```

安装完成后，确认 `hermes --version` 命令可正常执行。

### 安装与运行

```bash
# 1. 克隆仓库
git clone <repo-url>
cd Hermes-Yachiyo

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -e .

# 4. 启动应用
hermes-yachiyo
# 或直接运行
python -m apps.shell.app
```

### 功能验证

启动后可以：

- 在系统托盘查看状态
- 通过窗口界面查看运行信息
- 访问内部 API: <http://127.0.0.1:8420>
  - `GET /status` - 运行状态
  - `GET /tasks` - 任务列表
  - `POST /tasks` - 创建任务
  - `GET /screen/current` - 截图
  - `GET /system/active-window` - 活动窗口

## 开发

### 目录结构

```
apps/
  shell/           # 桌面应用壳
    app.py           # 主入口
    tray.py          # 系统托盘
    window.py        # pywebview 窗口
    config.py        # 用户配置
    modes/           # 显示模式
  core/            # Core Runtime
    runtime.py       # Hermes 运行时 + 安装检测集成
    state.py         # 应用状态管理
  bridge/          # 内部 API 桥梁
    deps.py          # 依赖注入
    server.py        # FastAPI 服务
    routes/          # API 路由 (+ hermes.py)
  locald/          # 本地能力适配器
    screenshot.py    # 截图（macOS）
    active_window.py # 活动窗口（macOS）
  installer/       # Hermes Agent 安装引导层
    hermes_check.py  # 安装检测
    hermes_install.py # 安装指导
    hermes_setup.py  # 环境设置
packages/
  protocol/        # Schema 定义
    enums.py         # 枚举 (+ Hermes 相关)
    schemas.py       # 请求/响应模型
    errors.py        # 错误模型
    events.py        # 审计事件
    install.py       # 安装相关模型
  tasking/         # 任务生命周期（占位）
  security/        # 安全模块（占位）
integrations/
  astrbot-plugin/  # QQ 桥接插件
    main.py          # 命令路由骨架
```

### 连通链路

1. **启动流程**: `shell/app.py` → 创建 `HermesRuntime` → Hermes 安装检测 → 注入 `bridge/deps.py` → 启动桥接 API
2. **任务流程**: Bridge 路由 → `deps.get_runtime()` → `core/state.py` → 任务操作
3. **安装流程**: `installer/hermes_check.py` → 检测 → `hermes_install.py` → 引导 → `hermes_setup.py` → 环境配置
4. **显示流程**: Shell → 托盘/窗口 → pywebview → Bridge API 状态查询

### 开发指导

#### 严格边界

- `apps/core` **不暴露** HTTP，只负责运行时与状态
- `apps/bridge` **只作** 内部通信桥梁，不是产品本体  
- `apps/shell` 是产品入口，但 pywebview 可替换为其他桌面技术
- `apps/locald` 只负责本地能力适配，不处理业务逻辑
- `integrations/astrbot-plugin` 只做 QQ 路由，不实现本地机器控制

#### 添加新功能

1. **新的本地能力**: 在 `apps/locald/` 添加适配器 → 在 `apps/bridge/routes/` 暴露 API
2. **新的任务类型**: 更新 `packages/protocol/enums.py` → 在 `apps/core/state.py` 处理逻辑
3. **新的显示模式**: 在 `apps/shell/modes/` 实现 → 在 `apps/shell/window.py` 集成

## AstrBot 集成

AstrBot 插件提供 QQ 桥接能力：

```
QQ 用户 → AstrBot → integrations/astrbot-plugin/main.py

命令路由:
- /y status /tasks /screen /window /do → Hermes-Yachiyo Bridge
- /y codex → Hapi (现有 Codex 后端)
```

插件职责严格限制为：解析命令 → 鉴权 → HTTP 调用 → 格式化响应。

## 后续规划

- [ ] 实现任务持久化（`packages/tasking`）
- [ ] 实现安全策略（`packages/security`）  
- [ ] 桌面壳迁移到更完整的方案（替换 pywebview）
- [ ] 气泡模式与 Live2D 模式实现
- [ ] 跨平台本地能力适配（Windows/Linux）
- [ ] AstrBot 插件的实际 HTTP 调用实现

## 许可证

MIT
