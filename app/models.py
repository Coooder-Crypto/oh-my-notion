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

