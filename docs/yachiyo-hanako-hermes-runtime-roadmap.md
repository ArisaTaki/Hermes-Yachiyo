# Oha-Yachiyo Hanako/Hermes Runtime Roadmap

This roadmap is the execution boundary for moving Oha-Yachiyo from a
rule-hit desktop helper toward a release-grade desktop execution agent. The
minimum bar is parity with the Hanako/Hermes class of products: arbitrary
desktop intent should be routed through discovery, operation, verification,
approval, and replayable runtime events instead of text-only advice or
per-application hardcoding. The target shape is:

- Chat Window, Bubble, and Live2D are daily entrypoints.
- Agent Studio remains the professional entrypoint for Agents, Groups,
  Workflows, Run Timeline, Tools, Approvals, and Artifacts.
- Runtime planning follows TaskIntent -> CapabilityPlan -> ToolPlan.
- Discovery comes before app-specific rules: inspect available capabilities,
  choose tools, execute, verify, and record replayable events.
- The project can be packaged, installed, smoke-tested, diagnosed, and
  documented as a complete Oha-Yachiyo application, not just a branch-local
  runtime experiment.
- Old route response shapes, database schema, Agent Studio, Groups, Workflow,
  Run Timeline, Approval, and Artifact behavior stay compatible.

## Execution Rule

This Phase 0-12 sequence is the authoritative implementation route for the
Hanako/Hermes runtime migration. Each implementation batch should map to one
of these phases, and cleanup of old app-specific hardcoding belongs in Phase
10 only after the replacement planner/runtime path is covered by tests. Phase
0 is a mandatory protection baseline, not a feature refactor. Phase-specific
application optimizations must not replace the capability discovery,
intent-routing, planning, execution, and verification chain.

## Release-Level Definition Of Done

Oha-Yachiyo is not considered Hanako/Hermes-level until all of the following
are true in the current worktree and release artifacts:

- Chat Window, Bubble, and Live2D can start low- and medium-risk desktop
  tasks without model hand-waving when the required tools are available.
- Arbitrary app names are resolved through desktop discovery and app/window/UI
  inspection before fallback aliases or user instructions.
- Risky actions pause at the existing approval/policy gate and resume from the
  same Run after approval without losing prior tool results.
- Agent Studio shows the same run through stable public contracts: intent,
  capabilities, plan, tool calls, approvals, artifacts, timeline, replay, and
  failure/recovery context.
- Groups and Workflow preserve planner/runtime event vocabulary and can be
  debugged from Agent Studio without special-case route shapes.
- Data analysis, browser research, file/artifact work, reminders, and code
  tasks route through capability plans, not desktop app launch as the default.
- Permission onboarding and recovery explain the missing macOS capability,
  affected tools, recovery action, and retry path.
- Packaging, signing/notarization or documented unsigned install flow, first
  run smoke tests, and crash/log diagnostics are reproducible from repository
  scripts and docs.

## Parity Acceptance Matrix

The following matrix defines the long-term release target. Each row needs
source-level tests plus at least one smoke or integration proof before the
project can claim release parity.

| Area | Hanako/Hermes-level behavior | Evidence required |
| --- | --- | --- |
| Daily desktop entry | Natural-language requests such as "open Linear and read the buttons" or "play this song in Music" produce discover/operate/verify tool plans. | Planner tests, Chat route tests, and a desktop smoke that records tool calls. |
| Generic app operation | Unknown app names use `desktop.list_apps`, window focus, UI inspection, and foreground tools instead of a new hardcoded branch. | Runtime planner tests and manual smoke logs for at least three non-bundled apps. |
| Browser/web work | Web research and current-page extraction use browser/current-page tools and artifacts before suggesting manual browser steps. | Browser route tests, artifact snapshot tests, and UI smoke. |
| Data analysis | CSV/XLSX/JSON/text-table inputs become analysis/report/chart artifacts; spreadsheet apps open only when requested. | Data planner tests, artifact readback tests, and sample dataset smoke. |
| Approval safety | Send/submit/delete/overwrite/shell/system-risk actions create approval cards, preserve pending input, and resume with prior context. | Approval route tests, Chat card smoke, and Run Timeline replay checks. |
| Agent Studio debug | Studio displays intent, capabilities, plan, tool calls, approvals, artifacts, memory/skill traces, and replay pages. | Studio service tests and Agent Studio smoke scripts. |
| Groups and Workflow | GroupRun and Workflow share the planner/runtime event vocabulary and remain first-class Studio surfaces. | Group/Workflow service tests and UI smoke scripts. |
| Release packaging | A user can install, grant permissions, run first task, collect diagnostics, and understand rollback/update steps. | Packaging docs, first-run smoke, release checklist, and signed/unsigned artifact proof. |

