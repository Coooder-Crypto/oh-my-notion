from __future__ import annotations

import json
import sqlite3

from app.retrieval.embeddings import cosine_similarity, embed_text_local, lexical_overlap_score
from app.retrieval.index import search_chunks
from app.storage.models import SearchResult


DEFAULT_CANDIDATE_MULTIPLIER = 4


def search_chunks_hybrid(
    connection: sqlite3.Connection,
    query: str,
    top_k: int = 5,
    candidate_k: int | None = None,
) -> list[SearchResult]:
    candidate_limit = max(top_k, candidate_k or (top_k * DEFAULT_CANDIDATE_MULTIPLIER))
    fts_results = search_chunks(connection=connection, query=query, top_k=candidate_limit)
    vector_results = search_chunks_by_vector(
        connection=connection,
        query=query,
        top_k=candidate_limit,
    )
    return merge_and_rerank(query=query, fts_results=fts_results, vector_results=vector_results, top_k=top_k)


def search_chunks_by_vector(
    connection: sqlite3.Connection,
    query: str,
    top_k: int = 5,
) -> list[SearchResult]:
    query_vector = embed_text_local(query)
    rows = connection.execute(
        """
        SELECT
            chunk_embeddings.chunk_id AS chunk_id,
            chunk_embeddings.vector AS vector,
            chunks.page_id AS page_id,
            pages.title AS title,
            chunks.heading AS heading,
            chunks.content AS content,
            pages.url AS url
        FROM chunk_embeddings
        JOIN chunks ON chunks.chunk_id = chunk_embeddings.chunk_id
        JOIN pages ON pages.id = chunks.page_id
        """
    ).fetchall()

    scored: list[SearchResult] = []
    for row in rows:
        vector = decode_vector(row["vector"])
        similarity = cosine_similarity(query_vector, vector)
        if similarity <= 0:
            continue
        scored.append(
            SearchResult(
                page_id=row["page_id"],
                chunk_id=row["chunk_id"],
                title=row["title"],
                heading=row["heading"],
                content=row["content"],
                url=row["url"],
                rank=-similarity,
                vector_score=similarity,
                retrieval_method="vector",
            )
        )

    scored.sort(key=lambda item: item.vector_score, reverse=True)
    return scored[:top_k]


def merge_and_rerank(
    query: str,
    fts_results: list[SearchResult],
    vector_results: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    merged: dict[str, SearchResult] = {}
    normalized_fts = normalize_fts_scores(fts_results)

    for result in fts_results:
        result.fts_score = normalized_fts.get(result.chunk_id, 0.0)
        result.retrieval_method = "fts"
        merged[result.chunk_id] = result

    for result in vector_results:
        existing = merged.get(result.chunk_id)
        if existing is None:
            merged[result.chunk_id] = result
            continue
        existing.vector_score = max(existing.vector_score, result.vector_score)
        existing.retrieval_method = "hybrid"

    reranked: list[SearchResult] = []
    for result in merged.values():
        overlap = lexical_overlap_score(query, f"{result.title} {result.heading} {result.content}")
        result.rerank_score = (
            (result.fts_score * 0.45)
            + (result.vector_score * 0.4)
            + (overlap * 0.15)
        )
        if result.vector_score > 0 and result.fts_score > 0:
            result.retrieval_method = "hybrid"
        reranked.append(result)

    reranked.sort(key=lambda item: item.rerank_score, reverse=True)
    return reranked[:top_k]


def normalize_fts_scores(results: list[SearchResult]) -> dict[str, float]:
    if not results:
        return {}
    raw_scores = [-result.rank for result in results]
    min_score = min(raw_scores)
    max_score = max(raw_scores)
    if max_score == min_score:
        return {result.chunk_id: 1.0 for result in results}
    normalized: dict[str, float] = {}
    for result, raw_score in zip(results, raw_scores):
        normalized[result.chunk_id] = (raw_score - min_score) / (max_score - min_score)
    return normalized


def encode_vector(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def decode_vector(payload: str) -> list[float]:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [float(value) for value in raw]
