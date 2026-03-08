from __future__ import annotations

import json
import sqlite3

from app.context.builder import build_context_bundle
from app.agent.executor import ToolObservation, execute_tool_calls
from app.agent.memory import (
    get_memory_summaries,
    get_session_turns,
    maybe_capture_memory_from_turn,
    save_session_turn,
)
from app.agent.planner import plan_tool_calls
from app.agent.rendering import build_template_answer
from app.agent.tools_registry import ToolDefinition, build_tool_registry
from app.core.config import Settings
from app.llm import generate_answer_from_context
from app.storage.models import SearchResult

MAX_AGENT_STEPS = 4


def run_agent(
    connection: sqlite3.Connection,
    settings: Settings,
    question: str,
    top_k: int = 5,
    session_id: str = "default",
) -> str:
    registry = build_tool_registry(connection, session_id=session_id)
    observations: list[ToolObservation] = []
    planner_trace: list[dict] = []
    session_history = serialize_session_turns(get_session_turns(connection, session_id=session_id))
    session_summaries = get_memory_summaries(connection, session_id=session_id, limit=2)
    for step_index in range(MAX_AGENT_STEPS):
        planned_calls = plan_tool_calls(
            question,
            top_k=top_k,
            settings=settings,
            tool_descriptions=serialize_tool_descriptions(registry),
            observations=serialize_observations(observations),
            session_history=session_history,
        )
        if not planned_calls:
            planner_trace.append({"step": step_index + 1, "thought": "No further tool call is needed.", "actions": [], "observation": "stop"})
            break
        planned_calls = remove_duplicate_calls(planned_calls, observations)
        if not planned_calls:
            planner_trace.append({"step": step_index + 1, "thought": "Planned calls were duplicates, stopping.", "actions": [], "observation": "duplicate_stop"})
            break
        step_observations = execute_tool_calls(registry, planned_calls)
        observations.extend(step_observations)
        planner_trace.append(
            {
                "step": step_index + 1,
                "thought": " ; ".join(call.reason for call in planned_calls),
                "actions": [
                    {"tool_name": call.tool_name, "arguments": call.arguments}
                    for call in planned_calls
                ],
                "observation": " | ".join(
                    f"{item.tool_name}: {summarize_result(item.result)}" for item in step_observations
                ),
            }
        )
        if should_stop_after_observation(step_observations):
            break

    search_results = extract_search_results(observations)
    memory_items = extract_memory_items(observations)
    link_results = extract_link_results(observations)
    network_content = extract_network_content(observations)
    domain_results = extract_domain_results(observations)
    context_bundle = build_context_bundle(
        question=question,
        search_results=search_results,
        memory_items=memory_items,
        session_turns=session_history,
        session_summaries=session_summaries,
        tool_observations=observations,
        network_content=network_content,
        planner_trace=planner_trace,
    )

    if search_results:
        if settings.openai_api_key:
            try:
                answer = generate_answer_from_context(
                    settings=settings,
                    question=question,
                    formatted_context=context_bundle.formatted_text,
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

    if network_content:
        answer = render_network_response(question, observations, network_content, planner_trace)
        persist_turns(connection, session_id, question, answer)
        return answer

    if link_results:
        answer = render_link_search_response(question, observations, link_results, planner_trace)
        persist_turns(connection, session_id, question, answer)
        return answer

    if domain_results:
        answer = render_domain_response(question, observations, domain_results, planner_trace)
        persist_turns(connection, session_id, question, answer)
        return answer

    if has_empty_link_search(observations):
        answer = (
            "本地 Notion 索引里暂时没有找到匹配的已保存链接。\n"
            "你可以换一个更具体的关键词，比如项目名、网站名、文档名，或者先检查相关页面是否已经被同步并产生了链接内容。"
        )
        persist_turns(connection, session_id, question, answer)
        return answer

    if memory_items:
        answer = render_memory_response(question, observations, memory_items, planner_trace)
        persist_turns(connection, session_id, question, answer)
        return answer

    answer = render_non_search_response(question, observations, planner_trace)
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


def render_non_search_response(
    question: str,
    observations: list[ToolObservation],
    planner_trace: list[dict] | None = None,
) -> str:
    if not observations:
        return f"未能为问题生成工具计划：{question}"

    lines = ["Agent 执行了以下工具：", ""]
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name}")
        lines.append(f"   reason: {observation.reason}")
        lines.append(f"   args: {observation.arguments}")
        lines.append(f"   result: {summarize_result(observation.result)}")
    if planner_trace:
        lines.append("")
        lines.append("Planner Trace:")
        lines.extend(render_planner_trace(planner_trace))
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
    planner_trace: list[dict] | None = None,
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
    if planner_trace:
        lines.append("")
        lines.append("Planner Trace:")
        lines.extend(render_planner_trace(planner_trace))
    return "\n".join(lines)


def extract_memory_items(observations: list[ToolObservation]) -> list[dict]:
    for observation in observations:
        if observation.tool_name in {"lookup_memory", "lookup_preferences"} and isinstance(observation.result, list):
            return [item for item in observation.result if isinstance(item, dict)]
        if observation.tool_name in {"save_memory", "save_preference"} and isinstance(observation.result, dict):
            return [observation.result]
    return []


def extract_link_results(observations: list[ToolObservation]) -> list[dict]:
    for observation in observations:
        if observation.tool_name == "search_saved_links" and isinstance(observation.result, list):
            return [item for item in observation.result if isinstance(item, dict)]
    return []


