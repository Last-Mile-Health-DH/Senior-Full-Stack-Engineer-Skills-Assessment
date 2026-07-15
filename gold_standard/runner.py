"""Run the versioned gold-standard eval through the real `/chat` pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.judge_agent import JudgeAgent
from app.database import async_session
from app.settings import settings
from gold_standard.client import ChatClient, ChatResult
from gold_standard.grader import GradeResult, aggregate, grade_answer

HERE = Path(__file__).resolve().parent


class GoldChatClient(Protocol):
    async def ask(self, question: str, session_id: str | None = None) -> ChatResult:
        ...


def _load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _weighted_sample(questions: list[dict], k: int) -> list[dict]:
    if k >= len(questions):
        return questions
    chosen: list[dict] = []
    pool = [(question, float(question.get("weight", 1.0))) for question in questions]
    for _ in range(k):
        total = sum(weight for _, weight in pool)
        cursor = random.uniform(0, total)
        upto = 0.0
        for index, (question, weight) in enumerate(pool):
            upto += weight
            if upto >= cursor:
                chosen.append(question)
                pool.pop(index)
                break
    return chosen


async def run_gold_eval(
    db: AsyncSession,
    trigger: str = "manual",
    sample_size: int | None = None,
    chat_client: GoldChatClient | None = None,
    judge_agent: JudgeAgent | None = None,
) -> dict:
    """Execute verified gold questions, persist results, and write a report."""
    questions_doc = _load_yaml(os.environ.get("GOLD_QUESTIONS_PATH", str(HERE / "questions.yaml")))
    rubric = _load_yaml(os.environ.get("GOLD_RUBRIC_PATH", str(HERE / "rubric.yaml")))
    manifest = _load_yaml(str(HERE / "corpus" / "corpus_manifest.yaml"))

    all_questions = list(questions_doc["questions"])
    verified = [question for question in all_questions if question.get("verified") is True]
    skipped = [question["id"] for question in all_questions if question.get("verified") is not True]
    to_run = _weighted_sample(verified, sample_size) if sample_size else verified

    client = chat_client or ChatClient()
    close_client = chat_client is None and hasattr(client, "aclose")
    judge = judge_agent or JudgeAgent(model=settings.gold_eval_judge_model or settings.judge_model)

    results: list[GradeResult] = []
    chat_results: dict[str, ChatResult] = {}
    semaphore = asyncio.Semaphore(max(1, settings.gold_eval_concurrency))

    async def grade_one(question: dict) -> tuple[GradeResult, ChatResult]:
        async with semaphore:
            chat = await client.ask(question["question"])
            qualitative = await judge.qualitative_scores(question, chat.answer, rubric)

            def judge_fn(criterion: str, _question: dict, _answer: str) -> float:
                result = qualitative.get(criterion)
                return result.score if result is not None else 0.0

            grade = grade_answer(
                q=question,
                answer=chat.answer,
                cited_docs=chat.cited_docs,
                cited_pages=chat.cited_pages,
                source_texts=chat.source_texts,
                rubric=rubric,
                judge=judge_fn,
            )
            rationales = [result.rationale for result in qualitative.values() if result.rationale]
            if rationales:
                grade.rationale = "; ".join(part for part in [grade.rationale, *rationales] if part)
            return grade, chat

    try:
        for grade, chat in await asyncio.gather(*(grade_one(question) for question in to_run)):
            results.append(grade)
            chat_results[grade.question_id] = chat
    finally:
        if close_client:
            await client.aclose()  # type: ignore[attr-defined]

    agg = aggregate(results)
    run = {
        "run_at": datetime.now(UTC),
        "git_sha": _git_sha(),
        "corpus_version": manifest["corpus_version"],
        "rubric_version": int(rubric["rubric_version"]),
        "judge_model": judge.metadata.model,
        "judge_temperature": float(judge.metadata.temperature),
        "trigger": trigger,
        "overall_score": agg["overall_score"],
        "category_scores": agg["category_scores"],
        "pass_rate": agg["pass_rate"],
        "question_count": agg["question_count"],
        "skipped_count": len(skipped),
        "skipped_ids": skipped,
    }

    run_id = await _persist(db, run, results, chat_results)
    run["id"] = run_id
    _write_report(run, results)
    return run


async def _persist(
    db: AsyncSession,
    run: dict,
    results: list[GradeResult],
    chat_results: dict[str, ChatResult],
) -> str:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO gold_eval_run (
                    run_at,
                    git_sha,
                    corpus_version,
                    rubric_version,
                    judge_model,
                    judge_temperature,
                    overall_score,
                    category_scores,
                    pass_rate,
                    question_count,
                    skipped_count,
                    trigger
                )
                VALUES (
                    :run_at,
                    :git_sha,
                    :corpus_version,
                    :rubric_version,
                    :judge_model,
                    :judge_temperature,
                    :overall_score,
                    CAST(:category_scores AS jsonb),
                    :pass_rate,
                    :question_count,
                    :skipped_count,
                    :trigger
                )
                RETURNING id
                """
            ),
            {
                **run,
                "category_scores": json.dumps(run["category_scores"]),
            },
        )
    ).mappings().one()
    run_id = row["id"]
    for result in results:
        chat = chat_results[result.question_id]
        await db.execute(
            text(
                """
                INSERT INTO gold_eval_result (
                    run_id,
                    question_id,
                    category,
                    weight,
                    per_question_score,
                    criterion_scores,
                    passed,
                    answer_text,
                    cited_docs,
                    cited_pages,
                    query_audit_log_id,
                    judge_rationale
                )
                VALUES (
                    :run_id,
                    :question_id,
                    :category,
                    :weight,
                    :per_question_score,
                    CAST(:criterion_scores AS jsonb),
                    :passed,
                    :answer_text,
                    :cited_docs,
                    :cited_pages,
                    :query_audit_log_id,
                    :judge_rationale
                )
                """
            ),
            {
                "run_id": run_id,
                "question_id": result.question_id,
                "category": result.category,
                "weight": result.weight,
                "per_question_score": result.per_question_score,
                "criterion_scores": json.dumps(result.criterion_scores.as_dict()),
                "passed": result.passed,
                "answer_text": chat.answer,
                "cited_docs": chat.cited_docs,
                "cited_pages": chat.cited_pages,
                "query_audit_log_id": UUID(chat.query_audit_log_id) if chat.query_audit_log_id else None,
                "judge_rationale": result.rationale,
            },
        )
    return str(run_id)


