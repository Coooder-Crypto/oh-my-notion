from __future__ import annotations

from dataclasses import dataclass
import inspect
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

        try:
            filtered_arguments = filter_arguments_for_handler(tool.handler, call.arguments)
            result = tool.handler(**filtered_arguments)
        except Exception as exc:
            observations.append(
                ToolObservation(
                    tool_name=tool.name,
                    arguments=call.arguments,
                    reason=call.reason,
                    result={"error": str(exc)},
                )
            )
            continue
        observations.append(
            ToolObservation(
                tool_name=tool.name,
                arguments=filtered_arguments,
                reason=call.reason,
                result=result,
            )
        )
    return observations


def filter_arguments_for_handler(handler, arguments: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(handler)
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return arguments
    allowed = {name for name in parameters}
    return {key: value for key, value in arguments.items() if key in allowed}
