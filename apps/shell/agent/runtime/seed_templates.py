"""Default Agent and Workflow templates for new local runtimes."""

from __future__ import annotations

from typing import Any, Callable


DEFAULT_AGENT_TEMPLATES: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "agent_yachiyo_orchestrator",
        "Yachiyo Orchestrator",
        "负责拆解目标、汇总上下文，并调度其他 Agent。",
        "orchestrator",
        "你是 Yachiyo 主控调度 Agent。你负责把用户目标整理成明确 brief，决定需要哪些 Agent 参与，并汇总最终结果。",
        "report",
    ),
    (
        "agent_coding",
        "Coding Agent",
        "负责实现代码改动、整理 diff 和验证建议。",
        "coding",
        "你是 Coding Agent。你负责根据 brief 输出最小可验证实现方案、变更摘要、测试建议和风险说明。",
        "diff",
    ),
    (
        "agent_design",
        "Design Agent",
        "负责信息架构、界面方案、原型说明和设计交付物。",
        "design",
        "你是 Design Agent。你负责把需求转成设计目标、界面结构、交互状态和可交付原型说明。",
        "artifacts",
    ),
    (
        "agent_review",
        "Review Agent",
        "负责检查实现质量、回归风险和测试缺口。",
        "review",
        "你是 Review Agent。你以代码审查视角输出问题优先级、证据、风险和必要的修复建议。",
        "report",
    ),
    (
        "agent_research",
        "Research Agent",
        "负责资料整理、事实核验和方案比较。",
        "research",
        "你是 Research Agent。你负责整理已知事实、指出不确定点，并输出可执行结论。",
        "markdown",
    ),
    (
        "agent_office",
        "Office Agent",
        "负责日报、表格、文档和工作材料整理。",
        "office",
        "你是 Office Agent。你负责把工作信息整理成清晰、可复用的文档、表格或汇报材料。",
        "report",
    ),
    (
        "agent_custom",
        "Custom Agent",
        "空白模板，用于从 GUI 配置专用 Agent。",
        "custom",
        "你是一个由用户配置的专用 Agent。严格遵循当前 Agent instructions 和挂载 Skills。",
        "chat",
    ),
)


def default_workflow_templates() -> list[dict[str, Any]]:
    phase4_tasks = {
        "orchestrator": "拆解全局目标，明确后续 Agent 的交付边界、依赖关系、风险和验收口径。",
        "research": "基于全局目标整理事实、约束、参考信息和不确定点，为设计与实现提供依据。",
        "design": "基于研究结果提出信息架构、交互结构、视觉方向和需要交付的设计要点。",
        "coding": "根据上游设计与约束给出实现方案、必要代码或变更计划，并说明验证方式。",
        "review": "审查上游实现或方案，列出问题优先级、风险、缺失测试和可验收结论。",
        "office": "把整条流程的目标、关键决策、产物、风险和后续待办整理成最终汇报。",
    }
    return [
        {
            "workflow_id": "workflow_web_idea_full",
            "name": "网页点子全流程",
            "description": "从点子 brief 到设计、编码、审查和人工确认的线性模板。",
            "nodes": [
                {"id": "start", "type": "start", "position": {"x": 0, "y": 80}, "data": {"label": "Start"}},
                {
                    "id": "design",
                    "type": "agent",
                    "position": {"x": 220, "y": 80},
                    "data": {
                        "label": "Design Agent",
                        "agent_id": "agent_design",
                        "task": "把网页点子转成可执行设计 brief，包含目标用户、页面结构、关键交互和视觉方向。",
                    },
                },
                {
                    "id": "approval",
                    "type": "approval",
                    "position": {"x": 440, "y": 80},
                    "data": {
                        "label": "人工审批",
                        "criteria": "确认设计 brief 已覆盖目标用户、页面结构、关键交互和验收点，再继续编码。",
                    },
                },
                {
                    "id": "coding",
                    "type": "agent",
                    "position": {"x": 660, "y": 80},
                    "data": {
                        "label": "Coding Agent",
                        "agent_id": "agent_coding",
                        "task": "根据已审批设计 brief 规划实现方案，产出代码、patch 或明确的实现步骤与验证方法。",
                    },
                },
                {
                    "id": "review",
                    "type": "agent",
                    "position": {"x": 880, "y": 80},
                    "data": {
                        "label": "Review Agent",
                        "agent_id": "agent_review",
                        "task": "审查实现结果，列出阻塞问题、风险、缺失测试和是否可以验收。",
                    },
                },
            ],
            "edges": [
                {"id": "e-start-design", "source": "start", "target": "design"},
                {"id": "e-design-approval", "source": "design", "target": "approval"},
                {"id": "e-approval-coding", "source": "approval", "target": "coding"},
                {"id": "e-coding-review", "source": "coding", "target": "review"},
            ],
            "enabled": True,
        },
        {
            "workflow_id": "workflow_phase4_agent_line_smoke",
            "name": "Phase 4 Agent 全线流通测试",
            "description": "依次调用 Orchestrator、Research、Design、Coding、Review、Office，并写出最终 Artifact。",
            "nodes": [
                {"id": "start", "type": "start", "position": {"x": 0, "y": 80}, "data": {"label": "Start"}},
                {
                    "id": "orchestrator",
                    "type": "agent",
                    "position": {"x": 220, "y": 80},
                    "data": {
                        "label": "Yachiyo Orchestrator",
                        "agent_id": "agent_yachiyo_orchestrator",
                        "task": phase4_tasks["orchestrator"],
                    },
                },
                {
                    "id": "research",
                    "type": "agent",
                    "position": {"x": 440, "y": 80},
                    "data": {
                        "label": "Research Agent",
                        "agent_id": "agent_research",
                        "task": phase4_tasks["research"],
                    },
                },
                {
                    "id": "design",
                    "type": "agent",
                    "position": {"x": 660, "y": 80},
                    "data": {
                        "label": "Design Agent",
                        "agent_id": "agent_design",
                        "task": phase4_tasks["design"],
                    },
                },
                {
                    "id": "coding",
                    "type": "agent",
                    "position": {"x": 880, "y": 80},
                    "data": {
                        "label": "Coding Agent",
                        "agent_id": "agent_coding",
                        "task": phase4_tasks["coding"],
                    },
                },
                {
                    "id": "review",
                    "type": "agent",
                    "position": {"x": 1100, "y": 80},
                    "data": {
                        "label": "Review Agent",
                        "agent_id": "agent_review",
                        "task": phase4_tasks["review"],
                    },
                },
                {
                    "id": "office",
                    "type": "agent",
                    "position": {"x": 1320, "y": 80},
                    "data": {
                        "label": "Office Agent",
                        "agent_id": "agent_office",
                        "task": phase4_tasks["office"],
                    },
                },
                {
                    "id": "artifact",
                    "type": "artifact",
                    "position": {"x": 1540, "y": 80},
                    "data": {
                        "label": "Flow Summary",
                        "kind": "artifact",
                        "artifact_path": "reports/phase-4-flow-summary.md",
                    },
                },
            ],
            "edges": [
                {"id": "e-start-orchestrator", "source": "start", "target": "orchestrator"},
                {"id": "e-orchestrator-research", "source": "orchestrator", "target": "research"},
                {"id": "e-research-design", "source": "research", "target": "design"},
                {"id": "e-design-coding", "source": "design", "target": "coding"},
                {"id": "e-coding-review", "source": "coding", "target": "review"},
                {"id": "e-review-office", "source": "review", "target": "office"},
                {"id": "e-office-artifact", "source": "office", "target": "artifact"},
            ],
            "enabled": True,
        },
    ]


