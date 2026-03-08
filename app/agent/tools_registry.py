from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Callable

from app.agent.memory import lookup_memory, save_memory_fact
from app.retrieval.tools import (
    get_page,
    list_recent_pages,
    read_network_link,
    search_local_notion,
    search_saved_links,
)


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    handler: Callable[..., Any]


def build_tool_registry(
    connection: sqlite3.Connection,
    session_id: str = "default",
) -> dict[str, ToolDefinition]:
    return {
        "search_local_notion": ToolDefinition(
            name="search_local_notion",
            description="Search local notion chunks by query and return top-k evidence.",
            handler=lambda query, top_k=5: search_local_notion(connection, query=query, top_k=top_k),
        ),
        "list_recent_pages": ToolDefinition(
            name="list_recent_pages",
            description="List recently indexed notion pages.",
            handler=lambda limit=10: list_recent_pages(connection, limit=limit),
        ),
        "get_page": ToolDefinition(
            name="get_page",
            description="Get page metadata by page id.",
            handler=lambda page_id: get_page(connection, page_id=page_id),
        ),
        "search_saved_links": ToolDefinition(
            name="search_saved_links",
            description="Search links saved in local notion pages and return matching URLs.",
            handler=lambda query, limit=10: search_saved_links(connection, query=query, limit=limit),
        ),
        "read_network_link": ToolDefinition(
            name="read_network_link",
            description="Read the content of a relevant URL saved in notion.",
            handler=lambda url, max_chars=4000: read_network_link(url=url, max_chars=max_chars),
        ),
        "lookup_memory": ToolDefinition(
            name="lookup_memory",
            description="Search saved long-term memory facts and notes relevant to the current question.",
            handler=lambda query, limit=5: lookup_memory(
                connection,
                query=query,
                limit=limit,
                session_id=session_id,
            ),
        ),
        "save_memory": ToolDefinition(
            name="save_memory",
            description="Save an important fact into long-term memory.",
            handler=lambda content, importance=1: save_memory_fact(
                connection,
                content=content,
                session_id=session_id,
                source="agent",
                importance=importance,
            ),
        ),
    }
