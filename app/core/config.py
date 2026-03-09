from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


DEFAULT_NOTION_VERSION = "2022-06-28"
SUPPORTED_NOTION_VERSIONS = {
    "2021-05-11",
    "2021-05-13",
    "2021-08-16",
    "2022-02-22",
    "2022-06-28",
    "2025-09-03",
    "2026-03-11",
}


@dataclass(slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    raw_dir: Path
    raw_cache_dir: Path
    knowledge_dir: Path
    db_dir: Path
    db_path: Path
    notion_token: str | None
    notion_root_page_id: str | None
    notion_version: str
    openai_api_key: str | None
    openai_model: str


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent.parent
    env_values = load_env_file(project_root / ".env")
    data_dir = project_root / "data"
    raw_dir = data_dir / "raw"
    raw_cache_dir = raw_dir / "_block_cache"
    knowledge_dir = Path(
        get_config_value("OH_MY_NOTION_KNOWLEDGE_DIR", env_values, str(project_root / "knowledge_files"))
    )
    db_dir = data_dir / "db"
    default_db_path = db_dir / "oh_my_notion.sqlite3"
    db_path = Path(
        get_config_value("OH_MY_NOTION_DB_PATH", env_values, str(default_db_path))
    )

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        raw_dir=raw_dir,
        raw_cache_dir=raw_cache_dir,
        knowledge_dir=knowledge_dir,
        db_dir=db_dir,
        db_path=db_path,
        notion_token=get_config_value("NOTION_TOKEN", env_values),
        notion_root_page_id=get_config_value("NOTION_ROOT_PAGE_ID", env_values),
        notion_version=normalize_notion_version(
            get_config_value("NOTION_VERSION", env_values, DEFAULT_NOTION_VERSION)
        ),
        openai_api_key=get_config_value("OPENAI_API_KEY", env_values),
        openai_model=get_config_value("OPENAI_MODEL", env_values, "gpt-4.1-mini") or "gpt-4.1-mini",
    )


def load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip().strip("'").strip('"')
        values[normalized_key] = normalized_value

    return values


def get_config_value(
    key: str,
    env_values: dict[str, str],
    default: str | None = None,
) -> str | None:
    return os.getenv(key) or env_values.get(key) or default


def normalize_notion_version(value: str | None) -> str:
    if value in SUPPORTED_NOTION_VERSIONS:
        return value
    return DEFAULT_NOTION_VERSION
