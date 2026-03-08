from __future__ import annotations

from typing import Any

from app.models import Chunk, Page


SUPPORTED_RICH_TEXT_TYPES = {
    "paragraph",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "heading_1",
    "heading_2",
    "heading_3",
    "code",
}

HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}


def build_page(page_data: dict[str, Any], raw_json_path: str | None) -> Page:
    return Page(
        id=page_data["id"],
        title=extract_page_title(page_data),
        url=page_data.get("url", ""),
        source_type=page_data.get("parent", {}).get("type", "page"),
        created_time=page_data.get("created_time", ""),
        last_edited_time=page_data.get("last_edited_time", ""),
        raw_json_path=raw_json_path,
    )


def build_chunks(page: Page, block_tree: list[dict[str, Any]], chunk_size: int = 800) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_heading = ""
    buffer: list[str] = []
    current_length = 0
    chunk_index = 0

    def flush_buffer() -> None:
        nonlocal buffer, current_length, chunk_index
        content = "\n".join(part for part in buffer if part.strip()).strip()
        if not content:
            buffer = []
            current_length = 0
            return
        chunks.append(
            Chunk(
                chunk_id=f"{page.id}-{chunk_index}",
                page_id=page.id,
                heading=current_heading,
                content=content,
                position=chunk_index,
                token_count=estimate_token_count(content),
            )
        )
        chunk_index += 1
        buffer = []
        current_length = 0

    for block in flatten_blocks(block_tree):
        block_type = block.get("type", "")
        text = extract_block_text(block)
        if block_type in HEADING_TYPES:
            flush_buffer()
            current_heading = text
            if text:
                buffer.append(text)
                current_length += len(text)
            continue

        if not text:
            continue

        if current_length + len(text) > chunk_size and buffer:
            flush_buffer()

        buffer.append(text)
        current_length += len(text)

    flush_buffer()
    return chunks


def flatten_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for block in blocks:
        flattened.append(block)
        children = block.get("_children", [])
        if children:
            flattened.extend(flatten_blocks(children))
    return flattened


def extract_page_title(page_data: dict[str, Any]) -> str:
    properties = page_data.get("properties", {})
    for value in properties.values():
        if value.get("type") == "title":
            return rich_text_to_plain_text(value.get("title", [])) or "Untitled"
    return "Untitled"


def extract_block_text(block: dict[str, Any]) -> str:
    block_type = block.get("type", "")
    if block_type in SUPPORTED_RICH_TEXT_TYPES:
        payload = block.get(block_type, {})
        text = rich_text_to_plain_text(payload.get("rich_text", []))
        if block_type == "to_do":
            checked = payload.get("checked", False)
            prefix = "[x] " if checked else "[ ] "
            return prefix + text if text else ""
        return text

    if block_type == "child_page":
        title = block.get("child_page", {}).get("title", "Untitled child page")
        return f"Child page: {title}"

    if block_type == "child_database":
        title = block.get("child_database", {}).get("title", "Untitled database")
        return f"Child database: {title}"

    return ""


def rich_text_to_plain_text(rich_text: list[dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text).strip()


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))
