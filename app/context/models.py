from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextItem:
    kind: str
    title: str
    content: str
    priority: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ContextBundle:
    question: str
    items: list[ContextItem]
    formatted_text: str
    total_chars: int

