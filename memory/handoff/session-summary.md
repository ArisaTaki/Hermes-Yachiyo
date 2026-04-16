# Session Summary

## 本轮完成内容 — Milestone 41: Hermes Setup 交互性修复

### 问题

`hermes setup` 的 TUI 菜单显示在 GUI 安装日志区域，但用户无法通过方向键/回车进行交互。

### 根因

`run_hermes_install()` 运行 `curl ... | bash` 时未设置 `stdin=DEVNULL`。官方安装脚本在安装
完二进制后自动调用 `hermes setup`，该进程的 TUI 输出被 PIPE 到 GUI，但无 PTY、无 stdin，
用户只能看到菜单文字，无法交互。

### 解决方案

| 修复点 | 变更 |
|--------|------|
| `run_hermes_install()` stdin | 加 `stdin=asyncio.subprocess.DEVNULL`，强制安装脚本中的交互程序立即得到 EOF |
| 非零退出回退检查 | `rc!=0` 时调用 `hermes --version`，若可用则仍返回 `success=True` |
| `open_hermes_setup_terminal()` | osascript 改用 `make new document`，确保打开新 Terminal 窗口 |

### 修改文件

| 文件 | 变更内容 |
|------|---------|
| `apps/installer/hermes_install.py` | `stdin=DEVNULL`；非零退出时 hermes 可用性回退检查 |
| `apps/shell/installer_api.py` | osascript `make new document` 强制新窗口 |
| `memory/progress/current-state.md` | 新增 Milestone 41 |
| `memory/handoff/session-summary.md` | 本文件 |

### 正确用户流程（修复后）

```
安装 Hermes → 安装日志（无交互 setup 输出）
→ recheck_status() 检测 INSTALLED_NEEDS_SETUP
→ App 重启 → "⚙️ 配置 Hermes Agent" 引导页
→ 点击"开始配置 Hermes"
→ Terminal.app 新窗口打开，运行 hermes setup（完整 PTY，全交互）
→ 用户完成配置，回 GUI 点击"我已完成配置，重新检测"
→ 进入正常模式
```

### 测试状态

- 107 tests passed（新增 2 个 startup 测试来自 Milestone 37 的 SETUP_IN_PROGRESS 状态）

### 下一步建议

- 如果 Hermes 官方安装脚本有非标准 post-install 行为，可在 `run_hermes_install()` 中增加
  `hermes setup` 输出的关键词检测，在日志中提示用户"检测到 setup 需要，将在独立终端中引导完成"
- 可测试 macOS 上的完整安装流程：安装 → setup → workspace init → 正常模式
