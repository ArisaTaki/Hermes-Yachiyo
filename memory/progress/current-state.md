# Current State

## 已完成

### Milestone 96 — Chat 群组协作与 Workflow 运行可观察性收口

- ✅ 群组对话现在按“长期群组 + 每轮目标独立 RunGroup”运行：用户直接在群里发布目标会交给主模型识别和派发；群内直接 `@Agent` 也会开启当前目标的运行批次，并在完成、失败、取消或审批结束后自动交给主模型整理。
- ✅ 群组调度上下文已补 Agent 能力摘要：主模型和被派出的 Agent 会看到群成员的类别、交付契约和职责说明，不再只凭昵称/名称猜谁适合接任务；主模型调度提示也会要求根据类别、职责和交付偏好选择最合适的成员，除非确实需要协作，不要默认派给所有 Agent；Agent Runtime 的 runnable summary 也会透出 `output_contract`，与主会话自动委派目标信息保持一致。
- ✅ 群组创建/设置弹窗的 Agent 列表也显示类别、交付偏好和职责摘要，用户添加成员时能判断谁适合进群；群头像支持上传后的 data URL 通过 Bridge create/update route 透传；后端回归锁定群组成员只能是启用 Agent，Workflow 不能通过接口混入群聊成员；Bridge 真实 `/ui/chat/groups` + `/ui/chat/messages` route 已覆盖创建群组、修改群组加入新 Agent 后，给主模型注入最新成员、类别、交付契约和职责说明的路径。
- ✅ 主模型派发协议已收紧为自然语言说明 + `<yachiyo_group_dispatch>` 机器块；Chat 层会隐藏派发 JSON、兼容常见模型输出变体，并在无效或跳过派发时给主模型整理未执行原因，不再让用户看到协议碎片或卡在“正在派发”；2026-06-05 追加：同一条主模型回复里如果分段输出多个 `<yachiyo_group_dispatch>` 块，Chat 也会全部收集并派发到同一轮 RunGroup，不会只执行第一个标签块；派发解析也兼容 `type/kind=agent`、`agentName/userGoal/taskGoal/objective/runnableId`、`Delegations` 这类模型常见字段变体，避免真实模型字段名偏一点就漏派。
- ✅ 2026-06-05 追加：群组派发解析继续兼容工具调用风格 envelope，例如 `{"tool":"dispatch_group_agent","input":{...}}`、`arguments/parameters/params/payload/request` 包一层，或 arguments 是 JSON 字符串；2026-06-06 追加：`agents: ["Design","Code"]` 这类目标列表，以及 `agents: "Design、Code"` 这类分隔符字符串，也会拆成同一轮 RunGroup 的多条 Agent 任务；如果同时提供 `goals: ["任务 A","任务 B"]`，会按索引给每个 Agent 分配各自任务；`assignments: {"Design":"任务 A","Code":"任务 B"}` 或 `agents` 映射对象即使省略 `action` 也会展开为多条派发；这些真实模型常见格式会被拆出 Agent 和目标并隐藏机器块，不再因为字段形态偏一点就跳过派发。
- ✅ 2026-06-05 追加：当用户明显要求主模型派发/安排群内 Agent，但主模型最终没有生成任何可执行派发请求时，Chat 会把该气泡标记为“群组任务未派发”、记录失败 activity，并在正文补充可操作提示；2026-06-06 收紧判定：只有“派发/派活/委派”或“安排/交给 + Agent/群成员/具体成员名”这类明确语境才触发，普通“安排计划”不会误报；如果主模型明确说明“我可以直接回答/不需要派发”，也会保持原回复不打扰。
- ✅ Agent 审批体验改为独立工具请求卡片：关联任务、工具名、请求参数分层展示，`terminal.run` 以 bash 代码块显示；Workflow 人工审批会展示审批节点、审批说明和当前上下文；Run Detail 的 Workflow Step 审批摘要不再被前端二次截断，长内容交给折叠控件展示；输入框上方会浮出待审批提醒并支持多审批切换，提醒条会优先显示 Workflow 审批节点/说明，并同时提供“定位消息”和“运行详情”，方便用户从输入区回到原气泡或打开 Run Detail 确认上下文；批准后会立即释放按钮 busy 并后台轮询 Agent 继续执行进度，完成后才触发主模型汇总。
- ✅ Chat 输入区在会话处理中不再锁死继续发言：发送按钮和 Enter 都保持发送语义，停止当前任务拆成独立按钮；Agent Run 创建后的前端轮询改为后台进行，用户可以在主模型整理、Agent 执行或等待审批期间继续补充约束/纠偏；Bridge message route 已覆盖图片附件和显式 runnable 目标透传，避免前端发图或 Agent 会话发送时丢上下文；当前会话状态、停止按钮和会话列表都会显示并发处理数量（例如“处理中 2 项”），计数会合并主模型 Task 与 active Agent/Workflow Run；后端回归覆盖重叠消息全部完成后仍能按 user/assistant 配对收束，并清掉会话 processing 状态与计数。
- ✅ 2026-06-05 追加：群组 Agent 执行期间用户继续发普通群聊/`@主模型` 补充时，后续主模型整理 Prompt 会带上“用户后续补充/纠偏”，覆盖主模型派发多 Agent 和群内直接 `@Agent` 两条路径；补充消息会在保存时记录所属父任务 / Agent 消息，且多个群组任务同时 active 时只归到最近一个 active 或已终态但尚未汇总的目标；接收新的群聊消息前会先静默同步已完成的主模型派发与 Run 状态，但不会抢先创建主模型汇总任务，避免第二批派发刚完成但 UI 尚未刷新时，用户一句“补充”被错误挂到旧任务或来不及进入第二批汇总；群聊里直接 `@Agent` 开新任务也会先静默同步旧 Run，并在新用户消息落库后补建旧 Agent 的主模型汇总任务，避免用户连续点名多个 Agent 时前一个结果迟迟不交给主模型；点名群外 Agent、手动 @Workflow 引导或其他 runnable error/guidance 分支也会在错误/引导消息落库后扫描待汇总 Agent，避免用户误操作后旧结果卡住；另一个独立 `@Agent` 指令、明显新目标提示、以及没有补充/修正语气的 `@主模型` 新请求，不会被误当作当前汇总的补充。
- ✅ 2026-06-05 追加：直接 `@主模型` 的自然纠偏短句也会进入当前群组任务汇总，例如“把验收说明改成...”“顺便加上...”这类用户正常补充，不再必须写“补充/修正/注意”等显式前缀；“另一个目标 / 安排第二轮”等新任务提示仍会单独处理，避免串台。
- ✅ 2026-06-05 追加：Chat 前端会在被归入当前群组任务或当前 Agent 汇总的用户补充消息下方显示轻量状态提示，用户能确认这条后续要求已经进入主模型整理上下文，而不是只能等待最终总结才知道是否生效。
- ✅ Chat 的“停止当前任务”现在会同步取消当前会话消息里挂载的 active Agent / Workflow Run，并把对应气泡刷新为取消终态；取消接口会回传最新 `processing_count`，用户显式停止时不会再额外启动主模型整理任务导致状态看起来又开始处理。
- ✅ Chat 的会话列表和 session info 也会先同步当前会话里的主模型 Task / Agent / Workflow Run 状态：即使没有打开消息流，已完成的 Agent / Workflow Run 也会从 processing 刷到完成态，孤儿 processing 消息会被修复为 failed，避免列表和气泡状态互相矛盾。
- ✅ 会话列表、消息 payload 和 session info 已暴露 `approval_count`；列表预览和右侧状态会优先显示“待审批 / 待审批 N”，审批卡和输入框上方提醒也会同时识别 Agent `run_id/run_status` 与 Workflow `workflow_run_id/workflow_status`，Workflow 自身审批会把 `pending_approval`、审批节点和当前上下文写入聊天消息，避免用户切走群聊后只看到“处理中”而错过或看不懂 Agent/Workflow 的确认请求。
- ✅ Workflow 因子 Agent 工具审批暂停时，Chat 只把真正有 `pending_approval.tool` 的子 Agent Run 计为待审批；父 Workflow 消息显示“正在等待子 Agent 审批”的进度说明，不再变成第二个可点击但不可操作的审批卡，避免用户连续点批准却不知道下一项是什么。
- ✅ 2026-06-06 追加：父 Workflow 等待子 Agent 工具审批时，聊天摘要会直接显示等待对象、Workflow 节点和审批工具，并把 `workflow_waiting_child_run_id` / `workflow_waiting_node` / `workflow_waiting_tool` 写入 metadata；Chat 输入区待审批提醒会在缺少子 Agent 审批气泡时，用这组 metadata 派生一个指向子 Run 的提醒项，真实子 Agent 审批消息或 activity 已存在时不会重复；父 Workflow metadata 也会透传子 Run 的 `pending_approval`，所以派生提醒同样能展示 terminal bash 命令或 patch 内容；`approval_count` 也会按实际待处理 Run ID 去重计数，即使只剩父 Workflow 消息也能让会话列表和 session info 显示待审批；子 Agent 审批通过后如果父 Workflow 恢复失败，失败 timeline 也会保留关联 `child_run_id`、子 Run 状态和节点信息，Run Detail 能定位到具体失败节点。
- ✅ 2026-06-06 追加：Chat 消息 metadata 更新支持删除过期键；父 Workflow 从“等待子 Agent 审批”恢复执行或进入完成/失败/取消终态时，会清理 `workflow_waiting_child_run_id` / `workflow_waiting_node` / `workflow_waiting_tool`，避免输入区继续派生旧审批提醒，也让 Run 详情和列表状态只反映当前真实进度。
- ✅ 2026-06-05 追加：子 Agent 工具审批通过并带动父 Workflow 继续后，Chat 会把子 Agent 消息和父 Workflow 消息一起同步到终态，`processing_count` / `approval_count` 会归零；父 Workflow 终态会按 Workflow 语义展示完成/失败/取消，只有缺少状态上下文的 result 才补 Workflow 标题，避免把子 Agent 输出直接塞成一条不明所以的流程消息。
- ✅ Chat 里直接触发的 Agent/Workflow 指令结果也统一按 `run_status/status` 和 `run_id/agent_run_id/workflow_run_id` 解释：进行中会后台轮询对应 Run，待审批会优先显示等待审批文案，避免不同返回字段导致前端不跟进。
- ✅ 2026-06-06 追加：Chat 前端后台轮询把 `cancelled` 也视为 Run 终态，并按 Agent Run / Workflow Run 区分状态文案，避免 Run 被其他入口取消后输入区一直等到轮询超时。
- ✅ 聊天消息底部状态也区分主模型流式回复和 Agent/Workflow Run：主模型仍显示“输入中”，挂载 Run metadata 的 Agent/Workflow 消息显示“处理中”，避免用户把后台执行误读成普通打字状态。
- ✅ 群聊派发与直接 `@Agent` 的异步完成回调都会写回创建它的原会话：用户在派活后切到新会话也不会丢结果，Agent 完成/失败仍会更新原群聊消息，并在原群聊里创建主模型汇总任务。
- ✅ 群聊中的 Agent 运行中进度会从 Run timeline 提取最新阶段：例如运行环境已准备、正在解析模型响应、正在处理工具结果、已写出产物；聊天气泡仍保持 loading，但进度卡不再只有泛泛的“Agent 正在执行”，也不会把工具调用 JSON 或 `<yachiyo...>` 这类内部协议片段暴露出来。
- ✅ 聊天气泡已接入 Run Detail：Agent 完成/失败时会显示真实产物数量和运行详情入口，主模型汇总 Prompt 也会带上 Agent 状态、汇报和 artifact 路径摘要，避免用户不知道文件在哪里或哪些 Agent 没有完成。
- ✅ 群组主模型整理状态现在直接体现在原 Agent / 派发气泡和底部全局状态上：等待、完成和失败都会按上下文区分“这一轮群组任务”和“这条 Agent 结果”，整理成功后原 Agent/派发气泡会保留轻量完成提示，如果整理任务失败，会在原气泡下显示失败原因；后端回归覆盖直接 `@Agent` 和主模型派发两条路径都会清掉 pending 并写入 `group_agent_summary_status/error`。
- ✅ 2026-06-06 追加：群组主模型整理任务如果被用户取消，原 Agent / 派发气泡会清掉 pending 并标记 `group_agent_summary_status=cancelled`；前端提示“主模型整理已取消”，不再把用户主动停止误显示成主模型整理失败。
- ✅ 2026-06-06 追加：群组主模型整理和普通自动委派 Run 整理的 prompt 会从 Run timeline 提取最近关键执行线索，包括工具调用/跳过/拒绝、审批、失败或取消节点，以及脱敏后的请求内容和执行结果；主模型收尾不再只依赖 Agent 最终一句汇报，也能说明 Agent 具体读写运行了什么。
- ✅ Workflow 入口边界按产品讨论收紧：Chat `@` 候选只保留主模型和 Agent，手动 `@Workflow` 或主模型误派发 Workflow 会提示去 Agent Studio 的 Workflow Studio / Runs 执行；Workflow 的设计、保存、保存并运行和 Runs 手动运行仍保持可用，且保存更新后立即运行会使用最新画布节点/连线，不会跑到旧版本；Bridge route 层也覆盖 create/update/run 这条用户实际点击路径。
- ✅ 2026-06-05 追加：Chat 里直接触发的 Workflow 总结消息和 Workflow 子 Agent 消息都会带真实产物数量与 artifact 摘要 metadata；有产物时气泡正文也会提示“产物 N 个，见运行详情”，让 Workflow 完成后的交付物入口和普通 Agent Run 保持一致。
- ✅ Workflow Studio 的 Agent palette、节点设置区和 Runs 手动运行目标选择已补能力摘要：会展示 Agent/Workflow 的类别、交付契约和职责说明，Runs 的目标下拉选项本身也带能力摘要，用户设计流程、维护节点或手动选择运行目标时能判断该把任务交给谁，而不是只看到名称。
- ✅ 2026-06-05 追加：Workflow Agent 节点支持配置 `Step Task`，运行时会把每个节点自己的任务说明与全局 Workflow Goal 合并后交给对应子 Agent；没有 Step Task 的节点保持旧行为，上游结果仍只进入 `Upstream Context`，避免上下文重复膨胀。运行快照和 timeline 会记录节点任务，Run Detail 的 Workflow Steps 也会显示该 Step Task，用户可以复盘每个 Agent 原本被要求做什么。
- ✅ 2026-06-05 追加：Workflow Approval 节点支持配置 `Approval Criteria`，运行到人工审批时会把审批说明写入 pending approval、timeline 和运行快照；审批卡会把“审批节点 / 审批说明 / 当前上下文”分层展示，Run Detail 的 Workflow Steps 也会保留该说明，让用户知道自己到底在批准什么，而不是只看到一个泛泛的确认按钮。
- ✅ 2026-06-05 追加：Workflow 的内置 seed 和 Agent Studio “全线测试模板”会预填每个 Agent 的 Step Task、网页点子模板的审批 Criteria，以及 Phase 4 模板的默认 artifact 路径；前端模板只会选择启用 Agent，用户新建模板时能直接看到每个节点要做什么，默认 seed 的回归也确认 6 个子 Agent 收到各自任务而不是同一个裸目标。
- ✅ 2026-06-05 追加：Workflow Studio 的 Workflow Run 区域会按当前画布显示运行顺序预览，Runs 面板手动选择 Workflow 时也会显示保存后流程的同款预览；预览列出将要执行的 Agent / Approval / Artifact 步骤、Step Task、审批说明和预计 artifact 路径，并和保存/校验请求复用同一套节点/连线组装逻辑，减少“画布看到的”“Runs 入口看到的”和“实际保存运行的”不一致。
- ✅ Workflow / Runs 的能力摘要会标出停用 Agent，Workflow palette 中停用项保持不可点击且有明确 disabled 视觉状态；Runs 手动运行下拉也会禁用停用目标，运行按钮会在目标停用时禁用并提示原因；已有节点绑定到停用 Agent 时，节点设置预览也能看见状态，便于解释为什么校验/运行会被拦截。
- ✅ Agent Studio 编辑页会直接展示当前 Agent 的运行前状态：缺 Chat Profile / Custom API 配置不完整、挂载停用 Skill、`workspace.write_patch` / `terminal.run` 会进入审批、写入 scope 为空等都会在 Capabilities 下提示；Quick Run 也会在模型配置不可用时提前禁用，减少用户把权限或配置问题误判成 Workflow 链路故障。
- ✅ 2026-06-05 追加：Runs 手动选择单个 Agent 时也会复用 Agent readiness 提示；后端会在创建 Agent Run 前拦截 Custom API 缺字段、停用 Skill、停用 Agent 等确定的本地配置错误，但保留旧 Profile 缺失 Agent 创建失败 Run 的兼容留档语义。
- ✅ Agent / Workflow 的近场运行入口也补齐防误触：Agent Quick Run 会在 Agent 停用、已挂载 Skill 停用、目标为空时禁用并给出可见原因；Workflow 保存并运行会在 Workflow 停用、校验错误或目标为空时禁用并提示原因，和 Runs 手动运行入口保持一致。
- ✅ Runs 手动运行入口也会对选中的 Workflow 复用 Workflow Studio 校验：旧数据或导入数据里若存在断链、缺失 Agent、停用 Agent、未知节点等问题，会在目标预览下提前显示原因并禁用运行按钮，而不是等后端创建 Run 时才报错。
- ✅ 2026-06-05 追加：Runs 手动运行选择 Workflow 时，如果校验错误不止一条，目标预览下会直接列出完整错误清单；按钮 title 仍保留首条短原因，方便用户一眼知道为什么不能运行、需要同时修哪些节点。
- ✅ Agent Studio / Workflow Studio / Runs 不再默认选择第一个 Agent / Workflow / Run；Workflow 新草稿保持空选择，节点设置支持 Agent / Approval / Artifact 配置，前后端都会校验线性流程、缺失/停用 Agent、未知节点、环和断链。
- ✅ Workflow Artifact 节点支持配置产物路径：用户可以在节点设置里指定 `reports/summary.md` 这类相对路径；留空时继续按 Label 自动生成，重复路径会自动去重为 `name-2.md`；Run Detail 的尚未执行步骤也会提前显示预计写出路径，前后端都会拦截越界路径。
- ✅ 2026-06-06 追加：Workflow Studio 前端 Artifact Path 校验和节点设置会同时读取 `artifact_path` / `artifactPath`，与后端运行校验保持一致；导入或旧数据使用 camelCase 时不会出现前端放行、后端运行才拒绝的错位。
- ✅ Workflow Studio 的保存与保存并运行会在硬校验错误时禁用，并把第一个错误放到按钮 title；2026-06-06 追加：Workflow 名称为空会进入同一个“需要修复”校验框，保存请求会 trim 名称，后端 update 也会 trim 并继续拒绝空名；只有 Start 节点这类低价值但可保存的状态仍作为 warning 提醒，避免用户在明显无效的 Workflow 上误点保存/运行。
- ✅ 2026-06-05 追加：Workflow 后端节点类型解析已和 ReactFlow 画布形态对齐；当节点 `type` 是 `input/default/output`、真实业务类型在 `data.kind` 时，Bridge 保存与运行仍会按 Start / Agent / Artifact 正确执行，避免导入画布或未清洗节点数据被误判为未知节点类型。
- ✅ 2026-06-06 追加：Workflow Studio 前端节点类型解析也与后端 `_node_kind` 对齐，会读取 `data.kind/node_type` 并只在 ReactFlow `input/default/output` 承载业务 kind 时转换；缺少业务 kind 的坏节点会明确报未知类型，运行预览也显示 Unknown，不再被前端误当成 Agent。
- ✅ 2026-06-06 追加：Workflow Run Detail 的 timeline 失败节点和运行快照也会保留 Unknown 节点类型，节点摘要会提示检查 Workflow 定义或导入数据，并用风险态视觉区分；不会把坏节点兜底显示成 Agent，减少排查误导。
- ✅ 2026-06-05 追加：Start-only Workflow 仍可作为草稿保存，但所有运行入口都会要求至少存在一个可执行节点（Agent、Approval 或 Artifact）；前端 warning 也会说明“可保存草稿、运行前需添加可执行节点”，后端 `create_workflow_run` 和 Bridge `/ui/workflow-runs` route 同步硬拦截，避免空流程直接 completed 造成“已运行但什么也没做”的假阳性。
- ✅ 2026-06-05 追加：Workflow 运行前会预检节点 Agent 的可运行性：缺 Chat Profile、默认 Chat Profile 不可用、Profile 不可用、Custom API 配置不完整、挂载 Skill 停用等确定失败会在创建 Run 前拦截；Workflow 节点设置预览和 Runs 目标预览也会显示同样原因，减少用户运行后才在详情页看到失败。
- ✅ 2026-06-05 追加：Workflow Studio 的“保存并运行 Workflow”禁用原因会在运行区直接显示，空 Goal、校验错误、缺可执行节点或 Agent 不可运行时不再只依赖按钮 title/hover 才能发现原因。
- ✅ 2026-06-05 追加：Chat 中手动 `@Workflow` 被引导到 Studio 时，引导消息会提供“打开 Workflow Studio”动作按钮，让 Workflow 触发边界更清晰：群聊协作继续走主模型/Agent，复用流程从 Workflow Studio / Runs 进入。
- ✅ Run Detail 已重做为任务、结果、Workflow Steps、Execution Timeline、Artifacts 的层级视图；History 可按 Agent / Workflow 分组、折叠，按完成、失败、进行中筛选，并能搜索目标、结果、Agent 名称、Run ID、timeline 与 artifact 线索，长任务和模型响应不再省略关键细节；Execution Timeline 的工具调用事件会同时展示脱敏后的请求内容和执行结果，用户能看到 Agent 具体读/写/运行了什么；主 History 只展示 Workflow 根 Run 与独立 Agent Run，Workflow 内部 child Agent Run 会从主列表隐藏，即使该 Workflow 是通过 delegation/统一委派入口创建，也不会把内部步骤刷进 Agent 历史卡片；Bridge artifact route 已覆盖从父 Workflow Run 的 artifact 列表打开 child Agent artifact，会按 `source_run_id` 读取真实子 Run 产物，避免详情页有按钮但点开 404。
- ✅ 2026-06-05 追加：父 Workflow 聚合子 Agent 产物时会跳过 `context` artifact，只保留真实交付物引用；Run Detail、聊天气泡和主模型汇总里的产物数量不会再把运行上下文当成交付物；2026-06-06 追加：Workflow Steps 里每个子 Agent 的 compact artifact 按钮也会过滤 `context`，保留真实交付物，完整上下文仍可从子 Run 详情查看。
- ✅ 2026-06-05 追加：Workflow Run Detail 会在对应 Workflow 定义仍存在时提供“打开 Workflow Studio”入口，用户从完成/失败/待审批 Run 看完步骤后可以直接回设计画布调整；Run History 分组和组内条目都会按更新时间稳定倒序，刚完成或刚失败的 Run 不会因为后端返回顺序藏到旧记录后面。
- ✅ 2026-06-05 追加：Run Detail 不再保留任何“刷新后自动选中第一个 Run”的路径，空详情会要求用户明确选择历史或创建新 Run；完成/失败/取消后的详情页新增“准备重跑”和“重新运行”，前者把原目标和任务填回 Runs 面板便于修改，后者会复用当前 Agent Studio 的 Agent/Workflow 可运行性、权限和校验结果直接创建新 Run。
- ✅ 2026-06-05 追加：Runs History 的状态筛选在窄宽度下改为稳定四列布局，分组 hover/选中态保留横向 padding，避免按钮被挤变形或 hover 紧贴边缘。
- ✅ 2026-06-05 追加：Runs History 搜索会把 Agent / Workflow 的名称、昵称、类别、描述、交付契约和启停状态一起纳入索引；旧 Run 即使缺少 `runnable_name`，也能按 Agent 能力线索查到对应历史。
- ✅ 2026-06-05 追加：Run Detail 的 Workflow Steps、Execution 和 Artifacts 区块支持折叠；长节点结果、模型响应和工具 payload 默认收起为可读摘要，展开后显示完整内容且不截断，失败和待审批内容会默认展开，方便用户先扫状态再钻取细节。
- ✅ Workflow 子 Agent 审批桥已闭环：父 Workflow 会显示正在等待哪个 child run 的工具审批，可在父详情页批准/拒绝；2026-06-06 追加：父详情页的子 Agent 审批桥会优先显示对应 Workflow 节点名，并展示 Step Task，用户在批准前能直接看到当前节点被要求做什么；审批恢复、拒绝、取消和父 Run 取消都会同步更新父子 Run、RunGroup 和步骤状态，避免留下孤儿审批；Run Detail 批准后会按返回状态提示“继续执行 / 需要下一次审批 / 已完成 / 已失败”，不再只显示泛泛的 action 完成；Bridge 审批批准 route 已覆盖暂停后编辑 Workflow 的场景，会继续原 Run 的运行时快照，不会把新画布混进旧 Run；Bridge 取消 route 已覆盖父 Workflow 等待子 Agent 工具审批时的取消路径，会同步取消 child Run 并清空 pending approval。
- ✅ Run Detail 的待审批区域也改为结构化请求视图：工具名、Run、关联任务、审批节点/路径/工作目录分层展示，`terminal.run` 请求内容按 bash 代码块呈现；父 Workflow 等待子 Agent 审批和普通 Agent / Workflow 审批共用同一套可读结构。
- ✅ Chat 里的 Workflow 失败/取消终态也会读取 timeline 节点信息：如果后端已记录 `workflow_node_label/kind`，气泡正文会直接显示“失败节点 / 取消节点”，用户不必先打开 Run Detail 才知道该查哪个步骤。
- ✅ 进行中或待审批 Run 在详情页会轻量轮询并显示“实时更新”，顶部提供带确认弹窗的 `Cancel Run`，取消后刷新详情缓存；后端会把 Workflow 自身审批和等待子 Agent 审批两种状态都清理到终态。
- ✅ Agent 工具误用更可恢复：`workspace.read` 读目录、`workspace.list` 列文件或路径不存在时会返回 `ok:false`、明确 hint 和建议工具，让模型有机会自我修正；如果工具循环仍超过上限，失败摘要会带上最后一次工具、错误/退出码和建议，越界和未授权仍保持硬拦截，避免用户把可纠正输入错误误判成权限没挂上。
- ✅ 2026-06-05 追加：Agent Runtime 会尊重用户目标里的显式限制：如果用户说“不需要创建/保存/修改文件”“只展示代码”或英文同义表达，模型误申请 `workspace.write_patch` / `artifact.write` 会被转成可恢复 tool result，引导它 inline 交付而不是弹审批；如果用户说不运行/不执行命令，误申请 `terminal.run` 也会被同样拦截。中文“代码完整展示即可”和 Workflow 子 Agent “不需要运行命令或脚本”已覆盖回归；空工具策略仍不会在 system prompt 暴露具体工具名。
- ✅ 2026-06-05 追加：普通主会话的 Yachiyo 自动委派解析也补齐容错：可识别 `<yachiyo_delegation>`、智能引号、`type/kind=agent/workflow`、`agentName/userGoal/objective/runnableId` 等字段变体，并会扫描长回复里的多个 JSON 对象，找到第一个有效委派请求；群组协调任务仍会禁用这条自动委派路径，交给群组派发协议处理。
- ✅ 2026-06-05 追加：普通主会话自动委派的子 Run 如果进入 `approval_required`，父链路不再把它当失败活动展示；`pending_approval` 会随委派结果写回主模型后续上下文，activity 事件也会记录 `run_id/run_status/pending_approval`，Chat 活动行可在有 Run ID 时直接打开 Run Detail，并用独立待审批样式提示用户；输入框上方的待审批提醒队列也会合并消息审批和 activity 审批，批准/拒绝成功后会本地抑制刚处理过的 composer approval item，避免旧 activity 审批继续浮在输入区；activity 来源审批后的 delegated Run 到达 completed/failed/cancelled 后，Chat 会创建一条主模型整理任务，把原用户请求、主模型委派上下文、Run 结果和产物摘要交回主模型收尾，避免用户批准后只看到子 Run 结束但对话没有汇总。
- ✅ 2026-06-05 追加：activity 来源审批触发主模型整理任务时，前端会把新 task 注册为“等待回复”并保持消息列表跟随到底部，用户批准后能自然看到主模型收尾气泡出现，而不是只靠状态栏猜测后台在整理。
- ✅ 2026-06-06 追加：activity 来源审批如果批准后 Run 先回到 `processing`，前端后台轮询到 completed/failed/cancelled 时也会继续创建 delegated Run 主模型整理任务；不再只覆盖“批准接口立刻返回终态”的情况。
- ✅ 2026-06-05 追加：输入框上方待审批 item 已改为“消息/活动 + 当前审批签名”维度，本地 suppression 不再误伤同一 Run 后续审批；审批 action 或后台轮询拿到新的 `pending_approval` 时，会用 Run 当前工具和参数覆盖旧 activity 详情，连续审批时用户能看到下一次到底要批准什么。
- ✅ 2026-06-05 追加验证：`HERMES_HOME=/private/tmp/hermes-yachiyo-pytest .venv/bin/python -m pytest tests/test_chat_api.py` → 112 passed；`git diff --check` → clean。
- ✅ 2026-06-05 追加验证：`HERMES_HOME=/private/tmp/hermes-yachiyo-pytest .venv/bin/python -m pytest tests/test_agent_runtime.py` → 76 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。
- ✅ 2026-06-05 追加验证：`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。
- ✅ 2026-06-06 追加验证：`pytest tests/test_chat_api.py` → 119 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_chat_api.py tests/test_agent_runtime.py tests/test_executor.py tests/test_ui_bridge_routes.py -q` → 308 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean；in-app Browser smoke 覆盖 Chat、群组设置、Runs、Workflow Studio、Workflow palette、Workflow 节点设置 Agent 预览、硬错误禁用保存/运行、Runs 不默认选择目标、Agent Quick Run / Workflow Run 空目标禁用、Run Detail 取消确认，以及 Chat 输入区草稿发送按钮可用性，console error 为空。2026-06-05 本轮追加验证再次跑过 `.venv/bin/python -m pytest tests/test_chat_api.py tests/test_agent_runtime.py tests/test_executor.py tests/test_ui_bridge_routes.py -q` → 315 passed；最新 `npm --prefix apps/frontend run build` → passed；重新拉起 Vite 后用 in-app Browser 复查当前 Chat 群聊样本：派发 JSON 未外露、Agent 终态和主模型汇总可见、Run Detail 可从聊天进入、Run History 按 Agent 分组且不默认选中 run、Run Detail 任务/结果/Timeline/Artifacts 完整显示、Workflow Studio 新草稿和 palette 正常、群组设置可打开/关闭且头像上传入口无 URL 栏、会话 ID 弹窗显示可手动选择的只读 ID，console error 为空；2026-06-05 自动委派审批可见性追加验证：`.venv/bin/python -m pytest tests/test_executor.py tests/test_chat_api.py` → 218 passed，`HERMES_HOME=/private/tmp/hermes-yachiyo-pytest .venv/bin/python -m pytest` → 751 passed、1 warning，`npm --prefix apps/frontend run build` → passed，in-app Browser 复查当前 Chat 页无 console error、已有 activity row 正常渲染；输入区 activity 审批队列追加验证：`npm --prefix apps/frontend run build` → passed，in-app Browser 硬刷新当前 Chat 页正常挂载且无新错误 overlay；自动委派审批后主模型整理追加验证：`.venv/bin/python -m pytest tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_executor.py` → 244 passed，`HERMES_HOME=/private/tmp/hermes-yachiyo-pytest .venv/bin/python -m pytest` → 753 passed、1 warning，`npm --prefix apps/frontend run build` → passed，in-app Browser 复查当前 Chat 页正常挂载、输入框和会话列表可见、console error 为空，最新 `git diff --check` → clean；2026-06-05 当前 HEAD 追加验证：`HERMES_HOME=/private/tmp/hermes-yachiyo-pytest .venv/bin/python -m pytest tests/test_chat_api.py tests/test_agent_runtime.py tests/test_executor.py tests/test_ui_bridge_routes.py` → 319 passed，`npm --prefix apps/frontend run build` → passed；本轮 Browser 连接受客户端 `ERR_BLOCKED_BY_CLIENT` 拦截，未作为通过证据。

