from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from app.agent import answer_question
from app.core.config import load_settings
from app.evaluation.agent import evaluate_agent_routing
from app.evaluation.retrieval import evaluate_retrieval
from app.ingestion.files import ingest_local_files
from app.inspection.inspectors import (
    inspect_chunks_snapshot,
    inspect_links_snapshot,
    inspect_page_snapshot,
    inspect_raw_snapshot,
    resolve_raw_target,
)
from app.notion.sync import sync_notion
from app.retrieval.tools import list_recent_pages, search_local_notion
from app.storage.db import connect, get_stats, init_db, replace_page_chunks
from app.storage.models import Chunk, Page
from app.storage.reindex import rebuild_index_from_raw
from app.webapp.server import run_server


app = typer.Typer(no_args_is_help=True, help="Local-first Notion agent CLI.")


def default_eval_dataset_path() -> str:
    settings = load_settings()
    project_root = settings.project_root
    if project_root.name == "app":
        project_root = project_root.parent
    return str(project_root / "eval" / "questions.jsonl")


@app.command("init-db")
def init_db_command() -> None:
    settings = load_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
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
    replace_page_chunks(connection, page, chunks, saved_links=[])
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
        typer.echo(
            "   "
            f"method={result.retrieval_method} "
            f"rerank={result.rerank_score:.3f} "
            f"fts={result.fts_score:.3f} "
            f"vector={result.vector_score:.3f}"
        )
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
        rebuild_index_from_raw(
            settings.raw_dir,
            settings.knowledge_dir,
            connection,
            progress=typer.echo,
            target=target,
        )
    )


@app.command("ingest-files")
def ingest_files_command(target: str | None = None) -> None:
    settings = load_settings()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(settings.db_path)
    init_db(connection)
    typer.echo(
        ingest_local_files(
            settings.knowledge_dir,
            connection,
            progress=typer.echo,
            target=target,
            cleanup_stale=True,
        )
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
    local_files = len(
        [
            path
            for path in settings.knowledge_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}
        ]
    )
    typer.echo(f"raw_snapshots: {raw_files}")
    typer.echo(f"local_files: {local_files}")
    for key, value in stats.items():
        typer.echo(f"{key}: {value}")


@app.command("eval-retrieval")
def eval_retrieval_command(
    dataset: str = typer.Option(default_eval_dataset_path(), help="Path to eval questions jsonl."),
    top_k: int = 5,
) -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    report, _rows = evaluate_retrieval(connection, dataset_path=Path(dataset), top_k=top_k)
    typer.echo(report)


@app.command("eval-agent")
def eval_agent_command(
    dataset: str = typer.Option(default_eval_dataset_path(), help="Path to eval questions jsonl."),
) -> None:
    report, _rows = evaluate_agent_routing(dataset_path=Path(dataset))
    typer.echo(report)


@app.command("eval-all")
def eval_all_command(
    dataset: str = typer.Option(default_eval_dataset_path(), help="Path to eval questions jsonl."),
    top_k: int = 5,
) -> None:
    settings = load_settings()
    connection = connect(settings.db_path)
    init_db(connection)
    dataset_path = Path(dataset)
    retrieval_report, _ = evaluate_retrieval(connection, dataset_path=dataset_path, top_k=top_k)
    agent_report, _ = evaluate_agent_routing(dataset_path=dataset_path)
    typer.echo(retrieval_report)
    typer.echo("")
    typer.echo(agent_report)


@app.command("serve")
def serve_command(host: str = "127.0.0.1", port: int = 8000) -> None:
    run_server(host=host, port=port)


if __name__ == "__main__":
    app()
