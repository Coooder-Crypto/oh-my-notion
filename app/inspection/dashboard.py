from __future__ import annotations

import sqlite3

from app.retrieval.embeddings import tokenize
from app.storage.db import get_stats


STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "into",
    "about",
    "what",
    "have",
    "will",
    "your",
    "local",
    "notion",
    "page",
    "pages",
    "agent",
    "notes",
    "正文",
}


def build_dashboard_payload(connection: sqlite3.Connection, raw_snapshots: int = 0) -> dict:
    overview = get_stats(connection)
    overview["raw_snapshots"] = raw_snapshots

    page_kinds = query_named_counts(
        connection,
        """
        SELECT page_kind AS name, COUNT(*) AS value
        FROM pages
        GROUP BY page_kind
        ORDER BY value DESC, name ASC
        """,
    )
    source_types = query_named_counts(
        connection,
        """
        SELECT source_type AS name, COUNT(*) AS value
        FROM pages
        GROUP BY source_type
        ORDER BY value DESC, name ASC
        LIMIT 8
        """,
    )
    recent_activity = query_named_counts(
        connection,
        """
        SELECT SUBSTR(last_edited_time, 1, 10) AS name, COUNT(*) AS value
        FROM pages
        WHERE last_edited_time != ''
        GROUP BY name
        ORDER BY name DESC
        LIMIT 14
        """,
    )[::-1]
    top_pages_by_chunks = [dict(row) for row in connection.execute(
        """
        SELECT
            pages.id AS id,
            pages.title AS title,
            pages.url AS url,
            pages.page_kind AS page_kind,
            COUNT(chunks.chunk_id) AS chunk_count,
            pages.link_count AS link_count,
            pages.last_edited_time AS last_edited_time
        FROM pages
        LEFT JOIN chunks ON chunks.page_id = pages.id
        GROUP BY pages.id
        ORDER BY chunk_count DESC, pages.link_count DESC, pages.last_edited_time DESC
        LIMIT 8
        """
    ).fetchall()]
    top_pages_by_links = [dict(row) for row in connection.execute(
        """
        SELECT id, title, url, link_count, child_count, last_edited_time
        FROM pages
        WHERE link_count > 0
        ORDER BY link_count DESC, child_count DESC, last_edited_time DESC
        LIMIT 8
        """
    ).fetchall()]
    top_headings = query_named_counts(
        connection,
        """
        SELECT heading AS name, COUNT(*) AS value
        FROM chunks
        WHERE heading != ''
        GROUP BY heading
        ORDER BY value DESC, name ASC
        LIMIT 10
        """,
    )
    top_domains = query_named_counts(
        connection,
        """
        SELECT domain AS name, COUNT(*) AS value
        FROM saved_links
        WHERE domain != ''
        GROUP BY domain
        ORDER BY value DESC, name ASC
        LIMIT 10
        """,
    )
    top_keywords = extract_top_keywords(connection)

    return {
        "overview": overview,
        "page_kinds": page_kinds,
        "source_types": source_types,
        "recent_activity": recent_activity,
        "top_pages_by_chunks": top_pages_by_chunks,
        "top_pages_by_links": top_pages_by_links,
        "top_headings": top_headings,
        "top_domains": top_domains,
        "top_keywords": top_keywords,
        "insights": build_insights(
            overview=overview,
            page_kinds=page_kinds,
            source_types=source_types,
            top_pages_by_chunks=top_pages_by_chunks,
            top_pages_by_links=top_pages_by_links,
            top_domains=top_domains,
            top_keywords=top_keywords,
        ),
    }


def query_named_counts(connection: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(row) for row in connection.execute(sql).fetchall()]


def extract_top_keywords(connection: sqlite3.Connection, limit: int = 12) -> list[dict]:
    token_counts: dict[str, int] = {}
    rows = connection.execute(
        """
        SELECT pages.title AS title, chunks.heading AS heading, chunks.content AS content
        FROM chunks
        JOIN pages ON pages.id = chunks.page_id
        """
    ).fetchall()
    for row in rows:
        text = f"{row['title']} {row['heading']} {row['content']}"
        for token in tokenize(text):
            normalized = token.strip().lower()
            if should_skip_token(normalized):
                continue
            token_counts[normalized] = token_counts.get(normalized, 0) + 1

    ranked = sorted(token_counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "value": value} for name, value in ranked[:limit]]


def should_skip_token(token: str) -> bool:
    if not token:
        return True
    if token in STOPWORDS:
        return True
    if token.isascii() and len(token) <= 2:
        return True
    if not token.isascii() and len(token) <= 1:
        return True
    if token.isdigit():
        return True
    return False


def build_insights(
    overview: dict,
    page_kinds: list[dict],
    source_types: list[dict],
    top_pages_by_chunks: list[dict],
    top_pages_by_links: list[dict],
    top_domains: list[dict],
    top_keywords: list[dict],
) -> list[str]:
    insights: list[str] = []
    if overview.get("pages", 0) == 0:
        return ["当前本地库还没有页面，先完成一次 sync 或 ingest-sample 才能看到内容分析。"]

    if page_kinds:
        dominant_kind = page_kinds[0]
        insights.append(
            f"当前知识库以 {dominant_kind['name']} 类型页面为主，共 {dominant_kind['value']} 页。"
        )
    if source_types:
        dominant_source = source_types[0]
        insights.append(
            f"主要来源类型是 {dominant_source['name']}，共有 {dominant_source['value']} 页。"
        )
    if top_pages_by_chunks:
        largest_page = top_pages_by_chunks[0]
        insights.append(
            f"内容最密集的页面是《{largest_page['title'] or 'Untitled'}》，包含 {largest_page['chunk_count']} 个 chunk。"
        )
    if top_pages_by_links:
        link_page = top_pages_by_links[0]
        insights.append(
            f"外部链接最多的页面是《{link_page['title'] or 'Untitled'}》，包含 {link_page['link_count']} 个链接。"
        )
    if top_keywords:
        keyword_text = "、".join(item["name"] for item in top_keywords[:5])
        insights.append(f"当前内容里的高频主题词包括：{keyword_text}。")
    if top_domains:
        domain_text = "、".join(item["name"] for item in top_domains[:3])
        insights.append(f"最常出现的外部站点包括：{domain_text}。")
    return insights