class RuntimeSeedTemplateService:
    """Seeds default Studio templates without owning Agent/Workflow persistence."""

    def __init__(
        self,
        *,
        conn: Any,
        create_agent: Callable[..., dict[str, Any]],
        create_workflow: Callable[..., dict[str, Any]],
        default_tool_policy: Callable[[str], dict[str, Any]],
        default_workspace_policy: Callable[[], dict[str, Any]],
        has_studio_deletion: Callable[[str, str], bool],
        agent_templates: tuple[tuple[str, str, str, str, str, str], ...] = DEFAULT_AGENT_TEMPLATES,
        workflow_templates: Callable[[], list[dict[str, Any]]] = default_workflow_templates,
    ) -> None:
        self._conn = conn
        self._create_agent = create_agent
        self._create_workflow = create_workflow
        self._default_tool_policy = default_tool_policy
        self._default_workspace_policy = default_workspace_policy
        self._has_studio_deletion = has_studio_deletion
        self._agent_templates = agent_templates
        self._workflow_templates = workflow_templates

    def seed(self) -> None:
        self.seed_agents()
        self.seed_workflows()

    def seed_agents(self) -> None:
        agent_rows = self._conn.execute("SELECT agent_id, name FROM agents").fetchall()
        existing_agent_ids = {str(row["agent_id"]) for row in agent_rows}
        existing_agent_names = {str(row["name"]).strip().lower() for row in agent_rows}
        for agent_id, name, description, category, instructions, output_contract in self._agent_templates:
            if (
                agent_id in existing_agent_ids
                or name.strip().lower() in existing_agent_names
                or self._has_studio_deletion("agent", agent_id)
            ):
                continue
            self._create_agent(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "description": description,
                    "category": category,
                    "instructions": instructions,
                    "model_mode": "follow_main",
                    "tool_policy": self._default_tool_policy(category),
                    "workspace_policy": self._default_workspace_policy(),
                    "output_contract": output_contract,
                    "enabled": True,
                },
                seed=True,
            )

    def seed_workflows(self) -> None:
        agent_ids = {
            str(row["agent_id"])
            for row in self._conn.execute("SELECT agent_id FROM agents").fetchall()
        }
        existing_workflows = self._conn.execute("SELECT workflow_id, name FROM workflows").fetchall()
        existing_workflow_ids = {str(row["workflow_id"]) for row in existing_workflows}
        existing_workflow_names = {str(row["name"]).strip().lower() for row in existing_workflows}
        for workflow in self._workflow_templates():
            workflow_id = str(workflow["workflow_id"])
            name = str(workflow["name"])
            if (
                workflow_id in existing_workflow_ids
                or name.strip().lower() in existing_workflow_names
                or self._has_studio_deletion("workflow", workflow_id)
            ):
                continue
            referenced_agents = [
                str((node.get("data") or {}).get("agent_id") or "")
                for node in workflow["nodes"]
                if str(node.get("type") or (node.get("data") or {}).get("kind") or "") == "agent"
            ]
            if any(agent_id and agent_id not in agent_ids for agent_id in referenced_agents):
                continue
            self._create_workflow(workflow, seed=True)
