from __future__ import annotations

import sqlite3

from app.agent_runtime import run_agent
from app.answer_rendering import build_template_answer
from app.config import Settings
from app.llm import generate_grounded_answer
from app.models import SearchResult
from app.tools import search_local_notion


def answer_question(
    connection: sqlite3.Connection,
    settings: Settings,
    question: str,
    top_k: int = 5,
    session_id: str = "default",
) -> str:
    return run_agent(
        connection=connection,
        settings=settings,
        question=question,
        top_k=top_k,
        session_id=session_id,
    )


def answer_question_legacy(
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
