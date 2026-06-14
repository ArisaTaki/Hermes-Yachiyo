# Agent Market Benchmark for Oha-Yachiyo

日期：2026-06-14

目标：调研 Open-Hanako/HanaAgent、Nous Hermes Agent、OpenClaw、OpenClaw Agents、AstrBot 等公开 Agent 项目的设计逻辑，并把它转成 Oha-Yachiyo 自研 Agent 的能力对照和改造优先级。

## 调研来源

- Open-Hanako/HanaAgent README: https://github.com/liliMozi/openhanako
- Nous Hermes Agent docs: https://hermes-agent.nousresearch.com/docs/
- Hermes Agent architecture: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
- Hermes Agent memory: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- Hermes Agent skills: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Hermes Agent security: https://hermes-agent.nousresearch.com/docs/user-guide/security
- OpenClaw README/docs index: https://github.com/openclaw/openclaw
- OpenClaw Gateway architecture: https://docs.openclaw.ai/concepts/architecture
- OpenClaw Agent runtime: https://docs.openclaw.ai/concepts/agent
- OpenClaw session management: https://docs.openclaw.ai/concepts/session
- OpenClaw skills: https://docs.openclaw.ai/tools/skills
- OpenClaw security/sandboxing: https://docs.openclaw.ai/gateway/security
- OpenClaw Agents kit: https://github.com/shenhao-stu/openclaw-agents
- Hermes multi-agent roadmap issue: https://github.com/NousResearch/hermes-agent/issues/344
- AstrBot official docs: https://docs.astrbot.app/
- AstrBot Agent runner: https://docs.astrbot.app/providers/agent-runners.html
- AstrBot built-in runner: https://docs.astrbot.app/providers/agent-runners/astrbot-agent-runner.html
- AstrBot function calling/tools: https://docs.astrbot.app/use/function-calling.html
- AstrBot Skills: https://docs.astrbot.app/use/skills.html
- AstrBot SubAgent: https://docs.astrbot.app/use/subagent.html
- AstrBot proactive Agent: https://docs.astrbot.app/use/proactive-agent.html
- AstrBot MCP: https://docs.astrbot.app/use/mcp.html
- AstrBot context compression: https://docs.astrbot.app/use/context-compress.html
- AstrBot sandbox: https://docs.astrbot.app/use/astrbot-agent-sandbox.html

## 市场设计共识