def _write_report(run: dict, results: list[GradeResult]) -> None:
    out = Path(os.environ.get("GOLD_EVAL_REPORT_PATH", settings.gold_eval_report_path))
    lines = [
        "# Gold-standard eval report",
        "",
        f"- Run at: {run['run_at'].isoformat()}",
        f"- Git: `{run['git_sha']}` | corpus `{run['corpus_version']}` | rubric v{run['rubric_version']} | judge `{run['judge_model']}` @ T={run['judge_temperature']}",
        f"- **Overall weighted score: {run['overall_score']} / 100** | pass-rate {run['pass_rate']}% | {run['question_count']} scored, {run['skipped_count']} skipped (unverified)",
        "",
        "## Category Scores",
        "",
        "| Category | Weighted score |",
        "|---|---|",
    ]
    for category, score in sorted(run["category_scores"].items()):
        lines.append(f"| {category} | {score} |")
    lines += [
        "",
        "## Per Question",
        "",
        "| Question | Cat | Score | Pass | Num | Ground | Compl | Safety | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in sorted(results, key=lambda item: item.per_question_score):
        scores = result.criterion_scores
        lines.append(
            f"| {result.question_id} | {result.category} | {result.per_question_score} | {'yes' if result.passed else 'no'} | "
            f"{scores.numeric_accuracy} | {scores.grounding} | {scores.completeness} | {scores.safety} | {result.rationale} |"
        )
    if run["skipped_count"]:
        lines += ["", f"## Skipped Unverified Questions: {', '.join(run['skipped_ids'])}"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Run the gold-standard eval.")
    parser.add_argument("--trigger", default="manual", choices=["manual", "ci", "scheduled"])
    parser.add_argument("--sample", type=int, default=None, help="weighted random subset size")
    parser.add_argument("--floor", type=float, default=None, help="CI: fail if overall score is below this")
    args = parser.parse_args()

    async with async_session() as db:
        run = await run_gold_eval(db, trigger=args.trigger, sample_size=args.sample)
        await db.commit()
    print(
        f"overall={run['overall_score']} pass_rate={run['pass_rate']}% "
        f"scored={run['question_count']} skipped={run['skipped_count']}"
    )
    if args.floor is not None and float(run["overall_score"]) < args.floor:
        print(f"FAIL: overall {run['overall_score']} < floor {args.floor}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain()))
