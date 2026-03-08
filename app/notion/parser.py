from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.storage.cleaner import normalize_block_text, should_skip_block
from app.storage.models import Chunk, Page, SavedLink


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
LIST_TYPES = {"bulleted_list_item", "numbered_list_item", "to_do"}


@dataclass(slots=True)
class TextUnit:
    kind: str
    heading_path: str
    text: str
    link_count: int


def build_page(
    page_data: dict[str, Any],
    raw_json_path: str | None,
    block_tree: list[dict[str, Any]] | None = None,
) -> Page:
    effective_blocks = block_tree or []
    return Page(
        id=page_data["id"],
        title=extract_page_title(page_data),
        url=page_data.get("url", ""),
        source_type=page_data.get("parent", {}).get("type", "page"),
        created_time=page_data.get("created_time", ""),
        last_edited_time=page_data.get("last_edited_time", ""),
        page_kind=classify_page_kind(effective_blocks),
        child_count=count_child_blocks(effective_blocks),
        link_count=len(extract_links_from_block_tree(effective_blocks)),
        raw_json_path=raw_json_path,
    )


def build_chunks(
    page: Page,
    block_tree: list[dict[str, Any]],
    chunk_size: int = 800,
    overlap_units: int = 1,
) -> list[Chunk]:
    units = build_text_units(block_tree)
    if not units:
        return []

    chunks: list[Chunk] = []
    buffer_units: list[TextUnit] = []
    current_length = 0
    chunk_index = 0
    current_heading = units[0].heading_path

    def flush_buffer(preserve_overlap: bool) -> None:
        nonlocal buffer_units, current_length, chunk_index
        content = "\n".join(unit.text for unit in buffer_units if unit.text.strip()).strip()
        if not content:
            buffer_units = []
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
        if preserve_overlap and overlap_units > 0:
            overlap = buffer_units[-overlap_units:]
            buffer_units = overlap[:]
            current_length = sum(len(unit.text) for unit in buffer_units)
        else:
            buffer_units = []
            current_length = 0

    for unit in units:
        if unit.heading_path != current_heading and buffer_units:
            flush_buffer(preserve_overlap=False)
            current_heading = unit.heading_path

        if unit.heading_path != current_heading:
            current_heading = unit.heading_path

        if current_length + len(unit.text) > chunk_size and buffer_units:
            flush_buffer(preserve_overlap=True)
            current_heading = unit.heading_path

        buffer_units.append(unit)
        current_length += len(unit.text)

    flush_buffer(preserve_overlap=False)
    return deduplicate_chunks(chunks)


def build_text_units(block_tree: list[dict[str, Any]]) -> list[TextUnit]:
    heading_stack = {"heading_1": "", "heading_2": "", "heading_3": ""}
    raw_units: list[TextUnit] = []

    for block in flatten_blocks(block_tree):
        block_type = block.get("type", "")
        text = extract_block_text(block)
        if block_type in HEADING_TYPES:
            update_heading_stack(heading_stack, block_type, text)
            continue

        if should_skip_block(block_type, text):
            continue

        heading_path = build_heading_path(heading_stack)
        raw_units.append(
            TextUnit(
                kind=block_type,
                heading_path=heading_path,
                text=text,
                link_count=count_links_in_block(block),
            )
        )

    grouped_units = merge_list_units(raw_units)
    return merge_short_units(grouped_units)


def flatten_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for block in blocks:
        flattened.append(block)
        children = block.get("_children", [])
        if children:
            flattened.extend(flatten_blocks(children))
    return flattened


def flatten_blocks_with_depth(
    blocks: list[dict[str, Any]],
    depth: int = 0,
) -> list[tuple[int, dict[str, Any]]]:
    flattened: list[tuple[int, dict[str, Any]]] = []
    for block in blocks:
        flattened.append((depth, block))
        children = block.get("_children", [])
        if children:
            flattened.extend(flatten_blocks_with_depth(children, depth=depth + 1))
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


def extract_links_from_block_tree(block_tree: list[dict[str, Any]]) -> list[str]:
    links: list[str] = []
    for block in flatten_blocks(block_tree):
        links.extend(extract_links_from_rich_text_for_block(block))
    return links


