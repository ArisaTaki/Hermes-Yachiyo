# Session Summary

## 本轮完成内容 — Milestone 46: CLI 修复 + 聊天窗口独立化 + SQLite 持久化

### Phase 1: HermesExecutor CLI 修复

- `_HERMES_CMD` 从 `["hermes", "run", "--prompt"]` 修正为 `["hermes", "chat", "-q"]`
- 新增 `_HERMES_FLAGS = ["-Q", "--source", "tool"]`（安静模式 + 第三方标记）
- exit=2 错误不再暴露 argparse 原始 usage 文本，改为友好提示
- 验证：`hermes chat -q "hi" -Q --source tool` 正常返回 session_id

### Phase 2: 独立聊天窗口

- 新建 `apps/shell/chat_window.py`：独立 pywebview 窗口（420×600）
- ChatWindowAPI 封装所有聊天操作 + 历史会话列表
- 单例管理：已开则聚焦，关闭事件自动清理引用
- 主窗口嵌入式聊天面板 → 「打开聊天窗口」按钮

### Phase 3: SQLite 持久化

- 新建 `apps/core/chat_store.py`：基于 `~/.hermes/yachiyo/chat.db`
- 表结构：chat_sessions + chat_messages（WAL 模式，外键约束）
- ChatSession.attach_store() 自动绑定，消息写入/状态更新自动同步到 DB
- get_chat_session() 初始化时自动创建 store 并绑定

### Phase 5: Bubble/Live2D 适配

- bubble.py：移除嵌入式聊天 UI，改为 `open_chat()` → 独立聊天窗口
- live2d.py：同上，移除 ChatAPI 依赖，改为 `open_chat()`
- 三模式统一入口：`open_chat_window(runtime)` from chat_window.py

### 测试

- `test_executor.py`：新增 CLI 命令常量验证测试
- `test_chat_store.py`（新建）：6 个 CRUD 测试用例
- 全部 14 测试通过

### 消息发送链路（更新）

```
用户输入 → sendMessage() [JS, 聊天窗口]
  → ChatAPI.send_message() [Python]
    → ChatSession.add_user_message() → SQLite 持久化
    → AppState.create_task()
    → ChatSession.link_message_to_task() → SQLite 更新
  → TaskRunner 轮询 PENDING 任务
  → HermesExecutor.run()
    → invoke_hermes_cli(query) → hermes chat -q "query" -Q --source tool
  → AppState.update_task_status(COMPLETED)
  → UI 轮询 get_messages()
    → ChatAPI._sync_task_status_to_messages()
    → ChatSession.add_assistant_message() → SQLite 持久化
  → 渲染 assistant 回复
```

### 下一步建议

1. **流式 token UI**：支持逐字显示 agent 回复
2. **Live2D 渲染器**：接入 PixiJS / CubismSDK
3. **历史会话加载**：从 SQLite 恢复历史会话
4. **Hermes session 关联**：用 `--resume SESSION_ID` 支持多轮对话
