from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextItem:
    kind: str
    title: str
    content: str
    priority: int
    citation_id: str = ""
    rationale: str = ""
    allocated_chars: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ContextBundle:
    question: str
    items: list[ContextItem]
    formatted_text: str
    explanation_text: str
    total_chars: int
    budget_report: dict[str, int] = field(default_factory=dict)
