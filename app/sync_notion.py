from __future__ import annotations

from app.config import Settings


def sync_notion(settings: Settings) -> str:
    if not settings.notion_token or not settings.notion_root_page_id:
        return (
            "Notion sync is not configured yet. "
            "Set NOTION_TOKEN and NOTION_ROOT_PAGE_ID before implementing the real sync flow."
        )

    return (
        "Notion sync entrypoint is reserved but not implemented yet. "
        "Next step: call the Notion API, save raw JSON into data/raw, then parse and index it."
    )

