from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    raw_dir: Path
    db_dir: Path
    db_path: Path
    notion_token: str | None
    notion_root_page_id: str | None


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    raw_dir = data_dir / "raw"
    db_dir = data_dir / "db"
    default_db_path = db_dir / "oh_my_notion.sqlite3"
    db_path = Path(os.getenv("OH_MY_NOTION_DB_PATH", str(default_db_path)))

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        raw_dir=raw_dir,
        db_dir=db_dir,
        db_path=db_path,
        notion_token=os.getenv("NOTION_TOKEN"),
        notion_root_page_id=os.getenv("NOTION_ROOT_PAGE_ID"),
    )

