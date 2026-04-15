# Session Summary

## 本轮完成内容 — Milestone 33: 设置生效策略 + 运行时反馈 + 控制入口

### 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/effect_policy.py | **新增** — 集中定义设置生效策略模型 |
| apps/shell/main_api.py | `_bridge_boot_config` 快照；`_current_app_state()` 增加 `config_dirty`；`update_settings()` 返回 `effects` |
| apps/shell/modes/live2d.py | `update_settings()` 返回 `effects` |
| apps/shell/window.py | 新增 `showEffectHints()` JS + `effect-hints` UI + `bridge-dirty-hint` + CSS |
| apps/shell/settings.py | 新增 `showEffectHints()` JS + `effect-hints` UI + CSS |
| memory/progress/current-state.md | Milestone 33 记录 |
| memory/handoff/session-summary.md | 本次汇报 |

### 设置生效策略模型

```
EffectType 枚举:
  IMMEDIATE            — 即时反映到 UI 和内存配置
  REQUIRES_MODE_RESTART — 需重启当前显示模式
  REQUIRES_BRIDGE_RESTART — 需重启 Bridge
  REQUIRES_APP_RESTART  — 需重启整个应用
```

### 字段 → 策略映射

| 字段 | 策略 |
|------|------|
| live2d.model_name/path/idle/expressions/physics | IMMEDIATE |
| live2d.window_on_top | REQUIRES_MODE_RESTART |
| display_mode | REQUIRES_MODE_RESTART |
| bridge_enabled/host/port | REQUIRES_BRIDGE_RESTART |
| tray_enabled | REQUIRES_APP_RESTART |

### `update_settings()` 返回结构新增

```json
{
  "ok": true,
  "applied": {"bridge_host": "0.0.0.0"},
  "effects": {
    "effects": [{"key": "bridge_host", "effect": "requires_bridge_restart", "message": "Bridge 地址变更需重启 Bridge 后生效"}],
    "has_immediate": false,
    "has_restart_bridge": true,
    "hint": "需重启 Bridge后生效"
  },
  "app_state": { "bridge": { "config_dirty": true, ... } }
}
```

### Bridge 配置漂移检测

- `_bridge_boot_config` 记录启动时 bridge 配置快照
- `_current_app_state()` 对比当前配置与快照，返回 `bridge.config_dirty`
- 设置页 Bridge 区域显示 `bridge-dirty-hint` 黄色提示条

### 架构决策

- 生效策略集中在 `effect_policy.py`，不散落在前端字符串
- `update_settings()` 统一返回 `effects`，主窗口和独立设置窗口共享同一消费逻辑
- display_mode 采用"保存 + 下次启动生效"策略（MVP 推荐）
- Bridge 当前不自动重启，仅提示用户配置已变更
