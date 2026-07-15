"""Deterministic coverage for the chat response presentation boundary."""

from __future__ import annotations

import re
from uuid import uuid4

from app.chat.response_presenter import (
    DOCUMENT_PREPARING_MESSAGE,
    NO_ANSWER_MESSAGE,
    RETRIEVAL_UNAVAILABLE_MESSAGE,
    UPLOAD_FIRST_MESSAGE,
    build_citation_candidates,
    document_display_title,
    is_no_answer,
    present_answer,
)
from app.retrieval.models import RetrievalCandidate
from app.security.guardrails import SAFE_FALLBACK_MESSAGE


def _chunk(filename: str, page: int, content: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_filename=filename,
        document_status="indexed",
        content=content,
        page_number=page,
    )


def _candidates() -> list:
    return build_citation_candidates(
        [
            _chunk("oral_rehydration_protocol.pdf", 1, "Child dose is 5 ml."),
            _chunk("who_guidance_2024.pdf", 14, "Adults receive 10 ml per hour."),
        ]
    )


def test_sentence_end_superscripts_and_reference_list() -> None:
    presented = present_answer(
        "The child dose is 5 ml.[cite:1] Adults receive 10 ml.[cite:2]",
        _candidates(),
    )

    assert presented.display_text == "The child dose is 5 ml.¹ Adults receive 10 ml.²"
    assert presented.references == [
        "1. Oral Rehydration Protocol, p. 1.",
        "2. Who Guidance 2024, p. 14.",
    ]
    assert len(presented.citations) == 2


def test_marker_before_punctuation_moves_to_sentence_end() -> None:
    presented = present_answer("The child dose is 5 ml [cite:1].", _candidates())

    assert presented.display_text == "The child dose is 5 ml.¹"


def test_multiple_sources_render_multiple_superscripts_at_sentence_end() -> None:
    presented = present_answer("Doses differ by age.[cite:1][cite:2]", _candidates())

    assert presented.display_text == "Doses differ by age.¹²"
    assert len(presented.references) == 2


def test_invalid_marker_is_dropped_and_creates_no_reference() -> None:
    presented = present_answer("The dose is 5 ml.[cite:99]", _candidates())

    assert presented.display_text == "The dose is 5 ml."
    assert presented.citations == []
    assert presented.references == []
    assert presented.dropped_markers == [99]
    assert presented.has_support is False


def test_leading_filename_prefix_is_removed() -> None:
    presented = present_answer(
        "oral_rehydration_protocol.pdf: The child dose is 5 ml.[cite:1]",
        _candidates(),
    )

    assert presented.display_text == "The child dose is 5 ml.¹"
    assert not presented.display_text.lower().startswith("oral_rehydration_protocol")


def test_leading_document_name_and_preamble_are_removed() -> None:
    candidates = _candidates()

    assert (
        present_answer("Based on oral_rehydration_protocol.pdf, the child dose is 5 ml.[cite:1]", candidates).display_text
        == "The child dose is 5 ml.¹"
    )
    assert (
        present_answer("Oral Rehydration Protocol - The child dose is 5 ml.[cite:1]", candidates).display_text
        == "The child dose is 5 ml.¹"
    )


def test_internal_details_never_reach_the_user() -> None:
    presented = present_answer(
        "The dose is 5 ml.[cite:1] This answer is based on chunk 8 and retrieval mode hybrid.",
        _candidates(),
    )

    assert presented.display_text == "The dose is 5 ml.¹"
    assert "chunk" not in presented.display_text.lower()
    assert "retrieval mode" not in presented.display_text.lower()


def test_repeated_caveat_is_collapsed() -> None:
    presented = present_answer(
        "The dose is 5 ml.[cite:1] The dose is 5 ml.[cite:1]",
        _candidates(),
    )

    assert presented.display_text == "The dose is 5 ml.¹"


def test_paragraphs_and_bullets_survive_presentation() -> None:
    presented = present_answer(
        "Doses vary.[cite:1]\n\n- Children get 5 ml.[cite:1]\n- Adults get 10 ml.[cite:2]",
        _candidates(),
    )

    assert presented.display_text == "Doses vary.¹\n\n- Children get 5 ml.¹\n- Adults get 10 ml.²"


