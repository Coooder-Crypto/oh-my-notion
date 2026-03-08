from __future__ import annotations

from app.agent.executor import ToolObservation
from app.context.models import ContextBundle, ContextItem
from app.storage.models import SearchResult


DEFAULT_CONTEXT_BUDGET = 7000


def build_context_bundle(
    question: str,
    search_results: list[SearchResult] | None = None,
    memory_items: list[dict] | None = None,
    session_turns: list[dict] | None = None,
    tool_observations: list[ToolObservation] | None = None,
    network_content: list[dict] | None = None,
    char_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> ContextBundle:
    items: list[ContextItem] = []
    items.extend(context_from_search_results(search_results or []))
    items.extend(context_from_memory(memory_items or []))
    items.extend(context_from_session(session_turns or []))
    items.extend(context_from_network(network_content or []))
    items.extend(context_from_observations(tool_observations or []))

    ranked = sorted(items, key=lambda item: item.priority)
    budgeted = apply_budget(ranked, char_budget)
    formatted_text = format_context(question, budgeted)
    return ContextBundle(
        question=question,
        items=budgeted,
        formatted_text=formatted_text,
        total_chars=len(formatted_text),
    )


def context_from_search_results(results: list[SearchResult]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, result in enumerate(results, start=1):
        items.append(
            ContextItem(
                kind="retrieval",
                title=f"Retrieval {index}: {result.title}",
                content=(
                    f"Heading: {result.heading or '正文'}\n"
                    f"URL: {result.url}\n"
                    f"Content: {result.content}"
                ),
                priority=10 + index,
                metadata={"page_id": result.page_id, "chunk_id": result.chunk_id},
            )
        )
    return items


def context_from_memory(memory_items: list[dict]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, item in enumerate(memory_items, start=1):
        items.append(
            ContextItem(
                kind="memory",
                title=f"Memory {index}",
                content=item.get("content", ""),
                priority=30 + index,
                metadata={
                    "source": str(item.get("source", "")),
                    "importance": str(item.get("importance", 1)),
                },
            )
        )
    return items


def context_from_session(session_turns: list[dict]) -> list[ContextItem]:
    items: list[ContextItem] = []
    recent_turns = session_turns[-4:]
    for index, turn in enumerate(recent_turns, start=1):
        items.append(
            ContextItem(
                kind="session",
                title=f"Session Turn {index} ({turn.get('role', '')})",
                content=turn.get("content", ""),
                priority=50 + index,
                metadata={"created_at": str(turn.get("created_at", ""))},
            )
        )
    return items


def context_from_network(network_items: list[dict]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, item in enumerate(network_items, start=1):
        if item.get("error"):
            continue
        items.append(
            ContextItem(
                kind="network",
                title=f"Network {index}",
                content=(
                    f"URL: {item.get('url', '')}\n"
                    f"Content-Type: {item.get('content_type', '')}\n"
                    f"Content: {item.get('content', '')}"
                ),
                priority=20 + index,
                metadata={"url": str(item.get("url", ""))},
            )
        )
    return items


def context_from_observations(observations: list[ToolObservation]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, observation in enumerate(observations[-4:], start=1):
        items.append(
            ContextItem(
                kind="tool",
                title=f"Tool Observation {index}: {observation.tool_name}",
                content=f"Args: {observation.arguments}\nSummary: {summarize_result(observation.result)}",
                priority=70 + index,
                metadata={"reason": observation.reason},
            )
        )
    return items


def apply_budget(items: list[ContextItem], char_budget: int) -> list[ContextItem]:
    selected: list[ContextItem] = []
    used = 0
    for item in items:
        item_text = item.title + "\n" + item.content
        item_size = len(item_text)
        if selected and used + item_size > char_budget:
            continue
        if not selected and item_size > char_budget:
            trimmed = ContextItem(
                kind=item.kind,
                title=item.title,
                content=item.content[: max(0, char_budget - len(item.title) - 20)],
                priority=item.priority,
                metadata=item.metadata,
            )
            selected.append(trimmed)
            return selected
        selected.append(item)
        used += item_size
    return selected


def format_context(question: str, items: list[ContextItem]) -> str:
    lines = [f"Question:\n{question}", "", "Context:"]
    for item in items:
        lines.append(f"- [{item.kind}] {item.title}")
        if item.metadata:
            metadata_text = ", ".join(f"{key}={value}" for key, value in item.metadata.items() if value)
            if metadata_text:
                lines.append(f"  Meta: {metadata_text}")
        lines.append(f"  {item.content}")
        lines.append("")
    return "\n".join(lines).strip()


def summarize_result(result) -> str:
    if result is None:
        return "None"
    if isinstance(result, list):
        return f"{len(result)} items"
    if isinstance(result, dict):
        if "content" in result:
            return str(result.get("content", ""))[:200]
        return str(result)
    return str(result)
