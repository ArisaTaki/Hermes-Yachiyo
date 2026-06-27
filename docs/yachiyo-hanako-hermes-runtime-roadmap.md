# Oha-Yachiyo Hanako/Hermes Runtime Roadmap

This roadmap is the execution boundary for moving Oha-Yachiyo from a
rule-hit desktop helper toward a capability-discovery desktop execution agent.
The target shape is:

- Chat Window, Bubble, and Live2D are daily entrypoints.
- Agent Studio remains the professional entrypoint for Agents, Groups,
  Workflows, Run Timeline, Tools, Approvals, and Artifacts.
- Runtime planning follows TaskIntent -> CapabilityPlan -> ToolPlan.
- Discovery comes before app-specific rules: inspect available capabilities,
  choose tools, execute, verify, and record replayable events.
- Old route response shapes, database schema, Agent Studio, Groups, Workflow,
  Run Timeline, Approval, and Artifact behavior stay compatible.

## Execution Rule

This Phase 0-10 sequence is the authoritative implementation route for the
Hanako/Hermes runtime migration. Each implementation batch should map to one
of these phases, and cleanup of old app-specific hardcoding belongs in Phase
10 only after the replacement planner/runtime path is covered by tests. Phase
0 is a mandatory protection baseline, not a feature refactor. Phase-specific
application optimizations must not replace the capability discovery,
intent-routing, planning, execution, and verification chain.

## Phase 0 - 基线审计与保护网

Confirm that existing Chat, Agent Studio, Groups, Workflow, Run Timeline,
Approval, Artifact, and legacy routes still work. Add the smallest useful
regression tests before deleting code later.

Exit evidence:

- Chat can start tasks and render task cards.
- Agent Studio can inspect runs, approvals, artifacts, groups, and workflows.
- Legacy `/agents` and `/ui/agents` shapes remain compatible.
- Focused tests cover the behavior that later cleanup would otherwise risk.

## Phase 1 - Public Contracts

Add task-level public contracts that explain why the runtime chose a plan:
`TaskIntentSnapshot`, `CapabilitySnapshot`, `ToolPlanSnapshot`,
`PlannerDecisionSnapshot`, and `RuntimePlanSnapshot`.

Exit evidence:

- Chat and Studio can both read the selected intent, considered capabilities,
  selected tools, missing capabilities, and route-to-studio hints.
- Existing public snapshots remain backward compatible.

## Phase 2 - Capability Registry

Build a capability registry that is not centered on hardcoded app rules.
Capabilities include file read/write, terminal execution, data analysis,
artifact output, browser, desktop app discovery, window/UI operation,
clipboard, reminders/schedule, Workflow, and GroupRun.

Exit evidence:

- Planner input can be expressed as capabilities rather than app aliases.
- Approval and policy metadata remain attached to each capability/tool.

## Phase 3 - Task Intent Router

Recognize task intent before selecting tools. Required intent families include
desktop operation, data analysis, report generation, web research, file
organization, email/communication, schedule/reminder, code task, Workflow, and
multi-agent collaboration.

Exit evidence:

- User requests map to observable intent candidates with confidence and inputs.
- The router handles generic app names and non-app tasks without adding a new
  one-off branch for each application.

## Phase 4 - Runtime Planner

Convert TaskIntent into CapabilityPlan and ToolPlan. For example, "analyze data
and output a report" should plan data-source discovery, file reads, analysis,
charts/report artifacts, and optional app opening only when useful.

Exit evidence:

- Planner decisions are visible in Chat task metadata and Studio run events.
- Plans can continue to the model when the first tool is only prefetch context.
- Missing capabilities are explicit instead of hidden in a text-only apology.

## Phase 5 - Desktop Discover/Operate Layer

Align with Hanako-style desktop operation: `list_apps`, `open_app`,
`focus_app`, `list_windows`, `read_ui`, `click`, `type`, `shortcut`, and
`verify`. The target is handling arbitrary app names by discovery and system
capabilities, not by writing a dedicated rule for every app.

Exit evidence:

- Generic app discovery normalizes user-provided app names.
- Desktop operations use inspect/operate/verify events.
- High-risk operations still go through approval and policy gates.

## Phase 6 - Data Analysis Capability

Add a stable data-analysis path for CSV, XLSX, JSON, and text-table inputs.
Prefer Python/pandas or built-in parsers and produce Markdown, HTML, CSV,
chart, or report artifacts. Open Excel/Numbers only when explicitly requested
or when the plan requires UI inspection.

Exit evidence:

- Data-source hints produce `workspace.read`/analysis/artifact plans.
- Artifacts are observable and readable through existing task/run surfaces.

## Phase 7 - Prompt/Skill Runtime Doctrine

Replace rule-classification prompts with a Hermes/Hanako-style operating
manual: discover first, execute with tools, verify results, inspect when
uncertain, and ask for approval for high-risk actions.

Exit evidence:

- Main chat runtime guidance emphasizes available tools over text-only advice.
- The doctrine is shared by Chat, Bubble, Live2D, Studio, Workflow, and Groups.

## Phase 8 - Chat/Bubble/Live2D Planner Integration

Daily entrypoints default to the new planner. Old `desktop_intents.py` remains
only as fallback while coverage is measured.

Exit evidence:

- Main Chat submits no-attachment, non-group messages through the planner-backed
  `/yachiyo/tasks` facade before falling back to the legacy Chat route.
- Chat, Bubble, and Live2D can start planner-backed tasks beyond desktop app
  launch/playback cases.
- Fallback branches are marked by source and planning reason.

## Phase 9 - Agent Studio Debug Surface

Agent Studio exposes Intent, Capabilities, Plan, Tool Calls, Approvals,
Artifacts, and Timeline. Groups and Workflow use the same planner/runtime
events.

Exit evidence:

- Studio can explain why a task chose specific tools.
- GroupRun and Workflow timelines show the same planner event vocabulary.

## Phase 10 - 删除旧硬编码与收敛代码

After coverage proves the new chain works, delete no-longer-needed app aliases,
special music/Finder/browser branches, and temporary intent patches. Keep old
API shapes, database schema, Studio, Groups, Workflow, Run Timeline, and
approval gates.

Exit evidence:

- Removed code is covered by replacement tests or explicit fallback deletion
  notes.
- No cleanup removes user-facing Studio, Groups, Workflow, Timeline, Approval,
  Artifact, or legacy route behavior.

## Non-Negotiable Guards

- 禁止删除 Agent Studio。
- 禁止删除 Groups, multi-agent, Workflow, or Run Timeline behavior。
- 禁止一次性重写 NativeRunEngine。
- 禁止改数据库 schema。
- 禁止破坏旧 route response shape。
- 禁止绕过 approval/policy gate。
- 禁止大规模格式化。
