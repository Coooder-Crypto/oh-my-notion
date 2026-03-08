from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
from pathlib import Path
import socket
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import Settings
from app.notion.parser import build_chunks, build_page
from app.storage.db import get_page_sync_state, init_db, replace_page_chunks


NOTION_API_BASE = "https://api.notion.com/v1"
REQUEST_TIMEOUT_SECONDS = 30
MAX_REQUEST_RETRIES = 3
RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class SyncStats:
    pages_seen: int = 0
    pages_indexed: int = 0
    pages_skipped: int = 0
    databases_seen: int = 0
    chunks_indexed: int = 0
    raw_files_written: int = 0
    page_failures: int = 0
    block_failures: int = 0
    database_failures: int = 0
    block_cache_hits: int = 0
    block_cache_writes: int = 0


class NotionClient:
    def __init__(self, settings: Settings, progress: Callable[[str], None] | None = None):
        self.settings = settings
        self.progress = progress or (lambda _message: None)

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
        page_number = 1
        while True:
            query = {"page_size": 100}
            if next_cursor:
                query["start_cursor"] = next_cursor
            self.progress(
                f"[api] GET {path} page={page_number}"
                + (" cursor=present" if next_cursor else "")
            )
            response = self._request_json(path, query=query)
            page_results = response.get("results", [])
            results.extend(page_results)
            self.progress(
                f"[api] GET {path} page={page_number} -> {len(page_results)} results"
            )
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")
            page_number += 1

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

        for attempt in range(1, MAX_REQUEST_RETRIES + 1):
            self.progress(f"[http] {method} {path} attempt={attempt}")
            try:
                with urlopen(request, data=data, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in RETRYABLE_HTTP_STATUS_CODES and attempt < MAX_REQUEST_RETRIES:
                    self._sleep_before_retry(path, attempt, f"HTTP {exc.code}")
                    continue
                raise RuntimeError(
                    f"Notion API request failed for {path} with HTTP {exc.code}: {detail}"
                ) from exc
            except socket.timeout as exc:
                if attempt < MAX_REQUEST_RETRIES:
                    self._sleep_before_retry(path, attempt, "socket timeout")
                    continue
                raise RuntimeError(f"Notion API request timed out for {path}") from exc
            except URLError as exc:
                if attempt < MAX_REQUEST_RETRIES and is_retryable_url_error(exc):
                    self._sleep_before_retry(path, attempt, f"URLError: {exc.reason}")
                    continue
                raise RuntimeError(f"Unable to reach Notion API for {path}: {exc.reason}") from exc
            except (
                http.client.RemoteDisconnected,
                ConnectionResetError,
                ConnectionAbortedError,
                TimeoutError,
            ) as exc:
                if attempt < MAX_REQUEST_RETRIES:
                    self._sleep_before_retry(path, attempt, type(exc).__name__)
                    continue
                raise RuntimeError(
                    f"Connection dropped while requesting {path}: {exc}"
                ) from exc

        raise RuntimeError(f"Notion API request failed after retries for {path}")

    def _sleep_before_retry(self, path: str, attempt: int, reason: str) -> None:
        delay_seconds = min(2 ** (attempt - 1), 8)
        self.progress(
            f"[retry] {path} after {reason}; retrying in {delay_seconds}s"
        )
        time.sleep(delay_seconds)


def sync_notion(
    settings: Settings,
    connection,
    progress: Callable[[str], None] | None = None,
) -> str:
    if not settings.notion_token or not settings.notion_root_page_id:
        return (
            "Notion sync is not configured yet. "
            "Set NOTION_TOKEN and NOTION_ROOT_PAGE_ID before running sync."
        )

    init_db(connection)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)

    reporter = progress or (lambda _message: None)
    client = NotionClient(settings, progress=reporter)
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
        progress=reporter,
    )

    return (
        f"Notion sync completed. Seen {stats.pages_seen} pages and {stats.databases_seen} databases, "
        f"indexed {stats.pages_indexed} pages, skipped {stats.pages_skipped} unchanged pages, "
        f"indexed {stats.chunks_indexed} chunks, wrote {stats.raw_files_written} raw files, "
        f"page failures={stats.page_failures}, database failures={stats.database_failures}, "
        f"block failures={stats.block_failures}, block cache hits={stats.block_cache_hits}, "
        f"block cache writes={stats.block_cache_writes}."
    )