Current Browser/Web planner artifact evidence is reproducible with
`python scripts/smoke_browser_planner_artifacts.py`; this proves the planner
selects browser tools and expected artifacts, while real browser/CDP execution
remains covered by later UI or opt-in integration smoke evidence.

Current desktop discovery/operate planner evidence is reproducible with
`python scripts/smoke_desktop_planner_discovery.py`; this proves arbitrary app
names and app-scoped click/type requests plan through `desktop.list_apps`,
app foreground tools, verification steps, and Studio-routable events.

Current approval/policy source evidence is reproducible with
`python scripts/smoke_approval_policy_gate.py`; this proves planner-facing
low-risk app/browser reads stay unblocked while medium-risk desktop/browser
interaction and high-risk runtime tools remain marked for approval by the
planner, group policy, and legacy runtime policy compiler. Real approve/resume
replay remains a later Run Timeline and UI smoke requirement.

Current source-level approval resume replay evidence is reproducible with
`python scripts/smoke_approval_resume_timeline.py`; this proves Chat and Agent
Studio public services can project the same fake-port lifecycle from pending
approval to approved tool completion, including event-page replay, approval
resolution, completed tool call, and artifact metadata. Packaged-app and real
NativeRunEngine approval resume remain later smoke requirements.

Current runtime-level approval resume evidence is reproducible with
`python scripts/smoke_runtime_approval_resume.py`; this drives the real
`RuntimeApprovalExecutionService` and `ApprovalResumeCoordinator` with fake
callbacks to prove claim, running projection, approved tool execution,
remaining-tool follow-up, continuation projection, duplicate-claim suppression,
next-approval projection, and fatal tool failure projection. It does not
replace real provider or packaged-app smoke evidence.

Current route-level approval boundary evidence is reproducible with
`python scripts/smoke_yachiyo_route_approval.py`; this calls the Chat task and
Agent Studio run approval route handlers with fake services to prove route
metadata, `approval_id`, event-page bounds, public task/run snapshots, and
artifact readback shape are preserved at the shared entrypoints. It does not
replace packaged renderer, native provider, or full `NativeRunEngine` evidence.

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
- Sample dataset artifact readback is reproducible with
  `python scripts/smoke_data_analysis_artifacts.py --workdir tmp/data-analysis-artifact-smoke`.

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

## Phase 11 - Release Productization

Turn the runtime migration into a product that can be installed and diagnosed
by someone who is not reading the source tree. This phase is not a runtime
rewrite; it packages the working surfaces and makes permission/setup failures
recoverable.

Exit evidence:

- macOS packaging, app identity, signing/notarization or documented unsigned
  install, and update/rollback steps are reproducible.
- First-run onboarding explains Screen Recording, Accessibility, Automation,
  Music/Media, browser/CDP, workspace, model profile, and tool approval
  permissions.
- A release smoke script covers launch, Chat desktop task, approval card,
  Agent Studio run timeline, GroupRun, Workflow, artifact readback, and
  diagnostics export.
- User-facing docs cover daily Chat, Bubble/Live2D, Agent Studio, Groups,
  Workflow, permissions, troubleshooting, and safe rollback.
- Crash/log diagnostics can be collected without exposing secrets.

## Phase 12 - Public Project Release

Make Oha-Yachiyo publishable as a complete project rather than a private
feature branch.

Exit evidence:

- README, user manual, architecture notes, release notes, and contribution
  guide describe the supported product shape and non-goals.
- Demo scripts show Hanako/Hermes-level flows: arbitrary app operation, data
  analysis artifact, browser research, approval resume, GroupRun, Workflow,
  and Studio replay.
- CI or documented local release gates run the core Python tests, route/API
  tests, UI smokes, packaging smoke, and security/secret checks.
- Legacy route compatibility and DB schema invariants are explicitly verified
  before release.
- The release checklist states known limitations honestly and does not claim
  capabilities that lack current smoke or integration evidence.

## Non-Negotiable Guards

- 禁止删除 Agent Studio。
- 禁止删除 Groups, multi-agent, Workflow, or Run Timeline behavior。
- 禁止一次性重写 NativeRunEngine。
- 禁止改数据库 schema。
- 禁止破坏旧 route response shape。
- 禁止绕过 approval/policy gate。
- 禁止大规模格式化。
- 禁止发布时夸大能力；没有测试、smoke 或实际运行证据的能力只能列为 roadmap。
