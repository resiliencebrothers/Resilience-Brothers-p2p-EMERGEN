"""iter114 — Profitability operations report PDF.

Investor-ready export of the profitability operations log (iter113):
executive KPI cards, per-payment-currency gains decomposition, and the
full operations detail table. Same dark branding, header band and
signature block used by every other PDF the platform issues.
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

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
    canvas.drawRightString(w - 36, h - 32, "RENTABILIDAD")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "PROFITABILITY REPORT")
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
        return f"Reporte del {since}"
    if since and until:
        return f"Reporte del {since} al {until}"
    if since:
        return f"Reporte desde {since}"
    if until:
        return f"Reporte hasta {until}"
    return "Reporte histórico completo"


def _summary_card_row(styles, cards: List[dict]) -> Table:
    body_muted = ParagraphStyle(
        "pc_lbl", parent=styles["Normal"], textColor=TEXT_MUTED,
        fontSize=8, leading=10, fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "pc_val", parent=styles["Normal"], textColor=TEXT,
        fontSize=10, leading=14,
    )
    header_row = [Paragraph(c["label"], body_muted) for c in cards]
    value_row = [
        Paragraph(
            f"<font size=14 color='{c.get('color', '#FFFFFF')}'><b>{c['value']}</b></font>",
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


def _currency_summary_table(rows: List[dict]) -> Table:
    headers = ["Moneda pago", "Operaciones", "Ganancia divisa", "Ganancia conversión", "Ganancia neta"]
    data = [headers]
    for r in rows:
        data.append([
            r["currency"],
            f"{r['count']:,}",
            f"{r['result_fx']:+,.2f}",
            f"{r['conversion_gain']:+,.2f}",
            f"{r['net_gain']:+,.2f}",
        ])
    if len(data) == 1:
        data.append(["—"] * 5)
    tbl = Table(data, colWidths=[1.2 * inch, 1.2 * inch, 1.65 * inch, 1.65 * inch, 1.7 * inch], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for idx, r in enumerate(rows, start=1):
        style.append(("TEXTCOLOR", (4, idx), (4, idx), GREEN if r["net_gain"] >= 0 else RED))
        style.append(("FONTNAME", (4, idx), (4, idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def _operations_table(ops: List[dict]) -> Table:
    headers = ["Fecha", "Cliente", "Par", "Cant.", "Venta", "Compra",
               "%C/%V", "G. conv.", "G. neta", "Rent.", "Estado"]
    data = [headers]
    for op in ops:
        data.append([
            op.get("op_date", "—"),
            (op.get("client_name") or "—")[:22],
            f"{op.get('currency', '')}→{op.get('payment_currency', '')}",
            f"{op.get('quantity', 0):,.2f}",
            f"{op.get('sell_price', 0):,.2f}",
            f"{op.get('buy_price', 0):,.2f}",
            f"{op.get('buy_pct', 0):g}/{op.get('sell_pct', 0):g}",
            f"{op.get('conversion_gain', 0):+,.2f}",
            f"{op.get('net_gain', 0):+,.2f}",
            f"{op.get('profitability_pct', 0):,.2f}%",
            "Rentable" if op.get("status") == "profitable" else "Pérdida",
        ])
    if len(data) == 1:
        data.append(["—"] * 11)
    tbl = Table(
        data,
        colWidths=[0.62 * inch, 1.05 * inch, 0.82 * inch, 0.52 * inch, 0.62 * inch,
                   0.62 * inch, 0.52 * inch, 0.72 * inch, 0.76 * inch, 0.52 * inch, 0.63 * inch],
        repeatRows=1,
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6.5),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (3, 1), (-2, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for idx, op in enumerate(ops, start=1):
        ok = op.get("status") == "profitable"
        style.append(("TEXTCOLOR", (9, idx), (9, idx), GREEN if (op.get("net_gain") or 0) >= 0 else RED))
        style.append(("FONTNAME", (9, idx), (9, idx), "Helvetica-Bold"))
        style.append(("TEXTCOLOR", (11, idx), (11, idx), GREEN if ok else RED))
    tbl.setStyle(TableStyle(style))
    return tbl


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


def _intro_story(st: dict, since: str, until: str, actor: dict,
                 kpis: Dict[str, float]) -> list:
    """Cabecera + emisor + tarjetas KPI."""
    return [
        Paragraph("/ CÁLCULO DE RENTABILIDAD", st["label"]),
        Paragraph(_range_title(since, until), st["h1"]),
        Paragraph(
            f"Emisor: <font color='#FFFFFF'><b>{actor.get('name', '')}</b></font> · {actor.get('email', '')}<br/>"
            "Registro de operaciones con clientes y su rentabilidad por conversión. "
            "Documento confidencial destinado a socios y auditores de Resilience Brothers FZ-LLC.",
            st["sub"],
        ),
        _summary_card_row(st["base"], [
            {"label": "Operaciones", "value": f"{kpis.get('total', 0):,}"},
            {"label": "Rentables", "value": f"{kpis.get('profitable', 0):,}", "color": "#22C55E"},
            {"label": "En pérdida", "value": f"{kpis.get('loss', 0):,}", "color": "#EF4444"},
            {"label": "Tasa de éxito", "value": f"{kpis.get('success_rate', 0):,.1f}%", "color": "#8B5CF6"},
        ]),
    ]


def _body_story(st: dict, ops: List[dict], currency_rows: List[dict]) -> list:
    """Tablas: ganancia por moneda + detalle de operaciones."""
    return [
        Spacer(1, 20),
        Paragraph("GANANCIA NETA POR MONEDA DE PAGO", st["section"]),
        _currency_summary_table(currency_rows),
        Spacer(1, 22),
        Paragraph("DETALLE DE OPERACIONES", st["section"]),
        _operations_table(ops),
    ]


def _closing_story(st: dict, actor: dict) -> list:
    """Nota metodológica + bloque de firma."""
    return [
        Spacer(1, 24),
        Paragraph(
            "<font color='#A3A3A3' size=7>* Ganancia neta = efectivo recuperado − costo de compra, "
            "donde efectivo recuperado = venta × (1 + %V) ÷ (1 + %C). Los porcentajes %C/%V indican "
            "el precio de compra y venta de la transferencia bancaria de la moneda "
            "de pago. Este documento es CONFIDENCIAL y su distribución requiere "
            "autorización del titular.</font>",
            st["base"]["Normal"],
        ),
        Spacer(1, 20),
        build_signature_block(
            lang=(actor.get("preferred_language") or "es"),
            client_name="", include_client_side=False, total_width_inches=7.0,
        ),
    ]


def generate_profitability_pdf(
    since: str,
    until: str,
    ops: List[dict],
    currency_rows: List[dict],
    kpis: Dict[str, float],
    actor: dict,
) -> bytes:
    """Build the profitability operations report PDF.

    Args:
      since / until: ISO date labels ('YYYY-MM-DD' or empty).
      ops: operation docs (newest first) already filtered by the caller.
      currency_rows: [{currency, count, result_fx, conversion_gain, net_gain}]
      kpis: {total, profitable, loss, success_rate}
      actor: user dict for the issuer line + signature.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )
    st = _styles()
    story: list = (
        _intro_story(st, since, until, actor, kpis)
        + _body_story(st, ops, currency_rows)
        + _closing_story(st, actor)
    )
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
