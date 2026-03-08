# Oh My Notion

`Oh My Notion` is a Python MVP for a local-first Notion agent. It prioritizes local search over synced Notion content, then uses the retrieved evidence to answer questions.

## Current Scope

- Local SQLite storage
- SQLite FTS5 full-text search
- Local-first agent flow
- CLI entrypoint for `init-db`, `ingest-sample`, `search`, and `ask`
- Stubbed Notion sync module for the next step

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
oh-my-notion init-db
oh-my-notion ingest-sample
oh-my-notion search "agent"
oh-my-notion ask "我之前写过哪些和 agent routing 有关的内容？"
```

## Environment Variables

- `OH_MY_NOTION_DB_PATH`: optional path to SQLite database
- `NOTION_TOKEN`: reserved for the upcoming sync implementation
- `NOTION_ROOT_PAGE_ID`: reserved for the upcoming sync implementation

## Suggested Next Steps

1. Implement real Notion sync in [app/sync_notion.py](/Users/coooder/Code/Agent/oh-my-notion/app/sync_notion.py)
2. Extend parsing and chunking rules
3. Add an LLM answer layer on top of the current evidence-first flow

