from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    expires_in_days: int | None = None,
) -> dict[str, Any]:
    expires_at = compute_expiry(expires_in_days)
    connection.execute(
        """
        INSERT INTO memory_facts (session_id, source, content, importance, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, source, content, importance, expires_at),
    )
    connection.commit()
    return {
        "status": "saved",
        "content": content,
        "session_id": session_id,
        "source": source,
        "importance": importance,
        "expires_at": expires_at,
    }


def lookup_memory(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 5,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, session_id, source, content, importance, created_at, expires_at
        FROM memory_facts
        WHERE content LIKE ?
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
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
            "memory_type": "fact",
            "expires_at": row["expires_at"],
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
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
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
                "memory_type": "fact",
            }
            for row in rows
        ]
    preferences = lookup_preferences(connection, query=query, limit=limit, session_id=session_id)
    if preferences:
        return preferences
    summaries = get_memory_summaries(connection, session_id=session_id, limit=2)
    return summaries


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


def save_memory_preference(
    connection: sqlite3.Connection,
    category: str,
    content: str,
    session_id: str | None = None,
    confidence: float = 0.8,
    expires_in_days: int | None = 90,
) -> dict[str, Any]:
    expires_at = compute_expiry(expires_in_days)
    connection.execute(
        """
        INSERT INTO memory_preferences (session_id, category, content, confidence, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, category, content, confidence, expires_at),
    )
    connection.commit()
    return {
        "status": "saved",
        "memory_type": "preference",
        "category": category,
        "content": content,
        "session_id": session_id,
        "confidence": confidence,
        "expires_at": expires_at,
    }


def lookup_preferences(
    connection: sqlite3.Connection,
    query: str,
    limit: int = 5,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, session_id, category, content, confidence, created_at, expires_at
        FROM memory_preferences
        WHERE (content LIKE ? OR category LIKE ?)
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
    """
    params: list[Any] = [f"%{query}%", f"%{query}%"]
    if session_id:
        sql += " AND (session_id = ? OR session_id IS NULL)"
        params.append(session_id)
    sql += " ORDER BY confidence DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = connection.execute(sql, tuple(params)).fetchall()
    results = [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "source": f"preference:{row['category']}",
            "content": row["content"],
            "importance": row["confidence"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "memory_type": "preference",
        }
        for row in rows
    ]
    if results:
        return results
    if session_id and is_generic_preference_query(query):
        rows = connection.execute(
            """
            SELECT id, session_id, category, content, confidence, created_at, expires_at
            FROM memory_preferences
            WHERE session_id = ?
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            ORDER BY confidence DESC, id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "source": f"preference:{row['category']}",
                "content": row["content"],
                "importance": row["confidence"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "memory_type": "preference",
            }
            for row in rows
        ]
    return []


def save_memory_summary(
    connection: sqlite3.Connection,
    session_id: str,
    summary: str,
    turn_count: int,
) -> dict[str, Any]:
    connection.execute(
        """
        INSERT INTO memory_summaries (session_id, summary, turn_count)
        VALUES (?, ?, ?)
        """,
        (session_id, summary, turn_count),
    )
    connection.commit()
    return {"status": "saved", "memory_type": "summary", "summary": summary, "turn_count": turn_count}


def get_memory_summaries(
    connection: sqlite3.Connection,
    session_id: str | None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    if not session_id:
        return []
    rows = connection.execute(
        """
        SELECT id, session_id, summary, turn_count, created_at
        FROM memory_summaries
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "source": "session_summary",
            "content": row["summary"],
            "importance": row["turn_count"],
            "created_at": row["created_at"],
            "memory_type": "summary",
        }
        for row in rows
    ]


def maybe_capture_memory_from_turn(
    connection: sqlite3.Connection,
    session_id: str,
    question: str,
    answer: str,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    normalized = question.strip()
    if normalized.startswith(("我喜欢", "我偏好", "我通常", "我更喜欢")):
        if not preference_exists(connection, session_id, normalized):
            saved.append(
                save_memory_preference(
                    connection,
                    category="user_preference",
                    content=normalized,
                    session_id=session_id,
                    confidence=0.9,
                )
            )
    elif normalized.startswith(("我在准备", "我的目标是", "我正在")):
        if not fact_exists(connection, session_id, normalized):
            saved.append(
                save_memory_fact(
                    connection,
                    content=normalized,
                    session_id=session_id,
                    source="implicit",
                    importance=2,
                    expires_in_days=30,
                )
            )

    turns = get_session_turns(connection, session_id=session_id, limit=6)
    if len(turns) >= 6 and len(turns) % 6 == 0:
        summary = summarize_session_turns(turns)
        if summary:
            saved.append(save_memory_summary(connection, session_id=session_id, summary=summary, turn_count=len(turns)))
    return saved


def summarize_session_turns(turns: list[sqlite3.Row]) -> str:
    parts: list[str] = []
    for row in turns[-6:]:
        role = row["role"]
        content = row["content"].strip().replace("\n", " ")
        if not content:
            continue
        prefix = "U" if role == "user" else "A"
        parts.append(f"{prefix}: {content[:120]}")
    return " | ".join(parts[:6])


def compute_expiry(expires_in_days: int | None) -> str | None:
    if not expires_in_days:
        return None
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    return expires_at.isoformat()


def is_generic_preference_query(query: str) -> bool:
    normalized = query.strip().lower()
    markers = ("偏好", "喜欢什么", "preference", "favored", "我喜欢", "我的偏好")
    return any(marker in normalized for marker in markers)


def preference_exists(connection: sqlite3.Connection, session_id: str, content: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM memory_preferences
        WHERE session_id = ? AND content = ?
        LIMIT 1
        """,
        (session_id, content),
    ).fetchone()
    return row is not None


def fact_exists(connection: sqlite3.Connection, session_id: str, content: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM memory_facts
        WHERE session_id = ? AND content = ?
        LIMIT 1
        """,
        (session_id, content),
    ).fetchone()
    return row is not None
