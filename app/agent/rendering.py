from __future__ import annotations

from app.storage.models import SearchResult


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