def test_no_answer_is_concise_and_uncited() -> None:
    presented = present_answer("I could not find that in the uploaded documents.", _candidates())

    assert presented.is_no_answer is True
    assert presented.display_text == NO_ANSWER_MESSAGE
    assert presented.citations == []
    assert presented.references == []


def test_no_answer_with_no_candidates_does_not_hallucinate_citations() -> None:
    presented = present_answer("I could not find that in the uploaded documents.", [])

    assert presented.is_no_answer is True
    assert presented.references == []


def test_citation_numbers_follow_first_appearance_order() -> None:
    presented = present_answer(
        "Adults receive 10 ml.[cite:2] Children receive 5 ml.[cite:1]",
        _candidates(),
    )

    assert presented.display_text == "Adults receive 10 ml.¹ Children receive 5 ml.²"
    assert presented.references == [
        "1. Who Guidance 2024, p. 14.",
        "2. Oral Rehydration Protocol, p. 1.",
    ]


def test_reference_list_uses_backend_metadata_not_model_text() -> None:
    candidates = build_citation_candidates([_chunk("who_guidance_2024.pdf", 14, "Adults receive 10 ml.")])
    presented = present_answer(
        "Adults receive 10 ml.[cite:1]\n\nReferences\n1. Invented Source, p. 99.",
        candidates,
    )

    assert presented.references == ["1. Who Guidance 2024, p. 14."]
    assert "Invented Source" not in " ".join(presented.references)
    assert "p. 99" not in " ".join(presented.references)


def test_section_path_is_included_when_present() -> None:
    chunk = _chunk("who_guidance_2024.pdf", 14, "Adults receive 10 ml.")
    candidates = build_citation_candidates([chunk.model_copy(update={"section_path": "Dose table"})])
    presented = present_answer("Adults receive 10 ml.[cite:1]", candidates)

    assert presented.references == ["1. Who Guidance 2024, Dose table, p. 14."]


def test_document_display_title_is_readable() -> None:
    assert document_display_title("oral_rehydration_protocol.pdf") == "Oral Rehydration Protocol"
    assert document_display_title("WHO-Guidance-2024.pdf") == "WHO Guidance 2024"


def test_is_no_answer_recognizes_model_phrasings() -> None:
    assert is_no_answer("I could not find that in the uploaded documents.") is True
    assert is_no_answer("The documents do not mention that.") is True
    assert is_no_answer("The child dose is 5 ml.") is False


def test_user_facing_copy_carries_no_retrieval_jargon() -> None:
    """These strings are read by people who just want answers from their own documents."""
    jargon = re.compile(
        r"\b(RAG|chunks?|corpus|grounded|grounding|retrieval|reranker|embedding|ingestion|indexed|index)\b",
        re.IGNORECASE,
    )
    for message in (
        NO_ANSWER_MESSAGE,
        RETRIEVAL_UNAVAILABLE_MESSAGE,
        UPLOAD_FIRST_MESSAGE,
        DOCUMENT_PREPARING_MESSAGE,
        SAFE_FALLBACK_MESSAGE,
    ):
        assert jargon.search(message) is None, f"user-facing copy contains jargon: {message}"


def test_empty_corpus_message_politely_asks_for_a_pdf() -> None:
    assert "please upload a pdf" in UPLOAD_FIRST_MESSAGE.lower()
    # A document that is merely still processing must not be told to upload one.
    assert "upload" not in DOCUMENT_PREPARING_MESSAGE.lower()


def test_no_answer_and_retrieval_failure_stay_distinguishable() -> None:
    """"Cannot search right now" must not be confused with "not in your documents"."""
    assert NO_ANSWER_MESSAGE != RETRIEVAL_UNAVAILABLE_MESSAGE
    assert "could not find" in NO_ANSWER_MESSAGE.lower()
    assert "could not search" in RETRIEVAL_UNAVAILABLE_MESSAGE.lower()
