# Session Summary

## 本轮完成内容 — Milestone 57: Control Center + 双显示模式

### 核心结果

Hermes-Yachiyo 现在不再把主控台作为显示模式，而是：

- **Control Center**：按需打开的总控台 / 仪表盘 / 诊断入口
- **Bubble Mode**：轻量常驻聊天模式
- **Live2D Mode**：角色聊天壳
- **Chat Window**：Bubble / Live2D / Control Center 共享的完整会话空间

四者围绕同一套聊天内核运行，没有分叉出独立聊天状态。

### 本轮主要变更

#### 1. 模式配置层重构

- `apps/shell/config.py`
  - 保留主控台窗口配置 `WindowModeConfig`
  - 新增 `BubbleModeConfig`
  - 新增 `Live2DModeConfig`
  - `AppConfig` 改为通用配置 + 按模式配置的结构
  - `display_mode` 收敛为 `bubble | live2d`，旧 `window` 配置迁移到 `bubble`
  - 兼容旧 `live2d` 配置块读取

- `apps/shell/mode_settings.py`
  - 集中模式设置读写、校验、序列化
  - 模式设置只暴露 `bubble_mode.*` / `live2d_mode.*`
  - 兼容旧 `live2d.*` 更新键

- `apps/shell/settings.py`
  - 改为 `Common + 当前模式设置`
  - 只显示 Bubble / Live2D 的模式设置，不再展示 Window 模式

#### 2. 模式壳职责重构

- `apps/shell/window.py`
  - 原主窗口改为 `Hermes-Yachiyo Control Center`
  - 保留状态、诊断、最近消息概览、最近会话概览、打开 Chat Window 入口
  - 新增 `open_main_window(runtime, config)`，供 Bubble / Live2D 打开 Control Center

- `apps/shell/modes/bubble.py`
  - 重写为真正 Bubble 模式
  - 支持展开/收起
  - 支持最近 1~3 条摘要显示
  - 支持快捷输入并继续当前会话
  - 支持 processing / failed / ready 状态展示
  - 支持打开 Chat Window / Control Center / Bubble 设置

- `apps/shell/modes/live2d.py`
  - 重写为角色聊天壳
  - 角色舞台 + 回复泡泡 + 最近摘要
  - 支持最小输入入口
  - 支持打开 Chat Window / Control Center / Live2D 设置
  - 保留 renderer 接入位，但本轮不做真实渲染

#### 3. 共享聊天概览层增强

- `apps/shell/chat_bridge.py`
  - 新增 `get_recent_sessions()`
  - 新增 `get_conversation_overview()`
  - Control Center / Bubble / Live2D 统一通过它读取当前会话摘要和最近会话

- `apps/shell/main_api.py`
  - `get_dashboard_data()` 新增 `chat` + `modes`
  - `get_settings_data()` 改为返回 `mode_settings`
  - `update_settings()` 改为委托 `mode_settings.apply_settings_changes()`
  - 新增 `open_mode_settings(mode_id)`

### 当前产品职责关系

#### Control Center

- 用途：总控台、仪表盘、诊断入口、设置入口
- 展示：Hermes / workspace / bridge / integration / task 状态、最近消息、最近会话
- 入口：Bubble / Live2D 右键菜单、主控台打开 API
- 不做：完整聊天消息区

#### Chat Window

- 用途：完整会话空间
- 展示：完整消息流、历史会话切换、会话清空/删除
- 关系：Bubble / Live2D / Control Center 都可打开它，它不是产品唯一入口

#### Bubble Mode

- 用途：轻量桌面聊天模式
- 已具备：
  - 展开/收起
  - 最近摘要
  - 快捷输入
  - 当前会话续聊
  - 状态标签
  - 打开完整聊天窗口
  - 打开 Bubble 设置

#### Live2D Mode

- 用途：角色聊天壳
- 已具备：
  - 角色舞台壳
  - 最近回复泡泡
  - 最近摘要
  - 最小输入入口
  - 当前会话状态感知
  - 打开完整聊天窗口
  - 打开 Live2D 设置
- 未做：
  - 真正 renderer / moc3 渲染
  - 动作 / 表情 / 口型驱动

### 统一聊天来源确认

仍然保持唯一来源：

```text
Control Center / Bubble / Live2D / Chat Window
        ↓
      ChatBridge / ChatAPI
        ↓
      ChatSession
        ↓
      ChatStore (SQLite)
```

没有新增任何独立消息状态容器。

### 测试覆盖

- `tests/test_mode_settings.py`
  - 模式配置模型分离
  - Bubble 配置读写
  - 旧 `live2d.*` 兼容更新
  - 新旧配置块加载/保存

- `tests/test_main_api_modes.py`
  - Control Center 仪表盘包含 chat overview + modes
  - 设置数据返回 `mode_settings`

- `tests/test_chat_bridge.py`
  - 新增 conversation overview 覆盖
  - Bubble / Live2D HTML 仍保留统一轮询契约

- `tests/test_window_exit.py`
  - 验证 Control Center 仍通过 Chat Window 承载完整会话

### 手工验证建议

1. 启动默认 `display_mode=bubble`，确认只出现圆形 launcher。
2. 从 Bubble 右键打开 Control Center，确认总控信息和最近消息/会话概览正常。
3. 在 Control Center 打开 Chat Window，确认完整消息流仍正常。
4. 切到 Live2D Mode，观察角色 launcher、缩放、跨 Spaces 配置和 Chat Window 展开行为。
5. 分别打开 Bubble / Live2D 设置，确认 `Common + 当前模式设置` 能保存并在切换模式时重启应用。

### 后续最合理的方向

1. 把 Bubble / Live2D 的窗口位置恢复、吸附和更细粒度未读态做成真正原生行为。
2. 为 Live2D 模式接入 renderer 占位实现（先 canvas / mock renderer，再接 moc3）。
3. 继续补 UI 层自动化或更细的 shell service 测试。
