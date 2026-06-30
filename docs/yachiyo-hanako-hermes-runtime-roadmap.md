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

Current Browser/Web planner artifact evidence is reproducible with:

```bash
python scripts/smoke_browser_planner_artifacts.py \
  --report-json tmp/browser-planner-artifacts.json
```

This proves the planner selects browser tools and expected artifacts, while
real browser/CDP execution remains covered by later UI or opt-in integration
smoke evidence.

Current desktop discovery/operate planner evidence is reproducible with:

```bash
python scripts/smoke_desktop_planner_discovery.py \
  --report-json tmp/desktop-planner-discovery.json
```

This proves arbitrary app names and app-scoped click/type requests plan through
`desktop.list_apps`, app foreground tools, verification steps, and
Studio-routable events.

Current app-name resolution evidence records the normalized query, best match,
match score/confidence/reason, resolved bundle path, and
`agent.tool.input_resolved` timeline event before follow-up app tools run. This
keeps arbitrary app handling explainable in Chat and Agent Studio without
adding app-specific branches.

Current real desktop discovery evidence is reproducible with:

```bash
python scripts/smoke_real_desktop_discovery.py \
  --report-json tmp/real-desktop-discovery.json
```

On macOS this runs the real `desktop.list_apps` implementation against
installed system apps without opening them, and archives permission preflight
diagnostics. On non-macOS source checks it records skipped evidence instead of
pretending desktop execution was exercised.

Current opt-in real desktop app open evidence is reproducible with:

```bash
python scripts/smoke_real_desktop_app_open.py \
  --report-json tmp/real-desktop-app-open.json
```

On macOS this runs the real
`desktop.list_apps -> desktop.open_app -> desktop.verify -> app.status` chain
through the runtime dispatch registry against Calculator by default, then
attempts cleanup only if the app was not already running before the smoke. The
RC verifier keeps this evidence skipped by default and only runs it with
`--run-real-desktop-app-open-smoke`, so source gates do not open user apps
unless explicitly requested.

Current opt-in real desktop UI inspection evidence is reproducible with:

```bash
python scripts/smoke_real_desktop_ui_inspection.py \
  --report-json tmp/real-desktop-ui-inspection.json
```

On macOS this runs the real `desktop.open_app`, `desktop.running_apps`,
`desktop.list_windows`, `desktop.focus_app`, `desktop.active_window`,
named-app `desktop.read_ui(app_name=...)`, and `desktop.verify` path through
the runtime dispatch registry. The evidence records whether focus was actually
verified and how many menu-level or control-like UI roles were observed, so
current environment limits remain visible instead of being hidden behind a
passing smoke.

Current foreground focus diagnostics also record each low-risk activation
strategy attempted by `app.focus`: AppleScript/System Events, AppKit,
LaunchServices `open -a`, and localized Dock item activation. When the target
process is launched but still cannot become frontmost, the evidence preserves
`process_visible`, `window_count`, `frontmost_app`, `dock_status`, and
`dock_item_name`. This distinguishes "app discovery/open works" from the
remaining host-level foreground limitation.

Readiness now separates foreground activation runtime blockers from permission
gaps. `desktop.permissions` and `desktop.permission_preflight` expose
`runtime_blocking_conditions` and flattened `blocking_conditions` separately
from `permission_targets`. `foreground_focus_unavailable` and
`desktop_session_locked` are reported through capability and tool-level
metadata, so Chat, Bubble, AgentTaskCard, Diagnostics, and Agent Studio can
show that `app.open` still works while `app.focus` and foreground-input tools
are currently blocked.

The Runtime Planner now consumes those readiness blockers before execution:
blocked foreground operation steps are marked `unavailable`, the affected
capability is reported in `missing_capabilities`, and both normal and direct
planner request conversion return no executable foreground request for that
blocked chain. Discovery and verification steps remain planned when their
tools are still available, so Agent Studio can show what was discoverable
without pretending the unsafe or unavailable operation ran.

The execution broker also propagates foreground focus failures from combined
`app.*_and_*` tools as `blocking_condition(s)`, `retryable`, `recovery_actions`,
and step-level fallback evidence. That keeps failed desktop actions replayable
in Run Timeline instead of collapsing into a generic tool failure.

Semantic foreground typing now mirrors semantic clicking when an accessibility
target cannot be matched: the tool returns candidate UI controls, visibility
metadata, screenshot recovery, coordinate-focus retry schema, and a follow-up
`desktop.type_text` hint without repeating the original text in the error
payload. This gives the agent a discover -> inspect -> recover path for
unknown app input fields. The follow-up tool and sanitized follow-up input are
also part of the public recovery metadata and replay context.

The Electron desktop shell now also starts a loopback-only native runtime
bridge and injects its URL/token into the Python backend. `app.focus` can use
that bridge as an additional `electron_native_bridge` strategy after local
Python subprocess strategies fail. The bridge is intentionally scoped to
authenticated local desktop operations and preserves the same focus evidence
shape, so Agent Studio can replay whether the Electron host actually improved
foreground control. Source/CLI smokes will not show this strategy unless the
backend was launched by Electron.

