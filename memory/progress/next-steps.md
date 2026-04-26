# Next Steps

1. 手工验证 PR #4 review 修复：主动桌面观察失败后先显示错误，等待间隔后自动重新创建低风险截图任务。
2. 手工验证 PR #4 review 修复：Live2D 真实 TTS provider 朗读完整长回复，而回复气泡/摘要仍保持截断展示。
3. 手工验证 PR #4 review 修复：Bubble 未读为呼吸光/红点，处理中和失败分别显示状态点，idle/empty/ready 无未读时隐藏。
4. 手工验证 Bubble / Live2D 聊天窗口 click-only：hover、pointerenter、窗口 focus、主动刷新均不得打开 Chat Window；只有点击入口按当前 click action 打开/切换。
5. 手工验证 Bubble 设置认知：尺寸 `80-192` 的视觉变化、位置/置顶/头像重启后生效、“应用并重启应用”入口、`edge_snap` 仍显示待实现。
6. 手工验证 Live2D 启动策略：`default_open_behavior` 只影响回复泡泡/快捷输入，`auto_open_chat_window` 仅在模式启动时打开一次且需重启当前模式。
7. 手工验证主动桌面观察：关闭状态、Hermes 未就绪 blocker、vision 受限 blocker、成功创建低风险截图任务、ack 清除提示。
8. 手工验证 TTS：默认关闭无感、`http` endpoint 调用、`command` 本地命令调用、错误配置不影响聊天。
9. 手工验证 AstrBot `/y ask` / `/y chat`：allow-list 拒绝、状态/截图/窗口摘要、自然语言低风险任务创建。
10. 设计下一步 AstrBot 记忆共享：只上传显式摘要/事实，不默认同步 QQ 原始聊天；本地端负责筛选、存储和 prompt 注入。
11. 继续推进 AstrBot 宿主绑定：在 AstrBot 插件框架中注册 `/y` 命令监听并调用 `on_y_command()`。
12. 继续对接 Hapi `/codex` 真实端点，保持 Codex CLI 执行不进入 Hermes-Yachiyo。
13. 后续再推进真实 Live2D renderer / moc3 动作、Bubble edge snap 原生吸边和更精细的未读/动画表现。
14. 完善任务持久化与安全策略模块（packages/tasking / packages/security），并补跨平台本地能力适配。
