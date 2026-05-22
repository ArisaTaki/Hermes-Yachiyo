# TODO: Skill Groups Page

## Current State

- Agent Studio now has a separate `Skill Groups` tab.
- `Skill Library` left panel only chooses the target folder for install/upload.
- Existing folder CRUD is backed by `/ui/skill-folders` and `AgentRuntimeService`.
- Deleting a folder moves its skills back to `无需分组`.
- Agent Mounted Skills can filter by folder and bulk select/clear the current filter.

## Product Decisions To Revisit

- Decide whether `Skill Groups` should remain a top-level Agent Studio tab, or become a secondary page under `Skill Library`.
- Decide final naming: `Skill Groups`, `Skill Folders`, or Chinese label such as `Skill 分组`.
- Decide whether the default group should count all ungrouped skills, or split counts into Yachiyo / Hermes to avoid the Hermes library making `无需分组` look too large.
- Decide whether Hermes Agent skills should be assignable to Yachiyo groups, or whether groups should only organize Yachiyo-managed skills.
- Decide whether folder management needs a delete confirmation modal before removing a group.

## Implementation TODO

- Add direct route state for the new page if needed, instead of keeping the URL at `#/agents` while switching internal tabs.
- Add a clearer empty state when no custom groups exist.
- Add inline validation copy for duplicate folder names and overly long names.
- Consider preserving selected folder when moving from `Skill Groups` -> `Skill Library` via the `查看` action.
- Add a delete confirmation flow that explains skills will return to `无需分组`.
- Polish responsive layout for narrower desktop windows.
- Review whether `source_scope` should be exposed in UI, or removed from the user-facing model for now.

## Test TODO

- Add route tests for rename and delete behavior through `/ui/skill-folders/{folder_id}`.
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

- Latest implementation commit before this TODO: `570d678 feat(agent): split skill groups management`.
- The backend crash reported while switching tabs was not reproduced after restarting through `.venv/bin/hermes-yachiyo`; current code now has a row factory regression test for `list_agents`.
