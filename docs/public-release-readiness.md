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

## Bundled macOS Background Driver Contract

The macOS release carries Cua Driver as an Oha-Yachiyo sidecar. End users must
not install `CuaDriver.app`, a global CLI, or a pip package, and the installed
app must not download this executable at runtime. The release build reads
`packaging/cua-driver.lock.json`, verifies the pinned official archive and
license SHA256 values, and prepares exactly these package inputs:

```text
dist/cua-driver/macos/cua-driver
dist/cua-driver/macos/LICENSE.md
dist/cua-driver/macos/manifest.json
```

They are shipped at `Contents/Resources/computer-use/macos/`. A packaged app
uses only that executable. The Electron main process, rather than the Python
backend or a separately installed gateway, directly starts it as
`cua-driver mcp --embedded --host-bundle-id io.github.arisataki.oha-yachiyo`.
The Python backend talks to that child only through an authenticated loopback
line-delimited JSON bridge. The bridge credential and non-secret generation id
rotate on every backend restart; it permits at most one long-lived execution
session plus one short health-probe session. Backend restart and application
exit close the sessions and terminate their driver children.

In packaged mode the bridge transport sentinel is authoritative. A missing
component, failed listener, or malformed bridge configuration fails closed and
cannot fall back to `PATH`, a custom command, or an unrelated machine-wide
installation. No driver is downloaded at runtime. Source development without
that sentinel may still use the explicit-command, `PATH`, or installed Cua
Driver fallback. This process layout establishes the intended Oha-Yachiyo
responsibility chain, but the exact final package still requires the real TCC
checks below before permission attribution is claimed as verified.

This is targeted background event delivery in the current macOS login session,
not a VM, remote desktop, isolated cursor, or separate keyboard. Release copy
must not imply stronger isolation. Targeted background support also depends on
the Cua API and the target application's accessibility/event behavior; an
unsupported app or operation must fail without a foreground fallback. The
exact packaged RC must demonstrate that supported background operations do not
steal the user's foreground focus, pointer, or keyboard.

CI prepares the locked component before packaging and runs its focused tests.
The release verifier and packaged-app workflow gate require the executable,
license, and manifest to be regular non-symlink files; validate the executable
bit, lock/license/manifest consistency, version, embedded invocation contract,
and universal `arm64` plus `x86_64` architectures; and verify the nested binary
signature. An offline build must supply the
hash-matching archive and license through the build cache or the prepare
script's `--archive` and `--license` inputs together with `--offline`.

The sidecar must not inherit Electron's JIT entitlements. Electron packaging
skips only the exact Cua Driver resource path. Every release mode then treats
the nested driver as a separate signing unit: sign it first with
`packaging/entitlements.cua-driver.plist`, then sign the outer app. The final
driver entitlement dictionary must contain exactly Apple Events and Screen
Capture;
`allow-jit`, `allow-unsigned-executable-memory`, and
`disable-library-validation` are forbidden on the driver. Certificate-free
builds use the same order with ad-hoc identities, so every release mode can
require a valid sidecar signature, exact sidecar entitlements, and deep strict
app signature.

In addition to the archive and license hashes, the lock pins a
`mach-o-without-code-signature-v1` canonical content SHA256. Electron/codesign
may legitimately rewrite raw Mach-O signature bytes, so the verifier removes
the signature only from a temporary copy and never mutates the packaged
original. The upstream binary contains Hermes compatibility help text; the
legacy-token scan exemption applies only to the exact bundled resource path
above and remains guarded by this canonical hash.

To upgrade the driver, review the new upstream release and license, update all
version/tag/URL/SHA256/architecture fields in the lock as one change, run
`python scripts/prepare_cua_driver.py --clean`, run the focused runtime and
distribution tests, build with `npm --prefix apps/frontend run pack:mac`, and
verify the resulting app. Never update an untracked `dist/` binary by hand as
the source of a release.

The following checks remain mandatory for every exact final macOS package. Do
not mark them passed from source tests alone:

- Install the RC at its intended stable path. In Screen Recording and
  Accessibility, only Oha-Yachiyo should need to be present and authorized;
  CuaDriver, Python, and Terminal should not be required.
- After reinstalling or changing the app signature, remove a stale
  Oha-Yachiyo TCC entry when necessary, add the current app again, grant it,
  and restart the app.
- Confirm embedded permission status reports the host bundle id
  `io.github.arisataki.oha-yachiyo` and host attribution.
- Run a non-destructive open/read/search-or-input/verify task while observing
  the current foreground app, pointer, and keyboard; none may be taken over.
- Revoke or deny a permission and confirm the app reports an actionable
  permission blocker instead of an Oha-Yachiyo execution failure or silent
  foreground fallback.

These source and packaging contracts do not claim that the outstanding real
macOS TCC checks for the current final package have already passed.

