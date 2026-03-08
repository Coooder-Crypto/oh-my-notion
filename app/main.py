from __future__ import annotations

from datetime import datetime, timezone

import typer

from app.agent import answer_question
from app.config import load_settings
from app.db import connect, get_stats, init_db, replace_page_chunks
from app.inspect import (
    inspect_chunks_snapshot,
    inspect_links_snapshot,
    inspect_page_snapshot,
    inspect_raw_snapshot,
    resolve_raw_target,
)
from app.models import Chunk, Page
from app.reindex import rebuild_index_from_raw
from app.sync_notion import sync_notion
from app.tools import list_recent_pages, search_local_notion
from app.web import run_server


app = typer.Typer(no_args_is_help=True, help="Local-first Notion agent CLI.")


@app.command("init-db")
def init_db_command() -> None:
    settings = load_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(settings.db_path)
    init_db(connection)
    typer.echo(f"Database initialized at {settings.db_path}")


@app.command("ingest-sample")
def ingest_sample_command() -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)

    now = datetime.now(timezone.utc).isoformat()
    page = Page(
        id="sample-agent-routing",
        title="Agent Routing Notes",
        url="https://example.local/notion/agent-routing-notes",
        source_type="sample",
        created_time=now,
        last_edited_time=now,
        raw_json_path=None,
    )
    chunks = [
        Chunk(
            chunk_id="sample-agent-routing-1",
            page_id=page.id,
            heading="Routing Basics",
            content=(
                "Agent routing decides whether a query should go to local search, "
                "remote APIs, or fallback tools. A local-first policy reduces latency "
                "and makes the system easier to debug."
            ),
            position=0,
            token_count=26,
        ),
        Chunk(
            chunk_id="sample-agent-routing-2",
            page_id=page.id,
            heading="Evidence Policy",
            content=(
                "The agent should answer only when retrieved chunks provide enough evidence. "
                "If local search is weak, the agent should say the evidence is insufficient "
                "instead of guessing."
            ),
            position=1,
            token_count=29,
        ),
    ]
    replace_page_chunks(connection, page, chunks)
    typer.echo("Sample page indexed.")


@app.command("search")
def search_command(query: str, top_k: int = 5) -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    results = search_local_notion(connection, query=query, top_k=top_k)

    if not results:
        typer.echo("No local results.")
        return

    for index, result in enumerate(results, start=1):
        typer.echo(f"{index}. {result.title} | {result.heading}")
        typer.echo(f"   {result.content}")
        typer.echo(f"   {result.url}")


@app.command("ask")
def ask_command(question: str, top_k: int = 5, session_id: str = "default") -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    typer.echo(
        answer_question(
            connection,
            settings=settings,
            question=question,
            top_k=top_k,
            session_id=session_id,
        )
    )


@app.command("recent")
def recent_command(limit: int = 10) -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    rows = list_recent_pages(connection, limit=limit)
    if not rows:
        typer.echo("No pages indexed.")
        return

    for row in rows:
        typer.echo(f"- {row['title']} | {row['last_edited_time']} | {row['url']}")


@app.command("sync")
def sync_command() -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    typer.echo(sync_notion(settings, connection, progress=typer.echo))


@app.command("reindex")
def reindex_command(target: str | None = None) -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    typer.echo(
        rebuild_index_from_raw(settings.raw_dir, connection, progress=typer.echo, target=target)
    )


@app.command("inspect-raw")
def inspect_raw_command(target: str, limit: int = 80) -> None:
    settings = load_settings()
    raw_path = resolve_raw_target(settings.raw_dir, target)
    typer.echo(inspect_raw_snapshot(raw_path, limit=limit))


@app.command("inspect-page")
def inspect_page_command(target: str) -> None:
    settings = load_settings()
    raw_path = resolve_raw_target(settings.raw_dir, target)
    typer.echo(inspect_page_snapshot(raw_path))


@app.command("inspect-chunks")
def inspect_chunks_command(target: str) -> None:
    settings = load_settings()
    raw_path = resolve_raw_target(settings.raw_dir, target)
    typer.echo(inspect_chunks_snapshot(raw_path))


@app.command("inspect-links")
def inspect_links_command(target: str) -> None:
    settings = load_settings()
    raw_path = resolve_raw_target(settings.raw_dir, target)
    typer.echo(inspect_links_snapshot(raw_path))


@app.command("stats")
def stats_command() -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    stats = get_stats(connection)
    raw_files = len(list(settings.raw_dir.glob("*.json")))
    typer.echo(f"raw_snapshots: {raw_files}")
    for key, value in stats.items():
        typer.echo(f"{key}: {value}")


@app.command("serve")
def serve_command(host: str = "127.0.0.1", port: int = 8000) -> None:
    run_server(host=host, port=port)


if __name__ == "__main__":
    app()
