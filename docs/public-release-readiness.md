# Oha-Yachiyo Public Release Readiness

This page is the public-project release checklist for Oha-Yachiyo. It is
intended for maintainers preparing a release, contributors checking whether a
change is release-facing, and users who need an honest view of what is supported
today.

## Supported Product Shape

Oha-Yachiyo is a desktop-first local personal Agent app.

Supported first-class surfaces:

- Chat Window for daily conversation and task entry.
- Bubble and Live2D as desktop entry points into the shared Chat runtime.
- Agent Studio for Agent definitions, skills, Groups, Workflow, Run Detail,
  approvals, artifacts, and replay.
- Native Agent runtime inside this repository, backed by `NativeRunEngine`,
  model profiles, `ToolBroker`, policy gates, approvals, artifacts, memory,
  skills, workflow runs, and group runs.
- Local Bridge APIs bound to loopback for the frontend and optional integrations.

The project should not require a separate external execution kernel for normal
Agent tasks. Release packages should not require users to have a global Python,
Node.js, or editable checkout.

## Known Limitations

Do not claim these as completed release capabilities unless the current RC
evidence proves them:

- macOS is the primary packaged target. Windows and Linux are still source-first
  or developer-targeted until they have their own packaged smoke evidence.
- Unsigned or self-signed macOS builds still require documented Gatekeeper
  first-launch handling.
- Screen Recording, Accessibility, Automation, browser/CDP, model profile, and
  workspace permissions may require user action before desktop tasks work.
- Real provider smokes require `OHA_YACHIYO_SMOKE_BASE_URL`,
  `OHA_YACHIYO_SMOKE_MODEL`, and `OHA_YACHIYO_SMOKE_API_KEY`.
- High-risk actions still require approval. A release must not bypass
  approval/policy gates to look more autonomous.
- A capability is roadmap-only when it lacks source, provider, packaged, UI, or
  manual evidence in the current release candidate.

## Demo Flows

Before presenting Oha-Yachiyo as Hanako/Hermes-level desktop execution, collect
evidence for these flows:

| Flow | Evidence |
| --- | --- |
| Arbitrary app operation | `desktop_planner_discovery_smoke` for source-level discover/operate/verify planning, `real_desktop_discovery_smoke` for non-mutating installed-app discovery, plus `real_desktop_*` smokes or RC capability matrix entries for app open, UI inspection, and interaction. |
| Data analysis artifact | `data_analysis_artifact_smoke` and artifact readback evidence. |
| Browser research | `browser_planner_artifact_smoke` evidence. |
| Approval resume | `approval_resume_timeline_smoke`, `runtime_approval_resume_smoke`, and route approval evidence. |
| GroupRun | `group_run_timeline_smoke` and Agent Studio GroupRun replay evidence. |
| Workflow | `workflow_run_timeline_smoke` WorkflowRun replay evidence, native Workflow full-chain provider smoke, and Workflow UI smoke evidence. |
| Studio replay | Run Detail / Agent Studio UI smoke plus RunEvent replay evidence. |
| Diagnostics export | `collect_release_diagnostics.py` bundle manifest and `release-smoke` diagnostics item. |

The public demo smoke runner is the maintained entry point for this checklist:

```bash
python scripts/run_public_demo_smokes.py \
  --output-json tmp/public-demo-smokes.json \
  --output-markdown tmp/public-demo-smokes.md
```

By default it runs only safe demos: data analysis artifact, browser research
artifact planning, desktop planner discovery, Chat/Agent desktop execution
entrypoints, Agent data analysis entrypoint, non-mutating real desktop app
discovery, approval resume, Yachiyo approval route evidence, GroupRun replay,
and WorkflowRun replay. Full Hanako/Hermes-level demo evidence requires explicit
opt-in:

```bash
python scripts/run_public_demo_smokes.py \
  --include-real-desktop \
  --include-provider-workflow \
  --include-ui \
  --output-json tmp/public-demo-smokes-full.json \
  --output-markdown tmp/public-demo-smokes-full.md
```

