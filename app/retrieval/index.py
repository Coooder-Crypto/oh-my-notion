from __future__ import annotations

import sqlite3

from app.retrieval.embeddings import tokenize
from app.storage.models import SearchResult


def search_chunks(connection: sqlite3.Connection, query: str, top_k: int = 5) -> list[SearchResult]:
    normalized_query = normalize_fts_query(query)
    if not normalized_query:
        return []
    rows = []
    try:
        rows = run_fts_query(connection, normalized_query, top_k)
    except sqlite3.OperationalError:
        fallback_query = " OR ".join(tokenize(query))
        if not fallback_query or fallback_query == normalized_query:
            return []
        try:
            rows = run_fts_query(connection, fallback_query, top_k)
        except sqlite3.OperationalError:
            return []

    return [
        SearchResult(
            page_id=row["page_id"],
            chunk_id=row["chunk_id"],
            title=row["title"],
            heading=row["heading"],
            content=row["content"],
            url=row["url"],
            rank=row["rank"],
            retrieval_method="fts",
        )
        for row in rows
    ]


def run_fts_query(connection: sqlite3.Connection, query: str, top_k: int) -> list[sqlite3.Row]:
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
    return cursor.fetchall()


def normalize_fts_query(query: str) -> str:
    tokens = tokenize(query)
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return " OR ".join(tokens)
