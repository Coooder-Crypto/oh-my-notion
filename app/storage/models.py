from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Page:
    id: str
    title: str
    url: str
    source_type: str
    created_time: str
    last_edited_time: str
    page_kind: str = "content"
    child_count: int = 0
    link_count: int = 0
    raw_json_path: str | None = None


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    page_id: str
    heading: str
    content: str
    position: int
    token_count: int


@dataclass(slots=True)
class SearchResult:
    page_id: str
    chunk_id: str
    title: str
    heading: str
    content: str
    url: str
    rank: float
    fts_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    retrieval_method: str = "fts"


@dataclass(slots=True)
class SavedLink:
    page_id: str
    chunk_id: str | None
    page_title: str
    heading: str
    url: str
    anchor_text: str
    domain: str
    context_snippet: str
