# Oh My Notion

`Oh My Notion` is a Python MVP for a local-first Notion agent. It prioritizes local search over synced Notion content, then uses the retrieved evidence to answer questions.

It is designed as a learning project for agent development:
- local-first retrieval before any remote model call
- grounded answers based on retrieved Notion evidence
- optional OpenAI summarization layer on top of local search

## Current Scope

- Local SQLite storage
- SQLite FTS5 full-text search
- Local-first agent flow
- CLI entrypoint for `init-db`, `ingest-sample`, `search`, `ask`, `sync`, `reindex`, and `serve`
- Real Notion sync for pages, child pages, and database entries
- Lightweight web frontend served by Python
- Optional OpenAI API integration for grounded answer generation

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

## Web Frontend

```bash
oh-my-notion serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Sync From Notion

Create a local config file first:

```bash
cp .env.example .env
```

Then edit `.env` and run:

```bash
oh-my-notion sync
oh-my-notion reindex
oh-my-notion recent
oh-my-notion ask "我关于 agent routing 的笔记写了什么？"
```

## Configuration

The app loads configuration from `.env` in the project root. Shell environment variables still work and override values from `.env`.

Example `.env`:

```bash
NOTION_TOKEN=secret_xxx
NOTION_ROOT_PAGE_ID=your-root-page-id
NOTION_VERSION=2022-06-28
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4.1-mini
```

Supported keys:

- `OH_MY_NOTION_DB_PATH`: optional path to SQLite database
- `NOTION_TOKEN`: your Notion integration token
- `NOTION_ROOT_PAGE_ID`: root page ID to start recursive sync
- `NOTION_VERSION`: optional Notion API version, defaults to `2022-06-28`
- `OPENAI_API_KEY`: enables grounded answer generation with OpenAI
- `OPENAI_MODEL`: OpenAI model name, defaults to `gpt-4.1-mini`

If `NOTION_VERSION` is missing or invalid, the app falls back to `2022-06-28`.

## OpenAI Integration

When `OPENAI_API_KEY` is configured, `ask` and the web UI will:
- search the local Notion index first
- send only the retrieved evidence to OpenAI
- generate a concise Chinese answer grounded in those snippets

If the API key is missing or the API call fails, the app falls back to the local evidence template.

## Reindex From Raw Data

If you only changed parsing or cleaning rules, you usually do not need to call Notion again.

```bash
oh-my-notion reindex
```

This rebuilds the local SQLite index from `data/raw/*.json`.

## Suggested Next Steps

1. Extend parsing coverage for more Notion block types
2. Add incremental sync based on `last_edited_time`
3. Add an LLM answer layer on top of the current evidence-first flow