### Milestone 95 — Chat 群组流式、汇总与审批体验收口

- ✅ 群组里 AgentRun 的 processing 气泡恢复为主模型同款三点 loading；不再先插入“已接收任务”文案造成信息噪音。
- ✅ 主模型流式输出中出现派发 JSON 时，Chat 层会隐藏内部协议但保留主模型已经输出的自然语言，不再把气泡内容清空回三点 loading 后又恢复。
- ✅ 主模型派发的 Agent 完成 / 失败 / 取消后，不再把完整结果各自直接散落给用户；Agent 气泡只显示“已交给主模型汇总”等状态，详细 `agent_report` 写入 metadata。
- ✅ 所有由主模型派发的 Agent 都进入同一个汇总链路：等本轮被派发 Agent 都到终态后，Chat 层自动创建主模型汇总任务，让主模型基于 Agent 汇报再流式回复用户。
- ✅ 直接 `@Agent` 的场景仍保留 Agent 自己回复；只有主模型派发出去的 Agent 结果会回到主模型统一汇报。
- ✅ 审批体验补强：Agent 待审批气泡继续显示工具名、关联任务和输入摘要；批准后会同步 AgentRun 结果并触发主模型汇总任务，前端状态会显示“等待主模型汇总”，不再看起来像批准后没结果。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_chat_store.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 109 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean；源码 Bridge 已重启并确认 `/chat` 页面可连接。

