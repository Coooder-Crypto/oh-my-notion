from __future__ import annotations

import sqlite3
from typing import Any


def save_session_turn(
    connection: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
) -> None:
    connection.execute(
        """
        INSERT INTO session_turns (session_id, role, content)
        VALUES (?, ?, ?)
        """,
        (session_id, role, content),
    )
    connection.commit()


def get_session_turns(
    connection: sqlite3.Connection,
    session_id: str,
    limit: int = 6,
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT id, session_id, role, content, created_at
        FROM session_turns
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return list(reversed(rows))


def save_memory_fact(
    connection: sqlite3.Connection,
    content: str,
    session_id: str | None = None,
    source: str = "agent",
    importance: int = 1,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO memory_facts (session_id, source, content, importance)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, source, content, importance),
    )
    connection.commit()
    return {
        "status": "saved",
        "content": content,
        "session_id": session_id,
        "source": source,
        "importance": importance,
    }


def lookup_memory(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 5,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, session_id, source, content, importance, created_at
        FROM memory_facts
        WHERE content LIKE ?
    """
    params: list[Any] = [f"%{query}%"]
    if session_id:
        sql += " AND (session_id = ? OR session_id IS NULL)"
        params.append(session_id)
    sql += " ORDER BY importance DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = connection.execute(sql, tuple(params)).fetchall()
    results = [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "source": row["source"],
            "content": row["content"],
            "importance": row["importance"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    if results:
        return results

    if session_id and is_generic_memory_query(query):
        rows = connection.execute(
            """
            SELECT id, session_id, source, content, importance, created_at
            FROM memory_facts
            WHERE session_id = ?
            ORDER BY importance DESC, id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "source": row["source"],
                "content": row["content"],
                "importance": row["importance"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    return []


def is_generic_memory_query(query: str) -> bool:
    normalized = query.strip().lower()
    generic_markers = (
        "记住了什么",
        "记得什么",
        "memory",
        "remembered",
        "saved",
        "之前",
        "刚才",
        "上次",
    )
    return any(marker in normalized for marker in generic_markers)
