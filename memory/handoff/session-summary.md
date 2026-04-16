# Session Summary

## 本轮完成内容 — Milestone 42: Hermes 能力补全入口

### 问题

主界面只展示受限工具列表（只读），没有操作入口，用户不知道如何补全能力。

### 解决方案

在仪表盘和设置页均新增 `basic_ready` 状态下的操作入口，支持：
- 打开 Terminal.app 运行 `hermes setup`（配置向导）
- 打开 Terminal.app 运行 `hermes doctor`（诊断）
- 原地重新检测 Hermes 状态并刷新 UI

### 修改文件

| 文件 | 变更 |
|------|------|
| `apps/shell/main_api.py` | 新增 `open_terminal_command(cmd)` + `recheck_hermes()` |
| `apps/shell/window.py` | 仪表盘补全按钮 + inline 面板；设置页操作区；`refreshDashboard/Settings` 控制显隐；3 个新 JS 函数 |
| `memory/progress/current-state.md` | 新增 Milestone 42 |
| `memory/handoff/session-summary.md` | 本文件 |

### 当前状态

```
basic_ready 时：
  仪表盘 Hermes 卡 → [🔧 补全 Hermes 能力] 按钮
    → 展开 inline 面板
        ├─ [▶ hermes setup]   → Terminal.app 新窗口
        ├─ [🔍 hermes doctor] → Terminal.app 新窗口
        └─ [🔄 重新检测]      → 重检 + 刷新 UI

  设置页 Hermes 节 → 同款操作区

full_ready 后：
  面板自动收起，状态行显示"✅ 完整就绪"
```

### 测试状态

107 tests passed

### 下一步建议

- 可考虑为 `hermes setup` 的各子项（auth / model / tools）提供更细粒度的入口
- 可增加"hermes setup 完成后自动触发 recheck"的轮询机制（类似 installer 的 setup polling）
- Live2D 渲染器实现（当前仍为占位）
