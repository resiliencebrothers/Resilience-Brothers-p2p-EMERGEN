"""PDF generation for Audit Log export."""
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
    canvas.drawString(88, h - 42, "Audit Log Export — Internal use only")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 28, "AUDIT LOG")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 42, "TRAZABILIDAD DE ACCIONES")
    canvas.drawString(36, 20, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 20, "resiliencebrothers.com")
    canvas.drawRightString(w - 36, 20, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 32, w - 36, 32)
    canvas.restoreState()


def _format_audit_ts(value: str) -> str:
    """Best-effort ISO timestamp → 'YYYY-MM-DD HH:MM:SS'. Falls back to raw."""
    try:
        return datetime.fromisoformat(value or "").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value or "—"


def _build_audit_row(e: dict) -> list:
    """Render a single audit entry as the 7-column row used in the PDF."""
    actor = e.get("actor_name") or e.get("actor_email") or "—"
    return [
        _format_audit_ts(e.get("created_at", "")),
        actor[:32],
        (e.get("actor_role") or "—").upper(),
        e.get("action", "—"),
        e.get("entity_type", "—"),
        (e.get("entity_id") or "—")[:10],
        (e.get("summary") or "—")[:80],
    ]


def _build_filters_paragraph(filters: dict, total: int, sub_style) -> Paragraph:
    f_action = filters.get("action") or "todas"
    f_actor = filters.get("actor_id") or "todos"
    f_since = filters.get("since") or "—"
    f_until = filters.get("until") or "—"
    return Paragraph(
        f"Filtros → Acción: <font color='#FFFFFF'><b>{f_action}</b></font> · "
        f"Actor: <font color='#FFFFFF'><b>{f_actor}</b></font> · "
        f"Desde: <font color='#FFFFFF'><b>{f_since}</b></font> · "
        f"Hasta: <font color='#FFFFFF'><b>{f_until}</b></font> · "
        f"Total: <font color='#8B5CF6'><b>{total}</b></font>",
        sub_style,
    )


def generate_audit_pdf(entries: list, filters: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(LETTER),
        leftMargin=24, rightMargin=24, topMargin=80, bottomMargin=44,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=20, leading=22, fontName="Helvetica-Bold", spaceAfter=4)
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE, fontSize=8, leading=10, fontName="Helvetica-Bold", spaceAfter=2)
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=9, leading=12, spaceAfter=14)

    story = []
    story.append(Paragraph("/ REGISTRO DE ACCIONES", label))
    story.append(Paragraph("Audit Log — Resilience Brothers", h1))
    story.append(_build_filters_paragraph(filters, len(entries), sub))

    headers = ["Cuándo (UTC)", "Quién", "Rol", "Acción", "Entidad", "ID", "Resumen"]
    data = [headers] + [_build_audit_row(e) for e in entries]
    if len(data) == 1:
        data.append(["—"] * 7)

    col_widths = [1.4*inch, 1.6*inch, 0.7*inch, 1.2*inch, 0.8*inch, 0.9*inch, 3.2*inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
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
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
