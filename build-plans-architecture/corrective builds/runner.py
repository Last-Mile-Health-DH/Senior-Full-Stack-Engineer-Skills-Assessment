"""
runner.py — execute the gold question bank through the real /chat, grade against the rubric,
persist a run, and write a Markdown report.

Run manually:
    python -m gold_standard.runner --trigger manual
    python -m gold_standard.runner --trigger manual --sample 8     # weighted random subset
CI gate (optional, makes real model calls):
    python -m gold_standard.runner --trigger ci --floor 85

The scheduled path (scheduler_job.py) calls run_gold_eval() directly.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .client import ChatClient
from .grader import GradeResult, aggregate, grade_answer
from .judge import make_judge

HERE = Path(__file__).resolve().parent


def _load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _weighted_sample(questions: list[dict], k: int) -> list[dict]:
    if k >= len(questions):
        return questions
    weights = [float(q.get("weight", 1.0)) for q in questions]
    # sample without replacement, weight-proportional
    chosen: list[dict] = []
    pool = list(zip(questions, weights))
    for _ in range(k):
        total = sum(w for _, w in pool)
        r = random.uniform(0, total)
        upto = 0.0
        for i, (q, w) in enumerate(pool):
            upto += w
            if upto >= r:
                chosen.append(q)
                pool.pop(i)
                break
    return chosen


async def run_gold_eval(
    db_pool,
    trigger: str = "manual",
    sample_size: int | None = None,
) -> dict:
    questions_doc = _load_yaml(os.environ.get("GOLD_QUESTIONS_PATH", str(HERE / "questions.yaml")))
    rubric = _load_yaml(os.environ.get("GOLD_RUBRIC_PATH", str(HERE / "rubric.yaml")))
    manifest = _load_yaml(str(HERE / "corpus" / "corpus_manifest.yaml"))

    all_qs = questions_doc["questions"]
    verified = [q for q in all_qs if q.get("verified") is True]
    skipped = [q["id"] for q in all_qs if q.get("verified") is not True]

    to_run = _weighted_sample(verified, sample_size) if sample_size else verified

    client = ChatClient(db_pool)
    judge = make_judge(rubric)  # pinned model/temperature; None if judging disabled

    results: list[GradeResult] = []
    per_q_lineage: dict[str, str | None] = {}
    for q in to_run:
        chat = await client.ask(q["question"])
        res = grade_answer(
            q=q,
            answer=chat.answer,
            cited_docs=chat.cited_docs,
            cited_pages=chat.cited_pages,
            source_texts=chat.source_texts,
            rubric=rubric,
            judge=judge,
        )
        results.append(res)
        per_q_lineage[q["id"]] = chat.query_audit_log_id

    agg = aggregate(results)
    run = {
        "run_at": datetime.now(timezone.utc),
        "git_sha": _git_sha(),
        "corpus_version": manifest["corpus_version"],
        "rubric_version": rubric["rubric_version"],
        "judge_model": os.environ.get("GOLD_EVAL_JUDGE_MODEL", os.environ.get("JUDGE_MODEL", "none")),
        "judge_temperature": float(os.environ.get("JUDGE_TEMPERATURE", "0.0")),
        "trigger": trigger,
        "overall_score": agg["overall_score"],
        "category_scores": agg["category_scores"],
        "pass_rate": agg["pass_rate"],
        "question_count": agg["question_count"],
        "skipped_count": len(skipped),
        "skipped_ids": skipped,
    }

    run_id = await _persist(db_pool, run, results, per_q_lineage)
    run["id"] = run_id
    _write_report(run, results)
    return run


async def _persist(db_pool, run: dict, results: list[GradeResult], lineage: dict) -> str:
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            run_id = await conn.fetchval(
                """
                INSERT INTO gold_eval_run
                  (run_at, git_sha, corpus_version, rubric_version, judge_model, judge_temperature,
                   overall_score, category_scores, pass_rate, question_count, skipped_count, trigger)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING id
                """,
                run["run_at"], run["git_sha"], run["corpus_version"], run["rubric_version"],
                run["judge_model"], run["judge_temperature"], run["overall_score"],
                __import__("json").dumps(run["category_scores"]), run["pass_rate"],
                run["question_count"], run["skipped_count"], run["trigger"],
            )
            for r in results:
                qal = lineage.get(r.question_id)
                await conn.execute(
                    """
                    INSERT INTO gold_eval_result
                      (run_id, question_id, category, weight, per_question_score, criterion_scores,
                       passed, query_audit_log_id, judge_rationale)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    run_id, r.question_id, r.category, r.weight, r.per_question_score,
                    __import__("json").dumps(r.criterion_scores.as_dict()), r.passed,
                    __import__("uuid").UUID(qal) if qal else None, r.rationale,
                )
    return str(run_id)


def _write_report(run: dict, results: list[GradeResult]) -> None:
    out = Path(os.environ.get("GOLD_EVAL_REPORT_PATH", str(HERE / "gold_eval_report.md")))
    lines = [
        f"# Gold-standard eval report",
        "",
        f"- Run at: {run['run_at'].isoformat()}",
        f"- Git: `{run['git_sha']}`  |  corpus `{run['corpus_version']}`  |  rubric v{run['rubric_version']}  |  judge `{run['judge_model']}` @ T={run['judge_temperature']}",
        f"- **Overall weighted score: {run['overall_score']} / 100**  |  pass-rate {run['pass_rate']}%  |  {run['question_count']} scored, {run['skipped_count']} skipped (unverified)",
        "",
        "## Category scores",
        "",
        "| Category | Weighted score |",
        "|---|---|",
    ]
    for cat, sc in sorted(run["category_scores"].items()):
        lines.append(f"| {cat} | {sc} |")
    lines += ["", "## Per-question", "", "| Question | Cat | Score | Pass | Num | Ground | Compl | Safety | Notes |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: x.per_question_score):
        c = r.criterion_scores
        lines.append(
            f"| {r.question_id} | {r.category} | {r.per_question_score} | {'✓' if r.passed else '✗'} | "
            f"{c.numeric_accuracy} | {c.grounding} | {c.completeness} | {c.safety} | {r.rationale} |"
        )
    if run["skipped_count"]:
        lines += ["", f"## Skipped (unverified — run verify_expected.py): {', '.join(run['skipped_ids'])}"]
    out.write_text("\n".join(lines))


# ---------------- CLI ----------------

async def _amain() -> int:
    ap = argparse.ArgumentParser(description="Run the gold-standard eval.")
    ap.add_argument("--trigger", default="manual", choices=["manual", "ci", "scheduled"])
    ap.add_argument("--sample", type=int, default=None, help="weighted random subset size")
    ap.add_argument("--floor", type=float, default=None, help="CI: fail if overall score below this")
    args = ap.parse_args()

    # INTEGRATOR TODO: build your asyncpg pool the same way the backend does.
    from app.db.pool import create_pool  # type: ignore  # noqa
    db_pool = await create_pool()
    try:
        run = await run_gold_eval(db_pool, trigger=args.trigger, sample_size=args.sample)
        print(f"overall={run['overall_score']} pass_rate={run['pass_rate']}% "
              f"scored={run['question_count']} skipped={run['skipped_count']}")
        if args.floor is not None and run["overall_score"] < args.floor:
            print(f"FAIL: overall {run['overall_score']} < floor {args.floor}")
            return 1
        return 0
    finally:
        await db_pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain()))
