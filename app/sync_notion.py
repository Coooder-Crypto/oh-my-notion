from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings
from app.db import init_db, replace_page_chunks
from app.notion_parser import build_chunks, build_page


NOTION_API_BASE = "https://api.notion.com/v1"


@dataclass(slots=True)
class SyncStats:
    pages_indexed: int = 0
    chunks_indexed: int = 0
    raw_files_written: int = 0


class NotionClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self._request_json(f"/pages/{page_id}")

    def get_block_children(self, block_id: str) -> list[dict[str, Any]]:
        return self._paginate(f"/blocks/{block_id}/children")

    def query_database(self, database_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if next_cursor:
                payload["start_cursor"] = next_cursor
            response = self._request_json(
                f"/databases/{database_id}/query",
                method="POST",
                payload=payload,
            )
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None
        while True:
            query = {"page_size": 100}
            if next_cursor:
                query["start_cursor"] = next_cursor
            response = self._request_json(path, query=query)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

    def _request_json(
        self,
        path: str,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{NOTION_API_BASE}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        request = Request(url=url, method=method)
        request.add_header("Authorization", f"Bearer {self.settings.notion_token}")
        request.add_header("Notion-Version", self.settings.notion_version)
        request.add_header("Content-Type", "application/json")

        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        try:
            with urlopen(request, data=data, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Notion API request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Unable to reach Notion API: {exc.reason}") from exc


def sync_notion(settings: Settings, connection) -> str:
    if not settings.notion_token or not settings.notion_root_page_id:
        return (
            "Notion sync is not configured yet. "
            "Set NOTION_TOKEN and NOTION_ROOT_PAGE_ID before running sync."
        )

    init_db(connection)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)

    client = NotionClient(settings)
    stats = SyncStats()
    visited_pages: set[str] = set()
    visited_databases: set[str] = set()

    sync_page_tree(
        page_id=settings.notion_root_page_id,
        client=client,
        settings=settings,
        connection=connection,
        stats=stats,
        visited_pages=visited_pages,
        visited_databases=visited_databases,
    )

    return (
        f"Notion sync completed. Indexed {stats.pages_indexed} pages, "
        f"{stats.chunks_indexed} chunks, wrote {stats.raw_files_written} raw files."
    )


def sync_page_tree(
    page_id: str,
    client: NotionClient,
    settings: Settings,
    connection,
    stats: SyncStats,
    visited_pages: set[str],
    visited_databases: set[str],
) -> None:
    if page_id in visited_pages:
        return
    visited_pages.add(page_id)

    page_data = client.get_page(page_id)
    block_tree = fetch_block_tree(client, page_id)
    raw_json_path = write_raw_payload(
        raw_dir=settings.raw_dir,
        object_id=page_id,
        payload={"page": page_data, "blocks": block_tree},
    )

    page = build_page(page_data, raw_json_path=str(raw_json_path))
    chunks = build_chunks(page, block_tree)
    replace_page_chunks(connection, page, chunks)
    stats.pages_indexed += 1
    stats.chunks_indexed += len(chunks)
    stats.raw_files_written += 1

    for block in walk_blocks(block_tree):
        block_type = block.get("type")
        if block_type == "child_page":
            child_page_id = block.get("id")
            if child_page_id:
                sync_page_tree(
                    page_id=child_page_id,
                    client=client,
                    settings=settings,
                    connection=connection,
                    stats=stats,
                    visited_pages=visited_pages,
                    visited_databases=visited_databases,
                )
        elif block_type == "child_database":
            database_id = block.get("id")
            if database_id:
                sync_database(
                    database_id=database_id,
                    client=client,
                    settings=settings,
                    connection=connection,
                    stats=stats,
                    visited_pages=visited_pages,
                    visited_databases=visited_databases,
                )


def sync_database(
    database_id: str,
    client: NotionClient,
    settings: Settings,
    connection,
    stats: SyncStats,
    visited_pages: set[str],
    visited_databases: set[str],
) -> None:
    if database_id in visited_databases:
        return
    visited_databases.add(database_id)

    pages = client.query_database(database_id)
    write_raw_payload(
        raw_dir=settings.raw_dir,
        object_id=database_id,
        payload={"database_id": database_id, "pages": pages},
    )
    stats.raw_files_written += 1

    for page in pages:
        page_id = page.get("id")
        if page_id:
            sync_page_tree(
                page_id=page_id,
                client=client,
                settings=settings,
                connection=connection,
                stats=stats,
                visited_pages=visited_pages,
                visited_databases=visited_databases,
            )


def fetch_block_tree(client: NotionClient, block_id: str) -> list[dict[str, Any]]:
    children = client.get_block_children(block_id)
    for child in children:
        if child.get("has_children"):
            child["_children"] = fetch_block_tree(client, child["id"])
    return children


def walk_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for block in blocks:
        output.append(block)
        children = block.get("_children", [])
        if children:
            output.extend(walk_blocks(children))
    return output


def write_raw_payload(raw_dir: Path, object_id: str, payload: dict[str, Any]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / f"{object_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
