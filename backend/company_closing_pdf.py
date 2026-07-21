"""iter91 — Company accounting closing PDF.

Investor-ready single-document snapshot of the platform's treasury
over an arbitrary date range: total operations, gross volume, revenue,
per-currency inflow/outflow decomposition, and the current net balance.

All numbers are computed by the same aggregators used by
`/api/admin/company-funds` — this PDF just packages them for hand-off
to auditors and partners, and signs the last page via the shared
`pdf_signature.build_signature_block` helper (same signature + stamp
used by every other PDF the platform issues).
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
    canvas.drawRightString(w - 36, h - 32, "CIERRE EMPRESA")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "COMPANY CLOSING REPORT")
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
        return f"Reporte del {since}"
    if since and until:
        return f"Reporte del {since} al {until}"
    if since:
        return f"Reporte desde {since}"
    if until:
        return f"Reporte hasta {until}"
    return "Reporte histórico completo"


def _summary_card_row(styles, cards: List[dict]) -> Table:
    """Render a horizontal band of `cards`; each dict has {label, value, color}."""
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


def _funds_table(funds_rows: List[dict]) -> Table:
    """Per-currency treasury decomposition table.

    Columns: Moneda | Entradas | Órdenes Out | Retiros Cli | Retiros Emp | Ajustes± | Balance
    """
    headers = [
        "Moneda", "Entradas",
        "Órdenes\n(salida)", "Retiros\nClientes",
        "Retiros\nEmpresa", "Ajustes\nnetos", "Balance",
    ]
    data = [headers]
    for r in funds_rows:
        adj_net = float(r.get("manual_inflow", 0)) - float(r.get("manual_outflow", 0))
        balance = float(r.get("balance", 0))
        data.append([
            r.get("currency", "—"),
            f"+{r.get('inflow', 0):,.2f}",
            f"-{r.get('outflow_orders', 0):,.2f}",
            f"-{r.get('outflow_clients', 0):,.2f}",
            f"-{r.get('outflow_company', 0):,.2f}",
            f"{adj_net:+,.2f}",
            f"{balance:+,.2f}",
        ])
    if len(data) == 1:
        data.append(["—"] * 7)

    tbl = Table(
        data,
        colWidths=[0.75 * inch, 1.15 * inch, 1.05 * inch, 1.05 * inch,
                   1.05 * inch, 1.0 * inch, 1.15 * inch],
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
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TEXTCOLOR", (1, 1), (1, -1), GREEN),
        ("TEXTCOLOR", (2, 1), (2, -1), RED),
        ("TEXTCOLOR", (3, 1), (3, -1), RED),
        ("TEXTCOLOR", (4, 1), (4, -1), RED),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    # Color the balance column per sign so partners see the net immediately.
    for idx, r in enumerate(funds_rows, start=1):
        style.append((
            "TEXTCOLOR", (6, idx), (6, idx),
            GREEN if float(r.get("balance", 0)) >= 0 else RED,
        ))
        style.append(("FONTNAME", (6, idx), (6, idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def _revenue_table(revenue_rows: List[dict]) -> Table:
    """Per-currency gross revenue (fees earned) with USD equivalent."""
    headers = ["Moneda", "Fees generados", "USD equivalente"]
    data = [headers]
    for r in revenue_rows:
        data.append([
            r.get("currency", "—"),
            f"{r.get('fees', 0):,.2f}",
            f"${r.get('fees_usd', 0):,.2f}",
        ])
    if len(data) == 1:
        data.append(["—"] * 3)
    tbl = Table(data, colWidths=[1.5 * inch, 2.5 * inch, 2.5 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TEXTCOLOR", (2, 1), (2, -1), GREEN),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def generate_company_closing_pdf(
    since: str,
    until: str,
    funds_rows: List[dict],
    revenue_rows: List[dict],
    kpis: Dict[str, float],
    actor: dict,
) -> bytes:
    """Build the full investor-grade company closing PDF.

    Args:
      since / until: ISO date range labels ('YYYY-MM-DD' or empty for
        'histórico completo').
      funds_rows: output of `_compute_company_funds_range()` — same shape
        as the on-screen /admin/company-funds cards.
      revenue_rows: list of {currency, fees, fees_usd} — gross fees
        earned per currency in the range.
      kpis: {total_orders, gross_volume_usd, revenue_usd, treasury_usd}
        — top-row executive summary.
      actor: user dict for the signature panel + audit trail.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=styles["Heading1"], textColor=TEXT,
        fontSize=22, leading=24, spaceAfter=4, fontName="Helvetica-Bold",
    )
    label = ParagraphStyle(
        "label", parent=styles["Normal"], textColor=BRAND_PURPLE,
        fontSize=8, leading=10, spaceAfter=2, fontName="Helvetica-Bold",
    )
    sub = ParagraphStyle(
        "sub", parent=styles["Normal"], textColor=TEXT_MUTED,
        fontSize=10, leading=13, spaceAfter=18,
    )
    section = ParagraphStyle(
        "section", parent=styles["Normal"], textColor=BRAND_PURPLE,
        fontSize=9, leading=12, spaceAfter=6, fontName="Helvetica-Bold",
    )

    story: list = []
    story.append(Paragraph("/ CIERRE CONTABLE EMPRESA", label))
    story.append(Paragraph(_range_title(since, until), h1))
    story.append(Paragraph(
        f"Emisor: <font color='#FFFFFF'><b>{actor.get('name', '')}</b></font> · {actor.get('email', '')}<br/>"
        "Documento confidencial destinado a socios y auditores de Resilience Brothers FZ-LLC.",
        sub,
    ))

    # Executive summary
    story.append(_summary_card_row(styles, [
        {"label": "Órdenes ejecutadas",
         "value": f"{kpis.get('total_orders', 0):,}"},
        {"label": "Volumen bruto USD",
         "value": f"${kpis.get('gross_volume_usd', 0):,.2f}"},
        {"label": "Ingresos (fees)",
         "value": f"${kpis.get('revenue_usd', 0):,.2f}",
         "color": "#22C55E"},
        {"label": "Tesorería neta USD",
         "value": f"${kpis.get('treasury_usd', 0):,.2f}",
         "color": "#8B5CF6"},
    ]))
    story.append(Spacer(1, 20))

    # Treasury decomposition per currency
    story.append(Paragraph("TESORERÍA POR MONEDA", section))
    story.append(_funds_table(funds_rows))
    story.append(Spacer(1, 22))

    # Revenue breakdown
    story.append(Paragraph("INGRESOS POR MONEDA (fees generados)", section))
    story.append(_revenue_table(revenue_rows))
    story.append(Spacer(1, 24))

    # Notes
    story.append(Paragraph(
        "<font color='#A3A3A3' size=7>* Los importes reflejan los movimientos "
        "registrados por la plataforma en el rango indicado. Retiros a clientes "
        "y a la empresa se contabilizan al marcarse como pagados. Ajustes "
        "manuales incluyen conciliaciones de tesorería aprobadas por Dirección. "
        "Este documento es CONFIDENCIAL y su distribución requiere autorización "
        "del titular.</font>",
        styles["Normal"],
    ))
    story.append(Spacer(1, 20))

    # Signature block (same helper used by every other PDF).
    story.append(build_signature_block(
        lang=(actor.get("preferred_language") or "es"),
        client_name="", include_client_side=False, total_width_inches=7.0,
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
