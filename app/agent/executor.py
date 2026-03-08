from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.planner import PlannedToolCall
from app.agent.tools_registry import ToolDefinition


@dataclass(slots=True)
class ToolObservation:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    result: Any


def execute_tool_calls(
    registry: dict[str, ToolDefinition],
    calls: list[PlannedToolCall],
) -> list[ToolObservation]:
    observations: list[ToolObservation] = []
    for call in calls:
        tool = registry.get(call.tool_name)
        if not tool:
            observations.append(
                ToolObservation(
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    reason=call.reason,
                    result={"error": f"Unknown tool: {call.tool_name}"},
                )
            )
            continue

        result = tool.handler(**call.arguments)
        observations.append(
            ToolObservation(
                tool_name=tool.name,
                arguments=call.arguments,
                reason=call.reason,
                result=result,
            )
        )
    return observations
