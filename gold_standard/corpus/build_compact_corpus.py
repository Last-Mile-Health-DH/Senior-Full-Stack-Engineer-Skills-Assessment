"""Deterministically generate the compact gold-evaluation corpus.

Why this exists
---------------
The authentic WHO corpus (IMCI chart booklet, hospital pocket book, community manual) totals
~659 pages. Indexing it end-to-end on a free-tier hosted embedding key is not reproducible:
the per-day embedding quota is exhausted long before the corpus finishes, and OCR of the
scanned booklet takes many minutes per document. A reviewer cannot run the gold eval that way.

This module builds a tiny, fully deterministic corpus instead — four short PDFs, each chosen
to force a *different* branch of the ingestion pipeline, so the eval exercises how the system
dynamically processes different document types while staying far inside the app's limits
(65 MB / 700 pages). The real WHO manifest is preserved alongside as `corpus_manifest.who.yaml`
for anyone who wants to run against the originals.

The four documents and the pipeline branch each is designed to trigger
--------------------------------------------------------------------
1. dosing_tables.pdf        — ruled tables, native text   -> structure-aware chunking (table)
                                                              + table-page image rasterization
2. referral_guidance.pdf    — flowing prose, no structure -> fixed-size chunking + overlap
3. treatment_protocol.pdf   — numbered heading hierarchy  -> structure-aware chunking (hierarchy)
4. scanned_dosing_card.pdf  — image only, no text layer   -> OCR fallback extraction

Determinism
-----------
`reportlab.rl_config.invariant = 1` removes the creation timestamp and the random document id,
so identical inputs produce byte-identical PDFs. The content is authored here (not scraped), so
every gold answer is grounded by construction — the expected facts are exactly what the tables
and paragraphs below say.

Clinical values follow the WHO IMCI framework (oral amoxicillin >=40 mg/kg twice daily for
5 days for fast-breathing pneumonia; zinc for diarrhoea; urgent-referral danger signs). They are
teaching values for a retrieval test, not a dosing authority.

Build:  pip install reportlab pillow  &&  python -m gold_standard.corpus.build_compact_corpus
(Pillow already ships in the backend image for OCR; only reportlab is an extra build dependency.)
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab import rl_config

# Byte-for-byte reproducible output: no embedded timestamp, no random /ID. Must be set before
# other reportlab modules read it.
rl_config.invariant = 1

from reportlab.lib import colors  # noqa: E402

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT_DIR = Path(__file__).resolve().parent / "files"


def _table(data: list[list[str]]) -> Table:
    """A grid-ruled table so pdfplumber detects it and the chunker goes structure-aware."""
    table = Table(data, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e1f2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_dosing_tables(path: Path) -> None:
    """Doc 1 — table-structured, native text. Forces structure-aware (table) chunking."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Paediatric Dosing Reference")
    # One table per page. With several ruled tables on a single page, pdfplumber can interleave
    # rows from adjacent tables, and a chunk that mixes the amoxicillin header with a paracetamol
    # row is exactly how a dose gets misread. A page break per table keeps each dosing table
    # whole in its own structure-aware chunk — strict table integrity is the whole point.
    story = [
        Paragraph("Paediatric Dosing Reference (Outpatient)", styles["Title"]),
        Spacer(1, 6 * mm),
        Paragraph("Table 1. Amoxicillin for fast-breathing pneumonia (250 mg tablet or 250 mg/5 ml syrup).", styles["Heading3"]),
        _table(
            [
                ["Weight", "Age", "Amoxicillin tablets", "Syrup", "Frequency", "Duration"],
                ["4 to under 10 kg", "2 up to 12 months", "1 tablet (250 mg)", "5 ml", "Twice daily", "5 days"],
                ["10 to under 14 kg", "12 months up to 3 years", "2 tablets (500 mg)", "10 ml", "Twice daily", "5 days"],
                ["14 to 19 kg", "3 up to 5 years", "3 tablets (750 mg)", "15 ml", "Twice daily", "5 days"],
            ]
        ),
        PageBreak(),
        Paragraph("Table 2. Zinc for diarrhoea (20 mg dispersible tablet).", styles["Heading3"]),
        _table(
            [
                ["Age", "Zinc dose", "Frequency", "Duration"],
                ["2 up to 6 months", "Half a 20 mg tablet", "Once daily", "14 days"],
                ["6 months up to 5 years", "One 20 mg tablet", "Once daily", "14 days"],
            ]
        ),
        PageBreak(),
        Paragraph("Table 3. Paracetamol for high fever (each dose, every 6 hours as needed).", styles["Heading3"]),
        _table(
            [
                ["Weight", "Age", "Paracetamol dose", "Frequency"],
                ["4 to under 10 kg", "2 up to 12 months", "60 mg", "Every 6 hours"],
                ["10 to 19 kg", "1 up to 5 years", "125 mg", "Every 6 hours"],
            ]
        ),
    ]
    doc.build(story)