## Runtime Maturity Invariants (2026-07-12 Worktree)

The current worktree has a stronger runtime-safety baseline, but this section
is not a claim that the application is fully delivered or that a release
candidate has passed every gate. The following invariants are covered by
focused tests or smokes in this worktree:

- **Public progress, not chain of thought.** Raw model reasoning is filtered
  from Chat and task projections. Daily surfaces render compact structured
  progress, approval state, results, and failure/recovery facts; detailed
  execution evidence remains lazy in task cards and Run Timeline instead of
  being dumped into the conversation.
- **Fail-closed completion.** The shared `OutcomeEvaluator` requires fresh,
  correlated RunEvent and tool evidence for the current attempt, step, target,
  and app. Missing or malformed event history, an empty UI observation,
  `count=0`, a mismatched app/target, or a generic `ok=true` cannot complete a
  desktop task. Direct daily-desktop completion uses the same evaluator.
- **Generation-fenced approval transitions.** Approval approve/reject/cancel
  and resume paths use the current `approval_id`, approval generation, and
  compare-and-set Run transitions. A stale approval, late pause projection, or
  losing terminal transition cannot resurrect a cancelled/completed Run or
  project a result for a different generation. Workflow Run and Group
  transitions use status/version CAS, and their durable transition events
  validate the expected Run status/version inside the event-write transaction.
- **Atomic local lifecycle commits.** Nested repository transactions share one
  locked SQLite connection, become rollback-only after an inner failure, and
  commit Run state, approval state, durable events, task links, and local
  projections together in the lifecycle paths covered by the regression
  matrix. Crash-injection tests exercise rollback and retry rather than relying
  only on happy-path ordering.
- **One live runtime owner.** Async executions use durable leases, heartbeat,
  takeover, and generation fencing. The desktop host also uses a runtime
  process lock and Electron single-instance guard. Startup reconciliation runs
  once per owning process, preserves still-valid approvals, and reclaims or
  resolves interrupted ownership from durable state.
- **One recovery owner per action.** Recovery requests have a stable identity
  derived from their source step, action tool, and normalized input. A
  continuation already consumed by the runner is not dispatched again by the
  outer loop, and repeated observation/recovery actions are suppressed until
  new user, model, or tool evidence exists.
- **Canonical activity recovery.** Startup reconciliation repairs terminal and
  orphaned Activity rows from authoritative task/Run links and keeps retry
  semantics idempotent instead of leaving a second, conflicting activity
  state machine behind.
- **Server-authoritative approval UI.** Chat and Agent Studio wait for the
  approval mutation response before clearing local cards. Conflict or network
  failure triggers an authoritative refresh while retaining the current card;
  retries reuse the real `approval_id`. Missing or stale IDs remain visible but
  non-actionable instead of being replaced with a fabricated Run/child ID.

Focused evidence actually run for this worktree includes:

- The final runtime regressions passed `348/348` in the main Agent-runtime
  file, `331/331` in the custom API Agent loop, `222/222` across tool execution
  and the native OutcomeEvaluator, `543/543` across planner and desktop hints,
  and `284/284` in the complete Chat API file. The daily-desktop and legacy
  port matrix passed `241/241` after its final semantic-verifier expectation
  was aligned.
- Source release verification completed with exit code `0`. All maintained
  source guards and source smokes passed, including desktop planner discovery,
  planner/runtime tool parity, Agent entrypoint execution with zero model
  calls, approvals, workflows, groups, and the native provider contract. The
  generated report is `output/release-source-verification-final.json`.
- A fresh local experimental RC was then rebuilt from this worktree. Artifact
  guards, DMG mount, packaged App startup, packaged Bridge identity/isolation,
  Gatekeeper diagnostics, packaged UI sampling, Chat native-file IPC, and
  revision guards all passed. The required Native Agent capability matrix is
  `29/29`; see `output/release-packaged-verification-final.json`. This local RC
  is ad-hoc signed and not notarized. Three of seven manual checks have
  automated evidence; Gatekeeper first launch, Screen Recording, real-provider,
  and external-integration signoff remain open.
- Frontend preservation, mature-flow, design acceptance, bundle-budget, CSP,
  and Electron single-instance contracts passed `106/106`, and
  `npm --prefix apps/frontend run build` completed successfully. The frozen
  bundle budget passes all nine measured limits; the current build's largest
  JavaScript chunk is about 271 kB, below the 600 kB release-budget ceiling.
- The opt-in macOS real-process single-instance smoke passed normal secondary
  launch plus primary `TERM`, primary `SIGKILL`, and kill-before-backend-ready
  takeover cases. The backend parent watchdog also has deterministic invalid
  owner, reparenting, missing-process, startup-order, and safe-ledger coverage.
