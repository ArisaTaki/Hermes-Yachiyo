# Next Steps

1. 手工验证 Bubble / Live2D 设置生效闭环：`click` / `hover`、透明度、回复气泡、快捷输入、默认启动表现。
2. 手工验证主动桌面观察：关闭状态、Hermes 未就绪 blocker、vision 受限 blocker、成功创建低风险截图任务、ack 清除提示。
3. 手工验证 TTS：默认关闭无感、`http` endpoint 调用、`command` 本地命令调用、错误配置不影响聊天。
4. 手工验证 AstrBot `/y ask` / `/y chat`：allow-list 拒绝、状态/截图/窗口摘要、自然语言低风险任务创建。
5. 继续推进 AstrBot 宿主绑定：在 AstrBot 插件框架中注册 `/y` 命令监听并调用 `on_y_command()`。
6. 继续对接 Hapi `/codex` 真实端点，保持 Codex CLI 执行不进入 Hermes-Yachiyo。
7. 后续再推进真实 Live2D renderer / moc3 动作、Bubble edge snap 原生吸边和更精细的未读/动画表现。
8. 完善任务持久化与安全策略模块（packages/tasking / packages/security），并补跨平台本地能力适配。
