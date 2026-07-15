from __future__ import annotations

from uuid import uuid4

import pytest

from app.retrieval.models import RetrievalCandidate
from app.security.guardrails import filter_output
from app.security.numeric_grounding import extract_quantities, numeric_claims_supported


def test_supported_dose_passes() -> None:
    supported, unsupported = numeric_claims_supported(
        "Give 5 ml amoxicillin two times daily.",
        ["The amoxicillin dose is 5 ml two times daily."],
    )

    assert supported is True
    assert unsupported == []


def test_wrong_dose_fails() -> None:
    supported, unsupported = numeric_claims_supported(
        "Give 15 ml amoxicillin two times daily.",
        ["The amoxicillin dose is 5 ml two times daily."],
    )

    assert supported is False
    assert unsupported == ["15 ml"]


def test_fraction_normalization_supports_decimal_and_unicode_fraction() -> None:
    supported, unsupported = numeric_claims_supported(
        "Give 1/2 tablet daily.",
        ["Give 0.5 tablet daily."],
    )

    assert supported is True
    assert unsupported == []
    assert extract_quantities("Give 1/2 tablet")[0].value == pytest.approx(0.5)


def test_bare_integers_are_ignored() -> None:
    supported, unsupported = numeric_claims_supported(
        "See step 3 for follow up.",
        ["Follow up instructions are listed."],
    )

    assert supported is True
    assert unsupported == []


@pytest.mark.asyncio
async def test_fabricated_dose_is_filtered_before_send() -> None:
    candidate = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_filename="source.pdf",
        document_status="indexed",
        content="The amoxicillin dose is 5 ml two times daily.",
        page_number=1,
    )

    result = await filter_output("The amoxicillin dose is 15 ml two times daily.", [candidate])

    assert result.status == "filtered"
    assert result.reason == "numeric_grounding_fail"


@pytest.mark.asyncio
async def test_output_numeric_grounding_ignores_tolerance_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "grounding_numeric_tolerance", 1.0)
    candidate = RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_filename="source.pdf",
        document_status="indexed",
        content="The amoxicillin dose is 5 ml two times daily.",
        page_number=1,
    )

    result = await filter_output("The amoxicillin dose is 5.1 ml two times daily.", [candidate])

    assert result.status == "filtered"
    assert result.reason == "numeric_grounding_fail"
