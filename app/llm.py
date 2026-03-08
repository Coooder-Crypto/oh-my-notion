from __future__ import annotations

from openai import OpenAI

from app.config import Settings
from app.models import SearchResult


SYSTEM_PROMPT = """
You are a local-first knowledge assistant for a personal Notion workspace.
Answer only from the provided evidence snippets.
If the evidence is insufficient, say so clearly.
Keep the answer concise and useful.
Always include a short Sources section listing the page titles you used.
""".strip()


def create_openai_client(settings: Settings) -> OpenAI | None:
    if not settings.openai_api_key:
        return None
    return OpenAI(api_key=settings.openai_api_key)


def generate_grounded_answer(
    settings: Settings,
    question: str,
    results: list[SearchResult],
) -> str:
    client = create_openai_client(settings)
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    evidence = format_evidence(results)
    response = client.responses.create(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Evidence:\n{evidence}\n\n"
                    "Write the answer in Chinese. Base it only on the evidence."
                ),
            },
        ],
    )
    return response.output_text.strip()


def format_evidence(results: list[SearchResult]) -> str:
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        lines.append(f"[{index}] Title: {result.title}")
        lines.append(f"[{index}] Heading: {result.heading or '正文'}")
        lines.append(f"[{index}] URL: {result.url}")
        lines.append(f"[{index}] Content: {result.content}")
        lines.append("")
    return "\n".join(lines).strip()
