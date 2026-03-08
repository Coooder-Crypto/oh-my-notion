from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(slots=True)
class EvalCase:
    id: str
    question: str
    expected_pages: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def load_eval_cases(dataset_path: Path) -> list[EvalCase]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Eval dataset not found: {dataset_path}")

    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON on line {line_number} in {dataset_path}: {exc}"
            ) from exc

        cases.append(
            EvalCase(
                id=str(payload.get("id") or f"case-{line_number}"),
                question=str(payload.get("question") or "").strip(),
                expected_pages=normalize_string_list(payload.get("expected_pages")),
                expected_tools=normalize_string_list(payload.get("expected_tools")),
                tags=normalize_string_list(payload.get("tags")),
            )
        )
    return cases


def normalize_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if item is None:
            continue
        normalized.append(str(item))
    return normalized

