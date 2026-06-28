"""PDF generation for VIP daily closing."""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
)


BRAND_YELLOW = colors.HexColor("#EAB308")
BG_DARK = colors.HexColor("#0A0A0A")
PANEL = colors.HexColor("#141414")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = LETTER
    # Background dark
    canvas.setFillColor(BG_DARK)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Header band
    canvas.setFillColor(PANEL)
    canvas.rect(0, h - 70, w, 70, fill=1, stroke=0)
    # Logo image
    if LOGO_PATH.exists():
        try:
            canvas.drawImage(str(LOGO_PATH), 32, h - 64, width=52, height=52,
                             preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(96, h - 32, "RESILIENCE BROTHERS")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(96, h - 46, "Global P2P Trade Infrastructure")
    # Top-right doc label
    canvas.setFillColor(BRAND_YELLOW)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 32, "CIERRE VIP")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "DAILY CLOSING REPORT")
    # Footer
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com")
    canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 38, w - 36, 38)
    canvas.restoreState()


def _compute_closing_totals(orders: list) -> dict:
    """Aggregate the four headline figures shown in the summary band."""
    total_received = 0.0
    total_in_native: dict = {}
    total_volume_from = 0.0
    for o in orders:
        total_volume_from += o.get("amount_from", 0) or 0
        amt_to = o.get("amount_to", 0) or 0
        if o.get("delivery_method") == "accumulate":
            total_received += amt_to
        else:
            total_in_native[o["to_code"]] = total_in_native.get(o["to_code"], 0) + amt_to
    return {
        "total_received_usd": total_received,
        "total_in_native": total_in_native,
        "total_orders": len(orders),
        "total_volume_from": total_volume_from,
    }


def _format_order_row(o: dict) -> list:
    """Render a single order as the 7-column row of the orders table."""
    ts = o.get("updated_at") or o.get("created_at")
    try:
        ts_fmt = datetime.fromisoformat(ts).strftime("%H:%M") if ts else "—"
    except Exception:
        ts_fmt = "—"
    return [
        o["id"][:6],
        ts_fmt,
        f"{o['from_code']}→{o['to_code']}",
        f"{o['amount_from']:.2f} {o['from_code']}",
        f"{o['amount_to']:.2f} {o['to_code']}",
        f"{o['rate_applied']:.4f}",
        o["delivery_method"],
    ]


def _build_currency_breakdown_table(total_in_native: dict) -> Table:
    rows = [["Moneda", "Total recibido"]]
    for code, total in total_in_native.items():
        rows.append([code, f"{total:,.2f}"])
    tbl = Table(rows, colWidths=[2*inch, 2*inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_YELLOW),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def generate_vip_closing_pdf(
    user: dict,
    orders: list,
    date_label: str,
    final_balance: float,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=22, leading=24, spaceAfter=4, fontName="Helvetica-Bold")
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_YELLOW, fontSize=8, leading=10, spaceAfter=2, fontName="Helvetica-Bold")
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=10, leading=12, spaceAfter=18)
    body = ParagraphStyle('body', parent=styles['Normal'], textColor=TEXT, fontSize=10, leading=14)
    body_muted = ParagraphStyle('bodym', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=9, leading=12)

    story = []

    story.append(Paragraph("/ CIERRE DIARIO VIP", label))
    story.append(Paragraph(f"Reporte del {date_label}", h1))
    story.append(Paragraph(
        f"Cliente: <font color='#FFFFFF'><b>{user.get('name','')}</b></font> · {user.get('email','')}", sub))

    # Summary cards
    totals = _compute_closing_totals(orders)
    total_received = totals["total_received_usd"]
    total_in_native = totals["total_in_native"]
    total_orders = totals["total_orders"]
    total_volume_from = totals["total_volume_from"]

    summary_data = [
        [Paragraph("Órdenes aprobadas", body_muted), Paragraph("Volumen total", body_muted), Paragraph("Acumulado USD", body_muted), Paragraph("Saldo al cierre", body_muted)],
        [
            Paragraph(f"<font size=18 color='#FFFFFF'><b>{total_orders}</b></font>", body),
            Paragraph(f"<font size=14 color='#FFFFFF'><b>{total_volume_from:,.2f}</b></font>", body),
            Paragraph(f"<font size=14 color='#EAB308'><b>${total_received:,.2f}</b></font>", body),
            Paragraph(f"<font size=14 color='#22C55E'><b>${final_balance:,.2f}</b></font>", body),
        ],
    ]
    tbl = Table(summary_data, colWidths=[1.85*inch]*4)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), PANEL),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 18))

    # Orders table
    story.append(Paragraph("Órdenes aprobadas", label))
    story.append(Spacer(1, 6))

    headers = ["ID", "Hora", "Par", "Envió", "Recibió", "Tasa", "Entrega"]
    data = [headers] + [_format_order_row(o) for o in orders]

    if len(data) == 1:
        data.append(["—", "—", "—", "—", "—", "—", "—"])

    orders_tbl = Table(data, colWidths=[0.7*inch, 0.6*inch, 1.0*inch, 1.2*inch, 1.3*inch, 0.9*inch, 1.0*inch])
    orders_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), PANEL),
        ("TEXTCOLOR", (0,0), (-1,0), BRAND_YELLOW),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 8),
        ("LEADING", (0,0), (-1,0), 10),
        ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,1), (-1,-1), 8.5),
        ("TEXTCOLOR", (4,1), (4,-1), BRAND_YELLOW),
        ("GRID", (0,0), (-1,-1), 0.4, BORDER),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
    ]))
    story.append(orders_tbl)
    story.append(Spacer(1, 18))

    # Breakdown by destination currency
    if total_in_native:
        story.append(Paragraph("Recibido por moneda destino (no acumulado)", label))
        story.append(Spacer(1, 4))
        story.append(_build_currency_breakdown_table(total_in_native))
        story.append(Spacer(1, 20))

    # Signature block
    sig_data = [[
        Paragraph("<font color='#A3A3A3' size=8>FIRMA / SELLO RESILIENCE BROTHERS</font><br/><br/><br/><font color='#525252' size=8>____________________________</font>", body_muted),
        Paragraph("<font color='#A3A3A3' size=8>CLIENTE VIP — CONFORMIDAD</font><br/><br/><br/><font color='#525252' size=8>____________________________</font>", body_muted),
    ]]
    sig_tbl = Table(sig_data, colWidths=[3.6*inch, 3.6*inch])
    sig_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 12),
    ]))
    story.append(sig_tbl)

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
