from __future__ import annotations

import re
from typing import Iterable


MEANINGLESS_TEXT = {
    "-",
    "--",
    "---",
    "...",
    "todo",
    "untitled",
}

SKIP_BLOCK_TYPES = {"child_page", "child_database", "divider", "breadcrumb", "table_of_contents"}


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = "\n".join(line.strip() for line in normalized.splitlines())
    normalized = "\n".join(remove_consecutive_duplicates(normalized.splitlines()))
    return normalized.strip()


def remove_consecutive_duplicates(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    previous = None
    for line in lines:
        if line == previous and line:
            continue
        cleaned.append(line)
        previous = line
    return cleaned


def should_skip_block(block_type: str, text: str) -> bool:
    if block_type in SKIP_BLOCK_TYPES:
        return True
    if not text:
        return True

    compact = " ".join(text.split()).strip().lower()
    if compact in MEANINGLESS_TEXT:
        return True
    if len(compact) <= 2 and compact not in {"ai", "ui", "db"}:
        return True
    return False


def normalize_block_text(block_type: str, text: str, checked: bool | None = None) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""

    if block_type == "to_do":
        prefix = "[DONE] " if checked else "[TODO] "
        return prefix + cleaned
    if block_type == "quote":
        return f"Quote: {cleaned}"
    if block_type == "code":
        return f"Code: {cleaned}"
    if block_type == "bulleted_list_item":
        return f"- {cleaned}"
    if block_type == "numbered_list_item":
        return f"1. {cleaned}"
    return cleaned

