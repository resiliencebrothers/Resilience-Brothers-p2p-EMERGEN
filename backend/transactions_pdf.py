"""PDF generation for Transactions Registry export (entradas + salidas)."""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#0A0A0F")
PANEL = colors.HexColor("#141322")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")
RED = colors.HexColor("#EF4444")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = landscape(LETTER)
    canvas.setFillColor(BG_DARK)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    canvas.setFillColor(PANEL)
    canvas.rect(0, h - 64, w, 64, fill=1, stroke=0)
    if LOGO_PATH.exists():
        try:
            canvas.drawImage(str(LOGO_PATH), 32, h - 58, width=46, height=46,
                             preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(88, h - 28, "RESILIENCE BROTHERS")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(88, h - 42, "Registro de Transacciones — Contabilidad")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 28, "TRANSACCIONES")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 42, "ENTRADAS · SALIDAS")
    canvas.drawString(36, 20, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 20, "resiliencebrothers.com")
    canvas.drawRightString(w - 36, 20, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 32, w - 36, 32)
    canvas.restoreState()


def _build_filters_paragraph(filters: dict, style: ParagraphStyle) -> Paragraph:
    """Format the filter bar shown under the PDF title."""
    f_dir = filters.get("direction") or "todas"
    f_cur = filters.get("currency") or "todas"
    f_holder = filters.get("holder") or "todos"
    f_since = filters.get("since") or "—"
    f_until = filters.get("until") or "—"
    f_min = filters.get("min_amount")
    f_max = filters.get("max_amount")
    amount_range = "—"
    if f_min is not None or f_max is not None:
        amount_range = f"{f_min if f_min is not None else '∞-'} a {f_max if f_max is not None else '+∞'}"
    return Paragraph(
        f"Filtros → Dirección: <font color='#FFFFFF'><b>{f_dir}</b></font> · "
        f"Moneda: <font color='#FFFFFF'><b>{f_cur}</b></font> · "
        f"Titular: <font color='#FFFFFF'><b>{f_holder}</b></font> · "
        f"Desde: <font color='#FFFFFF'><b>{f_since}</b></font> · "
        f"Hasta: <font color='#FFFFFF'><b>{f_until}</b></font> · "
        f"Monto: <font color='#FFFFFF'><b>{amount_range}</b></font>",
        style,
    )


def _build_totals_paragraph(totals: dict, style: ParagraphStyle) -> Paragraph | None:
    """Render per-currency in/out/net summary lines, or None when totals are empty."""
    by_cur = totals.get("by_currency", {})
    lines = []
    for code in sorted(by_cur.keys()):
        v = by_cur[code]
        in_amt = v.get("in", 0.0)
        out_amt = v.get("out", 0.0)
        net = in_amt - out_amt
        net_color = "#22C55E" if net >= 0 else "#EF4444"
        lines.append(
            f"<font color='#8B5CF6'><b>{code}</b></font>: "
            f"Entradas <font color='#22C55E'>+{in_amt:,.2f}</font> · "
            f"Salidas <font color='#EF4444'>-{out_amt:,.2f}</font> · "
            f"Neto <font color='{net_color}'><b>{net:+,.2f}</b></font>"
        )
    if not lines:
        return None
    return Paragraph("<b>TOTALES POR MONEDA</b><br/>" + "<br/>".join(lines), style)


def _format_entry_row(e: dict) -> list[str]:
    """Convert one transaction entry into a table row (8 cols)."""
    try:
        ts = datetime.fromisoformat(e.get("created_at", "")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts = e.get("created_at", "—")
    is_in = e.get("direction") == "in"
    tipo = "↓ ENTRADA" if is_in else "↑ SALIDA"
    return [
        ts,
        tipo,
        e.get("currency", "—"),
        f"{e.get('amount', 0):,.2f}",
        (e.get("holder_name") or "—")[:30],
        (e.get("client_name") or "—")[:24],
        e.get("method", "—"),
        (e.get("ref_id") or "—")[:8],
    ]


def _build_transactions_table(entries: list) -> Table:
    """Assemble the full transactions table with directional colouring on `Tipo`."""
    headers = ["Fecha (UTC)", "Tipo", "Moneda", "Monto", "Titular cuenta", "Cliente", "Método", "ID"]
    data = [headers] + [_format_entry_row(e) for e in entries]
    if len(data) == 1:
        data.append(["—"] * 8)

    col_widths = [1.1*inch, 0.9*inch, 0.7*inch, 1.0*inch, 1.9*inch, 1.6*inch, 0.9*inch, 0.7*inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style: list = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
    ]
    for row_idx, entry in enumerate(entries, start=1):
        color = GREEN if entry.get("direction") == "in" else RED
        style.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), color))
        style.append(("FONTNAME", (1, row_idx), (1, row_idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def generate_transactions_pdf(entries: list, filters: dict, totals: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(LETTER),
        leftMargin=24, rightMargin=24, topMargin=80, bottomMargin=44,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=20, leading=22, fontName="Helvetica-Bold", spaceAfter=4)
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE, fontSize=8, leading=10, fontName="Helvetica-Bold", spaceAfter=2)
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=9, leading=12, spaceAfter=10)
    totals_style = ParagraphStyle('totals', parent=styles['Normal'], textColor=TEXT, fontSize=10, leading=14, spaceAfter=14)

    story: list = [
        Paragraph("/ REGISTRO CONTABLE", label),
        Paragraph("Transacciones — Resilience Brothers", h1),
        _build_filters_paragraph(filters, sub),
    ]
    totals_para = _build_totals_paragraph(totals, totals_style)
    if totals_para is not None:
        story.append(totals_para)
    story.append(Paragraph(
        f"Total de transacciones: <font color='#8B5CF6'><b>{len(entries)}</b></font>",
        sub,
    ))
    story.append(_build_transactions_table(entries))
    story.append(Spacer(1, 14))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