Use `--include-real-desktop-open`, `--include-real-desktop-ui-inspection`, and
`--include-real-desktop-interaction` to collect the real desktop evidence in
smaller batches. `--include-real-desktop` remains the umbrella flag for all
three. These real desktop flags open or operate macOS apps,
`--include-provider-workflow` requires live provider smoke credentials, and
`--include-ui` starts Vite/Electron UI smokes. A default run can pass selected
source demos while still reporting `complete=false` until opt-in flows pass.
If the provider credentials are not configured, the Workflow provider smoke
writes `skipped=true`, `reason=provider_smoke_credentials_missing`, and the
missing `OHA_YACHIYO_SMOKE_*` variable names as release blocker evidence instead
of treating the local host as a product failure.
When the host can capture only a blank/black screen, `screen.capture` records
`visibility_status=blank_black` and `blocking_condition=screen_capture_blank`,
so release evidence does not treat an unobservable desktop as actionable UI.
The UI opt-in flows write per-flow JSON reports for Agent Studio Run Detail
replay and Workflow save/run replay, so release blockers retain the UI smoke
`stage`, `mode`, and boolean checks instead of only the shell exit code.
The JSON and Markdown summaries include `release_level`,
`missing_required_flow_ids`, and `release_blockers`: a public release needs
`release_level=full_public_demo_ready`; `partial_demo_ready` means the safe
default demos passed but required real desktop, provider, or UI evidence is
still missing.
When evidence is collected in batches, pass previous public-demo JSON files back
to the gate or local RC refresh helper with `--public-demo-report`. The gate,
`refresh_local_rc_signoff.py`, and release-smoke summary merge only flows that
actually passed, so a successful real app-open batch remains credited while
blocked UI inspection, interaction, provider, or UI flows stay in Next Actions.

The release-smoke summary is the quickest user-path view:

```bash
SHORT_COMMIT="$(git rev-parse --short=8 HEAD)"
python scripts/summarize_release_smoke.py \
  "tmp/rc-verification-${SHORT_COMMIT}-source-capabilities.json" \
  "tmp/rc-verification-${SHORT_COMMIT}-packaged-batch.json" \
  "tmp/rc-verification-${SHORT_COMMIT}-screen.json" \
  "tmp/rc-verification-${SHORT_COMMIT}-public-demo.json" \
  --diagnostics-zip "tmp/oha-yachiyo-diagnostics-${SHORT_COMMIT}.zip" \
  --output-json "tmp/rc-verification-${SHORT_COMMIT}-release-smoke.json" \
  --output-markdown "tmp/rc-verification-${SHORT_COMMIT}-release-smoke.md"
```

When the public demo report is partial or blocked, release-smoke keeps the
`public_demo` item incomplete and carries through the demo `release_level`,
missing flow IDs, and blocker details so release notes do not have to infer
what evidence is still absent. Equivalent RC capability evidence is also
projected into public-demo coverage for flows such as real app open, real UI
inspection, and real app interaction; provider and UI flows still need their own
smoke evidence. The archived `release/electron-ui-smoke.json` report is
projected only when the exact Run Detail / Workflow UI smoke scripts pass:
`scripts/smoke_agent_run_detail_ui.mjs` can cover `studio_replay_ui`, and
`scripts/smoke_workflow_save_run_ui.mjs` can cover `workflow_ui`. Generic
packaged UI sampling does not replace those behavior-level UI flows, and
provider workflow is projected only from live provider evidence: a passed
`provider_smoke` section whose `native_workflow_full_chain` check exited cleanly
with `summary.ok=true`, or the standalone
`scripts/smoke_native_workflow_full_chain.py` report. Local fake provider
contract evidence does not replace this release-facing provider flow.

## Local Release Gates

Run these before calling a local build release-ready:

```bash
python scripts/run_public_release_gate.py \
  --output-json tmp/public-release-gate.json \
  --output-markdown tmp/public-release-gate.md
python scripts/verify_release_artifacts.py
python scripts/verify_secret_redaction.py
python scripts/refresh_local_rc_signoff.py --channel experimental --repository kuguya-AI-app-develop/oha-yachiyo
python scripts/refresh_local_rc_signoff.py --print-status
```

