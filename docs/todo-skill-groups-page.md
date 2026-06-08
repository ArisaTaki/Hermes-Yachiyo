# TODO: Skill Groups Page

## Current State

- Agent Studio no longer exposes `Skill Groups` as a top-level tab; it is now a secondary page inside `Skill Library`.
- `Skill Library` has local navigation for `Skills 列表` and `分组管理`.
- Legacy `#/agents/skill-groups` links still open the `Skill Library > 分组管理` view; existing `#/agents/<run_id>` links still open Runs detail.
- `Skill Library` left panel only chooses the target folder for install/upload.
- Existing folder CRUD is backed by `/ui/skill-folders` and `AgentRuntimeService`.
- Deleting a folder moves its skills back to `无需分组`.
- Folder deletion can optionally delete contained skills through the grouped delete control; counts come from the backend folder summary.
- Agent Mounted Skills can filter by folder and bulk select/clear the current filter.
- Folder create/rename rejects duplicate names and names longer than 120 characters; the UI shows inline validation copy.
- Destructive and interruption-prone frontend actions now use the shared `ConfirmDialog` instead of `window.confirm`.
- The default `无需分组` group now splits counts into total / Yachiyo / Hermes.
- Latest implementation commit: `bb4436b feat(agent): finish skill groups todo`.

## Product Decisions To Revisit

- Final UI structure decided: `Skill Groups` is a secondary `Skill Library > 分组管理` page, not a top-level Agent Studio module.
- Current visible naming is `Skill 分组` / `分组管理`.
- Yachiyo and Hermes Agent skills remain separated by source filter. Yachiyo-installed/uploaded skills are user-managed; Hermes Agent skills are scanned references.
- `source_scope` remains an internal backend field for now; the UI should not expose it until there is a concrete user-facing rule.

## Remaining Implementation TODO

- Decide whether folder sorting should become user-controlled instead of only stored in the data model.
- If sorting becomes user-controlled, wire `sort_order` into the Skill Groups UI with move up/down controls and keep the default order stable.
- If Hermes Agent skills should stay read-only, prevent assigning Hermes skills to Yachiyo groups in the Skill card selector and document that boundary in the UI.
- Keep future destructive actions on the shared `ConfirmDialog`; `window.confirm` should not be reintroduced.

## Remaining Test TODO

- Add frontend smoke coverage for:
  - opening `Skill Library > 分组管理`;
  - creating a group;
  - renaming a group;
  - deleting a group;
  - verifying `Skill Library` still only shows the import target selector.
- Re-run:
  - `npm --prefix apps/frontend run build`
  - `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_chat_api.py tests/test_ui_bridge_routes.py -q`

## Notes

- Earlier implementation commit before this TODO: `570d678 feat(agent): split skill groups management`.
- The backend crash reported while switching tabs was not reproduced after restarting through `.venv/bin/hermes-yachiyo`; current code now has a row factory regression test for `list_agents`.
- Route-level folder rename/delete coverage was added in `tests/test_agent_runtime.py`; this repo does not currently have a frontend smoke test runner.
- 2026-05-24 browser smoke covered the former top-level `Skill Groups` tab. After the 2026-05-25 decision, re-smoke should verify `#/agents/skill-groups` opens `Skill Library > 分组管理` with `Skill Library` highlighted at the top level.