Current Electron native bridge host evidence is reproducible with:

```bash
python scripts/smoke_electron_native_bridge.py \
  --report-json tmp/electron-native-bridge-smoke.json
```

This compiles the Electron main process, starts it in native-bridge smoke mode,
checks that unauthenticated loopback requests are rejected, checks that
authenticated `/status` returns the Electron native runtime service payload,
and exits without starting the full backend or opening a desktop target app.
The release verifier exposes the same opt-in gate with
`--run-electron-native-bridge-smoke`.

Focused Electron bridge evidence is reproducible with:

```bash
python scripts/smoke_electron_native_bridge.py \
  --focus-app Calculator \
  --report-json tmp/electron-native-bridge-focus-calculator.json
```

When `--focus-app` is present, the smoke records the target app's pre-run
status, requires the Electron endpoint to verify `focus_verified=true` before
passing, and cleans up the app only if the smoke launched it. Failed foreground
activation remains useful evidence: it includes each native strategy attempted,
the observed frontmost app, window count, `foreground_focus_unavailable`, and
the cleanup result.

Current opt-in real desktop interaction evidence is reproducible with:

```bash
python scripts/smoke_real_desktop_interaction.py \
  --report-json tmp/real-desktop-interaction.json
```

On an unlocked macOS session it opens a previously stopped Calculator, types a
value, reads the named app UI tree, clicks a semantic accessibility control,
and verifies the visible result changed before cleaning up. It fails before
mutation when the desktop session is locked or the app was already running,
and the RC verifier only enables it with `--run-real-desktop-interaction-smoke`.

Runtime failures can also expose a non-permission `blocking_condition` such as
`desktop_session_locked`. Chat task cards plus Bubble and Live2D launcher task
lights preserve that condition separately from `permission_targets`, show the
localized blocker and recovery hint, and keep executable recovery actions
available without claiming that the user must grant another macOS permission.

Current planner/runtime tool parity evidence is reproducible with:

```bash
python scripts/smoke_planner_runtime_tool_parity.py \
  --report-json tmp/planner-runtime-tool-parity.json
```

This proves representative planner-selected desktop, data-analysis, browser,
media, terminal, and reminder tools are present in the runtime tool registry,
dispatch table, main Chat policy, model descriptors, and approval map. It does
not replace packaged-app or OS-permission execution smoke evidence.

Current approval/policy source evidence is reproducible with:

```bash
python scripts/smoke_approval_policy_gate.py \
  --report-json tmp/approval-policy-gate.json
```

This proves planner-facing low-risk app/browser reads stay unblocked while
medium-risk desktop/browser interaction and high-risk runtime tools remain
marked for approval by the planner, group policy, and legacy runtime policy
compiler. Real approve/resume replay remains a later Run Timeline and UI smoke
requirement.

Current source-level approval resume replay evidence is reproducible with:

```bash
python scripts/smoke_approval_resume_timeline.py \
  --report-json tmp/approval-resume-timeline.json
```

This proves Chat and Agent Studio public services can project the same fake-port
lifecycle from pending approval to approved tool completion, including
event-page replay, approval resolution, completed tool call, and artifact
metadata. Packaged-app and real NativeRunEngine approval resume remain later
smoke requirements.

Current runtime-level approval resume evidence is reproducible with:

```bash
python scripts/smoke_runtime_approval_resume.py \
  --report-json tmp/runtime-approval-resume.json
```

This drives the real `RuntimeApprovalExecutionService` and
`ApprovalResumeCoordinator` with fake callbacks to prove claim, running
projection, approved tool execution, remaining-tool follow-up, continuation
projection, duplicate-claim suppression, next-approval projection, and fatal
tool failure projection. It does not replace real provider or packaged-app smoke
evidence.

Current route-level approval boundary evidence is reproducible with:

```bash
python scripts/smoke_yachiyo_route_approval.py \
  --report-json tmp/yachiyo-route-approval.json
```

This calls the Chat task and Agent Studio run approval route handlers with fake
services to prove route metadata, `approval_id`, event-page bounds, public
task/run snapshots, and artifact readback shape are preserved at the shared
entrypoints. It does not replace packaged renderer, native provider, or full
`NativeRunEngine` evidence.

Current source-level GroupRun timeline evidence is reproducible with:

```bash
python scripts/smoke_group_run_timeline.py \
  --report-json tmp/group-run-timeline.json
```

This proves Agent Studio can start, list, fetch, and replay a GroupRun public
snapshot with participants, child run timelines, tool calls, pending approvals,
shared artifacts, and paginated group events preserved at the service boundary.
It does not replace packaged Agent Studio UI or real multi-agent provider
evidence.

Latest source-only release-candidate baseline, verified on June 30, 2026:

```bash
python scripts/verify_release_candidate.py --source-only \
  --report-json tmp/source-only-rc.json
```