`run_public_release_gate.py` is the cheap public-release preflight. By default
it runs release artifact guards, secret redaction, Agent market-parity evidence,
Planner-to-runtime tool parity, focused release pytest, and the safe public demo
smoke, then writes a non-blocking release-smoke assessment to
`tmp/public-release-gate/release-smoke.json`. A partial public demo or
incomplete release-smoke checklist keeps the report at
`status=needs_release_evidence` while still returning success if no command
failed; add `--require-release-ready` for final release signoff so missing
public-demo flows or missing 9-item release-smoke evidence make the command
fail. Existing RC reports and diagnostics bundles can be folded into the same
assessment with repeated `--release-smoke-report` and `--diagnostics-zip`
arguments.

When release evidence is still external, the gate also writes
`external_requirement_count` and `external_requirements` in the JSON report and
an `External Requirements` section in Markdown. These fields group the remaining
work into actionable classes such as `real_desktop_smoke_opt_in` and
`provider_smoke_credentials`, including missing public-demo flow IDs, missing
provider environment variables, blocking conditions, and rerun commands.
External JSON reports passed through `--release-smoke-report` or
`--public-demo-report` are also checked against the current Git HEAD when they
include `source_revision.commit` or packaged `build_metadata.commit`; stale
evidence is reported as `external_report_freshness` release evidence, not
silently treated as current release proof.

When collecting opt-in evidence incrementally, the same gate can pass through
granular public-demo flags such as `--include-real-desktop-open`,
`--include-real-desktop-ui-inspection`, `--include-real-desktop-interaction`,
and `--include-ui`. This lets maintainers archive a passing real app-open or
Studio UI replay result without forcing every foreground interaction smoke to
run in the same session. When the public demo remains partial, the gate's Next
Actions are grouped by dependency class such as real desktop, provider, and UI;
each command uses only the missing flow flags when they are known, and falls
back to the full-demo command only for unknown future flows.

The macOS release workflow keeps the default preflight safe on push builds. For
manual release-candidate runs, set the `public_demo` workflow input to `full` to
pass `--include-real-desktop --include-provider-workflow --include-ui` into the
preflight after frontend dependencies are installed.

`refresh_local_rc_signoff.py` builds/refreshes the current local RC evidence,
generates the Native Agent capability matrix, writes release readiness
diagnostics, exports a redacted diagnostics bundle, summarizes release-smoke
user paths, writes `tmp/rc-verification-${SHORT_COMMIT}-public-demo.json` and
`tmp/rc-verification-${SHORT_COMMIT}-public-demo.md`, and writes signoff drafts.
`--print-status` also prints the public-demo release level, missing required
demo flows, and blocker hints when those reports exist. If the current commit's
signoff draft is missing, `--print-status` lists the latest available signoff,
readiness, release-smoke, and public-demo evidence before printing the
`--reuse-current-reports` refresh command for the current commit.
If the final signoff is still blocked by manual Gatekeeper or Screen Recording
checks, that is a remaining release task, not a failure to hide.

## Diagnostics Bundle

When a maintainer needs support evidence, collect a redacted bundle:

```bash
SHORT_COMMIT="$(git rev-parse --short=8 HEAD)"
python scripts/collect_release_diagnostics.py \
  --label "$SHORT_COMMIT" \
  --include-app-logs \
  --output-zip "tmp/oha-yachiyo-diagnostics-${SHORT_COMMIT}.zip"
```

The bundle includes `diagnostics/manifest.json`. It records included and skipped
files, applies `packages.security` redaction, skips binary or oversized files,
and fails closed for files that still look secret-like after redaction.

## Release Notes

Use the release workflow or changelog helper to generate notes from git history.
Release notes must distinguish:

- Shipped capabilities with current evidence.
- Known limitations.
- Manual permission steps.
- Breaking changes or migration notes.
- Rollback steps and diagnostics collection.

## Contributor Boundary

See [CONTRIBUTING.md](../CONTRIBUTING.md). Release-facing contributions must
preserve Agent Studio, Groups, Workflow, Run Timeline, approval gates, legacy
route response shapes, and database schema compatibility unless a dedicated
migration plan and tests exist.
