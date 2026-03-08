# Agent Roadmap

## Goal

Upgrade `Oh My Notion` from a local-first RAG utility into a job-ready Agent system that demonstrates:

- tool-using agent behavior
- memory design
- hybrid retrieval
- context engineering
- evaluation workflow

This roadmap is aligned with Agent-focused job requirements around ReAct, Memory, RAG, tool calling, context management, and evaluation.

## Current Baseline

The project already includes:

- Notion sync to local raw JSON
- local SQLite + FTS5 retrieval
- basic RAG-style answer flow
- optional OpenAI answer generation
- data cleaning and reindex workflow
- local inspection commands
- sync fault tolerance and block-level cache

What is still missing is a real Agent runtime and the surrounding systems that make it feel like an Agent project instead of a retrieval utility.

## Phase 1: Tool-Using Agent

### Objective

Turn `ask` into a real tool-using agent instead of a fixed `search -> answer` pipeline.

### Scope

- define a tool registry
- define a tool call schema
- add an agent runtime that can:
  - inspect the user question
  - choose tools
  - execute tools
  - collect observations
  - produce a final answer

### Candidate Tools

- `search_local_notion(query, top_k)`
- `get_page(page_id)`
- `list_recent_pages(limit)`
- `search_links(query)`
- `lookup_memory(query)`
- `save_memory(fact)`
- `sync_if_needed()`

### Deliverables

- `app/tools_registry.py`
- `app/agent_runtime.py`
- `app/agent_planner.py`
- `app/agent_executor.py`

### Acceptance Criteria

- `ask` can choose different tools for different questions
- the agent supports multi-step tool execution
- answer generation is based on tool observations, not only raw retrieval

## Phase 2: Memory

### Objective

Add both short-term and long-term memory.

### Session Memory

Track:

- recent user turns
- recent assistant turns
- recent tool results
- active topic summary

### Long-Term Memory

Store:

- user preferences
- stable facts
- recurring topics
- useful conversation summaries

### Suggested Storage

- `memory_facts`
- `memory_preferences`
- `memory_summaries`

### Deliverables

- `app/session_memory.py`
- `app/long_term_memory.py`
- `app/memory.py`

### Acceptance Criteria

- follow-up questions can use prior turn context
- high-value information can be persisted and reused later

## Phase 3: Hybrid RAG

### Objective

Upgrade retrieval from pure keyword search to hybrid retrieval with rerank.

### Scope

- generate embeddings for chunks
- add vector retrieval
- merge FTS and vector results
- rerank retrieved candidates

### Suggested Components

- `app/embed.py`
- `app/vector_index.py`
- `app/hybrid_search.py`
- `app/rerank.py`

### Acceptance Criteria

- semantic matches improve recall over FTS alone
- rerank improves precision in top results

## Phase 4: Context Builder

### Objective

Make context management explicit and modular.

### Scope

- combine retrieval evidence, memory, and tool output
- control context budget
- rank context importance
- format citations consistently

### Deliverables

- `app/context_builder.py`
- `app/context_models.py`

### Acceptance Criteria

- prompt construction is structured and inspectable
- the agent can explain which evidence was included and why

## Phase 5: Eval

### Objective

Build a measurable evaluation loop for retrieval, answer quality, and tool use.

### Scope

- retrieval evaluation
- answer groundedness evaluation
- tool-choice evaluation
- regression testing for future changes

### Suggested Dataset Format

Each item should include:

- `question`
- `expected_pages`
- `expected_keywords`
- `expected_answer_points`

### Deliverables

- `eval/questions.jsonl`
- `app/eval_retrieval.py`
- `app/eval_answer.py`
- `app/eval_agent.py`

### Acceptance Criteria

- retrieval and answer changes can be measured
- baseline and improved runs can be compared

## Recommended Order

1. Tool-Using Agent
2. Memory
3. Context Builder
4. Hybrid RAG
5. Eval

## Two-Week Version

### Week 1

- Day 1-2: tool registry and runtime
- Day 3-4: session and long-term memory
- Day 5-6: context builder
- Day 7: integrate and stabilize

### Week 2

- Day 8-10: embedding, hybrid retrieval, rerank
- Day 11-12: eval dataset and scripts
- Day 13: compare baseline vs improved results
- Day 14: polish docs and interview story

## Interview Narrative

By the end of this roadmap, the project should let you clearly explain:

- why local-first retrieval was chosen
- how tool selection works
- how memory is split into short-term and long-term
- how context is engineered and budgeted
- how retrieval moved from keyword-only to hybrid search
- how quality is evaluated instead of guessed

That narrative is what turns this from a side project into a strong Agent interview project.
