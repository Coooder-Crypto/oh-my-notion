from __future__ import annotations

from pathlib import Path
import sqlite3

from app.models import Chunk, Page


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS pages (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        source_type TEXT NOT NULL,
        created_time TEXT NOT NULL,
        last_edited_time TEXT NOT NULL,
        page_kind TEXT NOT NULL DEFAULT 'content',
        child_count INTEGER NOT NULL DEFAULT 0,
        link_count INTEGER NOT NULL DEFAULT 0,
        raw_json_path TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        page_id TEXT NOT NULL,
        heading TEXT NOT NULL,
        content TEXT NOT NULL,
        position INTEGER NOT NULL,
        token_count INTEGER NOT NULL,
        FOREIGN KEY(page_id) REFERENCES pages(id)
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_id UNINDEXED,
        page_id UNINDEXED,
        title,
        heading,
        content
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        source TEXT NOT NULL,
        content TEXT NOT NULL,
        importance INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    ensure_pages_columns(connection)
    connection.commit()


def upsert_page(connection: sqlite3.Connection, page: Page) -> None:
    connection.execute(
        """
        INSERT INTO pages (
            id,
            title,
            url,
            source_type,
            created_time,
            last_edited_time,
            page_kind,
            child_count,
            link_count,
            raw_json_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            source_type = excluded.source_type,
            created_time = excluded.created_time,
            last_edited_time = excluded.last_edited_time,
            page_kind = excluded.page_kind,
            child_count = excluded.child_count,
            link_count = excluded.link_count,
            raw_json_path = excluded.raw_json_path
        """,
        (
            page.id,
            page.title,
            page.url,
            page.source_type,
            page.created_time,
            page.last_edited_time,
            page.page_kind,
            page.child_count,
            page.link_count,
            page.raw_json_path,
        ),
    )
    connection.commit()


def replace_page_chunks(connection: sqlite3.Connection, page: Page, chunks: list[Chunk]) -> None:
    upsert_page(connection, page)
    connection.execute("DELETE FROM chunks WHERE page_id = ?", (page.id,))
    connection.execute("DELETE FROM chunks_fts WHERE page_id = ?", (page.id,))

    for chunk in chunks:
        connection.execute(
            """
            INSERT INTO chunks (chunk_id, page_id, heading, content, position, token_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.page_id,
                chunk.heading,
                chunk.content,
                chunk.position,
                chunk.token_count,
            ),
        )
        connection.execute(
            """
            INSERT INTO chunks_fts (chunk_id, page_id, title, heading, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chunk.chunk_id, chunk.page_id, page.title, chunk.heading, chunk.content),
        )

    connection.commit()


def get_page_sync_state(connection: sqlite3.Connection, page_id: str) -> sqlite3.Row | None:
    cursor = connection.execute(
        """
        SELECT id, title, last_edited_time, raw_json_path, page_kind, child_count, link_count
        FROM pages
        WHERE id = ?
        """,
        (page_id,),
    )
    return cursor.fetchone()


def reset_index(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM chunks")
    connection.execute("DELETE FROM chunks_fts")
    connection.execute("DELETE FROM pages")
    connection.commit()


def ensure_pages_columns(connection: sqlite3.Connection) -> None:
    existing_columns = set()
    for row in connection.execute("PRAGMA table_info(pages)").fetchall():
        if isinstance(row, sqlite3.Row):
            existing_columns.add(row["name"])
        else:
            existing_columns.add(row[1])

    maybe_add_pages_column(
        connection,
        existing_columns,
        "page_kind",
        "ALTER TABLE pages ADD COLUMN page_kind TEXT NOT NULL DEFAULT 'content'",
    )
    maybe_add_pages_column(
        connection,
        existing_columns,
        "child_count",
        "ALTER TABLE pages ADD COLUMN child_count INTEGER NOT NULL DEFAULT 0",
    )
    maybe_add_pages_column(
        connection,
        existing_columns,
        "link_count",
        "ALTER TABLE pages ADD COLUMN link_count INTEGER NOT NULL DEFAULT 0",
    )


def maybe_add_pages_column(
    connection: sqlite3.Connection,
    existing_columns: set[str],
    column_name: str,
    statement: str,
) -> None:
    if column_name in existing_columns:
        return
    try:
        connection.execute(statement)
        existing_columns.add(column_name)
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def get_stats(connection: sqlite3.Connection) -> dict[str, int]:
    pages_count = connection.execute("SELECT COUNT(*) AS count FROM pages").fetchone()["count"]
    chunks_count = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"]
    empty_pages = connection.execute(
        "SELECT COUNT(*) AS count FROM pages WHERE page_kind = 'empty'"
    ).fetchone()["count"]
    container_pages = connection.execute(
        "SELECT COUNT(*) AS count FROM pages WHERE page_kind = 'container'"
    ).fetchone()["count"]
    content_pages = connection.execute(
        "SELECT COUNT(*) AS count FROM pages WHERE page_kind = 'content'"
    ).fetchone()["count"]
    links_count = connection.execute(
        "SELECT COALESCE(SUM(link_count), 0) AS count FROM pages"
    ).fetchone()["count"]
    session_turns = connection.execute(
        "SELECT COUNT(*) AS count FROM session_turns"
    ).fetchone()["count"]
    memory_facts = connection.execute(
        "SELECT COUNT(*) AS count FROM memory_facts"
    ).fetchone()["count"]
    return {
        "pages": pages_count,
        "chunks": chunks_count,
        "empty_pages": empty_pages,
        "container_pages": container_pages,
        "content_pages": content_pages,
        "links": links_count,
        "session_turns": session_turns,
        "memory_facts": memory_facts,
    }
