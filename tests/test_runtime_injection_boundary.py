"""Source-level guards for the single Native Agent runtime boundary."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"
RUNTIME_ACCESSORS = {"get_agent_runtime_service", "get_native_run_engine"}
RUNTIME_CONSTRUCTORS = {"AgentRuntimeService", "NativeRunEngine"}
IGNORED_DIRS = {"__pycache__", "node_modules", "dist", "dist-electron", ".vite"}
ALLOWED_RUNTIME_ACCESSOR_CALLS = {
    ("apps/bridge/routes/agents.py", "_agent_runtime_service", "get_agent_runtime_service"),
    ("apps/bridge/routes/runs.py", "_native_run_engine", "get_native_run_engine"),
    ("apps/core/executor.py", "_oha_delegation_catalog_context", "get_agent_runtime_service"),
    ("apps/core/executor.py", "_run_oha_delegation", "get_agent_runtime_service"),
    ("apps/core/executor.py", "NativeAgentExecutor._runtime_service", "get_native_run_engine"),
    ("apps/shell/agent_runtime.py", "get_agent_runtime_service", "get_native_run_engine"),
    ("apps/shell/chat_api.py", "ChatAPI._agent_runtime_service", "get_agent_runtime_service"),
}
ALLOWED_RUNTIME_CONSTRUCTOR_CALLS = {
    ("apps/shell/agent_runtime.py", "get_native_run_engine", "NativeRunEngine"),
}


class _RuntimeAccessorVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.findings: list[tuple[str, str, int]] = []
        self.constructor_findings: list[tuple[str, str, int]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        accessor = self._called_accessor_name(node)
        if accessor is not None:
            qualname = self._current_qualname()
            self.findings.append((qualname, accessor, node.lineno))
        constructor = self._called_constructor_name(node)
        if constructor is not None:
            qualname = self._current_qualname()
            self.constructor_findings.append((qualname, constructor, node.lineno))
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def _current_qualname(self) -> str:
        parts = [*self.class_stack]
        if self.function_stack:
            parts.append(self.function_stack[-1])
        return ".".join(parts) if parts else "<module>"

    @staticmethod
    def _called_accessor_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name) and node.func.id in RUNTIME_ACCESSORS:
            return node.func.id
        if isinstance(node.func, ast.Attribute) and node.func.attr in RUNTIME_ACCESSORS:
            return node.func.attr
        return None

    @staticmethod
    def _called_constructor_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name) and node.func.id in RUNTIME_CONSTRUCTORS:
            return node.func.id
        if isinstance(node.func, ast.Attribute) and node.func.attr in RUNTIME_CONSTRUCTORS:
            return node.func.attr
        return None


def _iter_app_python_files():
    for path in APPS_ROOT.rglob("*.py"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def test_native_runtime_global_accessors_stay_confined_to_injection_helpers() -> None:
    unexpected: list[str] = []
    for path in _iter_app_python_files():
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        visitor = _RuntimeAccessorVisitor(relative)
        visitor.visit(tree)
        for qualname, accessor, line in visitor.findings:
            key = (relative, qualname, accessor)
            if key not in ALLOWED_RUNTIME_ACCESSOR_CALLS:
                unexpected.append(f"{relative}:{line} {qualname} calls {accessor}()")

    assert unexpected == []


def test_native_runtime_construction_stays_confined_to_global_service_factory() -> None:
    unexpected: list[str] = []
    for path in _iter_app_python_files():
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        visitor = _RuntimeAccessorVisitor(relative)
        visitor.visit(tree)
        for qualname, constructor, line in visitor.constructor_findings:
            key = (relative, qualname, constructor)
            if key not in ALLOWED_RUNTIME_CONSTRUCTOR_CALLS:
                unexpected.append(f"{relative}:{line} {qualname} constructs {constructor}()")

    assert unexpected == []