- Seven focused Electron UI smokes passed: public task, group
  summary/replay/follow-up, Agent Studio groups, structured Agent progress,
  Run Detail replay, image attachment, and Chat approval. The approval smoke
  includes approve/reject plus a `409` authoritative refresh and same-ID retry;
  no legacy approval fallback, CSP violation, or Electron security warning was
  observed in the final runs.
- The opt-in real macOS TextEdit launch chain passed discovery, open,
  `launch_verified`, `desktop.verify`, status, and guarded cleanup. Its report
  is `output/runtime-ui-baseline/real-desktop-app-open-textedit-launch-final.json`.
  Strict foreground-action evidence was also attempted for Calculator and
  TextEdit, but the current macOS session exposed only menu-level UI and was
  correctly blocked as `foreground_focus_unavailable`; those reports are
  `output/runtime-ui-baseline/real-desktop-app-open-final.json` and
  `output/runtime-ui-baseline/real-desktop-app-open-textedit-final.json`.

These results do not replace a clean full-repository Python regression,
Developer ID signing/notarization, or the four remaining manual RC checks
below.

### P2 Work and Explicit Non-Claims

- **Post-side-effect continuation outbox:** covered local state/event/projection
  writes now share a transaction, but an external tool can succeed immediately
  before the process dies and before the next approval generation or terminal
  projection is durably queued. Recovery currently fences the stale owner and
  fails that interrupted Run rather than automatically resuming it. A durable,
  idempotent continuation outbox remains P2 work.
- **External side-effect exactly-once:** leases, generations, and idempotent
  projections prevent many duplicate local transitions, but they cannot roll
  back an OS/app/tool side effect that happened immediately before a process
  crash. Universal exactly-once execution for app launch, click/type, terminal,
  or third-party calls is not promised; operation-specific idempotency and
  postcondition verification remain required.
- **Packaged Electron lifecycle evidence:** source contracts, the runtime lock,
  parent watchdog, and opt-in real-process takeover smoke are tested, but the
  same two-instance/process-death report still needs to be archived from the
  exact signed/notarized release candidate.
- **Packaged performance evidence:** route-level lazy loading and a deterministic
  bundle budget are in place. Cold-start, first-interaction, long-conversation
  render, and memory profiling still need measurements from the packaged RC on
  the supported hardware baseline.

## Demo Flows

Before presenting Oha-Yachiyo as Hanako/Hermes-level desktop execution, collect
evidence for these flows:

| Flow | Evidence |
| --- | --- |
| Arbitrary app operation | `desktop_planner_discovery_smoke` for source-level discover/operate/verify planning, `real_desktop_discovery_smoke` for non-mutating installed-app discovery, plus `real_desktop_*` smokes or RC capability matrix entries for app open, UI inspection, and interaction. |
| Isolated desktop execution | `isolated_desktop_provider` public-demo evidence proving `open_app -> read_ui -> click_ui_element -> safe_type_text -> safe_shortcut -> verify` can run with `foreground_takeover_required=false`. |
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
discovery, isolated desktop provider discover/operate/verify routing, approval
resume, Yachiyo approval route evidence, GroupRun replay, and WorkflowRun replay. Full
Hanako/Hermes-level demo evidence requires explicit
opt-in:

```bash
python scripts/run_public_demo_smokes.py \
  --include-ui \
  --output-json tmp/public-demo-smokes-full.json \
  --output-markdown tmp/public-demo-smokes-full.md
```

Use `--include-real-desktop-open`, `--include-real-desktop-ui-inspection`, and
`--include-real-desktop-interaction` to collect the real desktop evidence in
smaller batches. `--include-real-desktop` remains the umbrella flag for all
three. These real desktop flags are optional foreground diagnostics: they open or
operate macOS apps and are no longer required for the non-invasive full public
demo baseline,
and `--allow-existing-real-desktop-app` may be added when the interaction smoke
must use an app that was already running before the smoke started.
`--include-provider-workflow` remains available as an optional live-provider
diagnostic requiring smoke credentials; the required provider path is covered by
`native_provider_contract`. `--include-ui` starts Vite/Electron UI smokes. A
default run can pass selected source demos while still reporting
`complete=false` until required UI flows pass.
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
  "tmp/rc-verification-${SHORT_COMMIT}-oha-desktop-agent-release-smoke.json" \
  "tmp/rc-verification-${SHORT_COMMIT}-public-demo.json" \
  --diagnostics-zip "tmp/oha-yachiyo-diagnostics-${SHORT_COMMIT}.zip" \
  --output-json "tmp/rc-verification-${SHORT_COMMIT}-release-smoke.json" \
  --output-markdown "tmp/rc-verification-${SHORT_COMMIT}-release-smoke.md"
