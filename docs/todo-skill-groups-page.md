# TODO: Skill Groups Page

## Current State

- Agent Studio now has a separate `Skill Groups` tab.
- `Skill Groups` can be opened directly at `#/agents/skill-groups`; existing `#/agents/<run_id>` links still open Runs detail.
- `Skill Library` left panel only chooses the target folder for install/upload.
- Existing folder CRUD is backed by `/ui/skill-folders` and `AgentRuntimeService`.
- Deleting a folder moves its skills back to `无需分组`.
- Agent Mounted Skills can filter by folder and bulk select/clear the current filter.
- Folder create/rename rejects duplicate names and names longer than 120 characters; the UI shows inline validation copy.
- Deleting a folder now asks for confirmation and explains that contained skills return to `无需分组`.
- The default `无需分组` group now splits counts into total / Yachiyo / Hermes.
- Latest implementation commit: `bb4436b feat(agent): finish skill groups todo`.

## Product Decisions To Revisit

- Decide whether `Skill Groups` should remain a top-level Agent Studio tab, or become a secondary page under `Skill Library`.
- Decide final naming: `Skill Groups`, `Skill Folders`, or Chinese label such as `Skill 分组`.
- Decide whether Hermes Agent skills should be assignable to Yachiyo groups, or whether groups should only organize Yachiyo-managed skills.
- Decide whether `source_scope` should remain an internal-only backend field or become a visible filter later.

## Remaining Implementation TODO

- Decide whether to promote `source_scope` into the UI; it is still kept backend-only for now.
- Decide whether folder sorting should become user-controlled instead of only stored in the data model.
- If sorting becomes user-controlled, wire `sort_order` into the Skill Groups UI with move up/down controls and keep the default order stable.
- If Hermes Agent skills should stay read-only, prevent assigning Hermes skills to Yachiyo groups in the Skill card selector and document that boundary in the UI.

## Remaining Test TODO

- Add frontend smoke coverage for:
  - opening `Skill Groups`;
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
- 2026-05-24 browser smoke opened `http://127.0.0.1:5174/#/agents/skill-groups`, confirmed the Skill Groups tab is active, switching to Skill Library updates the URL to `#/agents/skills`, and browser console errors are empty.
