from __future__ import annotations

import sqlite3

from app.config import Settings
from app.llm import generate_grounded_answer
from app.models import SearchResult
from app.tools import search_local_notion


def answer_question(
    connection: sqlite3.Connection,
    settings: Settings,
    question: str,
    top_k: int = 5,
) -> str:
    results = search_local_notion(connection=connection, query=question, top_k=top_k)
    if not results:
        return (
            "未在本地 Notion 索引中找到足够证据。\n"
            "建议下一步：补充内容、优化切分策略，或实现远程 Notion 同步后重试。"
        )

    if settings.openai_api_key:
        try:
            return generate_grounded_answer(settings=settings, question=question, results=results)
        except Exception as exc:
            fallback_header = f"OpenAI 回答失败，已回退到本地模板回答。\n原因：{exc}\n"
            return fallback_header + build_template_answer(results, llm_enabled=True)

    return build_template_answer(results, llm_enabled=False)


def build_template_answer(results: list[SearchResult], llm_enabled: bool) -> str:
    footer = (
        "当前 OpenAI 调用不可用，因此使用 evidence-first 模板回答。"
        if llm_enabled
        else "当前未配置 OpenAI API，因此使用 evidence-first 模板回答。"
    )
    lines = [
        "以下内容来自本地 Notion 索引：",
        summarize_results(results),
        "",
        footer,
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
