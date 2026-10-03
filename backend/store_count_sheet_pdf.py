"""IPV Fase 2 — PDF del acta de conteo físico firmable.

Mismo lenguaje visual que el cierre de tienda (`store_close_pdf`): tema oscuro,
cabecera de marca y tabla. Lista cada producto con stock teórico, conteo físico,
diferencia y estado, y un bloque de firma (Responsable / Revisado por / Folio)
que se rellena con el cierre guardado del día o deja líneas para firmar a mano.
"""
from datetime import datetime, timezone
from io import BytesIO
from typing import List

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from company_closing_pdf import (
    BG_DARK, BORDER, BRAND_PURPLE, GREEN, LOGO_PATH, PANEL, RED, TEXT,
    TEXT_MUTED,
)

_STATUS_ES = {
    "sin_conteo": "Sin conteo",
    "cuadra": "Cuadra",
    "faltante": "Faltante",
    "sobrante": "Sobrante",
    "ajustado": "Ajustado",
}


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
        except Exception:  # noqa: BLE001
            pass
    canvas.setFillColor(TEXT)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(96, h - 32, "RESILIENCE BROTHERS")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(96, h - 46, "Global P2P Trade Infrastructure")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 32, "ACTA DE CONTEO FÍSICO")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "PHYSICAL COUNT SHEET (IPV)")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com · CONFIDENCIAL")
    canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 38, w - 36, 38)
    canvas.restoreState()


def _table(headers: List[str], rows: List[list], widths: List[float],
           color_map=None) -> Table:
    data = [headers] + (rows if rows else [["—"] * len(headers)])
    tbl = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if color_map:
        for (r, c), color in color_map.items():
            style.append(("TEXTCOLOR", (c, r), (c, r), color))
    tbl.setStyle(TableStyle(style))
    return tbl


def _signature_block(styles, close: dict) -> Table:
    """Responsable / Revisado por / Folio — rellenados con el cierre guardado
    o con líneas en blanco para firmar a mano."""
    resp = (close or {}).get("responsable") or "______________________________"
    rev = (close or {}).get("revisado_por") or "______________________________"
    folio = (close or {}).get("folio") or "____________________"
    lbl = ParagraphStyle("sl", parent=styles["Normal"], textColor=TEXT_MUTED,
                         fontSize=8)
    val = ParagraphStyle("sv", parent=styles["Normal"], textColor=TEXT,
                         fontSize=10, fontName="Helvetica-Bold", spaceBefore=10)
    data = [
        [Paragraph("RESPONSABLE (PREPARÓ)", lbl), Paragraph("REVISADO POR", lbl)],
        [Paragraph(resp, val), Paragraph(rev, val)],
        [Paragraph("FOLIO DE CIERRE", lbl), Paragraph("FECHA / FIRMA", lbl)],
        [Paragraph(folio, val), Paragraph("______________________________", val)],
    ]
    tbl = Table(data, colWidths=[3.4 * inch, 3.4 * inch])
    tbl.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def build_count_sheet_pdf(sheet: dict) -> bytes:
    """sheet: payload de services.inventory_ipv.build_count_sheet."""
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], textColor=TEXT,
                           fontSize=16, alignment=0, spaceAfter=2)
    section = ParagraphStyle("s", parent=styles["Normal"], textColor=BRAND_PURPLE,
                             fontSize=10, fontName="Helvetica-Bold",
                             spaceBefore=14, spaceAfter=6)
    muted = ParagraphStyle("m", parent=styles["Normal"], textColor=TEXT_MUTED,
                           fontSize=8)

    rows = sheet.get("rows") or []
    table_rows = []
    color_map = {}
    for i, r in enumerate(rows, start=1):  # +1: fila 0 es la cabecera
        counted = r.get("counted")
        diff = r.get("difference")
        status = r.get("status") or "sin_conteo"
        table_rows.append([
            (r.get("name") or "")[:42],
            (r.get("category") or "")[:16],
            str(r.get("theoretical") if r.get("theoretical") is not None else "—"),
            "—" if counted is None else str(counted),
            "—" if diff is None else (f"+{diff}" if diff > 0 else str(diff)),
            _STATUS_ES.get(status, status),
        ])
        if status == "faltante":
            color_map[(i, 4)] = RED
            color_map[(i, 5)] = RED
        elif status == "sobrante":
            color_map[(i, 4)] = BRAND_PURPLE
            color_map[(i, 5)] = BRAND_PURPLE
        elif status == "cuadra":
            color_map[(i, 5)] = GREEN

    story = [
        Paragraph(f"Acta de conteo físico — {sheet['date']}", title),
        Paragraph(
            f"{sheet.get('productos_contados', 0)} de "
            f"{sheet.get('productos_activos', 0)} productos contados · "
            "el conteo no altera el arrastre; un ajuste autorizado lo corrige.",
            muted),
        Spacer(1, 10),
        Paragraph("CONTEO POR PRODUCTO", section),
        _table(
            ["Producto", "Categoría", "Teórico", "Conteo", "Diferencia", "Estado"],
            table_rows,
            [2.6, 1.3, 0.9, 0.9, 1.0, 1.1],
            color_map=color_map),
        Spacer(1, 26),
        Paragraph("REVISIÓN Y FIRMA", section),
        _signature_block(styles, sheet.get("close")),
    ]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, topMargin=90,
                            bottomMargin=54, leftMargin=36, rightMargin=36)
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