```

When the public demo report is partial or blocked, release-smoke keeps the
`public_demo` item incomplete and carries through the demo `release_level`,
missing flow IDs, and blocker details so release notes do not have to infer
what evidence is still absent. Equivalent RC capability evidence is also
projected into optional diagnostic coverage for flows such as real app open,
real UI inspection, and real app interaction; required UI flows still need their
own behavior-level smoke evidence. The archived `release/electron-ui-smoke.json` report is
projected only when the exact Run Detail / Workflow UI smoke scripts pass:
`scripts/smoke_agent_run_detail_ui.mjs` can cover `studio_replay_ui`, and
`scripts/smoke_workflow_save_run_ui.mjs` can cover `workflow_ui`. Generic
packaged UI sampling does not replace those behavior-level UI flows. Provider
workflow can still be projected from live provider evidence as an optional
diagnostic: a passed `provider_smoke` section whose `native_workflow_full_chain`
check exited cleanly with `summary.ok=true`, or the standalone
`scripts/smoke_native_workflow_full_chain.py` report. `native_provider_contract`
is the deterministic required provider-path proof for the public demo baseline.

## Local Release Gates

Run these before calling a local build release-ready:

```bash
python scripts/run_public_release_gate.py \
  --output-json tmp/public-release-gate.json \
  --output-markdown tmp/public-release-gate.md
python scripts/verify_release_artifacts.py
python scripts/verify_secret_redaction.py
python scripts/refresh_local_rc_signoff.py --channel experimental --repository kuguya-AI-app-develop/Hermes-Yachiyo
python scripts/refresh_local_rc_signoff.py --print-status
```

`run_public_release_gate.py` is the cheap public-release preflight. By default
it runs release artifact guards, secret redaction, Agent market-parity evidence,
Planner-to-runtime tool parity, the Oha desktop-agent product smoke, focused
release pytest, and the safe public demo smoke, then writes a non-blocking
release-smoke assessment to
`tmp/public-release-gate/release-smoke.json`. A partial public demo or
incomplete release-smoke checklist keeps the report at
`status=needs_release_evidence` while still returning success if no command
failed; add `--require-release-ready` for final release signoff so missing
public-demo flows or missing 10-item release-smoke evidence make the command
fail. Existing RC reports and diagnostics bundles can be folded into the same
assessment with repeated `--release-smoke-report` and `--diagnostics-zip`
arguments.

The product smoke inside this gate always runs with `--public-release`. Its
ordinary `ok` field still describes deterministic product coverage, while its
process exit code follows `public_release_ready`. A successful local foreground
broker probe is diagnostic fallback coverage only and can no longer satisfy the
default daily-provider release gate. `summarize_release_smoke.py` likewise
requires `oha_default_daily_provider_release_ready`, so publication fails closed
unless the report contains either a successful configured, non-loopback virtual
desktop provider smoke or explicit packaged background-provider acceptance.

After granting Accessibility and Screen Recording to the final packaged app,
record the local CUA acceptance in a JSON file and pass it through the gate:

```bash
python scripts/run_public_release_gate.py \
  --daily-provider-acceptance-json tmp/oha-daily-provider-acceptance.json \
  --require-release-ready \
  --output-json tmp/public-release-gate.json
```

The evidence uses schema `oha-yachiyo.daily-provider-acceptance.v1` and must
identify `local_packaged_tcc_acceptance`, `background_desktop`, `cua-driver`,
the packaged `.app`, its 40-character build revision, the Oha-Yachiyo host
bundle id, and the `cua_mcp_electron_bridge` transport. Both TCC permissions
must be `authorized`; host attribution must be verified; foreground takeover
must be false; and all nine packaged bridge, background launch, target-bound
observation, background input, postcondition, foreground/pointer/keyboard
non-takeover, and permission-denial fail-closed checks must be true. A generic
`{"ok": true}` payload, source-mode run, or foreground automation result is
rejected. Create this file only after the named checks have actually passed on
the exact packaged candidate.

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
pass `--include-ui` into the preflight after frontend dependencies are
installed. Run the provider or real desktop flags separately when you explicitly
want optional live-provider or foreground diagnostics.

`refresh_local_rc_signoff.py` builds/refreshes the current local RC evidence,
generates the Native Agent capability matrix, writes release readiness
diagnostics, exports a redacted diagnostics bundle, summarizes release-smoke
user paths, writes `tmp/rc-verification-${SHORT_COMMIT}-oha-desktop-agent-release-smoke.json`,
`tmp/rc-verification-${SHORT_COMMIT}-public-demo.json` and
`tmp/rc-verification-${SHORT_COMMIT}-public-demo.md`, and writes signoff drafts.
The Oha desktop-agent smoke is collected with isolated desktop provider
evidence, so the product smoke proves that daily app/media desktop execution
does not require taking over the user's foreground mouse or keyboard.
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