| 能力面 | 市场项目里的设计逻辑 | Oha-Yachiyo 当前对应 | 优先级 |
| --- | --- | --- | --- |
| 持久人格与用户关系 | Open-Hanako 把 Agent 做成有记忆、有性格、会主动行动的私人助理；OpenClaw 使用 `SOUL.md`、`IDENTITY.md`、`USER.md` 注入人格和用户上下文。 | Agent Studio 有 `nickname`、`persona_prompt`、`instructions`，主 Chat 有 persona/profile context。 | P0：继续强化 prompt/context 的长期一致性。 |
| 长期记忆 | Hermes 使用显式 memory/user 两类记忆，并自动注入；OpenClaw 有 workspace bootstrap、session store、memory engine、active memory；AstrBot 有知识库和自动上下文压缩。 | Oha 保留 `build_cross_session_memory_context()` 历史启发式，同时新增 SQLite `memory_items`/`memory_events`、`memory.add`、`memory.replace`、`memory.remove` 受控工具，以及 `/ui/memories` Bridge 管理 API；Agent context 会注入带 `memory_id` 的长期记忆摘要。 | P0：Agent-managed durable memory 和管理 API 已落地，后续补候选确认、项目记忆和设置页 UI。 |
| 技能渐进加载 | Hermes/OpenClaw/AstrBot 都把 Skill 当成任务手册，通过名称/描述先筛选，需要时再加载完整内容。 | Oha 有 Skill library、sync/import/install/folder、Agent mounted skills；本轮新增 `skill.read` 受控工具，Agent context 只放 Skill 摘要索引，需要完整手册时再按需读取。 | P0：本轮落地，后续可加更智能的 Skill 匹配/推荐。 |
| 受控工具循环 | Hermes/OpenClaw/AstrBot 都强调 tool calling、审批、沙盒、workspace 边界。 | `ToolBroker` 限定 workspace/artifact/terminal；`ApprovalCoordinator` 和 resume 逻辑已存在；高风险工具需审批。 | 已达 P0 基线，后续扩充工具生态和沙盒深度。 |
| 多 Agent 协作 | Open-Hanako 支持多 Agent 频道协作/互相委派；OpenClaw Agents 预置 9 个角色和 routing；Hermes roadmap 指向 DAG、共享记忆池、judge/taste gate、adversarial debate；AstrBot SubAgent 让主 Agent 只看委派工具，专门子 Agent 负责工具。 | Oha 已有 Agent Studio、group dispatch、Workflow child Agent、parallel/subworkflow/loop/approval。 | P0：补“角色化团队模板”和 judge/reviewer 质量门。 |
| 工作区/异步协作空间 | Open-Hanako 的“书桌”让 Agent 读写文件、便签和监听变化；OpenClaw Agent runtime 有 workspace/bootstrap 文件。 | Oha 有 workspace policies、artifacts、agent-context.md 和 Run Detail。 | P1：把 artifacts/workspace 提升成用户可见的 Agent 桌面/交接空间。 |
| 主动能力 | Open-Hanako 有定时任务与心跳；OpenClaw 有 cron/background/standing orders；AstrBot FutureTask 可自我唤醒并主动推送。 | `ProactiveDesktopService` 支持桌面观察、Bubble/Live2D/TTS 主动关怀；NativeRunEngine 新增 durable `future_tasks`/`future_task_events`、`future_task.schedule/list/cancel` 工具和 `/ui/future-tasks` Bridge API，到期后创建真实 Agent/Workflow Run。 | P1：FutureTask 持久化、Agent 工具和管理 API 已落地，后续补后台 tick、设置页 UI 和外部 channel delivery。 |
| 多渠道入口 | OpenClaw Gateway 统一 WhatsApp/Telegram/Slack/Discord/iMessage/WebChat；AstrBot 面向 QQ/微信/飞书/Telegram/Discord/Slack。 | Oha Bridge + AstrBot plugin 已覆盖 QQ/AstrBot 命令入口，桌面 app 是主入口。 | P1：把 Bridge 协议和外部会话上下文做成正式 channel surface。 |
| 安全与治理 | OpenClaw 强调 one operator boundary、security audit、pairing、sandbox；Hermes 有 approvals、YOLO、hardline blocklist；AstrBot 有 local/sandbox Computer Use。 | Oha 有 workspace scope、approval、secret redaction、packaged bridge isolation、release verifier。 | P0：加 Agent 市场基线 audit，后续补更强 sandbox/permission UI。 |
| 可观测性和运维 | AstrBot WebUI 有日志、Trace、插件管理；OpenClaw Gateway 有 health/presence/events；Hermes 有 session storage/FTS/tool registry。 | Oha 有 Run timeline/events、Diagnostics、Tool Center、Agent Studio。 | P1：给 Agent 市场基线做稳定 summary 和 UI/RC gate。 |

## 第一批落地方向

1. 固化 Market-grade Agent operating doctrine，让模型循环默认表现为“持久个人 Agent”，而不是只会完成单轮问答。
2. 新增 `summarize_agent_market_parity.py`，把上述市场共识转成可机器检查的 Oha 能力矩阵。
3. 本轮落地 Skill progressive disclosure：Agent context 先挂 Skill 摘要，模型需要时通过 `skill.read` 读取完整 `SKILL.md`。
4. 本轮落地 Agent-managed long-term memory：显式 durable memory store，支持 `memory.add`、`memory.replace`、`memory.remove`，并通过 `memory_events` 记录来源和审计。
5. 本轮落地 FutureTask 主动任务体系基线：支持 delay、绝对时间和简单 `cron`，模型可用 `future_task.schedule/list/cancel` 安排或管理，到期后进入现有 Run/审批/Artifact 链路。
6. 下一步补后台 tick、设置页 UI、外部 channel delivery，以及角色化团队模板：researcher/coder/reviewer/operator/companion 和 reviewer/judge 质量门。

## 判定标准

短期不追“功能名字相同”，追下面这些效果：

- 用户能感觉 Agent 有稳定人格、记得偏好、能承接长期任务。
- Agent 会正确选择工具、技能、子 Agent 或 Workflow，而不是把所有能力塞进一次 prompt。
- 高风险动作可审批、可恢复、可审计。
- 复杂任务能拆分、并行、汇总、复盘，有 artifact 或 Run Detail 可追溯。
- 外部入口和桌面入口共享同一个 Native Agent 能力，不出现第二套任务系统。
