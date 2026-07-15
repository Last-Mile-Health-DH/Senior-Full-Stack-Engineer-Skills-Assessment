"""Dynamic chunking-strategy selection."""

from __future__ import annotations

from app.documents.chunk_strategy import (
    FIXED_OVERLAP_RATIO,
    ChunkStrategy,
    flatten_for_fixed_size,
    profile_blocks,
    select_strategy,
)
from app.documents.chunking import StructuredBlock, chunk_structured_blocks


def _block(kind: str, page: int, content: str = "text") -> StructuredBlock:
    return StructuredBlock(content=content, page_number=page, block_type=kind)


def test_a_single_table_forces_the_structure_aware_path() -> None:
    """In clinical guidance the table IS the answer.

    A dose table split on a token boundary produces a chunk that reads like a dose but is
    not one, so any table at all is enough — regardless of how few headings there are.
    """
    blocks = [_block("table", 1, "Age | Dose\nChild | 5 ml")] + [
        _block("paragraph", page) for page in range(1, 40)
    ]

    plan = select_strategy(profile_blocks(blocks, page_count=40), default_overlap=0.15)

    assert plan.strategy is ChunkStrategy.STRUCTURE_AWARE
    assert "table" in plan.reason.lower()


def test_a_navigable_hierarchy_selects_structure_aware() -> None:
    blocks = [_block("heading", page, f"Chapter {page}") for page in range(1, 8)] + [
        _block("paragraph", page) for page in range(1, 8)
    ]

    plan = select_strategy(profile_blocks(blocks, page_count=10), default_overlap=0.15)

    assert plan.strategy is ChunkStrategy.STRUCTURE_AWARE
    assert "heading" in plan.reason.lower()


def test_a_structureless_scan_selects_fixed_size_with_overlap() -> None:
    """Cutting on absent structure invents boundaries that are not in the document."""
    blocks = [_block("paragraph", page) for page in range(1, 60)]

    plan = select_strategy(profile_blocks(blocks, page_count=60), default_overlap=0.15)

    assert plan.strategy is ChunkStrategy.FIXED_SIZE
    # The brief calls for 10-20% overlap on the unstructured path.
    assert 0.10 <= plan.overlap_ratio <= 0.20
    assert plan.overlap_ratio == FIXED_OVERLAP_RATIO


def test_one_stray_heading_in_a_long_scan_is_not_a_hierarchy() -> None:
    """A single bold line in a 200-page scan is noise, not navigation."""
    blocks = [_block("heading", 1, "Report")] + [
        _block("paragraph", page) for page in range(1, 200)
    ]

    plan = select_strategy(profile_blocks(blocks, page_count=200), default_overlap=0.15)

    assert plan.strategy is ChunkStrategy.FIXED_SIZE


def test_the_decision_is_recorded_for_the_reviewer() -> None:
    blocks = [_block("table", 1, "Age | Dose")]

    metadata = select_strategy(
        profile_blocks(blocks, page_count=1), default_overlap=0.15
    ).as_metadata()

    assert metadata["chunk_strategy"] == "structure_aware"
    assert metadata["chunk_strategy_reason"]
    assert metadata["structure"]["tables"] == 1


def test_flattening_strips_the_section_path_the_fixed_path_must_not_invent() -> None:
    """The chunker prefixes each chunk with its section path.

    On a document with no real hierarchy that prefix is invented context, and it pollutes
    the exact text that retrieval and grounding both read.
    """
    blocks = [
        StructuredBlock(content="Introduction", page_number=1, block_type="heading"),
        StructuredBlock(
            content="The patient was seen in clinic.",
            page_number=1,
            block_type="paragraph",
            section_path="Introduction",
        ),
    ]

    flattened = flatten_for_fixed_size(blocks)
    chunks = chunk_structured_blocks(flattened, overlap_ratio=FIXED_OVERLAP_RATIO)

    assert all(block.section_path is None for block in flattened)
    assert all(chunk.section_path is None for chunk in chunks)
    # The heading's words survive as content; only its structural role is dropped.
    joined = " ".join(chunk.content for chunk in chunks)
    assert "Introduction" in joined
    assert not joined.startswith("Introduction\n\n")


def test_a_table_survives_flattening_because_it_is_still_a_table() -> None:
    """Fixed-size is about absent hierarchy, not about shredding a table that does exist."""
    blocks = [StructuredBlock(content="Age | Dose", page_number=1, block_type="table")]

    flattened = flatten_for_fixed_size(blocks)

    assert flattened[0].block_type == "table"


def test_fixed_size_chunks_stay_inside_the_token_budget_with_overlap() -> None:
    """The overlap is the whole point of the fixed-size path.

    With no structure to cut on, a fact severed at a chunk boundary is simply lost to
    retrieval. Overlap is what gives it a second chance to survive intact in a neighbour.
    """
    long_prose = " ".join(f"word{i}" for i in range(2000))
    blocks = flatten_for_fixed_size(
        [StructuredBlock(content=long_prose, page_number=1, block_type="paragraph")]
    )

    chunks = chunk_structured_blocks(
        blocks, chunk_size_tokens=100, overlap_ratio=FIXED_OVERLAP_RATIO
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content.split()) <= 100

    # Consecutive chunks must share tokens, or there is no overlap at all.
    first = chunks[0].content.split()
    second = chunks[1].content.split()
    assert set(first) & set(second), "fixed-size chunks must overlap"
