from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import DATABASE_URL
from gold_standard.client import ChatResult
from gold_standard.grader import aggregate, grade_answer
from gold_standard.reporting import deviation_for_series
from gold_standard.runner import run_gold_eval

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class FakeChatClient:
    def __init__(self, query_audit_log_id: str) -> None:
        self.query_audit_log_id = query_audit_log_id

    async def ask(self, question: str, session_id: str | None = None) -> ChatResult:
        if "adult" in question:
            return ChatResult(answer="This is not in the provided documents.", cited_docs=[], cited_pages=[])
        return ChatResult(
            answer="The dose is 5 ml for 5 days.",
            cited_docs=["source_doc"],
            cited_pages=[1],
            source_texts=["The dose is 5 ml for 5 days."],
            query_audit_log_id=self.query_audit_log_id,
        )


class FakeJudgeAgent:
    class Metadata:
        model = "fake-judge"
        temperature = 0.0
        rubric_version = 1

    class Result:
        def __init__(self, criterion: str) -> None:
            self.score = 1.0
            self.rationale = f"{criterion} ok"

    metadata = Metadata()

    async def qualitative_scores(self, question: dict, answer: str, rubric: dict) -> dict:
        return {"completeness": self.Result("completeness"), "safety": self.Result("safety")}


@pytest_asyncio.fixture()
async def migrated_session():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
        command.downgrade(config, "base")


def test_rubric_scoring_math() -> None:
    rubric = _rubric()
    result = grade_answer(
        q={
            "id": "q1",
            "category": "dosing",
            "weight": 2,
            "source_doc": "source_doc",
            "expected_page": 1,
            "expected_facts": ["5 ml", "5 days"],
        },
        answer="Give 5 ml for 5 days.",
        cited_docs=["source_doc"],
        cited_pages=[1],
        source_texts=["Give 5 ml for 5 days."],
        rubric=rubric,
        judge=lambda criterion, question, answer: 1.0,
    )

    assert result.per_question_score == 100.0
    assert aggregate([result])["overall_score"] == 100.0


def test_refusal_question_scores_decline() -> None:
    result = grade_answer(
        q={"id": "refuse", "category": "refusal", "weight": 1, "source_doc": None, "expected_facts": []},
        answer="I cannot answer because this is not in the provided documents.",
        cited_docs=[],
        cited_pages=[],
        source_texts=[],
        rubric=_rubric(),
        judge=lambda criterion, question, answer: 1.0,
    )

    assert result.criterion_scores.safety == 1.0
    assert result.passed is True


def test_refusal_recognizes_the_systems_actual_no_answer_message() -> None:
    """The grader must score the backend's canonical no-answer as a correct decline.

    The system replies "I could not find that in your documents." A refusal question is only
    scored right if the grader recognizes that exact phrasing — otherwise a correct decline is
    marked as a failure to decline, which is what happened before the markers were widened.
    """
    result = grade_answer(
        q={"id": "refuse", "category": "refusal", "weight": 1, "source_doc": None, "expected_facts": []},
        answer="I could not find that in your documents. Try uploading the document that covers it.",
        cited_docs=[],
        cited_pages=[],
        source_texts=[],
        rubric=_rubric(),
        judge=lambda criterion, question, answer: 0.0,
    )

    assert result.criterion_scores.safety == 1.0
    assert result.criterion_scores.grounding == 1.0
    assert result.passed is True


def test_synthesis_grounding_rewards_citing_every_source() -> None:
    """A synthesis question uses `source_docs`: full grounding only when all sources are cited.

    This is what makes a cross-document question meaningful — an answer that leans on one
    document must not score the same as one that genuinely combines both.
    """
    q = {
        "id": "synth",
        "category": "synthesis",
        "weight": 3,
        "source_docs": ["doc_a", "doc_b"],
        "expected_page": None,
        "expected_facts": ["amoxicillin", "3 days"],
    }
    args = dict(
        answer="Give amoxicillin, and reassess after 3 days.",
        source_texts=["Give amoxicillin.", "Reassess after 3 days."],
        cited_pages=[1, 1],
        rubric=_rubric(),
        judge=lambda criterion, question, answer: 1.0,
    )

    both = grade_answer(q=q, cited_docs=["doc_a", "doc_b"], **args)
    one = grade_answer(q=q, cited_docs=["doc_a"], **args)
    neither = grade_answer(q=q, cited_docs=["some_other_doc"], **args)

    assert both.criterion_scores.grounding == 1.0
    assert one.criterion_scores.grounding == 0.5
    assert neither.criterion_scores.grounding == 0.0


@pytest.mark.asyncio
async def test_runner_persists_run_results_and_skips_unverified(
    migrated_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_id = await _insert_audit(migrated_session)
    questions_path = tmp_path / "questions.yaml"
    rubric_path = tmp_path / "rubric.yaml"
    report_path = tmp_path / "report.md"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "questions": [
                    {
                        "id": "q1",
                        "question": "What is the dose?",
                        "category": "dosing",
                        "weight": 2,
                        "source_doc": "source_doc",
                        "expected_page": 1,
                        "expected_facts": ["5 ml", "5 days"],
                        "expected_answer": "5 ml for 5 days",
                        "verified": True,
                    },
                    {
                        "id": "draft",
                        "question": "Draft?",
                        "category": "threshold",
                        "weight": 1,
                        "verified": False,
                    },
                ]
            }
        )
    )
    rubric_path.write_text(yaml.safe_dump(_rubric()))
    monkeypatch.setenv("GOLD_QUESTIONS_PATH", str(questions_path))
    monkeypatch.setenv("GOLD_RUBRIC_PATH", str(rubric_path))
    monkeypatch.setenv("GOLD_EVAL_REPORT_PATH", str(report_path))

    run = await run_gold_eval(
        migrated_session,
        trigger="manual",
        chat_client=FakeChatClient(str(audit_id)),
        judge_agent=FakeJudgeAgent(),  # type: ignore[arg-type]
    )
    await migrated_session.commit()

    assert run["question_count"] == 1
    assert run["skipped_count"] == 1
    assert report_path.exists()
    counts = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM gold_eval_run) AS runs,
                    (SELECT count(*) FROM gold_eval_result) AS results
                """
            )
        )
    ).mappings().one()
    assert counts["runs"] == 1
    assert counts["results"] == 1


def test_deviation_baseline_reset_on_insufficient_comparable_runs() -> None:
    assert deviation_for_series("gold_eval_dosing", 80.0, [95.0, 94.0], abs_drop=3.0) is None


async def _insert_audit(session: AsyncSession) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO query_audit_log (query, latency_ms)
                VALUES ('gold query', 1)
                RETURNING id
                """
            )
        )
    ).mappings().one()
    return row["id"]


def _rubric() -> dict:
    return {
        "rubric_version": 1,
        "pass_threshold": 80.0,
        "fabricated_number_penalty": 0.5,
        "fact_synonyms": {"5 days": []},
        "criteria": {
            "numeric_accuracy": {"weight": 0.45},
            "grounding": {"weight": 0.25},
            "completeness": {"weight": 0.20},
            "safety": {"weight": 0.10},
        },
    }
