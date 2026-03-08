from __future__ import annotations

from dataclasses import dataclass
import json

from app.config import Settings
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
) -> list[PlannedToolCall]:
    observation_items = observations or []
    if settings and tool_descriptions is not None:
        llm_plan = plan_tool_calls_with_llm(
            question=question,
            settings=settings,
            tool_descriptions=tool_descriptions,
            observations=observation_items,
            top_k=top_k,
        )
        if llm_plan is not None:
            return llm_plan

    fallback_follow_up = plan_fallback_follow_up(observation_items)
    if fallback_follow_up is not None:
        return fallback_follow_up
    if observation_items:
        return []

    normalized = question.strip().lower()

    if any(keyword in normalized for keyword in ("链接", "link", "网址", "url", "文档", "官网", "website")):
        return [
            PlannedToolCall(
                tool_name="search_saved_links",
                arguments={"query": question, "limit": 10},
                reason="The user asks about saved links or online resources.",
            )
        ]

    if any(keyword in normalized for keyword in ("最近", "recent", "latest")):
        return [
            PlannedToolCall(
                tool_name="list_recent_pages",
                arguments={"limit": 10},
                reason="The user asks for recent pages.",
            )
        ]

    if any(keyword in normalized for keyword in ("页面", "page id", "page ", "page_id")):
        return [
            PlannedToolCall(
                tool_name="search_local_notion",
                arguments={"query": question, "top_k": top_k},
                reason="The user likely needs evidence before selecting a page.",
            )
        ]

    return [
        PlannedToolCall(
            tool_name="search_local_notion",
            arguments={"query": question, "top_k": top_k},
            reason="Default local-first retrieval for answering the question.",
        )
    ]


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
