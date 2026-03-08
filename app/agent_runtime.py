from __future__ import annotations

import sqlite3

from app.answer_rendering import build_template_answer
from app.agent_executor import ToolObservation, execute_tool_calls
from app.agent_planner import plan_tool_calls
from app.config import Settings
from app.llm import generate_grounded_answer
from app.memory import get_session_turns, save_session_turn
from app.models import SearchResult
from app.tools_registry import ToolDefinition, build_tool_registry


def run_agent(
    connection: sqlite3.Connection,
    settings: Settings,
    question: str,
    top_k: int = 5,
    session_id: str = "default",
) -> str:
    registry = build_tool_registry(connection, session_id=session_id)
    observations: list[ToolObservation] = []
    session_history = serialize_session_turns(get_session_turns(connection, session_id=session_id))
    for _step in range(3):
        planned_calls = plan_tool_calls(
            question,
            top_k=top_k,
            settings=settings,
            tool_descriptions=serialize_tool_descriptions(registry),
            observations=serialize_observations(observations),
            session_history=session_history,
        )
        if not planned_calls:
            break
        observations.extend(execute_tool_calls(registry, planned_calls))
        if extract_network_content(observations):
            break

    search_results = extract_search_results(observations)

    if search_results:
        if settings.openai_api_key:
            try:
                answer = generate_grounded_answer(
                    settings=settings,
                    question=question,
                    results=search_results,
                )
                persist_turns(connection, session_id, question, answer)
                return answer
            except Exception as exc:
                header = f"OpenAI 回答失败，已回退到本地模板回答。\n原因：{exc}\n"
                answer = header + build_template_answer(search_results, llm_enabled=True)
                persist_turns(connection, session_id, question, answer)
                return answer
        answer = build_template_answer(search_results, llm_enabled=False)
        persist_turns(connection, session_id, question, answer)
        return answer

    network_content = extract_network_content(observations)
    if network_content:
        answer = render_network_response(question, observations, network_content)
        persist_turns(connection, session_id, question, answer)
        return answer

    memory_items = extract_memory_items(observations)
    if memory_items:
        answer = render_memory_response(question, observations, memory_items)
        persist_turns(connection, session_id, question, answer)
        return answer

    answer = render_non_search_response(question, observations)
    persist_turns(connection, session_id, question, answer)
    return answer


def extract_search_results(observations: list[ToolObservation]) -> list[SearchResult]:
    for observation in observations:
        if observation.tool_name == "search_local_notion" and isinstance(observation.result, list):
            if observation.result and isinstance(observation.result[0], SearchResult):
                return observation.result
            if observation.result == []:
                return []
    return []


def render_non_search_response(question: str, observations: list[ToolObservation]) -> str:
    if not observations:
        return f"未能为问题生成工具计划：{question}"

    lines = ["Agent 执行了以下工具：", ""]
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name}")
        lines.append(f"   reason: {observation.reason}")
        lines.append(f"   args: {observation.arguments}")
        lines.append(f"   result: {summarize_result(observation.result)}")
    return "\n".join(lines)


def summarize_result(result) -> str:
    if result is None:
        return "None"
    if isinstance(result, list):
        return f"{len(result)} items"
    if isinstance(result, dict):
        return str(result)
    return str(result)


def serialize_tool_descriptions(registry: dict[str, ToolDefinition]) -> list[dict]:
    return [{"name": tool.name, "description": tool.description} for tool in registry.values()]


def serialize_observations(observations: list[ToolObservation]) -> list[dict]:
    serialized: list[dict] = []
    for observation in observations:
        serialized.append(
            {
                "tool_name": observation.tool_name,
                "arguments": observation.arguments,
                "reason": observation.reason,
                "summary": summarize_result(observation.result),
                "result": safe_result_payload(observation.result),
            }
        )
    return serialized


def safe_result_payload(result):
    if isinstance(result, list):
        return [safe_result_payload(item) for item in result[:5]]
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dict__"):
        return result.__dict__
    if hasattr(result, "keys"):
        try:
            return dict(result)
        except Exception:
            return str(result)
    return str(result)


def extract_network_content(observations: list[ToolObservation]) -> list[dict]:
    items: list[dict] = []
    for observation in observations:
        if observation.tool_name == "read_network_link" and isinstance(observation.result, dict):
            items.append(observation.result)
    return items


def render_network_response(
    question: str,
    observations: list[ToolObservation],
    network_content: list[dict],
) -> str:
    lines = [f"已为问题读取相关网络链接：{question}", ""]
    for index, item in enumerate(network_content, start=1):
        lines.append(f"{index}. {item.get('url', '')}")
        if item.get("error"):
            lines.append(f"   error: {item['error']}")
        else:
            lines.append(f"   content_type: {item.get('content_type', '')}")
            lines.append(f"   snippet: {str(item.get('content', ''))[:600]}")
    lines.append("")
    lines.append("工具链路：")
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name} -> {summarize_result(observation.result)}")
    return "\n".join(lines)


def extract_memory_items(observations: list[ToolObservation]) -> list[dict]:
    for observation in observations:
        if observation.tool_name == "lookup_memory" and isinstance(observation.result, list):
            return [item for item in observation.result if isinstance(item, dict)]
    return []


def render_memory_response(
    question: str,
    observations: list[ToolObservation],
    memory_items: list[dict],
) -> str:
    lines = [f"与问题相关的记忆：{question}", ""]
    for index, item in enumerate(memory_items, start=1):
        lines.append(f"{index}. {item.get('content', '')}")
        lines.append(
            f"   source={item.get('source', '')} importance={item.get('importance', 1)} created_at={item.get('created_at', '')}"
        )
    lines.append("")
    lines.append("工具链路：")
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name} -> {summarize_result(observation.result)}")
    return "\n".join(lines)


def serialize_session_turns(rows: list[sqlite3.Row]) -> list[dict]:
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def persist_turns(connection: sqlite3.Connection, session_id: str, question: str, answer: str) -> None:
    save_session_turn(connection, session_id=session_id, role="user", content=question)
    save_session_turn(connection, session_id=session_id, role="assistant", content=answer)