The source-level Electron native bridge auth/status gate can be included
without checking stale packaged artifacts:

```bash
python scripts/verify_release_candidate.py --source-only \
  --run-electron-native-bridge-smoke \
  --report-json tmp/source-only-electron-bridge-rc.json
```

The low-risk real app open gate can also be included in source-only mode:

```bash
python scripts/verify_release_candidate.py --source-only \
  --run-real-desktop-app-open-smoke \
  --report-json tmp/source-only-real-app-open-after-runtime-blockers.json
```

This passed the current source release guards, data-analysis artifact smoke,
browser planner artifact smoke, desktop planner discovery smoke, real desktop
discovery smoke, real desktop app open smoke when requested, Electron native
bridge auth/status smoke when requested,
planner/runtime tool parity smoke, approval policy gate smoke, approval resume
timeline smoke, runtime approval resume smoke, Yachiyo route approval smoke,
and GroupRun timeline smoke. It intentionally skipped opt-in or
artifact-dependent gates: real desktop UI inspection/interaction, real Electron
focus-app bridge attempts, built artifacts, DMG
launch/screen/UI/native-file checks, real provider smoke, UI smokes, and manual
release-candidate checks. Passing this baseline proves the source-level
planner/runtime contracts are currently coherent; it is not release parity
until the skipped packaged, provider, real desktop, and manual evidence is
supplied.

Latest local real UI inspection and interaction attempts on June 30, 2026
opened Calculator successfully but stopped at `app.focus` because macOS
reported `desktop_session_locked`. The interaction smoke failed before any
typing or clicking and cleaned up Calculator, which is the intended guarded
behavior until the foreground session is unlocked and the smoke can prove the
full type -> inspect -> click -> verify loop. Both opt-in smoke reports now
surface that blocker at the top level as `error`, `blocking_condition(s)`,
`recovery_hints`, and `recovery_actions`, so release reports and Studio-style
debugging do not have to parse nested tool output to explain the failure.

Current opt-in OpenAI-compatible provider stream evidence is reproducible, when
`OHA_YACHIYO_SMOKE_*` credentials are configured, with:

```bash
python scripts/smoke_openai_compatible_stream.py \
  --report-json tmp/provider-stream.json
```

This validates streaming provider compatibility, including text chunks,
reasoning chunks when required, tool-call streaming, finish reasons, and
synthetic tool-result follow-up. The report writer fails closed if the summary
would contain sensitive provider text.

Current opt-in Native Agent full-chain provider evidence is reproducible, when
`OHA_YACHIYO_SMOKE_*` credentials are configured, with:

```bash
python scripts/smoke_native_agent_full_chain.py \
  --report-json tmp/native-agent-full-chain.json
```

This exercises model profile readiness, workspace read, artifact write,
multi-tool planning, Workflow child execution, terminal approval resume, and
main Chat model-loop execution against a real OpenAI-compatible provider. The
report writer uses the same redacted summary as stdout and fails closed if
sensitive provider text would be emitted.

Current opt-in advanced Workflow provider evidence is reproducible, when
`OHA_YACHIYO_SMOKE_*` credentials are configured, with:

```bash
python scripts/smoke_native_workflow_full_chain.py \
  --report-json tmp/native-workflow-full-chain.json
```

This exercises advanced Workflow orchestration with real OpenAI-compatible
model calls, including child workflow execution, condition routing, approval
pause/resume, parallel/loop nodes, artifact output, and workflow budget
boundary evidence. The report writer uses the same redacted summary as stdout
and fails closed if sensitive provider text would be emitted.

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
- Model follow-up RunEvents preserve all supported observed context snapshots
  in `content_snapshots` while keeping `content_snapshot` as the compatible
  latest-snapshot field for older consumers.
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
- Real macOS smoke evidence proves whether the Python subprocess path can
  foreground a target app; if it cannot, packaged Electron smoke evidence must
  verify whether the `electron_native_bridge` strategy can own the granted
  desktop permissions instead of hiding the failure behind app-specific rules.

## Phase 6 - Data Analysis Capability

Add a stable data-analysis path for CSV, XLSX, JSON, and text-table inputs.
Prefer Python/pandas or built-in parsers and produce Markdown, HTML, CSV,
chart, or report artifacts. Open Excel/Numbers only when explicitly requested
or when the plan requires UI inspection.

Exit evidence:

- Data-source hints produce `workspace.read`/analysis/artifact plans.
- Artifacts are observable and readable through existing task/run surfaces.
- CSV, JSON, text-table, and XLSX sample dataset artifact readback is
  reproducible with:

  ```bash
  python scripts/smoke_data_analysis_artifacts.py \
    --workdir tmp/data-analysis-artifact-smoke \
    --report-json tmp/data-analysis-artifacts.json
  ```

  The smoke also archives the `data.analyze` follow-up context snapshot for
  every source kind, so Agent Studio/Run Timeline can replay rows, columns,
  source kind, and generated artifact paths without relying on private tool
  output.

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
