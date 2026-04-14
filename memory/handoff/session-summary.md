# Session Summary

## 本轮完成内容

基于修正后的 desktop-first 产品形态，完成了仓库骨架和 protocol schema。

### 产品形态修正

- 从「纯 FastAPI 后端服务」修正为「桌面优先本地应用」
- pywebview 作为 MVP 桌面壳原型（不影响 core/bridge/protocol 长期边界）
- FastAPI 降级为内部通信桥梁层

### 五层架构

1. App Shell (apps/shell/) — 桌面壳入口，托盘/窗口/模式
2. Core Runtime (apps/core/) — Hermes 封装，任务/状态管理，不暴露 HTTP
3. Local Capabilities (apps/locald/) — 截图/活动窗口适配器
4. Bridge/API (apps/bridge/) — 内部 FastAPI，非产品本体
5. AstrBot Plugin (integrations/) — QQ 桥接骨架

### 创建的文件（30 个）

- apps/shell/: app.py, tray.py, window.py, config.py, modes/
- apps/core/: runtime.py, state.py
- apps/bridge/: server.py, routes/ (status, tasks, screen, system)
- apps/locald/: screenshot.py, active_window.py
- packages/protocol/: enums.py, schemas.py, errors.py, events.py
- packages/tasking/, packages/security/ — 占位
- integrations/astrbot-plugin/: main.py

### 待后续完成

- Bridge 路由接入 Runtime 实例
- 任务生命周期与持久化
- 安全策略模块
- AstrBot 实际 HTTP 调用
- 基础测试