### Milestone 94 — Chat 群组派活体验收口

- ✅ Chat 新建入口收敛到会话列表 tab 右侧 `+`：Agent tab 创建一对一对话，群组 tab 创建手动群组；右上角重复新建按钮已移除。
- ✅ 新对话默认是空对话页，用户 `@Agent` 才会进入对应 Agent；没有 `@` 时仍交给主模型。
- ✅ Agent / 群组标题和删除确认文案已按当前会话类型区分；Agent 标题会忽略开头 mention，群组删除不再显示“删除此对话”。
- ✅ 手动群组创建后会持久存在，即使没有消息也不会因切换会话消失；未填写名称时默认用主模型和所有选中 Agent 的 nickname 以 `、` 拼接。
- ✅ 群组成员计数包含主模型，主模型在群组内会收到当前群组成员清单，可正确理解“群里的其他 Agent”。
- ✅ mention 菜单改成 QQ 式候选体验，支持键盘上下选择；消息输入区和消息正文中的 mention 都有 token 样式。
- ✅ 群组主模型派活改为内部 `dispatch_group_agent` 协议：Chat 层隐藏 JSON、记录派发 activity、创建具体 AgentRun，并在最终主模型气泡中保留自然说明和派发摘要。
- ✅ 单个被派发 Agent 失败时，重试只重跑该 Agent 的原始 delegated goal，不会重新触发主模型规划整轮群组任务。
- ✅ AgentRun 在聊天中等待审批时保持 processing，消息会说明哪个 Agent 需要审批、准备调用哪个工具、输入摘要是什么，并提供批准 / 拒绝按钮。
- ✅ 验证：`pytest tests/test_chat_store.py tests/test_chat_api.py -q` → 80 passed；`pytest tests/test_executor.py::TestHermesExecutor::test_call_hermes_group_mode_returns_dispatch_for_chat_layer -q` → 1 passed；`npm --prefix apps/frontend run build` → passed。

### Milestone 93 — Chat Agent / Workflow 会话模式