def extract_saved_links(
    page: Page,
    block_tree: list[dict[str, Any]],
    chunks: list[Chunk] | None = None,
) -> list[SavedLink]:
    chunk_by_heading = build_chunk_lookup(chunks or [])
    heading_stack = {"heading_1": "", "heading_2": "", "heading_3": ""}
    saved_links: list[SavedLink] = []
    seen: set[tuple[str, str, str]] = set()

    for block in flatten_blocks(block_tree):
        block_type = block.get("type", "")
        text = extract_block_text(block)
        if block_type in HEADING_TYPES:
            update_heading_stack(heading_stack, block_type, text)
            continue

        heading_path = build_heading_path(heading_stack)
        rich_text = []
        if block_type in SUPPORTED_RICH_TEXT_TYPES:
            payload = block.get(block_type, {})
            rich_text = payload.get("rich_text", [])
        if not rich_text:
            continue

        chunk_id = chunk_by_heading.get(heading_path)
        context_snippet = text[:280]
        for part in rich_text:
            href = extract_rich_text_href(part)
            if not href:
                continue
            anchor_text = part.get("plain_text", "").strip()
            link_key = (heading_path, anchor_text, href)
            if link_key in seen:
                continue
            seen.add(link_key)
            saved_links.append(
                SavedLink(
                    page_id=page.id,
                    chunk_id=chunk_id,
                    page_title=page.title,
                    heading=heading_path,
                    url=href,
                    anchor_text=anchor_text,
                    domain=extract_domain(href),
                    context_snippet=context_snippet,
                )
            )
    return saved_links


def extract_links_from_rich_text_for_block(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type", "")
    if block_type not in SUPPORTED_RICH_TEXT_TYPES:
        return []
    payload = block.get(block_type, {})
    links: list[str] = []
    for part in payload.get("rich_text", []):
        href = extract_rich_text_href(part)
        if href:
            links.append(href)
    return links


def count_links_in_block(block: dict[str, Any]) -> int:
    return len(extract_links_from_rich_text_for_block(block))


def build_chunk_lookup(chunks: list[Chunk]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for chunk in chunks:
        lookup.setdefault(chunk.heading, chunk.chunk_id)
    return lookup


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def count_child_blocks(block_tree: list[dict[str, Any]]) -> int:
    return sum(
        1
        for block in flatten_blocks(block_tree)
        if block.get("type") in {"child_page", "child_database"}
    )


def classify_page_kind(block_tree: list[dict[str, Any]]) -> str:
    if not block_tree:
        return "empty"

    has_content = False
    has_child = False
    for block in flatten_blocks(block_tree):
        block_type = block.get("type", "")
        if block_type in {"child_page", "child_database"}:
            has_child = True
            continue
        text = extract_block_text(block)
        if should_skip_block(block_type, text):
            continue
        has_content = True

    if has_content:
        return "content"
    if has_child:
        return "container"
    return "empty"


def merge_list_units(units: list[TextUnit]) -> list[TextUnit]:
    if not units:
        return []
    merged: list[TextUnit] = []
    for unit in units:
        if (
            merged
            and unit.kind in LIST_TYPES
            and merged[-1].kind == unit.kind
            and merged[-1].heading_path == unit.heading_path
        ):
            merged[-1] = TextUnit(
                kind="list_group",
                heading_path=merged[-1].heading_path,
                text=f"{merged[-1].text}\n{unit.text}",
                link_count=merged[-1].link_count + unit.link_count,
            )
            continue
        merged.append(unit)
    return merged


def merge_short_units(units: list[TextUnit], max_merged_length: int = 260) -> list[TextUnit]:
    if not units:
        return []
    merged: list[TextUnit] = []
    for unit in units:
        if (
            merged
            and merged[-1].heading_path == unit.heading_path
            and merged[-1].kind not in HEADING_TYPES
            and unit.kind not in HEADING_TYPES
            and len(merged[-1].text) < 120
            and len(unit.text) < 120
            and len(merged[-1].text) + len(unit.text) < max_merged_length
            and not (merged[-1].kind == "code" and unit.kind == "code")
        ):
            merged[-1] = TextUnit(
                kind=merged[-1].kind,
                heading_path=merged[-1].heading_path,
                text=f"{merged[-1].text}\n{unit.text}",
                link_count=merged[-1].link_count + unit.link_count,
            )
            continue
        merged.append(unit)
    return merged


def deduplicate_chunks(chunks: list[Chunk]) -> list[Chunk]:
    deduped: list[Chunk] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        key = (chunk.heading, chunk.content)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped
