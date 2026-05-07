<div align="center">

# Hermes-Yachiyo

桌面优先的本地个人 Agent 应用

基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 构建，让 Hermes 以桌面助手、悬浮气泡或 Live2D 角色的形式常驻在本机。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest%20suite-brightgreen.svg)](#测试)

**[English](README.en.md)** | **中文** | **[日本語](README.ja.md)**

</div>

---

## 先看这里

Hermes-Yachiyo 目前仍是源码开发形态，不是已经打包好的普通桌面安装包。

这意味着：

- `git clone` 下来运行时，需要本机安装 Python、Node.js 和 npm。
- 启动命令 `hermes-yachiyo` 会启动 Electron + React 前端，也会拉起 Python 后端。
- 前端依赖缺失时，启动器会自动安装 `apps/frontend/node_modules`，但不会自动安装 Node.js 本体。
- 未来发布 `.app`、`.exe` 或 Linux 包后，普通用户不应该再需要全局 Python/Node 环境。

如果你只是想体验桌面软件，建议等 Release 包；如果你愿意从源码运行，请按下面步骤来。

## 它能做什么

Hermes-Yachiyo 不是另一个聊天网页，而是一个本地桌面壳：

- 主控台：查看 Hermes 状态、安装引导、会话中心和设置。
- Chat Window：完整对话窗口。
- Bubble 模式：桌面悬浮气泡，点击打开对话。
- Live2D 模式：桌面角色入口，支持 Live2D 模型资源导入。
- 本地 Bridge：只监听本机，供前端和可选 AstrBot 插件调用。

Control Center 不是一种桌面形态；它是主控台。真正常驻桌面的形态目前是 `bubble` 或 `live2d`。

## 推荐环境

### macOS

当前最推荐在 macOS 上开发和测试。

需要：

- Python 3.11 或更高版本
- Node.js 20.19 或更高版本
- npm
- Git
- Xcode Command Line Tools

如果你不确定这些有没有装，可以先运行：

```bash
python3 --version
node --version
npm --version
git --version
```

### Linux

源码结构已经尽量保持跨平台，但桌面能力和安装引导主要按 macOS 优先完善。Linux 需要自行准备 Python、Node.js、npm、Git 和可用的桌面环境。

### Windows

当前建议优先使用 WSL2 做后端开发。完整 Windows 桌面包仍属于后续目标。

## macOS 从零准备

如果你已经有 Python、Node.js、npm 和 Git，可以跳过本节。

### 1. 安装 Xcode Command Line Tools

```bash
xcode-select --install
```

如果系统提示已经安装，可以继续下一步。

### 2. 安装 Homebrew

Homebrew 是 macOS 常用的命令行软件管理工具。没有安装的话，按它的官方脚本安装：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

安装完成后，按终端最后给出的提示把 Homebrew 加到 shell 环境里。Apple Silicon Mac 通常是：

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Intel Mac 通常是：

```bash
echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/usr/local/bin/brew shellenv)"
```

### 3. 安装 Git 和 nvm

```bash
brew update
brew install git nvm
```

为 nvm 创建目录并写入 shell 配置：

```bash
mkdir -p ~/.nvm
cat <<'EOF' >> ~/.zshrc
export NVM_DIR="$HOME/.nvm"
[ -s "/opt/homebrew/opt/nvm/nvm.sh" ] && \. "/opt/homebrew/opt/nvm/nvm.sh"
[ -s "/usr/local/opt/nvm/nvm.sh" ] && \. "/usr/local/opt/nvm/nvm.sh"
EOF
source ~/.zshrc
```

### 4. 安装 Node.js 20.19+

```bash
nvm install 20.19.0
nvm use 20.19.0
node --version
npm --version
```

看到 `v20.19.0` 或更高版本即可。

## 下载和启动

### 1. 克隆项目

```bash
git clone <repo-url>
cd Hermes-Yachiyo
```

如果你不是通过 Git 克隆，而是下载 ZIP，也可以解压后进入项目目录。

### 2. 创建 Python 虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 3. 安装 Hermes-Yachiyo 源码包

```bash
pip install -e .
```

如果要运行测试或参与开发，使用：

```bash
pip install -e ".[dev]"
```

### 4. 确认 Node 环境

```bash
source ~/.nvm/nvm.sh
nvm use 20.19.0
```

### 5. 启动桌面应用

```bash
hermes-yachiyo
```

第一次启动可能会自动安装前端依赖，耗时取决于网络。启动成功后你会看到 Electron 桌面窗口。

如果只想启动 Python 后端：

```bash
hermes-yachiyo-backend
```

## 第一次打开后怎么做

应用会先检测 Hermes Agent 是否可用，然后按状态引导：

```text
未安装 Hermes Agent
  -> 安装 Hermes Agent
  -> 完成 hermes setup
  -> 初始化 Yachiyo 工作空间
  -> 进入主控台
```

安装页里有内置终端。你可以直接在应用里看安装输出，也可以在需要输入时直接输入。

如果安装失败，先看终端输出。常见情况：

- GitHub 克隆中断：通常是网络或代理问题，重新安装即可。
- `hermes` 命令未找到：安装完成后可能需要打开新终端，或点击“重新检测”。
- `setup` 没完成：点击“开始配置 Hermes”，在终端里完成 Hermes 的初次配置。

## 日常使用入口

### 主控台

主控台负责状态和设置：

- Hermes Agent 是否安装
- 会话中心
- 当前显示模式
- Bubble / Live2D 设置
- AstrBot / Hapi 集成状态
- 卸载、备份和恢复入口

### Chat Window

完整对话在 Chat Window 里进行。Bubble 和 Live2D 都只是桌面入口，不会把完整对话塞进小窗口。

### Bubble 模式

Bubble 是轻量悬浮入口：

- 点击气泡打开 Chat Window。
- 呼吸灯提示处理中、新消息或失败。
- 可在设置里调整尺寸、位置、透明度、靠边吸附和头像。

### Live2D 模式

Live2D 是角色桌面入口：

- 点击角色可以打开对话或切换回复气泡，取决于设置。
- 支持鼠标跟随、回复气泡、快捷输入入口。
- 模型资源是可选的。没有模型时，应用仍然能启动并提示你导入资源。

## Live2D 和头像资源

为了避免仓库过大，Live2D 模型不直接放进主仓库。资源包从 GitHub Releases 下载：

<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases>

推荐目录：

```text
~/.hermes/yachiyo/assets/
├── bubble/
│   └── avatars/
│       └── yachiyo-default.jpg
└── live2d/
    └── yachiyo/
        ├── 八千代辉夜姬.model3.json
        ├── 八千代辉夜姬.moc3
        └── 八千代辉夜姬.8192/
            ├── texture_00.png
            └── texture_01.png
```

最简单的导入方式是在主控台打开“Live2D 设置”，然后点击：

- “导入资源包 ZIP”
- 或“选择模型目录”

也可以手动解压：

```bash
mkdir -p ~/.hermes/yachiyo/assets/live2d
unzip hermes-yachiyo-live2d-yachiyo-20260423.zip -d ~/.hermes/yachiyo/assets/live2d/
```

更多资源说明见 [docs/live2d-assets.md](docs/live2d-assets.md)。

## 八千代 GPT-SoVITS 语音资源

主动关怀 TTS 的八千代 GPT-SoVITS 语音包也是可选资源，并且和应用 DMG 分开发布。应用 release 只包含程序本体；语音包放在独立资源 release 中：

<https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/tag/tts-assets-yachiyo-gpt-sovits-v4>

下载 `Hermes-Yachiyo-yachiyo-gpt-sovits-v4.zip` 后，在主控台打开“主动关怀语音”，选择 `GPT-SoVITS 本地服务`，再点击“导入语音包 ZIP”。

语音包只包含已经调配好的音色资源，不包含 GPT-SoVITS 服务本体。本地 API 服务仍需单独启动或通过设置页配置 LaunchAgent。

更多说明见 [docs/tts-voice-assets.md](docs/tts-voice-assets.md)。

## 常见问题

### 运行后入口或界面不对

当前虚拟环境里的命令入口可能还是旧版本。回到仓库根目录重新安装：

```bash
source .venv/bin/activate
pip install -e .
```

然后重新运行：

```bash
hermes-yachiyo
```

### 提示找不到 Node.js 或 npm

源码运行需要 Node.js。先确认：

```bash
node --version
npm --version
```

如果没有，请按上面的 macOS 准备步骤安装 nvm 和 Node.js 20.19+。

### Vite 端口被占用

开发模式默认使用 `127.0.0.1:5174`。如果这个端口被其他程序占用，关闭占用程序后重新启动。

macOS 可用下面命令查看占用：

```bash
lsof -i :5174
```

### 前端依赖安装失败

可以手动安装一次：

```bash
source ~/.nvm/nvm.sh
nvm use 20.19.0
npm --prefix apps/frontend install
```

然后重新运行：

```bash
hermes-yachiyo
```

### Hermes 安装时 GitHub clone 失败

常见错误包括：

```text
RPC failed
early EOF
fetch-pack: unexpected disconnect
invalid index-pack output
```

通常是网络中断、代理不稳定或 GitHub 连接问题。可以重新点击安装，或换一个网络环境后再试。

### Live2D 提示未检测到模型

这不影响主控台、Bubble 或 Chat Window。你只需要在“Live2D 设置”里导入资源包 ZIP，或选择包含 `.model3.json` / `.moc3` 的模型目录。

### 想完全重来

用户配置和工作目录主要在：

```text
~/.hermes-yachiyo/
~/.hermes/yachiyo/
```

删除这些目录会清掉本地配置、资源和会话相关数据。操作前请确认已经备份。

## QQ / AstrBot 桥接

AstrBot 插件是可选能力，用于从 QQ 侧转发命令到本机 Bridge。插件只做路由桥接，不直接实现本地机器控制。

常用命令：

| 命令 | 说明 |
|------|------|
| `/y status` | 查看状态 |
| `/y tasks` | 查看任务 |
| `/y do <描述>` | 创建任务 |
| `/y check <id>` | 查看任务详情 |
| `/y cancel <id>` | 取消任务 |
| `/y screen` | 查看截图信息 |
| `/y window` | 查看当前活动窗口 |
| `/y help` | 查看帮助 |

## 开发者说明

### 项目结构

```text
apps/
  frontend/           Electron + React/Vite/TypeScript 前端
  desktop_backend/    无窗口 Python 后端入口
  desktop_launcher.py 源码开发启动器
  shell/              配置、安装、桌面后端 UI 数据适配
  core/               Hermes 运行时封装、任务状态、聊天状态
  bridge/             本地 FastAPI Bridge
  locald/             截图、活动窗口等本地能力
  installer/          Hermes 安装检测、安装、工作区初始化
packages/
  protocol/           跨层数据模型
integrations/
  astrbot-plugin/     QQ 桥接插件
tests/                pytest 测试
docs/                 架构与资源文档
```

### 架构边界

- React 前端只负责界面，不直接调用 Python 对象。
- Electron 负责桌面窗口、托盘、内置终端和原生能力。
- Python backend 负责运行时、配置、安装检测和本地 Bridge。
- Bridge 只监听本机，供 UI 和插件调用。
- 旧 pywebview 承载层已移除，新 UI 工作统一放在 `apps/frontend/`。

更详细的前端架构见 [docs/desktop-frontend-architecture.md](docs/desktop-frontend-architecture.md)。

### 常用开发命令

```bash
source .venv/bin/activate
source ~/.nvm/nvm.sh
nvm use 20.19.0

# 前端构建
npm --prefix apps/frontend run build

# 运行测试
pytest -q

# 启动应用
hermes-yachiyo
```

### 测试

```bash
pip install -e ".[dev]"
pytest -q
```

当前测试覆盖：

- 协议模型
- 任务状态
- 执行器
- SQLite 会话
- Chat API
- 设置生效策略
- 安装器
- 卸载与备份
- 启动决策
- AstrBot handler

## 发布包计划

当前源码版需要开发环境。正式发布包的目标是：

- macOS 优先，之后再做 Windows 和 Linux。
- 前端预构建后随 Electron 打包。
- Python 后端冻结为可执行文件，或随包内置干净虚拟环境。
- 普通用户不需要全局安装 Python、Node.js 或 npm。
- `node-pty` 等 native 依赖需要在 Electron 包中正确 unpack。

## 许可证

MIT
