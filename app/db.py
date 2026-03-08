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
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.commit()


def upsert_page(connection: sqlite3.Connection, page: Page) -> None:
    connection.execute(
        """
        INSERT INTO pages (id, title, url, source_type, created_time, last_edited_time, raw_json_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            source_type = excluded.source_type,
            created_time = excluded.created_time,
            last_edited_time = excluded.last_edited_time,
            raw_json_path = excluded.raw_json_path
        """,
        (
            page.id,
            page.title,
            page.url,
            page.source_type,
            page.created_time,
            page.last_edited_time,
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
        SELECT id, title, last_edited_time, raw_json_path
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