def extract_domain_results(observations: list[ToolObservation]) -> list[dict]:
    for observation in observations:
        if observation.tool_name in {"list_top_link_domains", "find_pages_by_domain"} and isinstance(observation.result, list):
            return [item for item in observation.result if isinstance(item, dict)]
        if observation.tool_name == "get_link_domain_summary" and isinstance(observation.result, dict):
            return [observation.result]
    return []


def has_empty_link_search(observations: list[ToolObservation]) -> bool:
    for observation in observations:
        if observation.tool_name == "search_saved_links" and observation.result == []:
            return True
    return False


def render_memory_response(
    question: str,
    observations: list[ToolObservation],
    memory_items: list[dict],
    planner_trace: list[dict] | None = None,
) -> str:
    lines = [f"与问题相关的记忆：{question}", ""]
    for index, item in enumerate(memory_items, start=1):
        source = item.get("source", "") or item.get("memory_type", "")
        importance = item.get("importance", item.get("confidence", 1))
        lines.append(f"{index}. {item.get('content', '')}")
        lines.append(
            f"   source={source} importance={importance} created_at={item.get('created_at', '')}"
        )
    lines.append("")
    lines.append("工具链路：")
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name} -> {summarize_result(observation.result)}")
    if planner_trace:
        lines.append("")
        lines.append("Planner Trace:")
        lines.extend(render_planner_trace(planner_trace))
    return "\n".join(lines)


def render_link_search_response(
    question: str,
    observations: list[ToolObservation],
    link_results: list[dict],
    planner_trace: list[dict] | None = None,
) -> str:
    lines = [f"与问题相关的已保存链接：{question}", ""]
    for index, item in enumerate(link_results[:8], start=1):
        title = item.get("title", "") or "Untitled"
        heading = item.get("heading", "") or "正文"
        lines.append(f"{index}. {title} | {heading}")
        for link in item.get("links", [])[:3]:
            lines.append(f"   - {link}")
        if item.get("domain"):
            lines.append(f"   domain: {item['domain']}")
        if item.get("anchor_text"):
            lines.append(f"   anchor: {item['anchor_text']}")
        if item.get("score") is not None:
            lines.append(f"   score: {float(item['score']):.2f}")
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            lines.append(f"   snippet: {snippet[:180]}")
        page_url = item.get("page_url", "")
        if page_url:
            lines.append(f"   page: {page_url}")
    lines.append("")
    lines.append("工具链路：")
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name} -> {summarize_result(observation.result)}")
    if planner_trace:
        lines.append("")
        lines.append("Planner Trace:")
        lines.extend(render_planner_trace(planner_trace))
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
    maybe_capture_memory_from_turn(connection, session_id=session_id, question=question, answer=answer)


def remove_duplicate_calls(
    planned_calls,
    observations: list[ToolObservation],
):
    seen = {
        (observation.tool_name, stable_arguments(observation.arguments))
        for observation in observations
    }
    filtered = []
    for call in planned_calls:
        key = (call.tool_name, stable_arguments(call.arguments))
        if key in seen:
            continue
        seen.add(key)
        filtered.append(call)
    return filtered


def stable_arguments(arguments: dict) -> str:
    try:
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(arguments)


def should_stop_after_observation(observations: list[ToolObservation]) -> bool:
    if not observations:
        return True
    for observation in observations:
        if observation.tool_name == "read_network_link" and isinstance(observation.result, dict):
            return True
        if observation.tool_name == "search_local_notion" and isinstance(observation.result, list) and observation.result:
            return True
        if observation.tool_name in {"lookup_memory", "search_saved_links", "list_top_link_domains", "find_pages_by_domain"} and isinstance(observation.result, list) and observation.result:
            return True
        if observation.tool_name == "get_link_domain_summary" and isinstance(observation.result, dict) and not observation.result.get("error"):
            return True
    return False


def render_domain_response(
    question: str,
    observations: list[ToolObservation],
    domain_results: list[dict],
    planner_trace: list[dict] | None = None,
) -> str:
    first = domain_results[0]
    if "summary" in first:
        lines = [f"域名摘要：{question}", "", first.get("summary", "")]
    elif "page_count" in first or "sample_page" in first:
        lines = [f"本地保存最多的链接域名：{question}", ""]
        for index, item in enumerate(domain_results[:10], start=1):
            lines.append(
                f"{index}. {item.get('domain', '')} | links={item.get('link_count', 0)} | pages={item.get('page_count', 0)}"
            )
    else:
        lines = [f"与站点相关的页面：{question}", ""]
        for index, item in enumerate(domain_results[:10], start=1):
            lines.append(
                f"{index}. {item.get('title', '')} | links={item.get('link_count', 0)} | domain={item.get('domain', '')}"
            )
            anchors = item.get("anchors", [])
            if anchors:
                lines.append(f"   anchors: {', '.join(anchors[:5])}")
            if item.get("page_url"):
                lines.append(f"   page: {item['page_url']}")
    lines.append("")
    lines.append("工具链路：")
    for index, observation in enumerate(observations, start=1):
        lines.append(f"{index}. {observation.tool_name} -> {summarize_result(observation.result)}")
    if planner_trace:
        lines.append("")
        lines.append("Planner Trace:")
        lines.extend(render_planner_trace(planner_trace))
    return "\n".join(lines)


def render_planner_trace(planner_trace: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in planner_trace:
        lines.append(f"- step {item.get('step')}: {item.get('thought', '')}")
        actions = item.get("actions", [])
        for action in actions:
            lines.append(f"  action: {action.get('tool_name')} {action.get('arguments')}")
        lines.append(f"  observation: {item.get('observation', '')}")
    return lines
