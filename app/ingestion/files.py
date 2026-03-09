from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlparse

from app.storage.db import delete_page, init_db, list_file_source_pages, replace_page_chunks
from app.storage.models import Chunk, Page, SavedLink


SUPPORTED_FILE_SUFFIXES = {".md", ".txt"}
URL_PATTERN = re.compile(r"https?://[^\s)>\"']+")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(slots=True)
class FileChunkUnit:
    heading: str
    text: str


def ingest_local_files(
    files_dir: Path,
    connection,
    progress: Callable[[str], None] | None = None,
    target: str | None = None,
    cleanup_stale: bool = True,
) -> str:
    reporter = progress or (lambda _message: None)
    init_db(connection)

    if not files_dir.exists():
        files_dir.mkdir(parents=True, exist_ok=True)
        return f"No local files found in {files_dir}"

    file_paths = list_supported_files(files_dir, target=target)
    if not file_paths:
        return f"No supported local files found in {files_dir}"

    seen_page_ids: set[str] = set()
    pages_indexed = 0
    chunks_indexed = 0
    links_indexed = 0

    for file_path in file_paths:
        page, chunks, saved_links = build_file_document(file_path, files_dir)
        replace_page_chunks(connection, page, chunks, saved_links=saved_links)
        seen_page_ids.add(page.id)
        pages_indexed += 1
        chunks_indexed += len(chunks)
        links_indexed += len(saved_links)
        reporter(
            f"[files] {page.title}: {len(chunks)} chunks, {len(saved_links)} links from {file_path.relative_to(files_dir)}"
        )

    removed = 0
    if cleanup_stale:
        for row in list_file_source_pages(connection, str(files_dir.resolve())):
            if row["id"] in seen_page_ids:
                continue
            delete_page(connection, row["id"])
            removed += 1
            reporter(f"[files] removed stale index for {row['raw_json_path']}")

    return (
        f"Local file ingest completed. Indexed {pages_indexed} files, {chunks_indexed} chunks, "
        f"and {links_indexed} links from {files_dir}."
        + (f" Removed {removed} stale file entries." if removed else "")
    )


def list_supported_files(files_dir: Path, target: str | None = None) -> list[Path]:
    file_paths = [
        path
        for path in files_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_FILE_SUFFIXES
    ]
    file_paths.sort()
    if target:
        lowered = target.lower()
        file_paths = [path for path in file_paths if lowered in path.name.lower() or lowered in str(path).lower()]
    return file_paths


def build_file_document(file_path: Path, files_dir: Path) -> tuple[Page, list[Chunk], list[SavedLink]]:
    raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
    units = build_file_units(raw_text, default_heading=file_path.stem)
    page_id = build_file_page_id(file_path, files_dir)
    chunks = build_file_chunks(page_id=page_id, units=units)
    saved_links = extract_saved_links_from_chunks(
        page_id=page_id,
        page_title=extract_file_title(file_path, units),
        chunks=chunks,
    )
    timestamp = iso_timestamp_from_stat(file_path)
    source_type = "file_markdown" if file_path.suffix.lower() == ".md" else "file_text"
    page_kind = "empty" if not chunks else "content"
    page = Page(
        id=page_id,
        title=extract_file_title(file_path, units),
        url=str(file_path.resolve()),
        source_type=source_type,
        created_time=timestamp,
        last_edited_time=timestamp,
        page_kind=page_kind,
        child_count=0,
        link_count=len(saved_links),
        raw_json_path=str(file_path.resolve()),
    )
    return page, chunks, saved_links


def build_file_page_id(file_path: Path, files_dir: Path) -> str:
    relative_path = file_path.resolve().relative_to(files_dir.resolve())
    digest = sha1(str(relative_path).encode("utf-8")).hexdigest()[:16]
    return f"file-{digest}"


def extract_file_title(file_path: Path, units: list[FileChunkUnit]) -> str:
    for unit in units:
        if unit.heading and unit.heading != file_path.stem:
            return unit.heading
    return file_path.stem


