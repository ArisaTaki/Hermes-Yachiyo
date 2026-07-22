# Contributing to Oha-Yachiyo

Oha-Yachiyo is a desktop-first local Agent app. Contributions should move the
project toward a packaged, diagnosable, user-facing desktop product, not back to
an external-kernel wrapper.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

source ~/.nvm/nvm.sh
nvm use 20.19.0
npm --prefix apps/frontend install
```

Run the app from source:

```bash
oha-yachiyo
```

## Non-Negotiable Product Boundaries

Do not remove or degrade:

- Chat Window, Bubble, or Live2D daily entry points.
- Agent Studio.
- Groups, multi-Agent, Workflow, or Run Timeline behavior.
- Runtime observability for Run, RunEvent, ToolCall, Approval, Artifact, Memory,
  Skill, Workflow, and GroupRun.
- Approval and policy gates for high-risk actions.
- Legacy route response shapes.
- Existing database schema compatibility.

Avoid large formatting-only changes. Keep edits focused and reversible.

## Safety and Privacy

- Never commit API keys, tokens, credentials, or `.env` values.
- Route logs, artifacts, UI errors, crash text, and diagnostics through the
  shared secret-redaction helpers.
- Do not print raw provider tool arguments or raw model errors when they may
  contain secrets.
- Do not add network calls or external services without a clear product reason.

## Testing Expectations

Run focused tests for the area you touched. For release-facing changes, also
run:

```bash
python scripts/verify_release_artifacts.py
python scripts/verify_secret_redaction.py
```

For Agent runtime changes, prefer tests that prove both behavior and public
observability: task snapshots, RunEvent replay, approval cards, artifacts,
Workflow, GroupRun, and Agent Studio projections.

For frontend changes, run the relevant smoke script or browser check. Keep
stable `data-testid` selectors for user-facing workflows.

## Release-Facing Changes

Before calling a change release-ready, check:

- [docs/public-release-readiness.md](docs/public-release-readiness.md)
- [docs/release-packaging.md](docs/release-packaging.md)
- [docs/user-manual.md](docs/user-manual.md)

The local RC helper produces the evidence bundle maintainers use for signoff:

```bash
python scripts/refresh_local_rc_signoff.py --channel experimental --repository kuguya-AI-app-develop/Hermes-Yachiyo
python scripts/refresh_local_rc_signoff.py --print-status
```

For public demo evidence, start with the safe source-level demo runner:

```bash
python scripts/run_public_demo_smokes.py --output-json tmp/public-demo-smokes.json --output-markdown tmp/public-demo-smokes.md
```

Use `--include-real-desktop-open`, `--include-real-desktop-ui-inspection`, and
`--include-real-desktop-interaction` when collecting real desktop evidence in
smaller batches. Use `--include-real-desktop` only when the environment is ready
to run all real app operation smokes. `--include-provider-workflow` and
`--include-ui` require live provider calls and Electron UI smokes.

If a capability lacks current source, provider, packaged, UI, or manual
evidence, document it as a limitation or roadmap item instead of presenting it
as shipped.

## Pull Request Notes

Summaries should state:

- What changed.
- Which public surfaces are affected.
- Tests and smokes run.
- Remaining risks or manual checks.
- Rollback notes when the change affects packaging, persistence, or local data.
