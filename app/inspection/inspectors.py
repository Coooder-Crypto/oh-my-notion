from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.notion.parser import (
    build_chunks,
    build_page,
    classify_page_kind,
    extract_block_text,
    extract_links_from_block_tree,
    flatten_blocks_with_depth,
)
from app.storage.cleaner import clean_text


def resolve_raw_target(raw_dir: Path, target: str) -> Path:
    explicit_path = Path(target)
    if explicit_path.exists():
        return explicit_path

    direct_match = raw_dir / f"{target}.json"
    if direct_match.exists():
        return direct_match

    candidates = sorted(raw_dir.glob(f"*{target}*.json"))
    if not candidates:
        raise FileNotFoundError(f"No raw snapshot matches {target}")
    return candidates[0]


def load_raw_snapshot(raw_path: Path) -> dict[str, Any]:
    return json.loads(raw_path.read_text(encoding="utf-8"))


def inspect_raw_snapshot(raw_path: Path, limit: int = 80) -> str:
    payload = load_raw_snapshot(raw_path)
    page = payload.get("page", {})
    blocks = payload.get("blocks", [])
    lines = [
        f"file: {raw_path}",
        f"page_id: {page.get('id', '')}",
        f"title: {build_page(page, str(raw_path), blocks).title}",
        f"blocks: {len(blocks)}",
        "",
    ]
    for index, (depth, block) in enumerate(flatten_blocks_with_depth(blocks), start=1):
        if index > limit:
            lines.append(f"... truncated after {limit} blocks")
            break
        block_type = block.get("type", "unknown")
        text = clean_text(extract_block_text(block))
        indent = "  " * depth
        suffix = f" | {text[:120]}" if text else ""
        lines.append(f"{indent}- depth={depth} type={block_type} id={block.get('id', '')}{suffix}")
    return "\n".join(lines)


def inspect_page_snapshot(raw_path: Path) -> str:
    payload = load_raw_snapshot(raw_path)
    page_data = payload["page"]
    blocks = payload["blocks"]
    page = build_page(page_data, str(raw_path), blocks)
    return "\n".join(
        [
            f"file: {raw_path}",
            f"title: {page.title}",
            f"page_id: {page.id}",
            f"page_kind: {page.page_kind}",
            f"child_count: {page.child_count}",
            f"link_count: {page.link_count}",
            f"last_edited_time: {page.last_edited_time}",
            f"classifier: {classify_page_kind(blocks)}",
        ]
    )


def inspect_chunks_snapshot(raw_path: Path) -> str:
    payload = load_raw_snapshot(raw_path)
    page_data = payload["page"]
    blocks = payload["blocks"]
    page = build_page(page_data, str(raw_path), blocks)
    chunks = build_chunks(page, blocks)
    if not chunks:
        return f"{page.title}: no chunks generated"
    lines = [f"title: {page.title}", f"chunks: {len(chunks)}", ""]
    for chunk in chunks:
        lines.extend(
            [
                f"[{chunk.position}] heading={chunk.heading or 'ROOT'}",
                f"tokens={chunk.token_count}",
                chunk.content,
                "",
            ]
        )
    return "\n".join(lines).strip()


def inspect_links_snapshot(raw_path: Path) -> str:
    payload = load_raw_snapshot(raw_path)
    page_data = payload["page"]
    blocks = payload["blocks"]
    page = build_page(page_data, str(raw_path), blocks)
    links = extract_links_from_block_tree(blocks)
    if not links:
        return f"{page.title}: no links found"
    unique_links = list(dict.fromkeys(links))
    lines = [f"title: {page.title}", f"links: {len(unique_links)}", ""]
    lines.extend(unique_links)
    return "\n".join(lines)
