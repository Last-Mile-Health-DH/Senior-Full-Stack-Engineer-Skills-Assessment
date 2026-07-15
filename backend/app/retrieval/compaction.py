"""Deterministic context compaction for generation assembly."""

from __future__ import annotations

import re

SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]?")
TERM_PATTERN = re.compile(r"[A-Za-z0-9]+")


def compact_chunk(query: str, text: str, max_tokens: int = 120) -> str:
    """Select query-overlapping sentences within a word-token budget."""
    budget = max(1, max_tokens)
    sentences = [match.group(0).strip() for match in SENTENCE_PATTERN.finditer(text) if match.group(0).strip()]
    if not sentences:
        return _first_tokens(text, budget)

    query_terms = _terms(query)
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        overlap = len(query_terms & _terms(sentence))
        if overlap > 0:
            scored.append((index, overlap, sentence))

    if not scored:
        return _first_tokens(text, budget)

    selected: list[tuple[int, str]] = []
    used = 0
    for index, _, sentence in sorted(scored, key=lambda item: (-item[1], item[0])):
        token_count = _token_count(sentence)
        if token_count > budget:
            sentence = _first_tokens(sentence, budget)
            token_count = _token_count(sentence)
        if used + token_count <= budget:
            selected.append((index, sentence))
            used += token_count
        if used >= budget:
            break

    return " ".join(sentence for _, sentence in sorted(selected, key=lambda item: item[0])).strip()


def _terms(value: str) -> set[str]:
    return {match.group(0).lower() for match in TERM_PATTERN.finditer(value)}


def _token_count(value: str) -> int:
    return len(value.split())


def _first_tokens(value: str, max_tokens: int) -> str:
    return " ".join(value.split()[:max_tokens])
