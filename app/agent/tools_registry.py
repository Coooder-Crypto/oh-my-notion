from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Callable

from app.agent.memory import lookup_memory, lookup_preferences, save_memory_fact, save_memory_preference
from app.retrieval.tools import (
    find_pages_by_domain,
    get_page,
    get_link_domain_summary,
    list_recent_pages,
    list_top_link_domains,
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
    def tool_search_local_notion(query: str, top_k: int = 5) -> Any:
        return search_local_notion(connection, query=query, top_k=top_k)

    def tool_list_recent_pages(limit: int = 10) -> Any:
        return list_recent_pages(connection, limit=limit)

    def tool_get_page(page_id: str) -> Any:
        return get_page(connection, page_id=page_id)

    def tool_search_saved_links(query: str, limit: int = 10) -> Any:
        return search_saved_links(connection, query=query, limit=limit)

    def tool_read_network_link(url: str, max_chars: int = 4000) -> Any:
        return read_network_link(url=url, max_chars=max_chars)

    def tool_list_top_link_domains(limit: int = 10) -> Any:
        return list_top_link_domains(connection, limit=limit)

    def tool_find_pages_by_domain(domain: str, limit: int = 10) -> Any:
        return find_pages_by_domain(connection, domain=domain, limit=limit)

    def tool_get_link_domain_summary(domain: str) -> Any:
        return get_link_domain_summary(connection, domain=domain)

    def tool_lookup_memory(query: str, limit: int = 5) -> Any:
        return lookup_memory(
            connection,
            query=query,
            limit=limit,
            session_id=session_id,
        )

    def tool_lookup_preferences(query: str, limit: int = 5) -> Any:
        return lookup_preferences(
            connection,
            query=query,
            limit=limit,
            session_id=session_id,
        )

    def tool_save_memory(content: str, importance: int = 1) -> Any:
        return save_memory_fact(
            connection,
            content=content,
            session_id=session_id,
            source="agent",
            importance=importance,
        )

    def tool_save_preference(category: str, content: str, confidence: float = 0.9) -> Any:
        return save_memory_preference(
            connection,
            category=category,
            content=content,
            session_id=session_id,
            confidence=confidence,
        )

    return {
        "search_local_notion": ToolDefinition(
            name="search_local_notion",
            description="Search local notion chunks with hybrid retrieval (FTS + semantic vector search) and return top-k reranked evidence.",
            handler=tool_search_local_notion,
        ),
        "list_recent_pages": ToolDefinition(
            name="list_recent_pages",
            description="List recently indexed notion pages.",
            handler=tool_list_recent_pages,
        ),
        "get_page": ToolDefinition(
            name="get_page",
            description="Get page metadata by page id.",
            handler=tool_get_page,
        ),
        "search_saved_links": ToolDefinition(
            name="search_saved_links",
            description="Search links saved in local notion pages and return matching URLs.",
            handler=tool_search_saved_links,
        ),
        "read_network_link": ToolDefinition(
            name="read_network_link",
            description="Read the content of a relevant URL saved in notion.",
            handler=tool_read_network_link,
        ),
        "list_top_link_domains": ToolDefinition(
            name="list_top_link_domains",
            description="List domains that appear most often in saved links.",
            handler=tool_list_top_link_domains,
        ),
        "find_pages_by_domain": ToolDefinition(
            name="find_pages_by_domain",
            description="Find pages that saved links from a specific domain.",
            handler=tool_find_pages_by_domain,
        ),
        "get_link_domain_summary": ToolDefinition(
            name="get_link_domain_summary",
            description="Return a cached summary for how a domain appears in local notion notes.",
            handler=tool_get_link_domain_summary,
        ),
        "lookup_memory": ToolDefinition(
            name="lookup_memory",
            description="Search saved long-term memory facts and notes relevant to the current question.",
            handler=tool_lookup_memory,
        ),
        "lookup_preferences": ToolDefinition(
            name="lookup_preferences",
            description="Search saved user preferences relevant to the current question.",
            handler=tool_lookup_preferences,
        ),
        "save_memory": ToolDefinition(
            name="save_memory",
            description="Save an important fact into long-term memory.",
            handler=tool_save_memory,
        ),
        "save_preference": ToolDefinition(
            name="save_preference",
            description="Save a stable user preference into memory.",
            handler=tool_save_preference,
        ),
    }
