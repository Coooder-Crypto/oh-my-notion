from __future__ import annotations

import sqlite3

from app.models import SearchResult
from app.tools import search_local_notion


def answer_question(connection: sqlite3.Connection, question: str, top_k: int = 5) -> str:
    results = search_local_notion(connection=connection, query=question, top_k=top_k)
    if not results:
        return (
            "未在本地 Notion 索引中找到足够证据。\n"
            "建议下一步：补充内容、优化切分策略，或实现远程 Notion 同步后重试。"
        )

    lines = [
        "以下内容来自本地 Notion 索引：",
        summarize_results(results),
        "",
        "当前回答策略仍然是 evidence-first 模板，还没有接入 LLM 归纳层。",
    ]
    return "\n".join(lines)


def summarize_results(results: list[SearchResult]) -> str:
    output: list[str] = []
    for index, result in enumerate(results, start=1):
        snippet = compact_text(result.content)
        output.append(
            f"{index}. {result.title} | {result.heading or '正文'}\n"
            f"   {snippet}\n"
            f"   来源: {result.url}"
        )
    return "\n".join(output)


def compact_text(text: str, max_length: int = 160) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."

