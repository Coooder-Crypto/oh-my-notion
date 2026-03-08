from __future__ import annotations

from dataclasses import dataclass
import json

from app.core.config import Settings
from app.llm import create_openai_client


@dataclass(slots=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict
    reason: str


def plan_tool_calls(
    question: str,
    top_k: int = 5,
    settings: Settings | None = None,
    tool_descriptions: list[dict] | None = None,
    observations: list[dict] | None = None,
    session_history: list[dict] | None = None,
) -> list[PlannedToolCall]:
    observation_items = observations or []
    if settings and tool_descriptions is not None:
        llm_plan = plan_tool_calls_with_llm(
            question=question,
            settings=settings,
            tool_descriptions=tool_descriptions,
            observations=observation_items,
            session_history=session_history or [],
            top_k=top_k,
        )
        if llm_plan is not None:
            return normalize_planned_calls(llm_plan, question=question, top_k=top_k)

    fallback_follow_up = plan_fallback_follow_up(observation_items)
    if fallback_follow_up is not None:
        return normalize_planned_calls(fallback_follow_up, question=question, top_k=top_k)
    if observation_items:
        return []

    normalized = question.strip().lower()

    if any(keyword in normalized for keyword in ("链接", "link", "网址", "url", "文档", "官网", "website")):
        return normalize_planned_calls([
            PlannedToolCall(
                tool_name="search_saved_links",
                arguments={"query": question, "limit": 10},
                reason="The user asks about saved links or online resources.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("之前", "刚才", "上次", "记忆", "memory", "remember")):
        return normalize_planned_calls([
            PlannedToolCall(
                tool_name="lookup_memory",
                arguments={"query": question, "limit": 5},
                reason="The user refers to prior context or saved memory.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("记住", "remember this", "保存这个事实")):
        return normalize_planned_calls([
            PlannedToolCall(
                tool_name="save_memory",
                arguments={"content": extract_memory_content(question), "importance": 2},
                reason="The user explicitly asks to remember something.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("最近", "recent", "latest")):
        return normalize_planned_calls([
            PlannedToolCall(
                tool_name="list_recent_pages",
                arguments={"limit": 10},
                reason="The user asks for recent pages.",
            )
        ], question=question, top_k=top_k)

    if any(keyword in normalized for keyword in ("页面", "page id", "page ", "page_id")):
        return normalize_planned_calls([
            PlannedToolCall(
                tool_name="search_local_notion",
                arguments={"query": question, "top_k": top_k},
                reason="The user likely needs evidence before selecting a page.",
            )
        ], question=question, top_k=top_k)

    return normalize_planned_calls([
        PlannedToolCall(
            tool_name="search_local_notion",
            arguments={"query": question, "top_k": top_k},
            reason="Default local-first retrieval for answering the question.",
        )
    ], question=question, top_k=top_k)


def plan_fallback_follow_up(observations: list[dict]) -> list[PlannedToolCall] | None:
    if not observations:
        return None
    last_observation = observations[-1]
    if last_observation.get("tool_name") != "search_saved_links":
        return None

    result = last_observation.get("result", [])
    if not isinstance(result, list) or not result:
        return []

    first_item = result[0]
    if not isinstance(first_item, dict):
        return []
    links = first_item.get("links", [])
    if not links:
        return []

    return [
        PlannedToolCall(
            tool_name="read_network_link",
            arguments={"url": links[0], "max_chars": 4000},
            reason="Read the most relevant saved link after link retrieval.",
        )
    ]


def plan_tool_calls_with_llm(
    question: str,
    settings: Settings,
    tool_descriptions: list[dict],
    observations: list[dict],
    session_history: list[dict],
    top_k: int,
) -> list[PlannedToolCall] | None:
    client = create_openai_client(settings)
    if client is None:
        return None

    system_prompt = (
        "You are an agent planner for a local-first knowledge assistant. "
        "Return strict JSON only. "
        "Schema: {\"tool_calls\": [{\"tool_name\": string, \"arguments\": object, \"reason\": string}]}. "
        "If you already have enough information, return {\"tool_calls\": []}. "
        "Prefer local notion tools first. "
        "Use search_saved_links when the question is about links, docs, websites, URLs, official resources, or online references. "
        "Use read_network_link only after you already know which URL to inspect."
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "top_k": top_k,
            "tools": tool_descriptions,
            "observations": observations,
            "session_history": session_history,
        },
        ensure_ascii=False,
    )
    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        payload = json.loads(extract_json_object(response.output_text.strip()))
        calls = payload.get("tool_calls", [])
        planned_calls: list[PlannedToolCall] = []
        for call in calls:
            tool_name = call.get("tool_name")
            arguments = call.get("arguments", {})
            reason = call.get("reason", "LLM selected this tool.")
            if not tool_name or not isinstance(arguments, dict):
                continue
            planned_calls.append(
                PlannedToolCall(tool_name=tool_name, arguments=arguments, reason=reason)
            )
        return planned_calls
    except Exception:
        return None


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def extract_memory_content(question: str) -> str:
    normalized = question.strip()
    prefixes = ("记住：", "记住:", "请记住：", "请记住:", "remember this:")
    for prefix in prefixes:
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix):].strip() or normalized
    return normalized


def normalize_planned_calls(
    calls: list[PlannedToolCall],
    question: str,
    top_k: int,
) -> list[PlannedToolCall]:
    normalized_calls: list[PlannedToolCall] = []
    for call in calls:
        arguments = dict(call.arguments)
        if call.tool_name == "search_local_notion":
            query = str(arguments.get("query", "")).strip()
            arguments["query"] = query or question
            arguments["top_k"] = int(arguments.get("top_k") or top_k)
        elif call.tool_name == "search_saved_links":
            query = str(arguments.get("query", "")).strip()
            arguments["query"] = query or question
            arguments["limit"] = int(arguments.get("limit") or 10)
        elif call.tool_name == "lookup_memory":
            query = str(arguments.get("query", "")).strip()
            arguments["query"] = query or question
            arguments["limit"] = int(arguments.get("limit") or 5)
        elif call.tool_name == "save_memory":
            content = str(arguments.get("content", "")).strip()
            arguments["content"] = content or extract_memory_content(question)
            arguments["importance"] = int(arguments.get("importance") or 1)
        normalized_calls.append(
            PlannedToolCall(
                tool_name=call.tool_name,
                arguments=arguments,
                reason=call.reason,
            )
        )
    return normalized_calls