def build_file_units(raw_text: str, default_heading: str) -> list[FileChunkUnit]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    units: list[FileChunkUnit] = []
    current_heading = default_heading
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        text = "\n".join(line.strip() for line in buffer if line.strip()).strip()
        if text:
            units.append(FileChunkUnit(heading=current_heading, text=text))
        buffer = []

    for line in lines:
        heading_match = HEADING_PATTERN.match(line.strip())
        if heading_match:
            flush_buffer()
            current_heading = heading_match.group(2).strip() or default_heading
            continue

        if not line.strip():
            flush_buffer()
            continue

        buffer.append(line)

    flush_buffer()
    return units


def build_file_chunks(
    page_id: str,
    units: list[FileChunkUnit],
    chunk_size: int = 1200,
    overlap_units: int = 1,
) -> list[Chunk]:
    if not units:
        return []

    chunks: list[Chunk] = []
    buffer: list[FileChunkUnit] = []
    current_heading = units[0].heading
    current_length = 0
    chunk_index = 0

    def flush_buffer(preserve_overlap: bool) -> None:
        nonlocal buffer, current_length, chunk_index
        content = "\n\n".join(unit.text for unit in buffer if unit.text.strip()).strip()
        if not content:
            buffer = []
            current_length = 0
            return
        chunks.append(
            Chunk(
                chunk_id=f"{page_id}-{chunk_index}",
                page_id=page_id,
                heading=current_heading,
                content=content,
                position=chunk_index,
                token_count=max(1, len(content.split())),
            )
        )
        chunk_index += 1
        if preserve_overlap and overlap_units > 0:
            overlap = buffer[-overlap_units:]
            buffer = overlap[:]
            current_length = sum(len(unit.text) for unit in buffer)
        else:
            buffer = []
            current_length = 0

    for unit in units:
        if unit.heading != current_heading and buffer:
            flush_buffer(preserve_overlap=False)
            current_heading = unit.heading
        if unit.heading != current_heading:
            current_heading = unit.heading
        if current_length + len(unit.text) > chunk_size and buffer:
            flush_buffer(preserve_overlap=True)
            current_heading = unit.heading
        buffer.append(unit)
        current_length += len(unit.text)

    flush_buffer(preserve_overlap=False)
    return chunks


def extract_saved_links_from_chunks(
    page_id: str,
    page_title: str,
    chunks: list[Chunk],
) -> list[SavedLink]:
    saved_links: list[SavedLink] = []
    seen: set[tuple[str, str, str]] = set()

    for chunk in chunks:
        markdown_links = MARKDOWN_LINK_PATTERN.findall(chunk.content)
        markdown_urls = {url for _anchor_text, url in markdown_links}
        for anchor_text, url in markdown_links:
            key = (chunk.chunk_id, anchor_text, url)
            if key in seen:
                continue
            seen.add(key)
            saved_links.append(
                SavedLink(
                    page_id=page_id,
                    chunk_id=chunk.chunk_id,
                    page_title=page_title,
                    heading=chunk.heading,
                    url=url,
                    anchor_text=anchor_text.strip(),
                    domain=(urlparse(url).netloc or "unknown").lower(),
                    context_snippet=chunk.content[:240],
                )
            )

        for url in URL_PATTERN.findall(chunk.content):
            if url in markdown_urls:
                continue
            anchor_text = infer_anchor_text(chunk.content, url)
            key = (chunk.chunk_id, anchor_text, url)
            if key in seen:
                continue
            seen.add(key)
            saved_links.append(
                SavedLink(
                    page_id=page_id,
                    chunk_id=chunk.chunk_id,
                    page_title=page_title,
                    heading=chunk.heading,
                    url=url,
                    anchor_text=anchor_text,
                    domain=(urlparse(url).netloc or "unknown").lower(),
                    context_snippet=chunk.content[:240],
                )
            )

    return saved_links


def infer_anchor_text(content: str, url: str) -> str:
    if url in content:
        index = content.find(url)
        window_start = max(0, index - 60)
        prefix = content[window_start:index].strip()
        if prefix:
            return prefix.splitlines()[-1][-80:].strip(" -:")
    return url


def iso_timestamp_from_stat(file_path: Path) -> str:
    modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
    return modified_at.isoformat()