- ✅ Chat 会话存储新增 Agent / Workflow 上下文字段，消息存储新增 `metadata_json`，可持久化 sender、Run、RunGroup 和群组 participants。
- ✅ `@Agent` 会创建 AgentRun，并把会话绑定为 Agent 私聊；后续不写 `@` 的普通文本会继续交给该 Agent，不再创建普通 Hermes task。
- ✅ `@Workflow` 会创建 WorkflowRun / RunGroup，并把每个子 Agent 的结果按顺序写入聊天消息；消息 metadata 标明具体 Agent sender，最后追加 Workflow 完成状态。
- ✅ Workflow 群组内继续 `@某Agent` 会复用当前 Workflow `run_group_id`，把人工插手结果追加回同一个群组；不指定 Agent / Workflow 时仍交给主模型处理。
- ✅ React Chat 会话列表、标题栏和消息气泡已接入新上下文：Agent 私聊显示 Agent 头像/名称，Workflow 群组显示 participants 堆叠头像，消息气泡显示具体发言者。
- ✅ Composer 已移除 Agent / Workflow 下拉框；键入 `@` 会展示主模型、Agent 和 Workflow mention 菜单，选择带空格名称会插入 quoted mention，并显示 token 芯片。消息正文中的 mention 也有独立视觉样式。
- ✅ Workflow Studio 增加 Agent 快捷面板，可从已有 Agents 直接添加节点并自动接入 ReactFlow 线性链路；画布仍支持拖拽、连线、节点设置、保存和运行。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_chat_api.py tests/test_chat_store.py tests/test_chat_session.py tests/test_agent_runtime.py tests/test_ui_bridge_routes.py -q` → 157 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean；Browser 使用只读 fixture 验证 Chat 与 Workflow Studio：旧下拉框数量为 0，`@` 菜单和 quoted Workflow 芯片可见，Workflow 群组展示 3 个具体 Agent sender，画布从 `4 nodes / 3 edges` 添加 Agent 后变为 `5 nodes / 4 edges`，窄屏 Chat 与 Studio 无横向溢出，console error 为空。

### Milestone 92 — Runs 顶层历史与 Workflow 步骤产物

- ✅ 按真实用户流程重新创建 demo Skills、Design / Coding / Review Agents 和线性 Workflow，并用已配置默认 Chat Profile 跑通真实 Workflow：`workflow_run_8254dd42d09c` completed，三个子 Agent 分别产出 `DESIGN_DEMO_OK`、`CODING_DEMO_OK`、`REVIEW_DEMO_OK`。
- ✅ 修复真实多 Agent 串联暴露的问题：OpenAI-compatible chat 读取超时从 20 秒改为 60 秒常量；Workflow 后续 Agent 的 `user_goal` 保持原始目标，上一节点结果只进入 `Upstream Context`，避免上下文重复膨胀。
- ✅ Runs 列表语义改为顶层历史：Workflow 子 Agent Run 不再出现在主列表或 Agents 分类里；`Workflows` 只展示 Workflow root run，`Agents` 只展示用户单独运行 Agent 的 run。
- ✅ Workflow Run 详情新增 `Final Result` 与 `Workflow Steps`，按顺序展示每个子 Agent 的状态、输出、artifact 入口和 Open Run 入口；中间产物不再只能从 timeline 手动跳转查找。
- ✅ 已确认下一阶段产品方向：Agent / Workflow 需要从文本 demo 走向真实产物契约，Design Agent 产出原型或 Markdown，Coding Agent 产出代码或 patch，Review Agent 产出 Markdown review；Runs 要成为所有入口触发任务的统一产物查看面板。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_model_profiles.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 131 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。

### Milestone 91 — 真实模型 E2E 与 Workflow 缺陷收口

- ✅ 使用已配置默认 Chat Profile（`xiaomi_mimo/mimo-v2-pro`）完成真实 E2E：导入本地 Skill、挂载到 Agent、直接运行 Agent、API 运行 Workflow、Runs 页面触发 Workflow，均能创建真实 Run / 子 Run 并得到模型结果。
- ✅ Agent Runtime 现在尊重显式空工具集；`tool_policy.allowed_tools: []` 不再被强行补成 `artifact.write`，真实回归中两个子 Agent 的 compiled `allowed_tools` 均为 `[]`。
- ✅ Agent 模型调用改为 system message 承载运行时规则，明确精确输出要求优先；真实回归中 Skill Agent 能稳定返回 `HY_REAL_AGENT_OK HY_REAL_SKILL_MARKER_20260527`。
- ✅ Workflow 在子 Agent 初次执行失败或取消时会立即让父 Workflow fail/cancel，不再把失败结果当作正常上下文继续传递；取消子 Run 也会同步唤醒等待中的父 Workflow。
- ✅ Runs 详情 timeline 增加 child run 跳转按钮和节点状态；Workflow Studio 的 React Flow MiniMap / Controls / attribution 白底样式已统一到暗色主题。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 107 passed；`npm --prefix apps/frontend run build` → passed；`git diff --check` → clean。

### Milestone 90 — Workflow 子 Run 审批恢复

- ✅ Workflow 子 Agent Run 进入 `approval_required` 后，父 Workflow Run 会保持暂停并记录对应 `child_run_id`。
- ✅ 审批通过子 Agent Run 后，Agent Runtime 会找到同一 RunGroup 中等待该子 Run 的父 Workflow，从暂停节点之后继续执行后续 Agent / Approval / Artifact 节点。
- ✅ 子 Agent 审批后再次请求高风险工具时，父 Workflow 会继续停在 `approval_required`；子 Agent 审批后失败或被拒绝时，父 Workflow 会同步失败或取消。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py::test_workflow_resumes_after_child_agent_approval -q` → 1 passed；`.venv/bin/python -m pytest tests/test_agent_runtime.py -q` → 39 passed。

### Milestone 89 — Workflow Studio 基础补强

- ✅ Workflow seed 逻辑修正：默认 Workflow 会独立补种，已有 Agent 的数据库也能获得缺失的默认 Workflow。
- ✅ 新增 `Phase 4 Agent 全线流通测试` 默认 Workflow，线性调用 Orchestrator、Research、Design、Coding、Review、Office，并把最终上下文写入 Flow Summary artifact。
- ✅ 默认 Agent / `follow_main` Agent 可跟随默认 Chat Profile；旧数据中的默认 Agent 即使未显式绑定 `model_profile_id`，也能参与 Workflow Run。
- ✅ Workflow Studio 增加“全线测试模板”按钮，按当前默认 Agent 自动生成节点与边；手动新增 Agent / Approval / Artifact 节点会自动接到当前线性链末端。
- ✅ 节点设置区显示 node/edge 数量，Agent 节点可选择具体 Agent 或移除；移除中间节点时会自动桥接前后节点。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py -q` → 37 passed；`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 103 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed。

### Milestone 88 — Skill Folder / Collection

- ✅ 新增一层 Skill Folder 元数据层：`skill_folders` 表保存文件夹名称、说明、来源范围与排序；`skills.folder_id` 保存归属，默认显示为“无需分组”。
- ✅ Skill Folder 只作为管理和筛选维度，不移动 Hermes Agent 原路径，也不强制改动 Yachiyo 已导入 Skill 的本地快照路径。
- ✅ Skill Groups 独立成 Agent Studio 页面，负责文件夹新建、重命名、查看与删除；Skill Library 左侧只保留安装/上传时的目标文件夹选择。
- ✅ 删除文件夹会把 Skill 归回“无需分组”。
- ✅ Skill Library 卡片支持移动 Skill 到其他文件夹；Agent Mounted Skills 增加文件夹筛选，便于按 Laravel / Design 等主题为 Agent 挑选 Skill。
- ✅ Agent Mounted Skills 支持对当前筛选结果一键全选/清空；安装完成后不再显示 stdout/stderr 结果框，只保留同步结果提示。
- ✅ 修复 Agent Studio stale state：开发态 HMR 或临时刷新导致左侧 Agent 列表为空但右侧仍有 draft 时，会自动重新拉取 Agent 列表；`list_agents` 增加 row factory 回归覆盖，避免连接状态漂移后 `/ui/agents` 列表转换崩溃。
- ✅ Skill Groups 后续 TODO 已收口：`#/agents/skill-groups` 可直达，保留旧 `#/agents/<run_id>` Run 详情链接兼容；从 Skill Groups 点击“查看”会进入 Skill Library 并保留对应文件夹筛选。
- ✅ Skill Folder 创建/重命名新增前后端名称校验：拒绝空名、重复名和超过 120 字符的名称；删除文件夹前会确认并说明 Skill 会回到“无需分组”。
- ✅ “无需分组”现在拆分显示总数、Yachiyo 与 Hermes 计数，避免 Hermes 自带 Skills 让默认组看起来异常庞大。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 97 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed；浏览器打开 `http://127.0.0.1:5174/#/agents/skill-groups` 确认 Skill Groups 直达、Skill Library tab 跳转和 console error 为空。
- ✅ 最新实现提交：`bb4436b feat(agent): finish skill groups todo`。

### Milestone 87 — Yachiyo / Hermes 双 Skill 库与受限安装入口

- ✅ Skill Library 分成 Yachiyo 管理区与 Hermes Agent 管理区：Yachiyo 上传/安装的 Skill 留在 Yachiyo 工作区，Hermes Agent 自带全局 Skill 只登记 `~/.hermes/skills` 原路径引用，不复制到 Yachiyo 目录；项目级 `.hermes/skills` 暂不纳入本页管理。
- ✅ Skill 数据新增 `source_type`、`origin_path`、`source_ref`、`content_hash`、`last_synced_at`、`sync_status`；同步按 Yachiyo / Hermes 大类隔离去重，hash 变化会更新同一大类内已有 Skill。
- ✅ Skill Library 与 Agent Mounted Skills 都增加 Yachiyo / Hermes Agent 来源筛选和搜索，默认显示 Yachiyo，避免 Hermes 自带大量 Skill 挤占管理视图。
- ✅ 新增受限安装入口：支持直接输入 Skill 来源、`skills@latest add ...`、`npx skills add ...` / `npx -y skills@latest add ...` / `hermes skills install ...`，拒绝 shell 管道、串联和重定向；`skills` CLI 路径会固定使用 `hermes-agent`、补齐 `--copy -y`，在 Yachiyo 的 Skill 安装工作区执行并同步为 Yachiyo Skill。
- ✅ Skill 安装 UI 改成来源/安装命令输入，安装中显示不确定进度条并保留 stdout/stderr 尾部日志；不伪造 CLI 未提供的百分比进度。
- ✅ Agent 列表层级颜色、头像选择控件和 Skill 上传区域已按最新 UI 反馈调整：不再显示 avatar URL，不再显示手动导入路径 textarea。
- ✅ 验证：`.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q` → 92 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed。

### Milestone 86 — Agent Profile 与本地 Skill Library

- ✅ Agent 定义新增 `nickname`、`avatar_url` 与 `persona_prompt`；昵称和头像用于 Agent Studio 展示，也为后续对话框内直接和某个 Agent 聊天预留数据。
- ✅ `instructions` 明确作为功能 prompt，`persona_prompt` 单独作为人设/口吻/角色偏好 prompt；Agent context artifact 会分段写入 `# Functional Instructions` 与 `# Persona Prompt`。
- ✅ Agent Studio 编辑页新增头像预览、昵称输入、头像选择按钮和 Persona Prompt 输入框；头像选择沿用 Electron 图片选择器，保存为可直接渲染的 data URL。
- ✅ Skill Library 改成上传/导入体验：支持选择多个本地 Skill 目录或 ZIP，支持拖放/粘贴路径，导入后逐条显示成功、失败或跳过结果。
- ✅ Skill 数据新增 `local_path` 与 `enabled`；Skill 卡片展示本地路径、启停开关、删除和打开本地路径入口，不再提供下载。
- ✅ Agent 的 Mounted Skills 只从已启用 Skill Library 中选择；后端同时阻止挂载停用 Skill，并在运行前拒绝已挂载但已停用的 Skill。
- ✅ Agent Studio 补充 Output Contract、Capabilities、Default Workdir、Readable Scopes、Writable Scopes 的解释文案，并提示用“测试模型 + Quick Run”进行可行性验证。
- ✅ 验证：`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_model_profiles.py -q` → 107 passed；`npm --prefix apps/frontend run build` passed；`git diff --check` passed；Computer Use 冒烟确认 Agent 表单、Skill Library 导入、Skill 卡片和 Mounted Skills 显示正常。

### Milestone 85 — ToolBroker 真实执行层与审批恢复

