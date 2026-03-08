from __future__ import annotations

import sqlite3

from app.index import search_chunks
from app.models import SearchResult


def search_local_notion(
    connection: sqlite3.Connection,
    query: str,
    top_k: int = 5,
) -> list[SearchResult]:
    return search_chunks(connection=connection, query=query, top_k=top_k)


def list_recent_pages(connection: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    cursor = connection.execute(
        """
        SELECT id, title, url, last_edited_time
        FROM pages
        ORDER BY last_edited_time DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def get_page(connection: sqlite3.Connection, page_id: str) -> sqlite3.Row | None:
    cursor = connection.execute(
        """
        SELECT id, title, url, source_type, created_time, last_edited_time, raw_json_path
        FROM pages
        WHERE id = ?
        """,
        (page_id,),
    )
    return cursor.fetchone()

