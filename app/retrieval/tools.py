from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.retrieval.embeddings import tokenize
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
            saved_links.context_snippet AS snippet,
            pages.last_edited_time AS last_edited_time
        FROM saved_links
        JOIN pages ON pages.id = saved_links.page_id
        """
    ).fetchall()
    scored = []
    for row in rows:
        score = score_saved_link_row(row, normalized_query)
        if normalized_query and score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: (item[0], item[1]["last_edited_time"]), reverse=True)
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
            "score": score,
        }
        for score, row in scored[:limit]
    ]


def list_top_link_domains(connection: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            domain,
            COUNT(*) AS link_count,
            COUNT(DISTINCT page_id) AS page_count,
            MAX(page_title) AS sample_page
        FROM saved_links
        WHERE domain != ''
        GROUP BY domain
        ORDER BY link_count DESC, page_count DESC, domain ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def find_pages_by_domain(connection: sqlite3.Connection, domain: str, limit: int = 10) -> list[dict]:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return []
    rows = connection.execute(
        """
        SELECT
            saved_links.page_id AS page_id,
            saved_links.page_title AS title,
            pages.url AS page_url,
            COUNT(*) AS link_count,
            GROUP_CONCAT(DISTINCT saved_links.anchor_text) AS anchors
        FROM saved_links
        JOIN pages ON pages.id = saved_links.page_id
        WHERE saved_links.domain LIKE ?
        GROUP BY saved_links.page_id, saved_links.page_title, pages.url
        ORDER BY link_count DESC, title ASC
        LIMIT ?
        """,
        (f"%{normalized_domain}%", limit),
    ).fetchall()
    return [
        {
            "page_id": row["page_id"],
            "title": row["title"],
            "page_url": row["page_url"],
            "link_count": row["link_count"],
            "anchors": [anchor for anchor in str(row["anchors"] or "").split(",") if anchor][:6],
            "domain": normalized_domain,
        }
        for row in rows
    ]


def get_link_domain_summary(connection: sqlite3.Connection, domain: str) -> dict:
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return {"domain": domain, "error": "missing domain"}
    cached = connection.execute(
        """
        SELECT domain, summary, link_count, updated_at
        FROM link_summaries
        WHERE domain = ?
        """,
        (normalized_domain,),
    ).fetchone()
    if cached:
        return dict(cached)

    pages = find_pages_by_domain(connection, normalized_domain, limit=8)
    if not pages:
        return {"domain": normalized_domain, "error": "no pages found"}
    anchors = connection.execute(
        """
        SELECT anchor_text, COUNT(*) AS count
        FROM saved_links
        WHERE domain = ?
        GROUP BY anchor_text
        ORDER BY count DESC, anchor_text ASC
        LIMIT 8
        """,
        (normalized_domain,),
    ).fetchall()
    link_count = sum(page["link_count"] for page in pages)
    summary = build_link_summary_text(normalized_domain, pages, anchors)
    connection.execute(
        """
        INSERT INTO link_summaries (domain, summary, link_count)
        VALUES (?, ?, ?)
        ON CONFLICT(domain) DO UPDATE SET
            summary = excluded.summary,
            link_count = excluded.link_count,
            updated_at = CURRENT_TIMESTAMP
        """,
        (normalized_domain, summary, link_count),
    )
    connection.commit()
    return {"domain": normalized_domain, "summary": summary, "link_count": link_count}


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


def score_saved_link_row(row: sqlite3.Row, query: str) -> float:
    if not query:
        return 1.0
    normalized_query = query.lower()
    query_tokens = set(tokenize(query))
    score = 0.0
    domain = str(row["domain"] or "").lower()
    anchor = str(row["anchor_text"] or "").lower()
    url = str(row["url"] or "").lower()
    snippet = str(row["snippet"] or "").lower()
    title = str(row["title"] or "").lower()
    heading = str(row["heading"] or "").lower()

    if normalized_query in domain:
        score += 4.0
    if normalized_query in anchor:
        score += 3.5
    if normalized_query in url:
        score += 3.0
    if normalized_query in title:
        score += 2.0
    if normalized_query in heading:
        score += 1.5
    if normalized_query in snippet:
        score += 1.0

    text_tokens = set(tokenize(" ".join((domain, anchor, url, title, heading, snippet))))
    score += len(query_tokens & text_tokens) * 0.75
    return score


def normalize_domain(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return urlparse(raw).netloc.lower()
    return raw.removeprefix("www.")


def build_link_summary_text(domain: str, pages: list[dict], anchors: list[sqlite3.Row]) -> str:
    anchor_text = "、".join(str(row["anchor_text"]) for row in anchors if row["anchor_text"]) or "无明显锚文本"
    page_text = "、".join(page["title"] for page in pages[:5]) or "无页面"
    return (
        f"域名 {domain} 在本地知识库中主要出现在这些页面：{page_text}。"
        f"常见锚文本包括：{anchor_text}。"
    )
