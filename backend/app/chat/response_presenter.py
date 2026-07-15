"""Response presentation boundary for `/api/v1/chat`.

The generation model emits deterministic `[cite:N]` markers that index into the
citation candidates the backend built from retrieved chunks. This module is the
only place allowed to turn a raw model answer into user-facing text. It:

- strips document-name openings such as ``guidance.pdf:`` or ``Based on X,``
- validates every marker against backend candidates and drops invalid ones
- moves markers to the end of the sentence they support and renders them as
  Chicago-style superscripts
- assembles the reference list from chunk metadata only, never from model text

Reference-list content is never taken from the model. If the model invents a
source id, page number, or document name, it is dropped here rather than shown.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from app.retrieval.models import RetrievalCandidate

# User-facing copy. These are read by people who just want answers from their own
# documents, so they must never mention retrieval, chunks, indexing, or grounding.
NO_ANSWER_MESSAGE = (
    "I could not find that in your documents. "
    "Try uploading the document that covers it, or ask about a specific section."
)
RETRIEVAL_UNAVAILABLE_MESSAGE = "I could not search your documents right now. Please try again."
# Nothing has been uploaded yet, so there is nothing to answer from. Ask, do not scold.
UPLOAD_FIRST_MESSAGE = (
    "I do not have any documents to look in yet. "
    "Please upload a PDF first, then ask your question and I will answer from it."
)
# A PDF was uploaded but is not ready to search yet. Telling this user to "upload a PDF
# first" would be wrong, so the two cases are kept apart.
DOCUMENT_PREPARING_MESSAGE = (
    "Your document is still being prepared. Please try again in a moment."
)

REFERENCES_HEADING = "Sources"

_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

# One or more adjacent citation markers, e.g. "[cite:1]" or " [cite:1][cite:2]".
_MARKER_RUN = re.compile(r"(?:[ \t]*\[cite:\s*\d{1,3}\s*\])+")
_MARKER_ID = re.compile(r"\[cite:\s*(\d{1,3})\s*\]")

# A marker run that sits *before* the sentence punctuation it belongs to.
_MARKER_BEFORE_PUNCTUATION = re.compile(r"((?:[ \t]*\[cite:\s*\d{1,3}\s*\])+)[ \t]*([.!?])")

_FILE_EXTENSIONS = ("pdf", "docx", "doc", "txt", "md")
# "oral_rehydration_protocol.pdf:" / "guidance.pdf -" at the very start.
_FILENAME_OPENING = re.compile(
    rf"^\S+\.(?:{'|'.join(_FILE_EXTENSIONS)})\s*[:\-–—]\s*",
    re.IGNORECASE,
)
# "Based on <source>," / "According to <source>:" at the very start. The source may be a
# filename, so `.` has to stay inside the class; the lazy quantifier stops at the first
# comma or colon rather than swallowing the sentence.
_PREAMBLE_OPENING = re.compile(
    r"^(?:based on|according to|as (?:stated|described|noted|set out) in|per|from)\s+"
    r"(?P<source>[^,:;\n]{1,120}?)\s*[,:]\s*",
    re.IGNORECASE,
)
# "<source> - " / "<source>: " at the very start.
_NAME_DELIMITER_OPENING = re.compile(
    r"^(?P<source>[^\n:\-–—]{1,120}?)\s*[:\-–—]\s+",
)

# Generic stand-ins a model reaches for when it opens with the source instead of the answer.
_GENERIC_SOURCE_NAMES = frozenset(
    {
        "the document",
        "the documents",
        "the uploaded document",
        "the uploaded documents",
        "the provided document",
        "the provided documents",
        "the context",
        "the pdf",
        "the guidance",
        "the source",
        "the sources",
        "the text",
        "the table",
    }
)

# Retrieval internals that must never reach a user-facing answer. A sentence matching any
# of these is dropped whole.
_INTERNAL_DETAIL = re.compile(
    r"\b(?:chunk[ _]?ids?|chunk\s+\d+|retrieval\s+mode|search\s+mode|top[_ ]?k|"
    r"reranker|cross[- ]encoder|embedding\s+model|hnsw|pgvector|rrf)\b",
    re.IGNORECASE,
)

# Phrases that mean "the corpus does not support an answer", however the model words it.
_NO_ANSWER_SIGNALS = (
    "i could not find",
    "i couldn't find",
    "i cannot find",
    "i can't find",
    "i do not have enough",
    "i don't have enough",
    "not in the uploaded documents",
    "no relevant information",
    "the documents do not",
    "the documents don't",
    "insufficient context",
    "context is insufficient",
    "could not find document context",
)


@dataclass(slots=True, frozen=True)
class CitationCandidate:
    """One retrieved chunk offered to the model as a citable source."""

    number: int
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_filename: str
    page_number: int | None = None
    section_path: str | None = None
    snippet: str | None = None

    def reference_line(self, number: int | None = None) -> str:
        """Render a Chicago-style reference entry from chunk metadata only."""
        parts = [self.document_title]
        if self.section_path:
            parts.append(self.section_path)
        if self.page_number is not None:
            parts.append(f"p. {self.page_number}")
        return f"{number or self.number}. {', '.join(parts)}."


@dataclass(slots=True)
class PresentedAnswer:
    """A model answer converted into user-facing text plus validated citations."""

    display_text: str
    plain_text: str
    citations: list[CitationCandidate] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    dropped_markers: list[int] = field(default_factory=list)
    is_no_answer: bool = False

    @property
    def has_support(self) -> bool:
        return bool(self.citations)


def build_citation_candidates(chunks: list[RetrievalCandidate]) -> list[CitationCandidate]:
    """Enumerate retrieved chunks as the only citable sources, numbered from 1."""
    candidates: list[CitationCandidate] = []
    seen: set[UUID] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        candidates.append(
            CitationCandidate(
                number=len(candidates) + 1,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=document_display_title(chunk.document_filename),
                document_filename=chunk.document_filename,
                page_number=chunk.page_number,
                section_path=chunk.section_path,
                snippet=citation_snippet(chunk.content),
            )
        )
    return candidates


def present_answer(raw_answer: str, candidates: list[CitationCandidate]) -> PresentedAnswer:
    """Apply writing-style rules and render validated sentence-end citations.

    Markers are moved to the end of the sentence they support *first*, so that every
    later step can split sentences reliably: a model that writes "5 ml [cite:1]." leaves
    no whitespace after the period, which would otherwise hide the sentence boundary.
    """
    text = _MARKER_BEFORE_PUNCTUATION.sub(
        lambda match: match.group(2) + match.group(1).strip(),
        raw_answer.strip(),
    )
    text = strip_leading_source_prefix(text, candidates)
    text = _strip_internal_details(text)
    text = _collapse_repeated_sentences(text)

    plain_text = _normalize_whitespace(_MARKER_RUN.sub("", text))
    if is_no_answer(plain_text):
        return PresentedAnswer(
            display_text=NO_ANSWER_MESSAGE,
            plain_text=NO_ANSWER_MESSAGE,
            is_no_answer=True,
        )

    by_number = {candidate.number: candidate for candidate in candidates}
    renumbered: dict[int, int] = {}
    dropped: list[int] = []
    for raw_id in (int(value) for value in _MARKER_ID.findall(text)):
        if raw_id not in by_number:
            if raw_id not in dropped:
                dropped.append(raw_id)
            continue
        renumbered.setdefault(raw_id, len(renumbered) + 1)

    display_text = _normalize_whitespace(
        _MARKER_RUN.sub(lambda match: _render_marker_run(match.group(0), renumbered), text)
    )

    citations = [
        CitationCandidate(
            number=new_number,
            chunk_id=by_number[raw_id].chunk_id,
            document_id=by_number[raw_id].document_id,
            document_title=by_number[raw_id].document_title,
            document_filename=by_number[raw_id].document_filename,
            page_number=by_number[raw_id].page_number,
            section_path=by_number[raw_id].section_path,
            snippet=by_number[raw_id].snippet,
        )
        for raw_id, new_number in sorted(renumbered.items(), key=lambda item: item[1])
    ]
    return PresentedAnswer(
        display_text=display_text,
        plain_text=plain_text,
        citations=citations,
        references=[citation.reference_line() for citation in citations],
        dropped_markers=dropped,
    )


def strip_leading_source_prefix(answer: str, candidates: list[CitationCandidate]) -> str:
    """Remove document-name openings so the answer starts with the answer."""
    names = _source_names(candidates)
    text = answer.strip()
    for _ in range(3):  # peel at most three layered openings, then stop.
        stripped = _strip_one_opening(text, names)
        if stripped == text:
            break
        text = stripped
    return _recapitalize(text)


def is_no_answer(answer: str) -> bool:
    """Return whether the model said the corpus does not support an answer."""
    lowered = answer.strip().lower()
    if not lowered:
        return False
    return any(signal in lowered for signal in _NO_ANSWER_SIGNALS)


def document_display_title(filename: str) -> str:
    """Derive a readable document title from a stored filename."""
    stem = re.sub(r"\.(?:%s)$" % "|".join(_FILE_EXTENSIONS), "", filename.strip(), flags=re.IGNORECASE)
    spaced = re.sub(r"[_\-]+", " ", stem)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    if not spaced:
        return filename
    if spaced == spaced.lower():
        return spaced.title()
    return spaced


def citation_snippet(content: str, limit: int = 240) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}..."


def _render_marker_run(run: str, renumbered: dict[int, int]) -> str:
    numbers: list[int] = []
    for raw_id in (int(value) for value in _MARKER_ID.findall(run)):
        mapped = renumbered.get(raw_id)
        if mapped is not None and mapped not in numbers:
            numbers.append(mapped)
    if not numbers:
        return ""
    return "".join(str(number).translate(_SUPERSCRIPT_DIGITS) for number in sorted(numbers))


def _source_names(candidates: list[CitationCandidate]) -> frozenset[str]:
    names = set(_GENERIC_SOURCE_NAMES)
    for candidate in candidates:
        for value in (candidate.document_filename, candidate.document_title):
            normalized = _normalize_source_name(value)
            if normalized:
                names.add(normalized)
    return frozenset(names)


def _normalize_source_name(value: str) -> str:
    stem = re.sub(r"\.(?:%s)$" % "|".join(_FILE_EXTENSIONS), "", value.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", stem.lower())).strip()


def _strip_one_opening(text: str, names: frozenset[str]) -> str:
    match = _FILENAME_OPENING.match(text)
    if match:
        return text[match.end() :].lstrip()

    for pattern in (_PREAMBLE_OPENING, _NAME_DELIMITER_OPENING):
        match = pattern.match(text)
        if match and _normalize_source_name(match.group("source")) in names:
            remainder = text[match.end() :].lstrip()
            if remainder:
                return remainder
    return text


def _split_sentences(line: str) -> list[str]:
    """Split a line into sentences, keeping trailing citation markers attached.

    A sentence ends at `.`/`!`/`?` plus any markers that follow it, but only when
    whitespace or end-of-line comes next, so "5 ml. per dose" is not cut mid-clause.
    """
    sentences: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?](?:[ \t]*\[cite:\s*\d{1,3}\s*\])*", line):
        end = match.end()
        if end < len(line) and not line[end].isspace():
            continue
        sentence = line[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    tail = line[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _rewrite_lines(text: str, transform: Callable[[list[str]], list[str]]) -> str:
    """Apply a sentence-list transform per line, preserving paragraphs and bullets."""
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        bullet = re.match(r"^(?:[-*•]\s+|\d+[.)]\s+)", stripped)
        prefix = bullet.group(0) if bullet else ""
        kept = transform(_split_sentences(stripped[len(prefix) :]))
        body = " ".join(sentence for sentence in kept if sentence.strip())
        if body:
            lines.append(f"{prefix}{body}")
    return "\n".join(lines)


def _strip_internal_details(text: str) -> str:
    """Drop whole sentences that leak retrieval internals.

    Deleting only the offending tokens leaves fragments like "This answer is based
    on and", so the sentence is removed instead.
    """
    return _rewrite_lines(
        text,
        lambda sentences: [s for s in sentences if not _INTERNAL_DETAIL.search(s)],
    )


def _collapse_repeated_sentences(text: str) -> str:
    """Remove a caveat repeated verbatim, preserving paragraph and bullet structure."""
    seen: set[str] = set()

    def dedupe(sentences: list[str]) -> list[str]:
        kept: list[str] = []
        for sentence in sentences:
            key = _MARKER_RUN.sub("", sentence).strip().lower()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            kept.append(sentence)
        return kept

    return _rewrite_lines(text, dedupe)


def _normalize_whitespace(text: str) -> str:
    collapsed = re.sub(r"[ \t]+", " ", text)
    collapsed = re.sub(r" +([.,;:!?])", r"\1", collapsed)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def _recapitalize(text: str) -> str:
    if text and text[0].islower():
        return text[0].upper() + text[1:]
    return text