- ✅ Agent Runtime 新增统一 tool-call 循环：优先解析 OpenAI-compatible `message.tool_calls`，并保留 JSON fallback `{"action":"tool","tool":"workspace.list","input":{...}}`。
- ✅ OpenAI tool schema 使用函数名别名，后端映射回 dotted 工具名：`workspace_list`、`workspace_read`、`workspace_write_patch`、`terminal_run`、`artifact_write`。
- ✅ Tool loop 上限为 6 次；超限后 Run 失败。
- ✅ 非授权工具会失败并记录 `agent.tool.denied` timeline，不执行模型 payload。
- ✅ `workspace.list`、`workspace.read`、`artifact.write` 可直接执行；`terminal.run` 和 `workspace.write_patch` 永远不会因为模型 payload 自带 `approved=true` 而执行。
- ✅ 新增 Run 状态 `approval_required` 和 `pending_approval_json`；遇到高风险工具时 Run 与 RunGroup 同步停在 `approval_required`。
- ✅ `pending_approval` 对前端只暴露脱敏/截断后的展示信息；原始 tool input 只保留在后端用于审批后继续执行。
- ✅ 新增 `POST /ui/runs/{run_id}/approval/approve` 与 `POST /ui/runs/{run_id}/approval/reject`；approve 后执行 pending tool 并继续同一个 Run，reject 后 Run 变为 `cancelled`。
- ✅ Runs 详情页在 `approval_required` 时显示待审批工具、脱敏输入和 Approve / Reject。
- ✅ `openai_compatible_chat` 保持原文本返回行为，并新增完整 chat completion message helper 供 Agent Runtime 读取 `tool_calls`。
- ✅ 验证：真实 Electron + fake OpenAI-compatible server 冒烟，`terminal.run` 进入审批，UI Approve 后执行并回填 stdout，Run 最终 completed。

### Milestone 84 — Agent Studio 持久岗位 Runtime

- ✅ Agent Studio 设计收敛为“主 Agent + 持久自定义 Agent”：Hermes/Yachiyo 主助手继续负责总调度，Agent Studio 只管理长期登记的岗位 Agent 与 Workflow。
- ✅ 前端移除 `Execution Backend` 选择体验：用户现在配置岗位名称、职责、instructions、模型 Profile、Skills、工作区范围、能力开关和输出格式，不再看到 `Hermes Runtime` / `External CLI` 后端选项。
- ✅ 后端保留旧 `execution_backend` 字段兼容，但 `hermes_profile`、`external_cli`、空 backend 都归一为 `yachiyo_profile`；自定义 Agent 统一走 Yachiyo Agent Runtime。
- ✅ 删除 `external_cli` 执行路径；本地命令能力只能通过受控 `terminal.run` 工具授权进入，不能由 Agent prompt 绕过权限。
- ✅ Agent 保存/运行时会自动编译 runtime 配置：根据 category、instructions、Skills、workspace policy 和 output contract 生成运行 prompt、工具白名单、审批策略、workspace policy 与进度事件。
- ✅ 高风险工具默认需要审批：`terminal.run` 和 `workspace.write_patch` 会进入 `approval-required` 策略，不会直接执行。
- ✅ Agent Run 自动写入 context artifact，并记录 runtime 编译、artifact 写入、模型响应、工具调用、完成/失败等 timeline/progress 事件。
- ✅ Skill 运行前校验更严格：挂载 Skill 不存在时会在运行前报错，避免静默缺上下文。
- ✅ 主 Agent 新增 Yachiyo 委派桥：主会话上下文会注入已启用 Agent/Workflow 名录，可通过 `run_yachiyo_agent` / `run_yachiyo_workflow` 创建普通 Run，结果回填后继续整合最终回复。
- ✅ 委派安全边界已落地：未知目标、空目标、停用 Agent/Workflow 会拒绝；单轮自动委派最多 3 次，避免循环调用。
- ✅ 验证：`pytest` → 610 passed，1 warning；`npm run build`（`apps/frontend`）通过；`git diff --check` 通过；本地浏览器打开 Agent Studio 确认旧 backend 文案不可见，新 `Model` / `Capabilities` 配置可见。

### Milestone 83 — Agent Studio MVP 运行闭环

- ✅ Agent 编辑页新增 `Quick Run`：保存后的 Agent 可直接输入目标创建 Agent Run，完成后自动切到 Runs 详情。
- ✅ Workflow Studio 新增 `Workflow Run`：保存后的 Workflow 可直接输入目标创建 Workflow Run；新建未保存时按钮禁用并提示先保存。
- ✅ Skill 挂载反馈更清楚：Agent 编辑页显示 `mounted / skills` 计数；Skill Library 中已挂载 Skill 会显示 mounted 状态。
- ✅ Runs 详情整理为 MVP 查看面板：展示 runnable、goal、状态 pill、run kind、更新时间、RunGroup、run id、Result、Timeline 和 Artifacts。
- ✅ 无 Run 空状态已说明后续会展示 Result、Timeline 和 Artifacts，避免 Runs 页看起来像坏掉。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed；本地浏览器验证 Quick Run、Workflow Run、Skill 挂载计数和 Runs 空状态。

### Milestone 82 — Agent Studio Execution Backend 状态 UI

- ✅ Agent 编辑页的 `Execution Backend` 已从普通下拉改为三张能力状态卡片。
- ✅ `Hermes Runtime` 明确标注为实验能力：当前默认创建 RunGroup 与上下文，真实 Hermes CLI 执行需要显式后端开关。
- ✅ `Yachiyo Profile` 明确标注为可运行路径：依赖模型配置中已经测试通过的 chat Profile；无可用 Profile 时显示“需要 Profile”。
- ✅ `External CLI` 明确标注为占位能力：MVP 不暴露 command 输入，避免从 UI 提交任意 shell 命令。
- ✅ Backend 选择后的下方配置区按当前能力切换：Hermes 显示主模型管理入口，Yachiyo 显示 Chat Profile 选择器，External CLI 显示占位说明。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed；本地浏览器验证 backend 卡片切换、Yachiyo Profile 字段和 External CLI 无命令输入入口。

### Milestone 81 — Agent Studio 第一阶段稳定化

- ✅ Agent Studio 选择态已从数据刷新依赖中拆出：切换 Agent / Workflow 不再触发全页重新读取、`busy` notice 或表单闪烁。
- ✅ 修复“新建 Agent 闪一下无事发生”：新建现在会稳定进入空白 Agent 草稿，不会被初始化/刷新逻辑自动选回第一个内置模板。
- ✅ Agent 保存后显式保留刚保存的 Agent；删除后保留空白草稿，便于继续创建。
- ✅ Workflow 新建/保存/删除也使用显式选择状态，避免画布在非保存操作中被刷新重置。
- ✅ Run 创建后显式选中新 Run；通过 URL 进入的历史 Run ID 会继续保留并补取详情。
- ✅ 初始加载状态与操作状态拆分：只有首次读取显示加载提示，保存/删除/导入/运行等操作后再按需刷新列表。
- ✅ 阶段说明已补入 `docs/phase-4-hermes-sync-plan.md` 与 `docs/model-profile-runtime-notes.md`。
- ✅ 验证：`npm --prefix apps/frontend run build` passed；`python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_model_profiles.py` → 75 passed。

### Milestone 80 — 模型 Profile 统一化、Agent 执行后端与 TTS 入口整理

- ✅ Profile 已作为模型配置中心推进：模型配置页按 `对话`、`图片转述`、`文字转语音` 分离服务商源，测试通过后才进入对应场景选择列表。
- ✅ Hermes CLI 仍保留为主对话执行适配器；默认主模型只同步 Hermes 可执行的 `chat` Profile，避免把 OpenRouter 模型厂商误写成 Hermes provider。
- ✅ 新增 Hermes provider adapter 层：集中维护 provider id、API Key env、alias、Base URL host hint 和 OpenRouter 模型前缀边界，修复 Xiaomi MiMo / DeepSeek 等源同步到 Hermes config 的 provider mismatch。
- ✅ OpenRouter `/api/v1/models` 用于动态 OpenRouter 模型目录；本地仍维护各厂商源预设、Base URL、Hermes provider 映射和官方 icon。
- ✅ 新增 provider catalog 同步模块 `apps/shell/provider_catalog_sync.py`，可把主流 provider `/models` 元数据同步到本地缓存，为后续每日订阅更新打基础。
- ✅ Vision Profile 改为真实图片测试通过后才保存为 `available + vision`；远端 metadata 与本地已知能力表只作为“视觉/文本/未知”提示。
- ✅ Agent spec 增加 `execution_backend`，支持 `hermes_profile`、`yachiyo_profile`、`external_cli`；Agent run 增加 `run_group_id`，为 `@Agent`、Workflow 和后续自动编排统一运行组结构。
- ✅ 模型配置页交互修复：新增/返回列表会提示未保存变更；详情页有返回列表；保存按钮收敛为“保存并获取模型列表”和“测试连接并保存”；左侧状态会及时显示可用、失败、密钥配置和暂未选择模型。
- ✅ TTS tab 改为独立语音来源入口，补充 GSV TTS(Local)、HTTP TTS、Command TTS、OpenAI、MiMo、Edge、FishAudio、阿里云百炼、Azure、MiniMax、火山、Gemini 等预设。
- ✅ 侧栏原 `GPT-SoVITS` 改名为 `主动关怀`；该页定位为“主动关怀与桌面观察”，承载桌面观察、提醒触发、语音播报链路、音色资源与本地 GPT-SoVITS 服务。
- ✅ Provider icon 修正为厂商品牌图标，Hugging Face 已不再落到 OpenAI icon。
- ✅ 阶段说明已写入 `docs/model-profile-runtime-notes.md`，并在 `docs/phase-4-hermes-sync-plan.md` 记录 Batch 7。
- ✅ 验证：多轮 `npm --prefix apps/frontend run build` passed；模型配置页本地预览检查通过；相关后端迁移/Agent runtime/model profile/vision 测试在本轮变更中分批通过；最新文档同步仅涉及 Markdown。

### Milestone 79 — macOS 发布链路、应用更新器与安装体验收口

- ✅ macOS release workflow 现在覆盖 `main` 与 `develop` 两条渠道：`main` 生成正式版 stable DMG，`develop` 生成实验版 experimental prerelease DMG；滚动 release 分别维护 `main-latest` 与 `develop-latest`。
- ✅ 固定下载资产已统一：`Hermes-Yachiyo-main-latest.dmg`、`Hermes-Yachiyo-develop-latest.dmg`，并同步上传 `.sha256` 与 `.json` 元数据；latest JSON 包含 channel、branch、version、commit、build number、DMG 名称、SHA256、download URL 和 published time。
- ✅ CI 在构建前写入 `apps/frontend/public/hermes-yachiyo-build.json`，打包后的应用可知道自己所属渠道、当前版本、commit、build number 与对应 latest JSON URL。
- ✅ 免费分发签名策略已确认并落地：`.app` 自签名，`.dmg` 保持未签名；避免自签名 DMG 被 macOS 挂载前直接拒绝。首次启动仍需用户通过 Finder Control-click -> Open 或系统设置允许未知开发者应用。
- ✅ 新增 `scripts/create_macos_self_signed_cert.sh` 与 `scripts/build_macos_self_signed_dmg.sh`，支持本地生成自签名证书、导出 GitHub Secrets 辅助 env、签名 `.app` 并创建未签名 DMG。
- ✅ 打包版 Bridge 默认端口与开发环境拆开：开发默认 `8420`，打包默认 `18420`；打包版若发现 `18420` 已被占用，会临时分配空闲本地端口并传给内置 backend，避免误连本地 develop backend。
- ✅ 应用内更新器已接入通用设置页：按当前渠道检查对应 latest JSON，比较版本/build/commit，下载 DMG，校验 SHA256，退出当前应用后挂载 DMG、覆盖当前 `.app` 并重新打开。
- ✅ 更新器请求 latest JSON 时加 cache-busting query 与 `Cache-Control: no-cache` / `Pragma: no-cache`，避免 GitHub rolling asset/CDN 在 release 刚更新时返回旧 JSON，导致 `0.1.31` 误判为最新。
- ✅ 更新下载有实时进度：Electron main 通过 IPC 推送 `starting/downloading/verifying/completed/failed` 状态，设置页显示百分比或已下载大小；下载完成后按钮变为“安装并重启”。
- ✅ 已下载但未安装的更新会持久化到 Electron `userData/updates/downloaded-update.json`；重新进入设置页或重启后会自动识别本地 DMG 是否仍是当前渠道的更高版本，并直接提供“安装并重启”。
- ✅ release 更新日志已接入 git commit 同步：CI 以当前渠道上一条 `stable-v*` / `experimental-v*` tag 为基线生成 changelog，写入 GitHub release notes 与 latest JSON；应用内“应用更新”区会展示 latest JSON 中的更新内容和提交对比入口。
- ✅ 安装向导在更新后 backend/Bridge 尚未完全启动时，不再直接显示红色“无法连接本地 Bridge”；会进入“正在启动本地 Bridge”状态，并每 1.2 秒自动重新检测，Bridge 可用后恢复正常安装/就绪流程。
- ✅ Hermes Agent 检测修复：当 `~/.local/bin/hermes` 是 bash wrapper 且实际 `exec ~/.hermes/hermes-agent/venv/bin/hermes` 时，Yachiyo 会继续解析真实 venv launcher，定位 Hermes Agent 自带 Python，避免图片链路测试误报“无法定位 Hermes Agent 的 Python 环境”。
- ✅ Hermes 安装检测更稳：若存在 `~/.hermes/hermes-agent` 但 `hermes` 命令缺失或 wrapper 损坏，会返回可修复的 not installed/repair 指引，而不是把脏安装误判为 ready。
- ✅ 图片链路执行修复：`hermes_stream_bridge.py` 的 shebang 解析不再把 `/usr/bin/env` 当成脚本执行，修复打包临时目录中出现 `env: ...hermes_stream_bridge.py: Permission denied` 的问题。
- ✅ 验证：`python scripts/generate_release_changelog.py --channel experimental ...` 本地生成 changelog JSON/Markdown passed；`python -m py_compile scripts/generate_release_changelog.py` → passed；`PATH=<Node 20.19 runtime> npm --prefix apps/frontend run build` → passed（保留 Vite large chunk warning）；`python -m pytest tests/test_hermes_installer.py tests/test_runtime.py tests/test_executor.py tests/test_main_api_modes.py` → 134 passed；`ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-macos.yml")'` → passed；`git diff --check` → passed。

