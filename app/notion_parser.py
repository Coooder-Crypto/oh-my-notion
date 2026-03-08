from __future__ import annotations

from typing import Any

from app.cleaner import normalize_block_text, should_skip_block
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
    heading_stack = {"heading_1": "", "heading_2": "", "heading_3": ""}
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
        heading = build_heading_path(heading_stack)
        chunks.append(
            Chunk(
                chunk_id=f"{page.id}-{chunk_index}",
                page_id=page.id,
                heading=heading,
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
            update_heading_stack(heading_stack, block_type, text)
            if text:
                buffer.append(text)
                current_length += len(text)
            continue

        if should_skip_block(block_type, text):
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
        checked = payload.get("checked", False) if block_type == "to_do" else None
        return normalize_block_text(block_type, text, checked=checked)

    return ""


def rich_text_to_plain_text(rich_text: list[dict[str, Any]]) -> str:
    rendered_parts = [render_rich_text_part(part) for part in rich_text]
    return "".join(part for part in rendered_parts if part).strip()


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def update_heading_stack(heading_stack: dict[str, str], block_type: str, text: str) -> None:
    if block_type == "heading_1":
        heading_stack["heading_1"] = text
        heading_stack["heading_2"] = ""
        heading_stack["heading_3"] = ""
    elif block_type == "heading_2":
        heading_stack["heading_2"] = text
        heading_stack["heading_3"] = ""
    elif block_type == "heading_3":
        heading_stack["heading_3"] = text


def build_heading_path(heading_stack: dict[str, str]) -> str:
    return " / ".join(part for part in heading_stack.values() if part)


def render_rich_text_part(part: dict[str, Any]) -> str:
    plain_text = part.get("plain_text", "")
    href = extract_rich_text_href(part)
    if not href:
        return plain_text

    compact_plain_text = plain_text.strip()
    if not compact_plain_text:
        return href
    if compact_plain_text == href:
        return href
    return f"{plain_text} <{href}>"


def extract_rich_text_href(part: dict[str, Any]) -> str | None:
    href = part.get("href")
    if href:
        return href

    text_payload = part.get("text", {})
    link_payload = text_payload.get("link") or {}
    url = link_payload.get("url")
    if url:
        return url

    return None
