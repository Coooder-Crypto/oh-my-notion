from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agent.planner import plan_tool_calls
from app.evaluation.dataset import EvalCase, load_eval_cases


@dataclass(slots=True)
class AgentEvalRow:
    case_id: str
    question: str
    expected_tools: list[str]
    actual_tools: list[str]
    hit: bool


def evaluate_agent_routing(dataset_path: Path) -> tuple[str, list[AgentEvalRow]]:
    cases = load_eval_cases(dataset_path)
    agent_cases = [case for case in cases if case.expected_tools]
    if not agent_cases:
        return f"No agent routing cases found in {dataset_path}", []

    rows: list[AgentEvalRow] = []
    hits = 0
    for case in agent_cases:
        row = evaluate_agent_case(case)
        rows.append(row)
        if row.hit:
            hits += 1

    accuracy = hits / len(rows)
    lines = [
        f"Agent eval completed on {len(rows)} cases.",
        f"tool_selection_accuracy: {accuracy:.3f}",
        "",
    ]
    for row in rows:
        status = "PASS" if row.hit else "FAIL"
        lines.append(f"[{status}] {row.case_id} | {row.question}")
        lines.append(f"  expected_tools: {', '.join(row.expected_tools)}")
        lines.append(f"  actual_tools: {', '.join(row.actual_tools) if row.actual_tools else '(none)'}")
    return "\n".join(lines), rows


def evaluate_agent_case(case: EvalCase) -> AgentEvalRow:
    planned_calls = plan_tool_calls(case.question, settings=None, tool_descriptions=None)
    actual_tools = [call.tool_name for call in planned_calls]
    hit = actual_tools[: len(case.expected_tools)] == case.expected_tools
    return AgentEvalRow(
        case_id=case.id,
        question=case.question,
        expected_tools=case.expected_tools,
        actual_tools=actual_tools,
        hit=hit,
    )