### UX Fixes — 首用体验报告修复

- ✅ 新增 `/ui/tts/status`，主动关怀语音页可以显示最近一次自动播报的生成中、成功或失败状态，便于定位 GPT-SoVITS 自动播报 HTTP 400 等问题。
- ✅ 工具中心已区分 Hermes Agent 的 `tts` 工具与 Yachiyo 主动关怀 TTS；无 Hermes 原生配置卡片时会引导用户打开“主动关怀语音”页面。
- ✅ 备份策略和备份操作区已提示 Live2D/GPT-SoVITS/附件缓存会进入备份，资源越大备份越大、耗时越久。
- ✅ 图片附件读取时新增极小尺寸保护，低于 16x16 的图片会提示换用正常尺寸截图，减少上游视觉模型“图片不可处理”的失败体验。
- ✅ 验证：相关 TTS route tests 4 passed；`npm --prefix apps/frontend run build` passed（保留既有 Vite large chunk warning）；`git diff --check` passed。

### Documentation — DMG 首用走查与 VitePress 素材

- ✅ 使用 `/Applications/Hermes-Yachiyo.app` 发布包，在隔离 HOME/Profile 下完成一次真实“第一次用户”走查。
- ✅ 覆盖并截图：安装向导、Hermes Agent 检测、Xiaomi MiMo 模型配置、连接测试、工作空间初始化、主控台、图片链路、文本对话、图片附件、Bubble、Live2D 导入与渲染、GPT-SoVITS 导入与 TTS 测试、主动关怀、工具中心、诊断、更新检查、备份和卸载预览。
- ✅ 新增 43 张截图到 `docs/public/images/hermes-yachiyo/first-run/`，VitePress 可直接通过 `/images/hermes-yachiyo/first-run/<file>.png` 引用。
- ✅ 新增/更新文档：`docs/user-manual.md`、`docs/screenshot-index.md`、`docs/experience-report-2026-05-05.md`、`docs/first-run-smoke-test-2026-05-05.md`。
- ✅ 真实边界已记录：GUI 安装遇到 GitHub 克隆中断后可手动安装并重新检测；Web/CDP/Image Gen 缺外部 Key 时工具中心按预期受限；GPT-SoVITS 手动测试成功但一次主动关怀自动播报返回 HTTP 400。
- ✅ 测试环境已清理，未把一次性 API Key 明文写入文档。

### Milestone 78 — Release 重跑幂等修复

- ✅ `Build macOS DMG` workflow 的发布步骤改为 `Create or update GitHub release`：当目标 release tag 已存在时，会用 `gh release upload --clobber` 覆盖同名 DMG asset，并用 `gh release edit` 刷新标题、目标 commit 和 release notes；首次运行仍走 `gh release create`。
- ✅ 修复 GitHub Actions 重跑同一个 run 时因 `ReleaseAsset.name already exists` / HTTP 422 导致 `Create GitHub release` 失败的问题。

### Milestone 77 — Live2D 导入编码、Vision Key 兼容与 GPT-SoVITS 部署入口

- ✅ Live2D ZIP 导入改为自定义解包：当压缩包文件名缺少 UTF-8 标记时，会尝试按 UTF-8 / GB18030 / 日文/韩文编码恢复真实文件名，并把可疑乱码目录名替换为安全的导入目录名，避免 `~/.hermes/yachiyo/assets/live2d/` 后出现 box drawing 乱码路径。
- ✅ Live2D 资源下载入口统一走系统默认浏览器，并明确指向资源 release：`https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/tag/live2d-assets-20260423`；不会再把 Live2D release 打进内置窗口。
- ✅ 图片识别链路补上 OpenRouter 旧配置兼容：当 Hermes/Yachiyo 仍保存的是 `AUTO_API_KEY`，但 provider 推断为 OpenRouter 时，原生图片输入与 vision 预分析都会把它视为可用 key；UI 仍只显示 `OPENROUTER_API_KEY` 的配置状态，不泄漏或展示 `AUTO_API_KEY` 明文。
- ✅ 主动关怀 TTS 超时上限从 120 秒放宽到 600 秒，默认值调整为 180 秒；GPT-SoVITS 权重切换、`/tts` 生成和音频播放都使用同一超时设置，适配本地模型首次加载较慢的情况。
- ✅ 主动关怀 TTS 触发后会先进入 `tts_pending` 状态：Bubble/Live2D 不再提前显示文本提醒，等异步 TTS 完成并把音频附件写回会话后，下一轮 launcher 轮询才把主动消息作为可见提醒推出。
- ✅ 主动关怀语音页补齐 GPT-SoVITS 本地服务部署入口：新增“部署本地服务”按钮，会打开系统终端，经过用户确认后克隆 `RVC-Boss/GPT-SoVITS`、创建 `.venv`、安装依赖并启动 `127.0.0.1:9880` API；“安装开机自启”仍只负责把已配置的服务目录/命令写入 LaunchAgent。
- ✅ GPT-SoVITS 语音资源面板布局收紧为紧凑按钮栏，避免三个资源按钮被 CSS grid 拉成异常高的大块；语音资源下载仍走外部默认浏览器并指向独立的 `tts-assets-yachiyo-gpt-sovits-v4` release。
- ✅ 验证：`python -m pytest tests/test_ui_bridge_routes.py::test_launcher_tts_only_triggers_for_proactive_attention tests/test_ui_bridge_routes.py::test_launcher_tts_triggers_without_probability_gate tests/test_ui_bridge_routes.py::test_launcher_hides_proactive_reply_while_tts_audio_is_generating tests/test_ui_bridge_routes.py::test_live2d_zip_member_name_recovers_utf8_without_flag tests/test_tts.py::test_import_tts_voice_archive_returns_gpt_sovits_settings` → 5 passed；`python -m pytest tests/test_executor.py::TestHermesStreamBridgeImageRouting::test_xiaomi_text_model_vision_fallback_inherits_configured_base_url tests/test_main_api_modes.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py` → 93 passed；`python -m pytest tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_executor.py` → 165 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`git diff --check` → passed。

### Milestone 76 — 主动关怀截图链路、首启回退与发布自动化收口

- ✅ 主动关怀桌面观察的截图附件改为只作为内部附件传给对话链路，不再把“主动桌面观察”的系统指令文本写入用户消息；对话中仍可看到生成的桌面截图附件，方便用户确认本轮观察依据。
- ✅ 聊天附件读取改为 `inline` 响应，并移除图片查看器中的“打开原图”外部浏览器入口，避免主动关怀截图触发后自动弹出 Chrome/默认浏览器预览窗口，同时保持图片识别链路可继续读取本地附件。
- ✅ Hermes provider 推断补强：当配置为 `auto` 但 Base URL/模型指向 OpenRouter 时，Yachiyo 会按有效 provider 写入 `OPENROUTER_API_KEY` 并使用对应模型缓存判断图片原生输入能力，避免误报“API Key 无效”或错误回退到 vision 预分析。
- ✅ Electron 首启/激活流程继续加固：只要用户已经进入过主控台或安装信息显示 ready，Dock 图标激活就不会再用旧的 `lastInstallReady=false` 打回安装向导；进入主控台时会恢复配置中的 Bubble/Live2D 表现态，Live2D 无资源时自动回退 Bubble。
- ✅ Live2D 资源 gate 前后端双重兜底：设置页保存 `display_mode=live2d` 时如果没有有效资源，会返回 `redirect` 到 Live2D 设置页并保持 Bubble；Electron 表现态打开也会先检查资源状态，避免无资源透明窗口把用户困住。
- ✅ 主动关怀语音页新增 GPT-SoVITS 本地服务状态/安装/移除路由：可查看 API 是否可达、服务目录是否存在、LaunchAgent 是否安装/运行，并可把当前服务目录和命令写成当前用户的 macOS LaunchAgent；不会下载或改写 GPT-SoVITS 项目本体。
- ✅ Release workflow 改为自动生成带版本号的 stable/experimental release tag 与资产名：版本以 `pyproject.toml` 基础版本加 `GITHUB_RUN_NUMBER` 形成发布版本；应用 release 只发布 DMG，不再把八千代 GPT-SoVITS ZIP 附在每次 develop/main 构建里。
- ✅ 新增独立 `Publish TTS Voice Assets` workflow：只在手动触发时接收已经调配好的语音 ZIP URL，并上传到 `tts-assets-yachiyo-gpt-sovits-v4` 资源 release；不会从仓库重复构建语音包，也不会参与应用 DMG 常规构建。
- ✅ 卸载“删除当前应用本体”改为 macOS Finder 删除优先、shell 删除兜底；仍属于 best-effort，因为运行中的 `.app` 删除受 Finder/权限/签名路径影响，失败时继续提示用户手动从 Applications 移除。
- ✅ 验证：`python -m pytest tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py tests/test_main_api_modes.py tests/test_proactive.py tests/test_hermes_capabilities.py tests/test_executor.py` → 181 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-macos.yml")'` → passed；`git diff --check` → passed。

### Milestone 75 — DMG 首装流程、Live2D Gate 与 TTS 本地服务辅助

