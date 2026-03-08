from __future__ import annotations

from app.agent.executor import ToolObservation
from app.context.models import ContextBundle, ContextItem
from app.storage.models import SearchResult


DEFAULT_CONTEXT_BUDGET = 7000
DEFAULT_KIND_BUDGETS = {
    "retrieval": 3200,
    "network": 1800,
    "memory": 900,
    "summary": 700,
    "session": 500,
    "tool": 500,
    "trace": 500,
}


def build_context_bundle(
    question: str,
    search_results: list[SearchResult] | None = None,
    memory_items: list[dict] | None = None,
    session_turns: list[dict] | None = None,
    session_summaries: list[dict] | None = None,
    tool_observations: list[ToolObservation] | None = None,
    network_content: list[dict] | None = None,
    planner_trace: list[dict] | None = None,
    char_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> ContextBundle:
    items: list[ContextItem] = []
    items.extend(context_from_search_results(search_results or []))
    items.extend(context_from_memory(memory_items or []))
    items.extend(context_from_session_summaries(session_summaries or []))
    items.extend(context_from_session(session_turns or []))
    items.extend(context_from_network(network_content or []))
    items.extend(context_from_observations(tool_observations or []))
    items.extend(context_from_trace(planner_trace or []))

    ranked = sorted(items, key=lambda item: item.priority)
    budgeted = apply_budget(ranked, char_budget)
    budget_report = summarize_budget(budgeted)
    annotate_citations(budgeted)
    formatted_text = format_context(question, budgeted)
    explanation_text = format_explanation(budgeted, budget_report)
    return ContextBundle(
        question=question,
        items=budgeted,
        formatted_text=formatted_text,
        explanation_text=explanation_text,
        total_chars=len(formatted_text),
        budget_report=budget_report,
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
                    f"Retrieval Method: {result.retrieval_method}\n"
                    f"Content: {result.content}"
                ),
                priority=10 + index,
                rationale="High-confidence retrieved evidence from local notion index.",
                metadata={
                    "page_id": result.page_id,
                    "chunk_id": result.chunk_id,
                    "fts_score": f"{result.fts_score:.3f}" if result.fts_score else "",
                    "vector_score": f"{result.vector_score:.3f}" if result.vector_score else "",
                    "rerank_score": f"{result.rerank_score:.3f}" if result.rerank_score else "",
                },
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
                rationale="Long-term memory relevant to the current question.",
                metadata={
                    "source": str(item.get("source", "")),
                    "importance": str(item.get("importance", 1)),
                    "memory_type": str(item.get("memory_type", "")),
                },
            )
        )
    return items


def context_from_session_summaries(session_summaries: list[dict]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for index, item in enumerate(session_summaries, start=1):
        items.append(
            ContextItem(
                kind="summary",
                title=f"Session Summary {index}",
                content=item.get("content", ""),
                priority=40 + index,
                rationale="Compressed short-term memory summary for recent conversation state.",
                metadata={"source": str(item.get("source", ""))},
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
                rationale="Recent turn kept for conversational continuity.",
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
                rationale="External page content fetched from a saved link.",
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
                rationale="Recent tool outcome included for execution transparency.",
                metadata={"reason": observation.reason},
            )
        )
    return items


def context_from_trace(planner_trace: list[dict]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for item in planner_trace[-3:]:
        step = item.get("step", "")
        content = (
            f"Thought: {item.get('thought', '')}\n"
            f"Observation: {item.get('observation', '')}"
        )
        items.append(
            ContextItem(
                kind="trace",
                title=f"Planner Trace Step {step}",
                content=content,
                priority=80 + int(step or 0),
                rationale="Reasoning trace retained for explainability and debugging.",
            )
        )
    return items


def apply_budget(items: list[ContextItem], char_budget: int) -> list[ContextItem]:
    selected: list[ContextItem] = []
    used = 0
    kind_usage = {kind: 0 for kind in DEFAULT_KIND_BUDGETS}
    for item in items:
        remaining_total = max(0, char_budget - used)
        if remaining_total <= 0:
            break
        kind_budget = DEFAULT_KIND_BUDGETS.get(item.kind, 400)
        remaining_kind = max(0, kind_budget - kind_usage.get(item.kind, 0))
        if remaining_kind <= 0:
            continue
        max_for_item = min(remaining_total, remaining_kind)
        trimmed = trim_item_to_budget(item, max_for_item)
        if not trimmed.content.strip():
            continue
        item_size = len(trimmed.title) + len(trimmed.content)
        trimmed.allocated_chars = item_size
        selected.append(trimmed)
        used += item_size
        kind_usage[trimmed.kind] = kind_usage.get(trimmed.kind, 0) + item_size
    return selected


def trim_item_to_budget(item: ContextItem, budget: int) -> ContextItem:
    available = max(0, budget - len(item.title) - 24)
    if len(item.content) <= available:
        return item
    trimmed_content = item.content[:available].rstrip()
    if available > 32:
        trimmed_content += "..."
    return ContextItem(
        kind=item.kind,
        title=item.title,
        content=trimmed_content,
        priority=item.priority,
        citation_id=item.citation_id,
        rationale=item.rationale,
        allocated_chars=item.allocated_chars,
        metadata=item.metadata,
    )


def annotate_citations(items: list[ContextItem]) -> None:
    for index, item in enumerate(items, start=1):
        item.citation_id = f"C{index}"


def summarize_budget(items: list[ContextItem]) -> dict[str, int]:
    report: dict[str, int] = {}
    for item in items:
        report[item.kind] = report.get(item.kind, 0) + item.allocated_chars
    return report


def format_context(question: str, items: list[ContextItem]) -> str:
    lines = [f"Question:\n{question}", "", "Context:"]
    for item in items:
        lines.append(f"- [{item.citation_id}] [{item.kind}] {item.title}")
        if item.metadata:
            metadata_text = ", ".join(f"{key}={value}" for key, value in item.metadata.items() if value)
            if metadata_text:
                lines.append(f"  Meta: {metadata_text}")
        if item.rationale:
            lines.append(f"  Why included: {item.rationale}")
        lines.append(f"  {item.content}")
        lines.append("")
    return "\n".join(lines).strip()


def format_explanation(items: list[ContextItem], budget_report: dict[str, int]) -> str:
    lines = ["Context Explanation:"]
    for item in items:
        lines.append(
            f"- [{item.citation_id}] {item.kind}: {item.title} | chars={item.allocated_chars} | why={item.rationale}"
        )
    if budget_report:
        lines.append("")
        lines.append("Budget Usage:")
        for kind, value in sorted(budget_report.items()):
            lines.append(f"- {kind}: {value}")
    return "\n".join(lines)


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
