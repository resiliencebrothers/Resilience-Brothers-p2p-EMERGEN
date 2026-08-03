"""iter111 — VIP Ledger statement PDF.

Formal accounting statement of a VIP's ledger over an arbitrary date
range. Renders the initial balance (accumulated before the range),
every confirmed movement inside the range with a running balance
after each row, and the final balance.

Movements considered (only the ones that actually moved the ledger):
  * vip_capital_deposits with status="confirmed"       → positive +=
  * vip_batch_items       with status="approved"       → positive/negative +=
  * vip_settlements       with status="confirmed"      → positive/negative -=

Signed with the same shared signature+stamp Flowable used by every
other Resilience Brothers PDF.
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

from pdf_signature import build_signature_block


LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
BG_DARK = colors.HexColor("#0a0a0a")
PANEL = colors.HexColor("#141220")
BORDER = colors.HexColor("#2a2a2a")
BRAND_PURPLE = colors.HexColor("#8B5CF6")
TEXT = colors.HexColor("#F5F5F5")
TEXT_MUTED = colors.HexColor("#A3A3A3")
GREEN = colors.HexColor("#22C55E")
RED = colors.HexColor("#EF4444")
AMBER = colors.HexColor("#F59E0B")


def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = LETTER
    canvas.setFillColor(BG_DARK)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    canvas.setFillColor(PANEL)
    canvas.rect(0, h - 70, w, 70, fill=1, stroke=0)
    if LOGO_PATH.exists():
        try:
            canvas.drawImage(str(LOGO_PATH), 32, h - 64, width=52, height=52,
                             preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(96, h - 32, "RESILIENCE BROTHERS")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(96, h - 46, "Global P2P Trade Infrastructure")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 32, "ESTADO DE CUENTA VIP")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "VIP LEDGER STATEMENT")
    # Footer
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com · CONFIDENCIAL")
    canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 38, w - 36, 38)
    canvas.restoreState()


def _range_title(since: str, until: str) -> str:
    if since and until and since == until:
        return f"Estado del {since}"
    if since and until:
        return f"Estado del {since} al {until}"
    if since:
        return f"Estado desde {since}"
    if until:
        return f"Estado hasta {until}"
    return "Estado histórico completo"


def _styles():
    styles = getSampleStyleSheet()
    return {
        "base": styles,
        "h1": ParagraphStyle(
            "h1", parent=styles["Heading1"], textColor=TEXT,
            fontSize=22, leading=24, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "label": ParagraphStyle(
            "label", parent=styles["Normal"], textColor=BRAND_PURPLE,
            fontSize=8, leading=10, spaceAfter=2, fontName="Helvetica-Bold",
        ),
        "sub": ParagraphStyle(
            "sub", parent=styles["Normal"], textColor=TEXT_MUTED,
            fontSize=10, leading=13, spaceAfter=18,
        ),
        "section": ParagraphStyle(
            "section", parent=styles["Normal"], textColor=BRAND_PURPLE,
            fontSize=9, leading=12, spaceAfter=6, fontName="Helvetica-Bold",
        ),
    }


def _summary_card_row(styles, cards: List[dict]) -> Table:
    body_muted = ParagraphStyle(
        "sc_lbl", parent=styles["Normal"], textColor=TEXT_MUTED,
        fontSize=8, leading=10, fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "sc_val", parent=styles["Normal"], textColor=TEXT,
        fontSize=10, leading=14,
    )
    header_row = [Paragraph(c["label"], body_muted) for c in cards]
    value_row = [
        Paragraph(
            f"<font size=13 color='{c.get('color', '#FFFFFF')}'><b>{c['value']}</b></font>",
            body,
        )
        for c in cards
    ]
    n = len(cards)
    tbl = Table([header_row, value_row], colWidths=[(7.4 / n) * inch] * n)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return tbl


KIND_LABEL = {
    "deposit":    "Depósito",
    "batch_credit": "Lote (crédito)",
    "batch_debit":  "Lote (débito)",
    "payout":     "Pago (a favor)",
    "collection": "Cobro (nos pagas)",
}


def _movements_table(movements: List[dict]) -> Table:
    """Movement rows sorted asc by created_at.

    Columns: Fecha | Tipo | Referencia | Monto | USDT | Saldo (+) | Saldo (-)
    """
    headers = ["Fecha", "Tipo", "Referencia", "Monto", "USDT", "Saldo (+)", "Saldo (-)"]
    data = [headers]
    for m in movements:
        kind_lbl = KIND_LABEL.get(m["kind"], m["kind"])
        sign = "+" if m["kind"] in ("deposit", "batch_credit") else \
               "-" if m["kind"] in ("payout", "collection") else \
               "+"  # batch_debit adds to negative_usdt (still a +)
        usdt_disp = f"{sign}{m['amount_usdt']:,.2f}"
        data.append([
            (m.get("created_at") or "")[:10],
            kind_lbl,
            (m.get("reference") or "")[:32],
            f"{m['amount']:,.2f} {m.get('currency', '')}",
            usdt_disp,
            f"{m['running_positive']:,.2f}",
            f"{m['running_negative']:,.2f}",
        ])
    if len(movements) == 0:
        data.append(["—"] * 7)

    tbl = Table(
        data,
        colWidths=[
            0.75 * inch, 1.0 * inch, 1.55 * inch, 1.15 * inch,
            0.95 * inch, 0.95 * inch, 0.95 * inch,
        ],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (2, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    # Colorise USDT column per direction
    for idx, m in enumerate(movements, start=1):
        color = (
            GREEN if m["kind"] in ("deposit", "batch_credit")
            else AMBER if m["kind"] == "batch_debit"
            else RED  # payouts/collections DECREASE balances
        )
        style.append(("TEXTCOLOR", (4, idx), (4, idx), color))
        style.append(("FONTNAME", (4, idx), (4, idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def _title_block(story: list, styles: dict, vip: dict, since: str, until: str,
                 actor: dict) -> None:
    story.append(Paragraph("/ ESTADO DE CUENTA VIP", styles["label"]))
    story.append(Paragraph(_range_title(since, until), styles["h1"]))
    story.append(Paragraph(
        f"VIP: <font color='#FFFFFF'><b>{vip.get('name', '')}</b></font> · "
        f"{vip.get('email', '')} · "
        f"<font color='#A3A3A3'>id: {vip.get('user_id', '')}</font><br/>"
        f"Emisor: <font color='#FFFFFF'>{actor.get('name', '')}</font> · "
        f"{actor.get('email', '')}<br/>"
        "Documento confidencial destinado al titular VIP y sus contadores.",
        styles["sub"],
    ))


def _executive_cards(initial_pos, initial_neg, final_pos, final_neg,
                     total_deposits, total_payouts, total_collections,
                     movements_count) -> list:
    net_initial = round(initial_pos - initial_neg, 2)
    net_final = round(final_pos - final_neg, 2)
    return [
        {"label": "Saldo inicial (neto)", "value": f"${net_initial:+,.2f}",
         "color": ("#22C55E" if net_initial >= 0 else "#EF4444")},
        {"label": "Saldo final (neto)", "value": f"${net_final:+,.2f}",
         "color": ("#22C55E" if net_final >= 0 else "#EF4444")},
        {"label": "Movimientos", "value": f"{movements_count:,}"},
        {"label": "Depósitos / Pagos / Cobros",
         "value": f"${total_deposits:,.0f} / ${total_payouts:,.0f} / ${total_collections:,.0f}"},
    ]


def _balance_recap_table(initial_pos, initial_neg, final_pos, final_neg) -> Table:
    headers = ["", "Saldo (+) USDT", "Saldo (-) USDT", "Neto USDT"]
    data = [
        headers,
        ["Al inicio del período",
         f"{initial_pos:,.2f}", f"{initial_neg:,.2f}",
         f"{initial_pos - initial_neg:+,.2f}"],
        ["Al cierre del período",
         f"{final_pos:,.2f}", f"{final_neg:,.2f}",
         f"{final_pos - final_neg:+,.2f}"],
    ]
    tbl = Table(data, colWidths=[2.0 * inch, 1.8 * inch, 1.8 * inch, 1.6 * inch],
                repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TEXTCOLOR", (1, 1), (1, -1), GREEN),
        ("TEXTCOLOR", (2, 1), (2, -1), RED),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    # Color the Neto column per sign
    for idx, pos, neg in [
        (1, initial_pos, initial_neg),
        (2, final_pos, final_neg),
    ]:
        style.append((
            "TEXTCOLOR", (3, idx), (3, idx),
            GREEN if (pos - neg) >= 0 else RED,
        ))
        style.append(("FONTNAME", (3, idx), (3, idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def generate_vip_ledger_pdf(
    vip: dict,
    since: str,
    until: str,
    initial_positive: float,
    initial_negative: float,
    movements: List[dict],
    actor: dict,
) -> bytes:
    """Build the VIP ledger statement PDF.

    Args:
      vip: {user_id, name, email} of the VIP.
      since / until: ISO date labels ('YYYY-MM-DD' or empty).
      initial_positive / initial_negative: accumulated ledger BEFORE `since`.
      movements: list of dicts already sorted asc by `created_at`, each with:
        {created_at, kind, reference, amount, currency, amount_usdt,
         running_positive, running_negative}
      actor: user issuing the PDF (for signature block + audit context).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )
    styles = _styles()

    if movements:
        final_positive = movements[-1]["running_positive"]
        final_negative = movements[-1]["running_negative"]
    else:
        final_positive = initial_positive
        final_negative = initial_negative

    total_deposits = round(sum(
        m["amount_usdt"] for m in movements if m["kind"] == "deposit"
    ), 2)
    total_payouts = round(sum(
        m["amount_usdt"] for m in movements if m["kind"] == "payout"
    ), 2)
    total_collections = round(sum(
        m["amount_usdt"] for m in movements if m["kind"] == "collection"
    ), 2)

    story: list = []
    _title_block(story, styles, vip, since, until, actor)
    story.append(_summary_card_row(
        styles["base"],
        _executive_cards(
            initial_positive, initial_negative,
            final_positive, final_negative,
            total_deposits, total_payouts, total_collections,
            len(movements),
        ),
    ))
    story.append(Spacer(1, 18))
    story.append(Paragraph("SALDOS DEL PERÍODO", styles["section"]))
    story.append(_balance_recap_table(
        initial_positive, initial_negative, final_positive, final_negative,
    ))
    story.append(Spacer(1, 20))
    story.append(Paragraph("DETALLE DE MOVIMIENTOS", styles["section"]))
    story.append(_movements_table(movements))
    story.append(Spacer(1, 22))
    story.append(Paragraph(
        "<font color='#A3A3A3' size=7>* Solo se listan movimientos "
        "confirmados/aprobados — los pendientes o rechazados no afectan "
        "los saldos. El saldo (+) representa el USDT que la empresa "
        "adeuda al VIP; el saldo (-) representa el USDT que el VIP "
        "adeuda a la empresa. Este documento es CONFIDENCIAL y su "
        "distribución requiere autorización del titular.</font>",
        styles["base"]["Normal"],
    ))
    story.append(Spacer(1, 18))
    story.append(build_signature_block(
        lang=(actor.get("preferred_language") or "es"),
        client_name=vip.get("name", ""), include_client_side=True,
        total_width_inches=7.0,
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
