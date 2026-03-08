from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from app.evaluation.dataset import EvalCase, load_eval_cases
from app.retrieval.tools import search_local_notion


@dataclass(slots=True)
class RetrievalEvalRow:
    case_id: str
    question: str
    expected_pages: list[str]
    actual_pages: list[str]
    hit: bool
    reciprocal_rank: float


def evaluate_retrieval(
    connection: sqlite3.Connection,
    dataset_path: Path,
    top_k: int = 5,
) -> tuple[str, list[RetrievalEvalRow]]:
    cases = load_eval_cases(dataset_path)
    retrieval_cases = [case for case in cases if case.expected_pages]
    if not retrieval_cases:
        return f"No retrieval cases found in {dataset_path}", []

    rows: list[RetrievalEvalRow] = []
    hits = 0
    reciprocal_rank_sum = 0.0

    for case in retrieval_cases:
        rows.append(evaluate_retrieval_case(connection, case, top_k))

    for row in rows:
        if row.hit:
            hits += 1
        reciprocal_rank_sum += row.reciprocal_rank

    hit_rate = hits / len(rows)
    mean_reciprocal_rank = reciprocal_rank_sum / len(rows)

    lines = [
        f"Retrieval eval completed on {len(rows)} cases.",
        f"hit_rate: {hit_rate:.3f}",
        f"mrr: {mean_reciprocal_rank:.3f}",
        "",
    ]
    for row in rows:
        status = "PASS" if row.hit else "FAIL"
        lines.append(f"[{status}] {row.case_id} | {row.question}")
        lines.append(f"  expected_pages: {', '.join(row.expected_pages)}")
        lines.append(f"  actual_pages: {', '.join(row.actual_pages) if row.actual_pages else '(none)'}")
        lines.append(f"  reciprocal_rank: {row.reciprocal_rank:.3f}")
    return "\n".join(lines), rows


def evaluate_retrieval_case(
    connection: sqlite3.Connection,
    case: EvalCase,
    top_k: int,
) -> RetrievalEvalRow:
    results = search_local_notion(connection=connection, query=case.question, top_k=top_k)
    actual_pages = list(dict.fromkeys(result.page_id for result in results))
    hit = any(page_id in case.expected_pages for page_id in actual_pages)
    reciprocal_rank = compute_reciprocal_rank(case.expected_pages, actual_pages)
    return RetrievalEvalRow(
        case_id=case.id,
        question=case.question,
        expected_pages=case.expected_pages,
        actual_pages=actual_pages,
        hit=hit,
        reciprocal_rank=reciprocal_rank,
    )


def compute_reciprocal_rank(expected_pages: list[str], actual_pages: list[str]) -> float:
    expected = set(expected_pages)
    for index, page_id in enumerate(actual_pages, start=1):
        if page_id in expected:
            return 1.0 / index
    return 0.0
