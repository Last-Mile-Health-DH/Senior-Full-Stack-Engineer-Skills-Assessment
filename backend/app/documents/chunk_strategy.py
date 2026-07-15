"""Per-document chunking strategy selection.

The ingestion agent already assesses every page (headings, tables, figures, text yield).
This module turns that assessment into an explicit decision about HOW to chunk, instead of
running one strategy over every document and hoping it fits.

Why this matters:

- A **structured** document (WHO chart booklets, clinical protocols) carries meaning in its
  hierarchy. A dose table split across two chunks is worse than useless — half a dose table
  is a wrong dose. Section headings are the strongest retrieval signal such a document has,
  so chunks are cut on structure boundaries, tables are kept whole, and each chunk carries
  its section path.

- An **unstructured** document (scanned prose, an OCR'd letter, a flat report) has no
  hierarchy to preserve. Cutting it on "structure" invents boundaries that are not there,
  and prefixing a spurious section path onto every chunk adds noise to the very text used
  for retrieval. Fixed-size chunks with overlap are the right tool: the overlap is what
  stops a fact being severed at a boundary.

The decision is recorded on `documents.metadata` so a reviewer can see which strategy each
document actually got, rather than having to infer it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.documents.chunking import StructuredBlock

logger = logging.getLogger(__name__)


class ChunkStrategy(str, Enum):
    STRUCTURE_AWARE = "structure_aware"
    FIXED_SIZE = "fixed_size"


# A document needs enough headings to be *navigable*, not just to contain a bold line. One
# heading in a 200-page scan is noise; a heading every few pages is a real hierarchy.
MIN_HEADINGS = 3
MIN_HEADINGS_PER_PAGE = 0.05

# Overlap for the unstructured path. The brief calls for 10-20%; 15% is the midpoint and is
# what the fixed-size path uses. Overlap is what stops a fact being cut in half at a chunk
# boundary when there is no structure to cut on instead.
FIXED_OVERLAP_RATIO = 0.15


@dataclass(frozen=True, slots=True)
class StructureProfile:
    """What the ingestion agent found in the document."""

    page_count: int
    heading_count: int
    table_count: int
    figure_count: int
    ocr_page_count: int

    @property
    def headings_per_page(self) -> float:
        if self.page_count <= 0:
            return 0.0
        return self.heading_count / self.page_count

    @property
    def has_navigable_hierarchy(self) -> bool:
        return (
            self.heading_count >= MIN_HEADINGS
            and self.headings_per_page >= MIN_HEADINGS_PER_PAGE
        )


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    """The chosen strategy plus the reason, which is persisted for the reviewer."""

    strategy: ChunkStrategy
    overlap_ratio: float
    reason: str
    profile: StructureProfile

    def as_metadata(self) -> dict[str, object]:
        return {
            "chunk_strategy": self.strategy.value,
            "chunk_overlap_ratio": self.overlap_ratio,
            "chunk_strategy_reason": self.reason,
            "structure": {
                "pages": self.profile.page_count,
                "headings": self.profile.heading_count,
                "tables": self.profile.table_count,
                "figures": self.profile.figure_count,
                "ocr_pages": self.profile.ocr_page_count,
            },
        }


def profile_blocks(blocks: list[StructuredBlock], page_count: int) -> StructureProfile:
    """Summarize what structure the ingestion agent actually detected."""
    pages = page_count or len({block.page_number for block in blocks}) or 1
    return StructureProfile(
        page_count=pages,
        heading_count=sum(1 for block in blocks if block.block_type == "heading"),
        table_count=sum(1 for block in blocks if block.block_type == "table"),
        figure_count=sum(1 for block in blocks if block.block_type == "figure"),
        ocr_page_count=0,
    )


def select_strategy(profile: StructureProfile, default_overlap: float) -> ChunkPlan:
    """Choose the chunking strategy for one document.

    Tables dominate the decision. In clinical guidance a table IS the answer — a dosage
    chart, a classification grid — and splitting one on a token boundary produces a chunk
    that reads like a dose but is not one. Any table at all is therefore enough to require
    the structure-aware path, regardless of how few headings the document has.
    """
    if profile.table_count > 0:
        return ChunkPlan(
            strategy=ChunkStrategy.STRUCTURE_AWARE,
            overlap_ratio=default_overlap,
            reason=(
                f"{profile.table_count} table(s) detected; tables are kept whole because "
                "half a dose table is a wrong dose"
            ),
            profile=profile,
        )

    if profile.has_navigable_hierarchy:
        return ChunkPlan(
            strategy=ChunkStrategy.STRUCTURE_AWARE,
            overlap_ratio=default_overlap,
            reason=(
                f"{profile.heading_count} headings across {profile.page_count} pages "
                f"({profile.headings_per_page:.2f}/page); section paths are a strong "
                "retrieval signal"
            ),
            profile=profile,
        )

    return ChunkPlan(
        strategy=ChunkStrategy.FIXED_SIZE,
        overlap_ratio=FIXED_OVERLAP_RATIO,
        reason=(
            f"no tables and only {profile.heading_count} heading(s) across "
            f"{profile.page_count} pages; cutting on absent structure would invent "
            "boundaries, so fixed-size chunks with overlap are used instead"
        ),
        profile=profile,
    )


def flatten_for_fixed_size(blocks: list[StructuredBlock]) -> list[StructuredBlock]:
    """Strip structure from the blocks so the fixed-size path cannot re-introduce it.

    The chunker prefixes each chunk with its section path. On a document with no real
    hierarchy that prefix is invented context: it pollutes the chunk text that retrieval
    and grounding both read. Flattening to plain per-page text blocks is what makes
    "fixed-size" actually fixed-size rather than structure-aware with fewer headings.
    """
    flattened: list[StructuredBlock] = []
    for block in blocks:
        if block.block_type == "heading":
            # Keep the words (they are still content) but not the hierarchy role.
            flattened.append(
                StructuredBlock(
                    content=block.content,
                    page_number=block.page_number,
                    block_type="text",
                    section_path=None,
                )
            )
            continue
        flattened.append(
            StructuredBlock(
                content=block.content,
                page_number=block.page_number,
                block_type="text" if block.block_type != "table" else "table",
                section_path=None,
            )
        )
    return flattened
