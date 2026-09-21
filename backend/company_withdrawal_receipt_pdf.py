"""iter286 — Recibo PDF de retiro de empresa PAGADO.

Documento firmable: membrete Resilience Brothers, datos del retiro,
desglose de billetes entregados (si el pago salió de una caja de efectivo)
y bloque de firmas (sello/firma de la empresa + conformidad del
beneficiario con líneas para nombre, ID y teléfono).
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone

from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from pdf_signature import build_signature_block

BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#14101F")
PANEL = colors.HexColor("#1A1730")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _fmt(n: float) -> str:
    return f"{float(n or 0):,.2f}"


def _fmt_date(iso_str: str) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        return iso_str[:16]


def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = LETTER
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
    canvas.drawString(88, h - 42, "Recibo de retiro del fondo de empresa")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 28, "RECIBO")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 42, "COMPROBANTE DE PAGO")
    gen_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    canvas.drawString(36, 20, f"Generado: {gen_ts}")
    canvas.drawCentredString(w / 2, 20, "resiliencebrothers.com")
    canvas.drawRightString(w - 36, 20, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 32, w - 36, 32)
    canvas.restoreState()


def _info_table(cw: dict) -> Table:
    rows = [
        ("Beneficiario", cw.get("beneficiary") or "—"),
        ("Monto", f"{_fmt(cw.get('amount'))} {cw.get('currency', '')}"),
        ("Concepto", cw.get("concept") or "—"),
        ("Nota", cw.get("note") or "—"),
        ("Pagado desde", cw.get("paid_from_account_label") or "Sin asignar"),
        ("Autorizado por", cw.get("authorized_by_name")
         or cw.get("authorized_by_email") or "—"),
        ("Fecha de solicitud", _fmt_date(cw.get("created_at", ""))),
        ("Fecha de pago", _fmt_date(cw.get("paid_at", ""))),
    ]
    data = [[k, v] for k, v in rows]
    tbl = Table(data, colWidths=[1.9 * inch, 5.1 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), TEXT),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("FONT", (1, 1), (1, 1), "Helvetica-Bold", 12),
        ("TEXTCOLOR", (1, 1), (1, 1), GREEN),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


def _denoms_table(cw: dict) -> Table:
    denoms = cw.get("denominations") or {}
    entries = sorted(((int(float(k)), int(v)) for k, v in denoms.items()),
                     key=lambda x: -x[0])
    currency = cw.get("currency", "")
    data = [["Denominación", "Cantidad", "Subtotal"]]
    total = 0.0
    for denom, qty in entries:
        sub = denom * qty
        total += sub
        data.append([f"{denom:,} {currency}", f"× {qty}", f"{_fmt(sub)} {currency}"])
    data.append(["TOTAL ENTREGADO", "", f"{_fmt(total)} {currency}"])
    tbl = Table(data, colWidths=[2.8 * inch, 1.6 * inch, 2.6 * inch])
    last = len(data) - 1
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("BACKGROUND", (0, 1), (-1, last - 1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, last - 1), TEXT),
        ("FONT", (0, 1), (-1, last - 1), "Helvetica", 9),
        ("BACKGROUND", (0, last), (-1, last), colors.HexColor("#122117")),
        ("TEXTCOLOR", (0, last), (-1, last), GREEN),
        ("FONT", (0, last), (-1, last), "Helvetica-Bold", 10),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return tbl


def _receiver_lines() -> Table:
    """Líneas para que el beneficiario complete sus datos al recibir."""
    line = "_" * 46
    data = [
        ["Nombre y apellidos del receptor:", line],
        ["No. de ID / Carné:", line],
        ["Teléfono:", line],
    ]
    tbl = Table(data, colWidths=[2.4 * inch, 4.6 * inch])
    tbl.setStyle(TableStyle([
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#666666")),
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def generate_withdrawal_receipt_pdf(cw: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=84, bottomMargin=48,
    )
    styles = getSampleStyleSheet()
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE,
                           fontSize=8, leading=10, fontName="Helvetica-Bold", spaceAfter=2)
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=18,
                        leading=21, fontName="Helvetica-Bold", spaceAfter=2)
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED,
                         fontSize=9, leading=12, spaceAfter=10)
    section = ParagraphStyle('section', parent=styles['Normal'], textColor=BRAND_PURPLE,
                             fontSize=9, leading=12, fontName="Helvetica-Bold",
                             spaceBefore=12, spaceAfter=4)
    note = ParagraphStyle('note', parent=styles['Normal'], textColor=TEXT_MUTED,
                          fontSize=7.5, leading=10, spaceBefore=6)

    cwid = str(cw.get("id") or "")
    story = [
        Paragraph("/ COMPROBANTE DE PAGO", label),
        Paragraph("Recibo de Retiro de Empresa", h1),
        Paragraph(f"Referencia: {cwid}", sub),
        _info_table(cw),
    ]
    if cw.get("denominations"):
        story.append(Paragraph("DESGLOSE DE BILLETES ENTREGADOS", section))
        story.append(_denoms_table(cw))
    story.append(Paragraph("DATOS DEL RECEPTOR", section))
    story.append(_receiver_lines())
    story.append(Paragraph(
        "Declaro haber recibido el monto arriba indicado en su totalidad, "
        "conforme al desglose detallado en este comprobante.", note))
    story.append(Spacer(1, 18))
    story.append(build_signature_block(
        lang="es", client_name=cw.get("beneficiary") or "",
        include_client_side=True, total_width_inches=7.0))
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
