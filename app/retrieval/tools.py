from __future__ import annotations

import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.retrieval.index import search_chunks
from app.storage.models import SearchResult


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


def search_saved_links(connection: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    rows = connection.execute(
        """
        SELECT pages.id AS page_id, pages.title AS title, pages.url AS page_url, chunks.heading AS heading, chunks.content AS content
        FROM chunks
        JOIN pages ON pages.id = chunks.page_id
        WHERE chunks.content LIKE ?
        ORDER BY pages.last_edited_time DESC
        LIMIT ?
        """,
        (f"%{query}%", limit),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        links = extract_links(row["content"])
        if not links:
            continue
        results.append(
            {
                "page_id": row["page_id"],
                "title": row["title"],
                "page_url": row["page_url"],
                "heading": row["heading"],
                "links": links,
                "snippet": row["content"][:300],
            }
        )
    return results


def read_network_link(url: str, max_chars: int = 4000) -> dict:
    request = Request(url=url, headers={"User-Agent": "oh-my-notion/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read(max_chars).decode("utf-8", errors="replace")
            return {
                "url": url,
                "content_type": response.headers.get("Content-Type", ""),
                "content": body[:max_chars],
            }
    except HTTPError as exc:
        return {"url": url, "error": f"HTTP {exc.code}"}
    except URLError as exc:
        return {"url": url, "error": f"URL error: {exc.reason}"}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def extract_links(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"https?://[^\s>]+", text)))
