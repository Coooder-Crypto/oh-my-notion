# Oh My Notion

`Oh My Notion` is a Python MVP for a local-first Notion agent. It prioritizes local search over synced Notion content, then uses the retrieved evidence to answer questions.

It is designed as a learning project for agent development:
- local-first retrieval before any remote model call
- grounded answers based on retrieved Notion evidence
- optional OpenAI summarization layer on top of local search
- hybrid retrieval with FTS + local semantic embeddings + rerank

## Current Scope

- Local SQLite storage
- SQLite FTS5 full-text search
- Local embedding index for semantic retrieval
- Local file ingestion for `.md` and `.txt`
- Local-first agent flow
- CLI entrypoint for `init-db`, `ingest-sample`, `ingest-files`, `search`, `ask`, `sync`, `reindex`, and `serve`
- Real Notion sync for pages, child pages, and database entries
- Lightweight web frontend served by Python
- Optional OpenAI API integration for grounded answer generation
- Local inspection commands for raw snapshots, parsed pages, chunks, links, and stats
- Local eval commands for retrieval and agent tool routing

## Architecture

The project now uses a `source -> tool -> skill -> planner -> runtime -> context -> answer` architecture.

### 1. Sources

The agent reads from multiple local knowledge sources:

- Notion snapshots in `data/raw/*.json`
- Local files in `knowledge_files/`
- SQLite memory tables for session memory, facts, preferences, and summaries
- Structured link records extracted from Notion pages and local files

Main code:

- `app/notion/sync.py`
- `app/notion/parser.py`
- `app/ingestion/files.py`
- `app/storage/db.py`

### 2. Data / Index Layer

All sources are normalized into the same local storage model:

- `pages`
- `chunks`
- `chunk_embeddings`
- `saved_links`
- `session_turns`
- `memory_facts`
- `memory_preferences`
- `memory_summaries`

This keeps Notion pages and local files inside the same retrieval plane.

Main code:

- `app/storage/models.py`
- `app/storage/db.py`
- `app/storage/reindex.py`

### 3. Tools

Tools are the smallest executable capabilities. They do not decide the full task flow; they only fetch or update data.

Current tools include:

- `search_local_notion`
- `list_recent_pages`
- `get_page`
- `search_saved_links`
- `list_top_link_domains`
- `find_pages_by_domain`
- `get_link_domain_summary`
- `read_network_link`
- `lookup_memory`
- `lookup_preferences`
- `save_memory`
- `save_preference`

Main code:

- `app/retrieval/tools.py`
- `app/agent/memory.py`
- `app/agent/tools_registry.py`

### 4. Skills

Skills are task-oriented orchestration units built on top of tools. A skill may call one or more tools and may decide whether a follow-up step is needed.

Current skills:

- `local_qa_skill`
- `multi_source_research_skill`
- `link_research_skill`
- `memory_skill`
- `recent_activity_skill`
- `generic_research_skill`

Main code:

- `app/skills/registry.py`

### 5. Planner

The planner is now skill-first.

It decides:

- which skill should handle the question
- which arguments should be passed to the skill
- whether the next step should stop or continue based on observations

There are two planner modes:

- LLM-driven skill planning when OpenAI is available
- rule-based skill routing as fallback

Main code:

- `app/agent/planner.py`

### 6. Runtime

The runtime executes a `thought -> skill -> tool -> observation` loop with:

- step limits
- duplicate-call prevention
- follow-up tool execution
- planner trace recording
- session persistence
- automatic memory capture

Main code:

- `app/agent/runtime.py`
- `app/agent/executor.py`

### 7. Context Builder

The context builder turns retrieved evidence, memory, network results, and planner trace into a bounded final context for the LLM.

It handles:

- layered token budgets
- retrieval / memory / network / trace allocation
- dynamic trimming
- citation ids
- explanation output

Main code:

- `app/context/builder.py`
- `app/context/models.py`

### 8. Answer Layer

The final answer layer has two modes:

- OpenAI grounded generation using the built context
- local evidence-first fallback when OpenAI is unavailable

Main code:

- `app/llm.py`
- `app/agent/rendering.py`
- `app/agent/service.py`

### 9. Eval / Inspection

The project includes built-in tooling for:

- retrieval evaluation
- agent routing evaluation
- local snapshot inspection
- dashboard analysis

Main code:

- `app/evaluation/`
- `app/inspection/`
- `app/webapp/server.py`

## Ask Flow

A normal `ask` request runs roughly like this:

1. The planner selects a skill.
2. The skill expands into one or more tool calls.
3. Tools return observations from local knowledge, links, memory, or network content.
4. The runtime decides whether to stop or continue another step.
5. The context builder assembles the final evidence bundle.
6. The answer layer returns either:
   - an OpenAI grounded answer
   - or a local fallback answer
7. The session is persisted and memory may be updated.

In short:

```text
Question
-> Planner
-> Skill
-> Tool Calls
-> Observations
-> Context Builder
-> Answer
-> Memory Update / Eval
```

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
oh-my-notion init-db
oh-my-notion ingest-sample
oh-my-notion ingest-files
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
- `OH_MY_NOTION_KNOWLEDGE_DIR`: optional path to the local files directory, defaults to `knowledge_files/`
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
It also regenerates chunk embeddings for hybrid retrieval and rebuilds local files from `knowledge_files/`.

You can also rebuild only matching raw files:

```bash
oh-my-notion reindex notes
```

## Local Files As A Second Source

Put local `.md` or `.txt` files under:

```text
knowledge_files/
```

Then ingest them into the same local index:

```bash
oh-my-notion ingest-files
oh-my-notion search "agent"
oh-my-notion ask "我在本地文件和 Notion 里关于 agent 写了什么？"
```

The file source shares the same chunks, embeddings, hybrid retrieval, and agent pipeline as Notion pages.

## Local Analysis Commands

These commands help inspect local data without calling Notion again:

```bash
oh-my-notion inspect-raw <page-id-or-file>
oh-my-notion inspect-page <page-id-or-file>
oh-my-notion inspect-chunks <page-id-or-file>
oh-my-notion inspect-links <page-id-or-file>
oh-my-notion stats
```

## Eval

Use the built-in eval dataset or provide your own JSONL file:

```bash
oh-my-notion eval-retrieval
oh-my-notion eval-agent
oh-my-notion eval-all
```

Default dataset location:

```text
eval/questions.jsonl
```

Each JSONL item can include:

- `question`
- `expected_pages`
- `expected_tools`

## Hybrid RAG

The project now uses a lightweight Hybrid RAG pipeline:

- FTS5 for keyword recall
- local hashed embeddings for semantic recall
- score merge + rerank before answer generation

This keeps the system fully local by default. Rebuild the index once after upgrading:

```bash
oh-my-notion reindex
oh-my-notion search "agent routing"
oh-my-notion ask "我关于 agent routing 的笔记写了什么？"
```

## Suggested Next Steps

1. Extend parsing coverage for more Notion block types
2. Add incremental sync based on `last_edited_time`
3. Add an LLM answer layer on top of the current evidence-first flow
