from __future__ import annotations

import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.retrieval.hybrid import search_chunks_hybrid
from app.storage.models import SearchResult


def search_local_notion(
    connection: sqlite3.Connection,
    query: str,
    top_k: int = 5,
) -> list[SearchResult]:
    return search_chunks_hybrid(connection=connection, query=query, top_k=top_k)


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
    normalized_query = (query or "").strip()
    if normalized_query:
        rows = connection.execute(
            """
            SELECT
                saved_links.page_id AS page_id,
                saved_links.page_title AS title,
                pages.url AS page_url,
                saved_links.heading AS heading,
                saved_links.url AS url,
                saved_links.anchor_text AS anchor_text,
                saved_links.domain AS domain,
                saved_links.context_snippet AS snippet
            FROM saved_links
            JOIN pages ON pages.id = saved_links.page_id
            WHERE
                saved_links.anchor_text LIKE ?
                OR saved_links.url LIKE ?
                OR saved_links.domain LIKE ?
                OR saved_links.context_snippet LIKE ?
                OR saved_links.page_title LIKE ?
                OR saved_links.heading LIKE ?
            ORDER BY pages.last_edited_time DESC
            LIMIT ?
            """,
            (
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                f"%{normalized_query}%",
                limit,
            ),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT
                saved_links.page_id AS page_id,
                saved_links.page_title AS title,
                pages.url AS page_url,
                saved_links.heading AS heading,
                saved_links.url AS url,
                saved_links.anchor_text AS anchor_text,
                saved_links.domain AS domain,
                saved_links.context_snippet AS snippet
            FROM saved_links
            JOIN pages ON pages.id = saved_links.page_id
            ORDER BY pages.last_edited_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "page_id": row["page_id"],
            "title": row["title"],
            "page_url": row["page_url"],
            "heading": row["heading"],
            "links": [row["url"]],
            "url": row["url"],
            "anchor_text": row["anchor_text"],
            "domain": row["domain"],
            "snippet": row["snippet"],
        }
        for row in rows
    ]


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
