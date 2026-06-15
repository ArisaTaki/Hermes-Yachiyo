from apps.shell import agent_runtime
from apps.shell.agent.runtime import workflow_path, workflow_start
from apps.shell.agent.runtime.serialization import (
    json_dump_compact,
    json_dump_sorted,
    json_load,
    slug,
)


def test_runtime_serialization_helpers_preserve_legacy_agent_runtime_aliases() -> None:
    assert agent_runtime._json_load is json_load
    assert agent_runtime._json_dump is json_dump_sorted
    assert agent_runtime._slug is slug

    assert agent_runtime._json_load('{"b": 2}', {}) == {"b": 2}
    assert agent_runtime._json_load("not-json", {"fallback": True}) == {"fallback": True}
    assert agent_runtime._json_dump({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'
    assert agent_runtime._slug("Hello Yachiyo!", "agent") == "hello-yachiyo"


def test_workflow_modules_use_compact_runtime_serialization_helpers() -> None:
    assert workflow_path._json_load is json_load
    assert workflow_path._json_dump is json_dump_compact
    assert workflow_path._slug is slug
    assert workflow_start._json_load is json_load
    assert workflow_start._json_dump is json_dump_compact

    assert workflow_path._json_dump({"b": 2, "a": 1}) == '{"b":2,"a":1}'
    assert workflow_start._json_load("", []) == []
