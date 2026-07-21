"""iter90 — Shared signature + stamp Flowable for every PDF the platform
issues (client history, VIP closing, admin audit, revenue analytics).

Renders a light off-white panel at the bottom of the last page that
holds the Resilience Brothers signature ("O Bry") on the left and the
company stamp ("Resilience Brothers FZ-LLC · RAK - U.A.E.") on the
right, so both remain legible on top of the dark report backgrounds.

Callers pass `lang` for label localisation and (optionally)
`show_client_side=True` when a formal client conformity line is
required (VIP daily closing). The block is a single Table Flowable so
it composes cleanly into any `SimpleDocTemplate.build(story)` pipeline.
"""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, Table, TableStyle


ASSETS = Path(__file__).parent / "assets"
# iter94 — signature.png is the clean vector-quality "O Bry" signature
# extracted from the operator's reference PDF (546x237 RGBA with an
# alpha channel, so it composites cleanly on the off-white panel).
SIG_PATH = ASSETS / "signature.png"
STAMP_PATH = ASSETS / "stamp.png"

_PANEL_LIGHT = colors.HexColor("#F5F5F0")  # off-white paper tone
_TEXT_DARK = colors.HexColor("#14101F")
_TEXT_MUTED = colors.HexColor("#525252")
_BORDER = colors.HexColor("#8B5CF6")


def _lbl(en: str, es: str, lang: str) -> str:
    return en if (lang or "").lower().startswith("en") else es


def _sig_cell(lang: str):
    """iter94 — Left column: signature image only, no personal name.

    The operator asked us to drop the incorrect "O'Brayan Fibla — Managing
    Partner" line and leave *just* the signature + stamp as the legal
    proof. The signature.png ships with a transparent alpha channel so
    it lands cleanly on the off-white panel; we still fall back to a
    plain underscore line if the asset was removed during a restore.
    """
    styles = getSampleStyleSheet()
    label = ParagraphStyle(
        "sig_label", parent=styles["Normal"], textColor=_TEXT_MUTED,
        fontSize=7.5, leading=10, fontName="Helvetica-Bold",
        alignment=0, spaceBefore=6,
    )
    parts: list = []
    if SIG_PATH.exists():
        try:
            # iter94b — signature dimensions shrunk (2.2×0.95 → 1.4×0.6)
            # so the round corporate seal remains the visual anchor of
            # the legal block, matching the reference example where the
            # signature sits noticeably smaller than the stamp.
            parts.append(Image(str(SIG_PATH), width=1.4 * inch, height=0.6 * inch))
        except Exception:
            parts.append(Paragraph("<font color='#888'>__________________</font>", label))
    else:
        parts.append(Paragraph("<font color='#888'>__________________</font>", label))
    parts.append(Paragraph(
        _lbl("Signature & Seal", "Firma / Sello", lang),
        label,
    ))
    return parts


def _stamp_cell():
    """Center-ish column: circular stamp image.

    iter94 — bumped from 1.05" → 1.4" since the operator asked to
    make the seal + signature the visual focus of the block. The
    new stamp source is 753×641 (near-square) so aspect stays true."""
    if STAMP_PATH.exists():
        try:
            return Image(str(STAMP_PATH), width=1.4 * inch, height=1.4 * inch)
        except Exception:
            pass
    return Paragraph("<font color='#888'>[STAMP]</font>",
                     getSampleStyleSheet()["Normal"])


def _client_cell(lang: str, client_name: str = ""):
    """Right column: client conformity signature line."""
    styles = getSampleStyleSheet()
    label = ParagraphStyle(
        "cl_label", parent=styles["Normal"], textColor=_TEXT_MUTED,
        fontSize=7.5, leading=10, fontName="Helvetica-Bold",
    )
    name = ParagraphStyle(
        "cl_name", parent=styles["Normal"], textColor=_TEXT_DARK,
        fontSize=8.5, leading=11, fontName="Helvetica-Bold",
    )
    parts = [
        Paragraph("<font color='#888888'>_________________________</font>", label),
        Paragraph(_lbl("Client — Conformity", "Cliente — Conformidad", lang), label),
    ]
    if client_name:
        parts.append(Paragraph(client_name, name))
    return parts


def build_signature_block(lang: str = "es", client_name: str = "",
                          include_client_side: bool = True,
                          total_width_inches: float = 7.0) -> Table:
    """Build the signature+stamp+conformity Table Flowable.

    Layout:
      +----------------------+---------+------------------------+
      | Signature img        | Stamp   | Client conformity line |
      | Label                | image   | Label + optional name  |
      | Name / Role          |         |                        |
      +----------------------+---------+------------------------+

    When `include_client_side=False` (audit, revenue, admin-only
    reports where no counter-party signs) the third column collapses.
    """
    left = _sig_cell(lang)
    center = _stamp_cell()
    right = _client_cell(lang, client_name) if include_client_side else []

    if include_client_side:
        row = [left, center, right]
        col_widths = [
            total_width_inches * 0.42,
            total_width_inches * 0.20,
            total_width_inches * 0.38,
        ]
    else:
        row = [left, center]
        col_widths = [
            total_width_inches * 0.65,
            total_width_inches * 0.35,
        ]

    tbl = Table([row], colWidths=[w * inch for w in col_widths])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PANEL_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.75, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    return tbl