- ✅ 基于 `develop` 当前 HEAD `67b7f74` 的 DMG 清机验证反馈，修复安装向导在 Hermes 终端安装完成后的衔接：重新检测到 `installed_needs_setup` / `setup_in_progress` / `installed_not_initialized` 后会滚动到模型配置向导，引导用户填写 Provider、模型、Base URL 和 API Key。
- ✅ 初始化 Yachiyo 工作空间前新增模型/API Key 完整性提示：如果当前 Provider、模型或所需 API Key 缺失，会提示“直接初始化可能导致首次对话不可用”，用户确认后仍可继续，取消则回到模型配置区。
- ✅ Hermes ready / 工作空间初始化成功后，桌面壳会进入主控台并主动打开 Bubble 表现态；macOS 点击 Dock 图标时会先刷新 `/hermes/install-info`，避免使用旧的 `lastInstallReady=false` 把已初始化用户拉回安装向导，同时恢复当前表现态。
- ✅ 通用设置中的 Live2D 模式切换新增资源 gate：若 `mode_settings.live2d.config.model_state` 不是 `path_valid` / `loaded`，不会切换到 Live2D，而是跳到 Live2D 资源配置页要求导入 ZIP 或选择有效模型目录；后端 `apply_settings_changes()` 同步拒绝无资源的 `display_mode=live2d`。
- ✅ Electron 表现态启动也新增 Live2D gate：显式打开 Live2D 且资源未就绪时进入设置页；默认打开表现态时如当前配置是 Live2D 但资源不可用，会回退到 Bubble，避免用户进入不可点击、找不到 Dock 图标的死路。
- ✅ Live2D 真模型渲染增加 Electron/WebGL 保护：加载 runtime 后配置 Pixi WebGL2 偏好并关闭 major performance caveat；遇到 `checkMaxIfStatementsInShader` / `invalid value of 0` 时保留静态预览并显示明确的 WebGL 回退说明，避免把资源导入成功误判成导入失败。
- ✅ 主动关怀 TTS 的 GPT-SoVITS 配置新增本地服务辅助字段：`tts.gsv_service_workdir` 与 `tts.gsv_service_command`；导入八千代语音包后会默认填入 `http://127.0.0.1:9880`、权重/参考音频路径和默认服务启动命令，服务目录可由语音包 manifest 提供或由用户手动填写。
- ✅ 主动关怀语音设置页新增“GPT-SoVITS 本地服务”区块：可填写服务目录与启动命令，并通过受控 `/ui/hermes/terminal-command` 打开终端启动本地服务；说明语音 ZIP 只包含权重/参考音频，本地 API 服务仍需单独运行。
- ✅ 卸载页新增“同时删除当前应用本体”选项：完成工作区/Hermes 数据卸载后，可由 Electron 启动受控 shell 删除当前 `.app` bundle 并退出；失败时会提示手动移除 Applications 中的应用。
- ✅ GitHub Actions DMG workflow 失败原因已定位为 CI 未安装 `pytest-asyncio`，`pyproject.toml` dev extras 已补 `pytest-asyncio>=0.23.0`，workflow 的 async smoke tests 可正常收集执行。
- ✅ 验证：`npm --prefix apps/frontend run build` → passed；`python -m pytest tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_uninstall.py` → 131 passed，1 known duplicate ZIP warning；workflow smoke suite `python -m pytest tests/test_screenshot.py tests/test_proactive.py tests/test_chat_session.py tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py` → 112 passed；`python -m pytest tests/test_hermes_installer.py` → 10 passed；全量 `python -m pytest` → 421 passed，1 known duplicate ZIP warning；`git diff --check` → passed。

### Milestone 74 — Tool Center Doctor 分级与工具配置修复

- ✅ 基于当前 `phase-2/feature/repair-tools` 的提交树补齐进度记录：`7307fd3` 合入了 2026-05-01 至 2026-05-02 的 Electron 固定前端、配置诊断、图片附件/vision 路由、图片链路校验缓存和窗口身份持久化等工作；其前序关键提交包括 `1ddba0a`、`41126f9`、`28c23ff`、`eac0dcb`、`0d0aee0`、`254ce91`、`9f55c9f`。
- ✅ `hermes doctor` 输出解析已从只看受限项扩展为同时解析 `available_tools`、`limited_tools`、受限原因和 issue count；旧的三元返回值仍保留兼容安装器调用。
- ✅ Runtime、Dashboard、Settings 和 Tool Center 已透传 Doctor 新字段，工具中心不再只依赖 `hermes.ready` 推断状态。
- ✅ Tool Center 已拆分基础 `browser` 和高级 `browser-cdp`：基础浏览器自动化可按 `browser` 可用状态显示，CDP 端口缺失只影响 `browser-cdp`。
- ✅ 新增工具配置安全接口 `/ui/hermes/tools/config`：按工具返回不同配置项，只展示 env 名和配置状态，不回传任何 token/key 明文；保存统一走 `hermes config set`。
- ✅ 第一批配置目录已覆盖 `web`、`browser`、`browser-cdp`、`image_gen`、Discord、Home Assistant、MoA、RL；Spotify、腾讯元宝和 messaging 先提供 Hermes 原生向导入口；Tool Center 现会读取 `hermes tools list`，只展示当前 Hermes 暴露的工具组。
- ✅ `image_gen` 配置已收敛为当前 Hermes 已知 provider：内置 FAL 与已装 OpenAI/OpenAI Codex/xAI 插件提供模型建议，不再主动列出 Hermes 未暴露的生图后端。
- ✅ 工具配置页新增“保存并测试 / 测试配置”：保存后会做必需配置静态检查，并运行 `hermes doctor` 对应工具状态，不会默认触发发消息、生图、RL 训练等有副作用/成本的真实调用。
- ✅ 新增 Hermes 更新检查与更新入口：Tool Center 可检查 `hermes version` / `hermes update --check`，更新通道跟随 Hermes 官方 updater 的当前 checkout `origin/main`；默认执行 `hermes update --gateway --yes --no-backup`，可勾选完整备份后改走 `--backup`，更新完成会自动刷新 `hermes tools list`、工具配置、Dashboard 与 Doctor 缓存，并展示工具清单变化。
- ✅ `image_gen` provider 列表改为从当前 Hermes `plugins/image_gen/*/plugin.yaml` 读取，确保已安装的 OpenAI、OpenAI Codex、xAI 插件不会被前端压成只剩 FAL。
- ✅ 新增 `/ui/hermes/tools/browser-cdp/launch`：可尝试启动或连接本机 Chrome `9222` 调试端口，成功后写入 `browser.cdp_url=http://127.0.0.1:9222`，失败时返回 Hermes 生成的手动命令。
- ✅ Tool Center React 视图新增 `#/tools/:toolId` 独立配置页，受限/可配置卡片会进入对应配置页而不是在长列表顶部展开；配置页顶部和底部都有保存入口，未保存切换时会弹出“保存并继续 / 弃置更改 / 继续编辑”确认。
- ✅ 诊断缓存指纹已纳入工具配置安全快照，工具配置或 env 配置状态变化后会让旧 Doctor 缓存标记为过期。
- ✅ 验证：`python -m pytest tests/test_hermes_installer.py tests/test_main_api_modes.py tests/test_ui_bridge_routes.py tests/test_hermes_capabilities.py` → 49 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`git diff --check` → passed。

### Milestone 73 — 一键安装错误捕获 hotfix

- ✅ `run_hermes_install()` 不再丢弃带 ANSI 颜色控制序列的安装脚本输出；会清洗控制码并保留可读错误文本，避免 UI 只显示 `exit=1` 而隐藏真正失败原因。
- ✅ 安装脚本非零退出后，兜底检测改为复用 `locate_hermes_binary()`，可识别 Hermes 已落盘但当前 GUI 进程 PATH 尚未刷新的场景。
- ✅ 通过备用路径找到 Hermes 且 `hermes --version` 成功时，将结果视为安装成功，并提示当前应用 PATH 已修复、仍需完成 `hermes setup`。
- ✅ 安装脚本真实失败时，失败文案提示用户查看上方安装日志中的错误详情。
- ✅ 修复 `apps/installer/hermes_install.py` 中已有 `Dict[str, any]` 类型标注问题，相关文件 diagnostics 清零。
- ✅ 新增回归测试覆盖 ANSI 错误日志保留、`exit=1` 后通过备用路径识别已安装 Hermes。
- ✅ 相关测试：`python -m pytest tests/test_hermes_installer.py` → 8 passed。
- ✅ 全量测试：`python -m pytest` → 425 passed，1 warning（已有重复 ZIP entry 警告）。
- ✅ `git diff --check` → passed。

### Milestone 72 — 备份清理与导入源安全收敛

- ✅ `find_backups()` 只纳入严格匹配托管命名规则的 `hermes-yachiyo-backup-YYYYMMDD-HHMMSS[-N].zip`，不再把 `*-draft.zip` / `*-external.zip` 等前缀相似文件纳入管理列表。
- ✅ `cleanup_old_backups()` 删除旧备份时若遇到 `ValueError`，会记录 warning 并跳过该文件，避免自动清理导致 `create_backup(auto_cleanup=True)` 中断。
- ✅ `import_backup()` 恢复 `app-config` 前强制确认备份源是非 symlink 目录；若备份里是文件或非目录形态，会跳过并给出原因，不会替换目标配置目录。
- ✅ `import_backup()` 恢复 `yachiyo-workspace` 前同样强制确认备份源是非 symlink 目录，再检查初始化标识和目标安全性，避免文件替换目标工作空间目录。
- ✅ 新增回归测试覆盖不可管理删除错误跳过、非规范命名 ZIP 不进入 `find_backups()`、文件形态 app-config/workspace 源不会被恢复。
- ✅ 相关测试：`python -m pytest tests/test_uninstall.py` → 45 passed。
- ✅ 全量测试：`python -m pytest` → 423 passed。

### Milestone 71 — 受保护路径集合缓存

- ✅ `protected_paths()` 改为复用按当前 home 路径缓存的受保护路径集合，避免备份导入/卸载安全检查中反复执行多组 `exists()` / `resolve()`。
- ✅ `is_protected_path()` 直接查询缓存的 `frozenset`，不再为每次判断重新构造受保护路径集合。
- ✅ 移除 `protected_paths()` 中不可达且引用未定义 `home` 的旧 return，避免静态检查与后续维护误判。

### Milestone 70 — 备份 ZIP 解压实际写入限流

- ✅ `_extract_zip_safely()` 不再只依赖 `ZipInfo.file_size` 头部声明；解压成员改为分块读写，并按实际写入字节数校验单条目和总解压体积限制。
- ✅ 解压过程中一旦实际写入量超出单条目或总量限制，会中止并删除当前部分输出文件，避免恶意 ZIP 通过虚假 header 触发磁盘填充风险。

### Milestone 72 — Electron 固定前端与 Python Headless 后端

