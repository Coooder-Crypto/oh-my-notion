from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app.notion.parser import build_chunks, build_page, extract_saved_links
from app.storage.db import init_db, replace_page_chunks, reset_index


def rebuild_index_from_raw(
    raw_dir: Path,
    connection,
    progress: Callable[[str], None] | None = None,
    target: str | None = None,
) -> str:
    reporter = progress or (lambda _message: None)
    init_db(connection)

    raw_files = sorted(raw_dir.glob("*.json"))
    if target:
        raw_files = [path for path in raw_files if target in path.stem or target in path.name]
    page_snapshots = []
    for raw_file in raw_files:
        payload = load_payload(raw_file)
        if not payload or "page" not in payload or "blocks" not in payload:
            continue
        page_snapshots.append((raw_file, payload))

    if not page_snapshots:
        return f"No page snapshots found in {raw_dir}"

    reset_index(connection)

    pages_indexed = 0
    chunks_indexed = 0
    for raw_file, payload in page_snapshots:
        page_data = payload["page"]
        blocks = payload["blocks"]
        page = build_page(page_data, raw_json_path=str(raw_file), block_tree=blocks)
        chunks = build_chunks(page, blocks)
        saved_links = extract_saved_links(page, blocks, chunks)
        replace_page_chunks(connection, page, chunks, saved_links=saved_links)
        pages_indexed += 1
        chunks_indexed += len(chunks)
        reporter(
            f"[reindex] {page.title or page.id}: {len(chunks)} chunks, {len(saved_links)} links from {raw_file.name}"
        )

    return (
        f"Reindex completed. Indexed {pages_indexed} pages and {chunks_indexed} chunks "
        f"from {len(page_snapshots)} raw snapshots."
    )


def load_payload(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