def build_referral_guidance(path: Path) -> None:
    """Doc 2 — unstructured prose, no tables and no heading hierarchy. Forces fixed-size chunking."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=11, leading=16, spaceAfter=10)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Recognising a Sick Child Who Needs Referral")
    paras = [
        "Recognising a sick child who needs urgent referral",
        "A community health worker cannot treat every illness at home, and part of caring for a "
        "sick child is knowing when the child is too unwell to stay in the community. Certain "
        "signs mean the child could become seriously ill or die without hospital care, and they "
        "are the same whatever the child came in for.",
        "A child who is not able to drink or breastfeed at all, or who vomits everything that is "
        "given, cannot keep down the fluids and medicines needed to recover and must be referred "
        "to hospital urgently. A child who has had a convulsion during this illness, or who is "
        "unusually sleepy, difficult to wake, lethargic, or unconscious, is also showing a general "
        "danger sign and needs to be seen at a hospital without delay.",
        "Before the child leaves for the hospital, give the first dose of an appropriate antibiotic "
        "if one is indicated, keep the child warm, and encourage the mother to continue breastfeeding "
        "on the way if the child is able to feed. Explain to the family why the referral is urgent, "
        "help them arrange transport, and write down what treatment has already been given so the "
        "hospital team can continue care without repeating or missing a dose.",
        "Referral is not a failure of home care. It is the safest decision when a danger sign is "
        "present, and acting quickly on these signs is one of the most important ways a health "
        "worker protects a child's life.",
    ]
    story = [Paragraph(paras[0], styles["Title"]), Spacer(1, 6 * mm)]
    story += [Paragraph(text, body) for text in paras[1:]]
    doc.build(story)


def build_treatment_protocol(path: Path) -> None:
    """Doc 3 — numbered heading hierarchy, no tables. Forces structure-aware (hierarchy) chunking."""
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Heading2"], fontSize=14, spaceBefore=10, spaceAfter=6)
    hh = ParagraphStyle("hh", parent=styles["Heading3"], fontSize=12, spaceBefore=6, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=11, leading=15, spaceAfter=8)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Outpatient Management Protocol: Cough or Difficult Breathing")
    story = [
        Paragraph("Outpatient Management Protocol: Cough or Difficult Breathing", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph("1. Assessment", h),
        Paragraph(
            "Ask how long the child has had cough, and count the breaths in one minute while the "
            "child is calm. Look for chest indrawing and for any general danger sign.",
            body,
        ),
        Paragraph("2. Classification", h),
        Paragraph(
            "Fast breathing without chest indrawing or a danger sign is classified as pneumonia. "
            "Chest indrawing or any general danger sign is classified as severe pneumonia.",
            body,
        ),
        Paragraph("3. Treatment", h),
        Paragraph("3.1 Pneumonia (non-severe)", hh),
        Paragraph(
            "Treat at home with oral amoxicillin twice daily for 5 days at the dose for the child's "
            "weight, and advise the family on when to return immediately.",
            body,
        ),
        Paragraph("3.2 Severe pneumonia", hh),
        Paragraph(
            "Give the first dose of amoxicillin and refer the child urgently to hospital for oxygen "
            "and injectable antibiotics.",
            body,
        ),
        Paragraph("4. Follow-up", h),
        Paragraph(
            "Ask the family to bring a child treated for pneumonia back for reassessment after 3 days. "
            "If the child is breathing faster, is unable to drink, or has developed a danger sign, "
            "refer urgently. If the child is improving, complete the full 5-day course.",
            body,
        ),
    ]
    doc.build(story)


def build_scanned_dosing_card(path: Path) -> None:
    """Doc 4 — an image of text with no text layer. Forces the OCR fallback path.

    The page is drawn as a rasterised image (via Pillow) and placed with drawImage only, so the
    PDF carries no extractable text and the ingestion agent must OCR it to recover the content.
    """
    from PIL import Image, ImageDraw, ImageFont

    scale = 2  # render at 2x for legible OCR
    width, height = 1240, 1754  # A4 at ~150 dpi
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    def font(size: int):
        for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    lines = [
        ("QUICK REFERENCE CARD", 54, 90),
        ("Oral Rehydration and Vitamin A", 40, 180),
        ("", 20, 240),
        ("Oral rehydration solution (ORS):", 36, 300),
        ("Give 10 ml/kg of ORS after each loose stool.", 34, 360),
        ("Continue breastfeeding between drinks.", 34, 415),
        ("", 20, 470),
        ("Vitamin A supplementation:", 36, 530),
        ("6 up to 12 months: 100 000 IU as a single dose.", 34, 590),
        ("12 months and older: 200 000 IU as a single dose.", 34, 645),
        ("", 20, 700),
        ("Zinc reduces the duration of diarrhoea and is", 34, 760),
        ("given daily for 14 days alongside ORS.", 34, 815),
    ]
    for text, size, y in lines:
        if text:
            draw.text((110, y), text, fill="black", font=font(size))

    # Save the raster straight to a single-page PDF via Pillow. This produces an image-only
    # page (no text layer, so ingestion must OCR it) and, unlike reportlab's image re-encoding,
    # is byte-deterministic once the creation-date metadata is removed below.
    image.save(str(path), "PDF", resolution=150.0)
    _strip_pdf_dates(path)


def _strip_pdf_dates(path: Path) -> None:
    """Pin Pillow's non-deterministic /CreationDate so repeated builds are byte-identical.

    Only the 14 date digits are overwritten, with a fixed value of identical length, so no byte
    offset shifts and the PDF cross-reference table stays valid.
    """
    raw = path.read_bytes()
    raw = re.sub(rb"D:\d{14}", b"D:20000101000000", raw)
    path.write_bytes(raw)


BUILDERS = {
    "dosing_tables.pdf": build_dosing_tables,
    "referral_guidance.pdf": build_referral_guidance,
    "treatment_protocol.pdf": build_treatment_protocol,
    "scanned_dosing_card.pdf": build_scanned_dosing_card,
}


def build_all(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, builder in BUILDERS.items():
        target = out_dir / filename
        builder(target)
        written.append(target)
        print(f"  wrote {target.relative_to(out_dir.parent.parent)} ({target.stat().st_size} bytes)")
    return written


if __name__ == "__main__":
    print("Building compact gold-evaluation corpus:")
    build_all()
    print("Done.")