def sync_page_tree(
    page_id: str,
    client: NotionClient,
    settings: Settings,
    connection,
    stats: SyncStats,
    visited_pages: set[str],
    visited_databases: set[str],
    progress: Callable[[str], None],
) -> None:
    if page_id in visited_pages:
        return
    visited_pages.add(page_id)
    stats.pages_seen += 1

    progress(f"[page] fetching metadata {page_id}")
    try:
        page_data = client.get_page(page_id)
    except RuntimeError as exc:
        stats.page_failures += 1
        progress(f"[page] failed metadata {page_id}: {exc}")
        if page_id == settings.notion_root_page_id:
            raise
        return
    page = build_page(page_data, raw_json_path=None, block_tree=[])
    sync_state = get_page_sync_state(connection, page_id)
    cached_payload = load_cached_payload(sync_state)
    is_unchanged = (
        sync_state is not None
        and sync_state["last_edited_time"] == page.last_edited_time
        and cached_payload is not None
    )

    if is_unchanged:
        block_tree = cached_payload.get("blocks", [])
        page.raw_json_path = sync_state["raw_json_path"]
        page.page_kind = sync_state["page_kind"]
        page.child_count = sync_state["child_count"]
        page.link_count = sync_state["link_count"]
        stats.pages_skipped += 1
        progress(
            f"[page] skip unchanged {page.title or page_id} "
            f"({page.last_edited_time})"
        )
    else:
        progress(f"[page] indexing {page.title or page_id}")
        try:
            cache_namespace = build_cache_namespace(page.id, page.last_edited_time)
            block_tree = fetch_block_tree(
                client,
                page_id,
                progress=progress,
                stats=stats,
                cache_dir=settings.raw_cache_dir / cache_namespace,
            )
        except RuntimeError as exc:
            stats.page_failures += 1
            progress(f"[page] failed blocks {page.title or page_id}: {exc}")
            if page_id == settings.notion_root_page_id:
                raise
            return
        raw_json_path = write_raw_payload(
            raw_dir=settings.raw_dir,
            object_id=page_id,
            payload={"page": page_data, "blocks": block_tree},
        )
        page = build_page(page_data, raw_json_path=str(raw_json_path), block_tree=block_tree)
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
                try:
                    sync_page_tree(
                        page_id=child_page_id,
                        client=client,
                        settings=settings,
                        connection=connection,
                        stats=stats,
                        visited_pages=visited_pages,
                        visited_databases=visited_databases,
                        progress=progress,
                    )
                except RuntimeError as exc:
                    stats.page_failures += 1
                    progress(f"[page] skipped child page {child_page_id}: {exc}")
        elif block_type == "child_database":
            database_id = block.get("id")
            if database_id:
                try:
                    sync_database(
                        database_id=database_id,
                        client=client,
                        settings=settings,
                        connection=connection,
                        stats=stats,
                        visited_pages=visited_pages,
                        visited_databases=visited_databases,
                        progress=progress,
                    )
                except RuntimeError as exc:
                    stats.database_failures += 1
                    progress(f"[database] skipped child database {database_id}: {exc}")


def sync_database(
    database_id: str,
    client: NotionClient,
    settings: Settings,
    connection,
    stats: SyncStats,
    visited_pages: set[str],
    visited_databases: set[str],
    progress: Callable[[str], None],
) -> None:
    if database_id in visited_databases:
        return
    visited_databases.add(database_id)
    stats.databases_seen += 1

    progress(f"[database] fetching entries {database_id}")
    try:
        pages = client.query_database(database_id)
    except RuntimeError as exc:
        stats.database_failures += 1
        progress(f"[database] failed entries {database_id}: {exc}")
        return
    write_raw_payload(
        raw_dir=settings.raw_dir,
        object_id=database_id,
        payload={"database_id": database_id, "pages": pages},
    )
    stats.raw_files_written += 1

    for page in pages:
        page_id = page.get("id")
        if page_id:
            try:
                sync_page_tree(
                    page_id=page_id,
                    client=client,
                    settings=settings,
                    connection=connection,
                    stats=stats,
                    visited_pages=visited_pages,
                    visited_databases=visited_databases,
                    progress=progress,
                )
            except RuntimeError as exc:
                stats.page_failures += 1
                progress(f"[page] skipped database entry {page_id}: {exc}")


def fetch_block_tree(
    client: NotionClient,
    block_id: str,
    progress: Callable[[str], None],
    stats: SyncStats,
    cache_dir: Path,
    depth: int = 0,
) -> list[dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_children = load_cached_block_children(cache_dir, block_id)
    if cached_children is not None:
        stats.block_cache_hits += 1
        progress(f"[blocks] depth={depth} cache hit for {block_id}")
        children = cached_children
    else:
        progress(f"[blocks] depth={depth} loading children for {block_id}")
        children = client.get_block_children(block_id)
        write_cached_block_children(cache_dir, block_id, children)
        stats.block_cache_writes += 1
        progress(f"[blocks] depth={depth} cached {len(children)} children for {block_id}")
    progress(f"[blocks] depth={depth} loaded {len(children)} children for {block_id}")
    for child in children:
        if child.get("has_children"):
            block_type = child.get("type", "unknown")
            progress(
                f"[blocks] depth={depth} recurse into {child['id']} type={block_type}"
            )
            try:
                child["_children"] = fetch_block_tree(
                    client,
                    child["id"],
                    progress=progress,
                    stats=stats,
                    cache_dir=cache_dir,
                    depth=depth + 1,
                )
            except RuntimeError as exc:
                stats.block_failures += 1
                progress(
                    f"[blocks] depth={depth} skip child {child['id']} type={block_type}: {exc}"
                )
                child["_children"] = []
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


def load_cached_payload(sync_state: Any) -> dict[str, Any] | None:
    if sync_state is None:
        return None

    raw_json_path = sync_state["raw_json_path"]
    if not raw_json_path:
        return None

    path = Path(raw_json_path)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def build_cache_namespace(page_id: str, last_edited_time: str) -> str:
    safe_revision = (
        last_edited_time.replace(":", "-")
        .replace("+", "_")
        .replace("/", "_")
    )
    return f"{page_id}_{safe_revision}"


def block_cache_path(cache_dir: Path, block_id: str) -> Path:
    return cache_dir / f"{block_id}.json"


def load_cached_block_children(cache_dir: Path, block_id: str) -> list[dict[str, Any]] | None:
    path = block_cache_path(cache_dir, block_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        return payload
    return None


def write_cached_block_children(cache_dir: Path, block_id: str, children: list[dict[str, Any]]) -> None:
    path = block_cache_path(cache_dir, block_id)
    path.write_text(json.dumps(children, ensure_ascii=False, indent=2), encoding="utf-8")


def is_retryable_url_error(exc: URLError) -> bool:
    reason = str(exc.reason).lower()
    retry_keywords = (
        "timed out",
        "temporary failure",
        "connection reset",
        "connection aborted",
        "connection refused",
        "network is unreachable",
        "service not known",
        "try again",
        "ssl",
    )
    return any(keyword in reason for keyword in retry_keywords)
