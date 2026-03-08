from __future__ import annotations

import sqlite3

from app.models import SearchResult


def search_chunks(connection: sqlite3.Connection, query: str, top_k: int = 5) -> list[SearchResult]:
    cursor = connection.execute(
        """
        SELECT
            chunks.page_id AS page_id,
            chunks.chunk_id AS chunk_id,
            pages.title AS title,
            chunks.heading AS heading,
            chunks.content AS content,
            pages.url AS url,
            bm25(chunks_fts, 5.0, 2.0, 1.0) AS rank
        FROM chunks_fts
        JOIN chunks ON chunks.chunk_id = chunks_fts.chunk_id
        JOIN pages ON pages.id = chunks.page_id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, top_k),
    )
    rows = cursor.fetchall()
    return [
        SearchResult(
            page_id=row["page_id"],
            chunk_id=row["chunk_id"],
            title=row["title"],
            heading=row["heading"],
            content=row["content"],
            url=row["url"],
            rank=row["rank"],
        )
        for row in rows
    ]

