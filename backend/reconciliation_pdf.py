"""iter146 — Collection-account reconciliation PDF.

One-click accounting hand-off: daily inflow per collection account
(P2P orders + VIP batch items with account snapshot), confirmed vs
pending, plus per-currency grand totals. Same dark branding + signed
footer used by every other PDF the platform issues.
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
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
    canvas.drawRightString(w - 36, h - 32, "CONCILIACIÓN")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "ACCOUNT RECONCILIATION REPORT")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com · CONFIDENCIAL")
    canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 38, w - 36, 38)
    canvas.restoreState()


def _fmt(n) -> str:
    return f"{float(n or 0):,.2f}"


_TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), PANEL),
    ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
    ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
    ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
    ("TEXTCOLOR", (3, 1), (3, -1), GREEN),
    ("TEXTCOLOR", (4, 1), (4, -1), AMBER),
    ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
])


def _detail_table(rows: List[dict]) -> Table:
    """Per-day/per-account detail rows."""
    data = [["Fecha", "Cuenta", "Moneda", "Confirmado", "Pendiente", "Total", "Ops"]]
    for r in rows:
        data.append([
            r["date"], r["label"], r["currency_code"],
            _fmt(r["confirmed"]), _fmt(r["pending"]), _fmt(r["total"]),
            str(int(r.get("count_confirmed", 0)) + int(r.get("count_pending", 0))),
        ])
    if len(data) == 1:
        data.append(["—", "Sin movimientos en el período", "", "", "", "", ""])
    table = Table(data, colWidths=[58, 190, 46, 72, 72, 72, 30], repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    return table


def _currency_totals_table(rows: List[dict]) -> Optional[Table]:
    """Per-currency grand totals; None when there are no rows."""
    by_cur: dict = {}
    for r in rows:
        c = by_cur.setdefault(r["currency_code"], {"confirmed": 0.0, "pending": 0.0})
        c["confirmed"] += float(r["confirmed"])
        c["pending"] += float(r["pending"])
    if not by_cur:
        return None
    tdata = [["Moneda", "", "", "Confirmado", "Pendiente", "Total", ""]]
    for code in sorted(by_cur):
        c = by_cur[code]
        tdata.append([
            code, "", "", _fmt(c["confirmed"]), _fmt(c["pending"]),
            _fmt(c["confirmed"] + c["pending"]), "",
        ])
    totals = Table(tdata, colWidths=[58, 190, 46, 72, 72, 72, 30])
    totals.setStyle(_TABLE_STYLE)
    return totals


def generate_reconciliation_pdf(rows: List[dict], start: str,
                                account_label: str, actor: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15,
                           textColor=TEXT, spaceAfter=4)
    muted = ParagraphStyle("m", fontName="Helvetica", fontSize=8,
                           textColor=TEXT_MUTED, spaceAfter=2)
    section = ParagraphStyle("s", fontName="Helvetica-Bold", fontSize=10,
                             textColor=BRAND_PURPLE, spaceBefore=14, spaceAfter=6)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    story: list = [
        Paragraph("Conciliación de cuentas de cobro", title),
        Paragraph(f"Período: {start} al {today} (días UTC)", muted),
        Paragraph(f"Cuenta: {account_label or 'Todas las cuentas'}", muted),
        Paragraph(
            f"Generado por: {actor.get('name') or actor.get('email') or 'admin'}",
            muted,
        ),
        Spacer(1, 10),
        Paragraph("DETALLE POR DÍA Y CUENTA", section),
        _detail_table(rows),
    ]

    totals = _currency_totals_table(rows)
    if totals is not None:
        story.append(Paragraph("TOTALES DEL PERÍODO POR MONEDA", section))
        story.append(totals)

    story.append(Paragraph(
        "<font color='#A3A3A3' size=7>* Confirmado = órdenes aprobadas/completadas "
        "e ítems de lote VIP aprobados. Pendiente = operaciones aún en revisión. "
        "Los rechazos no se incluyen. Día contable en UTC.</font>",
        muted,
    ))
    story.append(Spacer(1, 26))
    story.append(build_signature_block(lang="es", include_client_side=False))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
