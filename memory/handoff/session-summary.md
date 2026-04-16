# Session Summary

## 本轮完成内容 — Milestone 51: 重复 assistant 修复 + Processing UI + 多轮对话 + 历史会话

### Milestone 47: 重复 assistant 修复 + Processing UI

**根因**：`ChatAPI._sync_task_status_to_messages()` 中 `has_assistant_reply()` + `add_assistant_message()` 是两次独立加锁操作（TOCTOU 竞态），并发轮询可同时通过检查并各自新增 assistant 消息。

**修复**：
- 新增 `ChatSession.upsert_assistant_message(task_id, content, status, error)` — 在同一把 RLock 内完成"查找 → 更新/创建"，原子不可分割
- `ChatAPI._sync_task_status_to_messages()` 全面改用 `upsert_assistant_message()`
- RUNNING → 创建 PROCESSING 占位消息；COMPLETED → 更新同一条消息；FAILED → 更新同一条消息
- 不允许从终态（COMPLETED/FAILED）回退到 PROCESSING

**Processing UI**：
- 聊天窗口新增 `.processing` CSS 类 + `@keyframes thinking-dots` 打字动画
- assistant PROCESSING 气泡显示"正在思考..."动画
- 轮询间隔从 1500ms 缩短到 800ms

### Milestone 51: 多轮对话 + 历史会话 + 消息排序

**`--resume SESSION_ID` 多轮对话**：
- `ChatSession` 增加 `hermes_session_id` 字段，记录 Hermes CLI 返回的 session ID
- `invoke_hermes_cli()` 支持 `hermes_session_id` 参数，自动附加 `--resume`
- `HermesExecutor` 从 `ChatSession` 读取 session ID 并传入 CLI
- Hermes stdout 中的 `[Session: xxx]` 自动解析并存入 `ChatSession`
- 同一个 Yachiyo 会话内的多次查询共享 Hermes 上下文

**历史会话加载**：
- `ChatWindowAPI.load_session(session_id)` 加载历史会话消息到当前 ChatSession
- 聊天窗口 header 新增历史会话下拉菜单
- UI 支持切换到历史会话查看消息

**消息排序优化**：
- `get_messages()` 返回时按 task 关联关系重排：user 消息后紧跟其 assistant 回复

### 消息发送链路（更新）

```
用户输入 → sendMessage() [JS, 聊天窗口]
  → ChatAPI.send_message() [Python]
    → ChatSession.add_user_message() → SQLite 持久化
    → AppState.create_task()
    → ChatSession.link_message_to_task() → SQLite 更新
  → TaskRunner 轮询 PENDING 任务
  → HermesExecutor.run()
    → invoke_hermes_cli(query, hermes_session_id) → hermes chat -q "query" -Q --source tool [--resume ID]
  → AppState.update_task_status(COMPLETED)
  → UI 轮询 get_messages()
    → ChatAPI._sync_task_status_to_messages()
    → ChatSession.upsert_assistant_message() → 原子创建/更新 → SQLite 持久化
  → 渲染 assistant 回复（按 task 关联排序）
```

### 下一步建议

1. **字符级 token streaming**：需 Hermes 底层支持增量输出
2. **Live2D 渲染器**：接入 PixiJS / CubismSDK
3. **处理进度百分比**：需 Hermes 提供进度回调
