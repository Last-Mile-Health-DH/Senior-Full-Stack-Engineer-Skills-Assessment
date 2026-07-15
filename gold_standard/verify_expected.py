#!/usr/bin/env python3
"""Print source context for human verification of gold expected answers."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

import yaml

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect source pages for gold expected-answer verification.")
    parser.add_argument("--question-id", help="only inspect one question id")
    parser.add_argument("--search", action="store_true", help="search for expected facts when expected_page is unset")
    parser.add_argument("--context-chars", type=int, default=700)
    args = parser.parse_args()

    questions = yaml.safe_load((HERE / "questions.yaml").read_text())["questions"]
    manifest = yaml.safe_load((HERE / "corpus" / "corpus_manifest.yaml").read_text())
    docs = {doc["id"]: doc for doc in manifest["documents"]}

    selected = [q for q in questions if not args.question_id or q["id"] == args.question_id]
    if args.question_id and not selected:
        raise SystemExit(f"unknown question id: {args.question_id}")

    for question in selected:
        _print_question(question, docs, search=args.search, context_chars=args.context_chars)
    return 0


def _print_question(question: dict, docs: dict[str, dict], *, search: bool, context_chars: int) -> None:
    print("\n" + "=" * 88)
    print(f"{question['id']} [{question.get('category')}] verified={question.get('verified')}")
    print(f"Q: {question.get('question')}")
    print(f"Expected: {question.get('expected_answer')}")
    print(f"Facts: {', '.join(str(fact) for fact in question.get('expected_facts') or [])}")

    source_doc = question.get("source_doc")
    if source_doc is None:
        print("Source: refusal/negative question; verify that no corpus document should answer it.")
        return

    doc = docs[source_doc]
    pdf_path = HERE / "corpus" / "files" / doc["filename"]
    print(f"Source: {source_doc} ({pdf_path})")
    if not pdf_path.exists():
        print("PDF missing. Run: python -m gold_standard.fetch_corpus")
        return

    page_spec = question.get("expected_page")
    if page_spec is not None:
        for page_number in _page_numbers(page_spec):
            print(_page_context(pdf_path, page_number, context_chars))
        return

    if search:
        for snippet in _search_facts(pdf_path, question.get("expected_facts") or [], context_chars):
            print(snippet)
    else:
        print("expected_page is unset. Re-run with --search to locate candidate source context.")


def _page_numbers(page_spec: int | str) -> Iterable[int]:
    if isinstance(page_spec, int):
        yield page_spec
        return
    if isinstance(page_spec, str) and "-" in page_spec:
        lo, hi = (int(part) for part in page_spec.split("-", 1))
        yield from range(lo, hi + 1)
        return
    yield int(page_spec)


def _page_context(pdf_path: Path, page_number: int, context_chars: int) -> str:
    text = _extract_page(pdf_path, page_number)
    return f"\n--- page {page_number} ---\n{text[:context_chars].strip()}"


def _search_facts(pdf_path: Path, facts: list[str], context_chars: int) -> list[str]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - exercised only outside backend image.
        raise SystemExit("pdfplumber is required for --search; run inside the backend image or install test deps") from exc

    snippets: list[str] = []
    patterns = [_fact_pattern(fact) for fact in facts if str(fact).strip()]
    with pdfplumber.open(str(pdf_path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            normalized = re.sub(r"\s+", " ", text)
            if not normalized:
                continue
            if not patterns or any(pattern.search(normalized) for pattern in patterns):
                snippets.append(f"\n--- candidate page {index} ---\n{normalized[:context_chars].strip()}")
            if len(snippets) >= 5:
                break
    return snippets or ["No candidate pages found for expected facts."]


def _extract_page(pdf_path: Path, page_number: int) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - exercised only outside backend image.
        raise SystemExit("pdfplumber is required; run inside the backend image or install test deps") from exc

    with pdfplumber.open(str(pdf_path)) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            return f"page {page_number} is outside PDF page range 1..{len(pdf.pages)}"
        return page.extract_text() or ""


def _fact_pattern(fact: str) -> re.Pattern[str]:
    escaped = re.escape(str(fact).replace("\u00bd", "1/2"))
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\-", r"[-\s]*(?:to\s+)?")
    return re.compile(escaped, re.IGNORECASE)


if __name__ == "__main__":
    raise SystemExit(main())