- ✅ 固定桌面壳改为 Electron + React/Vite/TypeScript，前端工作区落在 `apps/frontend/`，不再通过 pywebview 承载新 UI。
- ✅ 新增 `apps/desktop_backend/app.py`，Python 侧只负责 `HermesRuntime`、Bridge lifecycle 与本地能力边界，不创建桌面窗口。
- ✅ 新增 `apps/bridge/routes/ui.py`，提供 `/ui/dashboard`、`/ui/settings`、`/ui/chat/*`、`/ui/modes/{mode}/settings` 给 React renderer 调用。
- ✅ `hermes-yachiyo` 入口改为启动 Electron 前端；`hermes-yachiyo-backend` 可单独启动后端；旧 pywebview 入口保留为 `hermes-yachiyo-legacy-pywebview`。
- ✅ 前端移除 `window.pywebview.api` 调用，改用 HTTP bridge client；新增通用设置、模式设置、聊天和主控台 React 视图。
- ✅ Node 使用 `nvm install/use 20.19.0`，并用 Node 20.19 刷新 latest 前端依赖与 `apps/frontend/package-lock.json`；`npm audit` 当前为 0 vulnerabilities。
- ✅ Electron dev server 固定为 `127.0.0.1:5174` strict port，避免 5173 被占用时 Vite 自动漂移导致 Electron 加载错误端口。
- ✅ `hermes-yachiyo` 默认入口会优先使用 nvm Node 20.19；缺少前端 `node_modules/.bin` 工具时自动执行一次 `npm ci`，然后打开 Electron 前端并拉起 Python backend。
- ✅ `apps/desktop_launcher.py` 已补 Node 20.19+ 版本预检、前端子进程失败提示和 Ctrl-C/验证中断的无 traceback 退出；启动失败时会优先显示可操作原因，而不是裸 Python traceback。
- ✅ 已排查用户运行后仍像旧窗口的问题：当前 venv 的 `hermes-yachiyo` console script 曾残留为 `apps.shell.app:main`；重新 `pip install -e .` 后已刷新为 `apps.desktop_launcher:main`，旧入口仅在 `hermes-yachiyo-legacy-pywebview`。
- ✅ 已修复 React 主控台 `Failed to fetch` 红条成功后不清除的问题，并把网络失败文案改为“无法连接本地 Bridge”。Bridge 卡片兼容 `state/status/running` 字段。
- ✅ Electron main 新增按当前 `display_mode` 自动打开 Bubble/Live2D 透明表现态窗口；React LauncherView 新增第一版 Bubble/Live2D 表现态 UI 与打开对话/设置入口。完整旧 pywebview 表现态能力仍需继续迁移。
- ✅ Bubble/Live2D Electron 表现态已接入真实 Bridge 状态：新增 `/ui/launcher`、`/ui/launcher/ack`、`/ui/launcher/quick-message`，复用 `ChatBridge` 与 `LauncherNotificationTracker` 提供未读、处理中、最近回复和快捷输入；Electron 右键菜单已接入打开对话/主控台/设置/重开表现态/关闭表现态/退出应用。
- ✅ Electron 表现态窗口已支持位置持久化：新增 `/ui/launcher/position`，Electron 在 Bubble/Live2D 移动或缩放后防抖写回配置；Bubble 会按旧 pywebview 逻辑吸附最近屏幕边缘，Live2D 会保存位置和窗口尺寸。
- ✅ `/ui/launcher` 已补 Live2D 资源状态摘要，React 表现态可根据资源是否就绪调整 stage 视觉状态，为后续接入真实 Live2D renderer 准备数据边界。
- ✅ React ChatView 已对照旧 pywebview Chat Window 补回核心体验：500ms 处理中轮询、typewriter 渐进显示、Markdown 渲染、复制按钮、会话下拉、新对话/删除、executor badge，并通过 `/ui/chat/*` HTTP Bridge 接入。
- ✅ Electron Chat Window 已恢复旧 pywebview 单例语义：主控台、Bubble、Live2D 和任意 `openView('chat')` 都打开/置前同一个独立 Chat BrowserWindow，不再把 ChatView 装进主窗口或表现态小窗口；Chat 窗口内的“主控台”按钮会回到主窗口。
- ✅ React renderer 已加入 hash route 层：`#/`、`#/chat`、`#/settings`、`#/settings/bubble`、`#/settings/live2d`、`#/bubble`、`#/live2d` 等路由可在同一窗口内切换，并保留旧 `?view=` 兼容。
- ✅ Bubble/Live2D mode window 已加入 Electron 导航保护：表现态窗口只承载 launcher route，非 launcher 导航会被 Electron 转发到主窗口或 Chat 单例，避免 112×112 气泡里显示完整 ChatView。
- ✅ React 主控台已对照旧 pywebview Control Center 补回 Hermes、Workspace、Runtime/Bridge、Tasks、Integrations、会话摘要和模式入口等主要信息。
- ✅ React 通用设置页已补回旧 pywebview 主要内容：Hermes 诊断、Workspace 详情、显示模式、助手资料、Bridge 状态/漂移/重启、集成状态、应用设置、备份管理和卸载预览/执行入口。
- ✅ UI Bridge 已补旧 MainWindowAPI 操作路由：Hermes terminal/recheck、Bridge restart、backup status/create/restore/delete/open-location、uninstall preview/run，React 只调用 HTTP route，不复制业务逻辑。
- ✅ React 通用设置页已从只读状态页推进为字段级编辑表单：可编辑显示模式、助手称呼、助手人设、Bridge 启用/host/port、托盘入口；只提交与当前配置不同的字段到 `/ui/settings`，保存后重新拉取后端状态。浏览器实机检查确认真实 Bridge 数据能填充表单、待保存状态能正确启用按钮、非法端口会显示自定义错误且修正后自动清除。
- ✅ React Bubble/Live2D 模式设置页已从 JSON 预览推进为字段级编辑表单：Bubble 支持窗口尺寸、默认位置百分比、置顶、吸附、启动展开、头像路径、默认展示、摘要条数、未读灯、自动淡出、透明度和主动观察；Live2D 支持模型/路径、窗口位置尺寸、缩放、置顶/Spaces、回复气泡、启动表现、点击行为、快捷输入、鼠标跟随、动作/表情/物理开关、主动观察和 Live2D TTS。表单只提交差异字段到 `/ui/settings`，保存后重新读取 `/ui/modes/{mode}/settings`。
- ✅ React Live2D 模式设置页已恢复旧 pywebview 的资源操作入口：`选择模型目录` 和 `导入资源包 ZIP` 由 Electron 原生文件选择器选取路径，Bridge 负责验证/导入并返回 `live2d_mode.model_path` 草稿；`打开导入目录` 走 Electron `shell.openPath`，`打开 Releases` 走 Electron `shell.openExternal`。选择/导入不会直接保存配置，仍需用户点击 `保存更改`。
- ✅ 已修复无桌面 preload/IPC 场景的两处回归：Live2D 资源区在没有 Electron 文件选择器时会显示内联“模型目录路径 / 资源包 ZIP 路径”输入框，按钮改为按路径检查/导入；Bubble 点击在无 `openView` IPC 时不再把 ChatView 塞进 112×112 表现态窗口，而是打开新的 `view=chat` 窗口/标签。
- ✅ 已收紧“React renderer ≠ 产品运行态”的边界：产品态必须通过 Electron 桌面壳运行，浏览器/Vite 只作为开发 fallback；`hermes-yachiyo` 在发现 `127.0.0.1:5174` 已有 Vite dev server 时会复用它并直接启动 Electron，不再因为 strict port 占用退出。Live2D 透明 pointer passthrough 改为实验能力，默认关闭，以“表现态可点击/可右键/可操作”优先；Live2D 舞台、角色、资源提示、回复气泡和快捷输入已从 Electron drag 区域中排除，避免 div 点击被窗口拖拽吞掉；需要测试透明穿透时显式设置 `HERMES_YACHIYO_LIVE2D_POINTER_PASSTHROUGH=1`。
- ✅ 已用 Downloads 中真实资源包 `hermes-yachiyo-live2d-yachiyo-20260423.zip` 做模拟导入验证：临时目录导入识别到 1 个 `.model3.json` 和 1 个 `.moc3`，草稿预览 `model_state=path_valid`，`renderer_entry` 指向 `八千代辉夜姬.model3.json`；直接调用 `/ui/live2d/archive/import` 路由函数并将导入根目录替换为临时目录后同样返回成功，真实 `config.live2d_mode.model_path` 保持为空，未持久化用户配置。
- ✅ Electron Bubble 已对照旧 pywebview 表现恢复头像气泡结构：Bridge 返回头像 data URI、`expand_trigger`、`suppress_status_dot`、主动桌面观察状态；React 恢复旧 `.bubble-launcher` / `.portrait` / `.status-dot` 视觉、未读/处理中/失败状态点、auto-hide 透明度公式、title 提示和 6px 拖拽点击阈值。
- ✅ Electron Live2D 已完成第一步旧表现还原：Bridge 返回 preview data URI、resource 状态和 renderer scaffold；React 恢复预览图 fallback、资源提示条、默认打开行为、回复气泡、快捷输入和处理中/有消息发光状态。真实 Pixi/Cubism 模型渲染、鼠标跟随和透明命中区域仍是下一步。
- ✅ Electron Live2D 已接入第一版真模型渲染路径：Bridge 新增 `/live2d/runtime` 与 `/live2d/runtime/{dependency_id}`，复用旧 pywebview 的 Pixi/Cubism 依赖缓存；React 按顺序加载 runtime scripts，使用 `renderer.model_url` 创建 Pixi Application 与 Live2DModel，模型加载成功后淡出 preview，失败时保留静态预览并显示错误；已补窗口内鼠标跟随 focus。透明命中区域、全局鼠标同步、动作/表情细节仍待迁移和实机验证。
- ✅ Electron Live2D 已接入第一版透明命中区域：Electron main 新增 `setLauncherPointerInteractive` 窄 IPC 并用 `BrowserWindow.setIgnoreMouseEvents(..., { forward: true })` 切换空白区域穿透；React 从 preview/canvas 生成 alpha mask，并把资源提示、回复气泡、快捷输入作为 UI 命中区域参与判定。仍需真实模型实机验证穿透、拖拽和全局鼠标同步边界。
- ✅ 文档新增 `docs/desktop-frontend-architecture.md`，`docs/ui-resource-architecture.md` 改为 legacy 记录。
- ✅ 手工启动基线：`hermes-yachiyo` 已确认走当前 venv 的 `apps.desktop_launcher:main`，启动后拉起 Vite `127.0.0.1:5174`、Electron、Python backend 与 Bridge `127.0.0.1:8420`；日志中 `/ui/dashboard` 与 `/ui/launcher?mode=bubble` 返回 200。验证结束时的 exit 130 来自手动中断，不是应用主动崩溃。
- ✅ 验证：`npm --prefix apps/frontend run build` 通过；设置页浏览器实机检查通过，包括通用设置、Bubble 模式设置和 Live2D 模式设置的真实数据填充、待保存状态、非法数值提示与恢复原值同步状态；新增 Live2D 资源入口后再次 `npm --prefix apps/frontend run build` 通过；真实 Downloads Live2D ZIP 临时导入和 Bridge 路由模拟导入通过；无桌面 IPC 浏览器场景验证通过：资源区显示内联 ZIP 路径输入且空路径提示正常，Bubble 点击保持 `view=bubble` 并通过 `window.open(...view=chat)` 打开对话；Electron 运行态短启动验证确认 Vite + Electron 进程能拉起；最新 `npm --prefix apps/frontend run build` → 通过，`dist/assets/index-BB_YwRRT.css` / `dist/assets/index-DklLRZW3.js`；最新 `pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 18 passed；`pytest tests/test_ui_bridge_routes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 45 passed；`pytest tests/test_ui_bridge_routes.py tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 48 passed；`pytest tests/test_bridge_server.py tests/test_ui_bridge_routes.py tests/test_chat_bridge.py tests/test_mode_settings.py tests/test_chat_api.py tests/test_desktop_launcher.py` → 119 passed；相关 VS Code diagnostics 无错误。此前 `pytest tests/test_ui_bridge_routes.py tests/test_bridge_server.py tests/test_chat_api.py tests/test_mode_settings.py tests/test_runtime.py` → 57 passed；`npm --prefix apps/frontend run dev` 已拉起 Electron、Python backend，并看到 renderer 请求 `/ui/dashboard` 200。
- ✅ 最新追加验证：`npm --prefix apps/frontend run build` 通过；`/Users/cxldefontaine/个人项目/Hermes-Yachiyo/.venv/bin/python -m pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 19 passed；VS Code diagnostics 对最新改动文件无错误。

### UI 资源分离第一阶段

- ✅ 新增 `apps/shell/ui/styles/` 作为 pywebview 前端视觉资源目录，主控台、安装页、聊天窗、模式设置、Bubble、Live2D 的视觉覆盖样式已从 Python 字符串迁出。
- ✅ 新增 `read_ui_asset()` / `inject_css()`，Python 只保留窗口创建、JS API 绑定和占位符替换，视觉层通过外部 CSS 注入。
- ✅ `pyproject.toml` 已加入 `apps.shell.ui` package-data，确保 editable / wheel 安装时 CSS 资源随包分发。
- ✅ 清理前期 UI 探索生成的一次性 patch 脚本，仓库只保留正式源码与资源文件。
- ✅ 相关验证：`/usr/local/bin/python3 -m pytest tests/test_chat_window.py tests/test_chat_bridge.py tests/test_mode_settings.py` → 89 passed。
- ✅ 资源加载验证：`read_ui_asset("styles/elegant.css")`、`_CHAT_HTML`、`_BUBBLE_HTML` 均确认能读取/注入外部 CSS。

### UI / Visual Overhaul (Gemini Aesthetic Pass)

- ✅ Refactored the UI across all modules (chat_window, window, settings, mode_settings, bubble, live2d) focusing strictly on visual representation without altering underlying Python execution logic or string injection markers.
- ✅ Replaced the rigid, high-contrast Tsukuyomi cyberpunk design with an elegant macOS-inspired "Glassmorphism" deep dark theme (`--bg-main: #0B0E14`).
- ✅ Implemented radial lighting, smooth transition animations, and subpixel-antialiased typography using `SF Pro Text` / system fonts.
- ✅ Successfully restored broken mode setting configurations (like bubble size and opacity configurations mapping in `settings.py`) by isolating CSS block injection instead of full string replacement.
