# develop issue hotfix 汇总

日期：2026-05-25  
分支：`hotfix/develop-issues`  
基线：`develop`

## 处理范围

本次集中处理 GitHub open issues #31、#32、#33、#34。改动目标是修复发布分支上的已知体验问题，并保留可回查的验证步骤。

## Issue 对应方案

| Issue | 现象 | 处理方案 | 主要文件 |
| --- | --- | --- | --- |
| #31 对话记录过长时一直处理中 | Hermes 已经返回内容，但 UI 仍停在 processing，点击中止后才显示结果 | `stream bridge` 收到 `done` 后立即以最终回复收口，只给子进程 2 秒清理窗口；若子进程未退出则回收进程，但任务按已收到的 `done` 完成 | `apps/core/executor.py`, `tests/test_executor.py` |
| #32 活动详情完整日志被省略 | 活动详情的“完整过程”只有压缩摘要，省略部分无法展开 | 活动详情每条 trace 增加“全文/收起”按钮；工具完成事件把更完整的结果写入 metadata，供详情页展开查看 | `apps/frontend/src/views/OpenDesignView.tsx`, `apps/frontend/src/styles/app.css`, `apps/core/hermes_stream_bridge.py`, `apps/core/activity_store.py` |
| #33 长期记忆优化 | 跨会话明确交代过的长期偏好或约束容易遗忘 | 每轮 Hermes prompt 注入本地历史会话中明确表达的长期记忆，例如“请记住”“以后”“不要”“许可”等语句；profile API 标记本地聊天历史记忆已启用 | `apps/core/executor.py`, `apps/bridge/routes/assistant.py`, `packages/protocol/schemas.py`, `apps/frontend/src/views/ModeSettingsView.tsx` |
| #34 review 回复格式问题 | `::: review diff` 一类 review 输出没有按 Markdown 渲染，原始符号暴露 | 扩展现有 Markdown 渲染器，支持冒号 fence、波浪线 fence 和三反引号 fence，并把 `review diff` 归类成 diff 代码块 | `apps/frontend/src/views/ChatView.tsx` |

## 关键实现说明

### #31 processing 收口

原因判断：截图表现像是最终文本已经在后端收到，但 bridge 子进程没有自然退出，导致上层一直等待进程结束，消息状态没有切到 completed。

改动：

- `_consume_stream_bridge()` 收到 `done` 后停止继续读 stdout。
- 新增 `_wait_for_bridge_exit_after_done()`，给 bridge 一个短暂退出 grace period。
- 若 bridge 卡住，调用 `_terminate_process_after_done()` 回收进程，并把 `done.response` 作为成功结果返回。
- 新增测试 `test_done_event_finishes_even_if_bridge_process_hangs` 覆盖“done 已收到但进程不退出”的场景。

### #32 完整过程展开

原因判断：活动日志存储和列表展示都偏向“安全摘要”，UI 只显示单行 detail。老数据无法恢复超过存储上限的内容，新数据需要保留更多可展开信息。

改动：

- 活动详情 trace 行新增展开状态 `expandedTraceIds`。
- 每条有 detail 或 metadata 的 trace 显示“全文”按钮，展开后显示完整摘要和 metadata。
- tool complete 事件 metadata 增加 `result` 字段。
- activity metadata 存储上限从 4000 提升到 12000，单个 metadata 字符串从 300 提升到 1800。

注意：历史日志如果写入时已经被截断，只能展开当时已保存的内容；新日志会保留更多详情。

### #33 长期记忆

原因判断：目前跨会话只依赖 Hermes resume session 和配置资料字段，没有把用户在其他会话中明确要求“记住”的偏好稳定注入到新会话 prompt。

改动：

- 新增 `build_cross_session_memory_context()`，读取本地 `ChatStore` 最近历史会话。
- 只抽取用户消息中带明显长期意图的内容，避免普通任务描述大量进入记忆。
- 注入顺序保持在 profile context 内，位于 persona 和本轮 request 之前。
- assistant profile API 的 `memory_enabled` 改为 `true`，`memory_scope` 改为 `local_chat_history`。

当前策略是轻量启发式，不做外部向量库或新数据库表，避免发布分支引入大迁移风险。

### #34 review Markdown

原因判断：review 输出使用了冒号 fence，例如 `::: review diff`，原渲染器只识别三反引号，导致 review diff 被当普通段落渲染。

改动：

- 新增 `parseMarkdownFence()`。
- 支持三反引号、`~~~`、`:::` 三类 fence。
- `review diff`、`review-diff`、`patch` 统一归一为 `diff` 代码块。

## 验证记录

已执行：

```bash
pytest
```

结果：`562 passed, 1 warning`。warning 来自既有 zip duplicate entry 测试，不是本次改动引入。

已执行：

```bash
cd apps/frontend
npm run build
```

结果：TypeScript、Vite、Electron TypeScript 构建均通过。

已执行局部回归：

```bash
pytest tests/test_executor.py tests/test_assistant_profile_route.py
```

结果：`105 passed`。

已做浏览器手动检查：

- 本地前端 dev server 使用 `http://127.0.0.1:5175/`，因为 `5174` 已被占用。
- 打开活动详情 `#/activity-detail/24ba24c5f32f`。
- 确认“完整过程”中 trace 行出现“全文”按钮。
- 点击后能展开“完整摘要”，展示保存的完整 detail。

## 明天复查建议

1. 在 `hotfix/develop-issues` 分支启动应用。
2. 发送一条会产生较长输出的对话，确认最终回复出现后不会长期停在“处理中”。
3. 进入“活动日志”详情页，选择工具调用记录，确认“全文/收起”按钮可用。
4. 在一个会话里发送“请记住：不要擅自推送 GitHub，需要获得许可再推送。”，再新建会话询问相关偏好，观察回答是否遵守该记忆。
5. 让模型生成或粘贴一段 `::: review diff` 内容，确认聊天气泡中按代码块渲染。
6. 运行 `pytest` 和 `cd apps/frontend && npm run build` 做最终检查。

## 风险与注意事项

- 长期记忆目前是启发式抽取，只处理明确长期意图，不会理解所有隐含偏好。
- 旧活动日志已经被截断的内容无法补全；本次主要改善新日志和已保存 metadata 的展开。
- `done` 后强制收口只在 bridge 已明确发出最终事件时生效，未收到 `done` 的真实执行超时仍按原超时逻辑处理。
- `.codegraph/` 是本地索引目录，未纳入本次提交。
