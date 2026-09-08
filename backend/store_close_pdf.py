"""iter231 — PDF del cierre diario de la tienda física.

Mismo lenguaje visual que el cierre de empresa (tema oscuro, tarjetas,
firma y sello via pdf_signature) pero acotado a la caja del día de la
tienda: ventas, compras, ganancia y caja neta en CUP efectivo, más la
línea de ventas web en USDT y el desglose por producto.
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
    TEXT_MUTED, _summary_card_row,
)
from pdf_signature import build_signature_block


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
    canvas.drawRightString(w - 36, h - 32, "CIERRE TIENDA FÍSICA")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 46, "DAILY STORE CLOSING")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com · CONFIDENCIAL")
    canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 38, w - 36, 38)
    canvas.restoreState()


def _table(headers: List[str], rows: List[list], widths: List[float]) -> Table:
    data = [headers] + (rows if rows else [["—"] * len(headers)])
    tbl = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl


def build_store_close_pdf(close: dict) -> bytes:
    """close: payload de services.inventory.build_daily_close."""
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], textColor=TEXT,
                           fontSize=16, alignment=0, spaceAfter=2)
    section = ParagraphStyle("s", parent=styles["Normal"], textColor=BRAND_PURPLE,
                             fontSize=10, fontName="Helvetica-Bold",
                             spaceBefore=14, spaceAfter=6)
    muted = ParagraphStyle("m", parent=styles["Normal"], textColor=TEXT_MUTED,
                           fontSize=8)

    cur = close["store_currency"]
    fis, web = close["fisica"], close["web"]
    rec = close.get("recogidas") or {"num": 0, "unidades": 0,
                                     "total_usdt": 0.0, "detalle": []}

    def _hhmm(iso_str):
        try:
            from zoneinfo import ZoneInfo
            return datetime.fromisoformat(iso_str).astimezone(
                ZoneInfo("America/Havana")).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            return ""
    story = [
        Paragraph(f"Cierre de tienda física — {close['date']}", title),
        Paragraph(f"Caja del día en {cur} efectivo · hora de Cuba", muted),
        Spacer(1, 12),
        _summary_card_row(styles, [
            {"label": "VENTAS TIENDA",
             "value": f"{fis['ventas']:,.2f} {cur}", "color": "#22C55E"},
            {"label": "COMPRAS MERCANCÍA",
             "value": f"{fis['compras']:,.2f} {cur}", "color": "#F59E0B"},
            {"label": "GANANCIA TIENDA",
             "value": f"{fis['ganancia']:,.2f} {cur}",
             "color": "#22C55E" if fis["ganancia"] >= 0 else "#EF4444"},
            {"label": "CAJA NETA EFECTIVO",
             "value": f"{fis['caja_neta']:+,.2f} {cur}",
             "color": "#22C55E" if fis["caja_neta"] >= 0 else "#EF4444"},
        ]),
        Spacer(1, 8),
        Paragraph(
            f"Ventas tienda: {fis['unidades_vendidas']} unidad(es) en "
            f"{fis['num_ventas']} venta(s) · Compras: "
            f"{fis['unidades_compradas']} unidad(es) en "
            f"{fis['num_compras']} entrada(s)", muted),
        Paragraph("VENTAS WEB (USDT)", section),
        _summary_card_row(styles, [
            {"label": "COBRADO EN USDT",
             "value": f"{web['ventas_usdt']:,.2f} USDT", "color": "#8B5CF6"},
            {"label": f"EQUIVALENTE {cur}",
             "value": f"{web['ventas_store']:,.2f} {cur}"},
            {"label": "CANJES",
             "value": f"{web['unidades']} ud. / {web['num_ventas']} canje(s)"},
            {"label": "GANANCIA WEB",
             "value": f"{web['ganancia']:,.2f} {cur}",
             "color": "#22C55E" if web["ganancia"] >= 0 else "#EF4444"},
        ]),
        Paragraph("ENTREGAS EN TIENDA (RECOGIDAS DEL DÍA)", section),
        Paragraph(
            f"{rec['unidades']} unidad(es) entregadas en {rec['num']} "
            f"recogida(s) web · valor {rec['total_usdt']:,.2f} USDT "
            "(cobrado al canjear; la mercancía salió del estante hoy)", muted),
        _table(
            ["Hora", "Cliente", "Producto", "Ud.", "Sucursal", "USDT"],
            [[_hhmm(p.get("delivered_at") or ""),
              (p.get("user_name") or "")[:22],
              (p.get("product_name") or "")[:28], str(p.get("quantity") or 0),
              (p.get("store_name") or "")[:18],
              f"{float(p.get('total_usd') or 0):,.2f}"]
             for p in rec["detalle"]],
            [0.7, 1.6, 2.0, 0.5, 1.3, 1.0]),
        Paragraph("VENDIDO EN EL DÍA", section),
        _table(
            ["Producto", "Unidades", "De ellas web", f"Total {cur}", "Ganancia"],
            [[p["name"][:46], str(p["unidades"] + p["unidades_web"]),
              str(p["unidades_web"]), f"{p['total']:,.2f}",
              f"{p['ganancia']:,.2f}"] for p in close["productos"]],
            [3.0, 1.0, 1.1, 1.2, 1.1]),
        Paragraph("MERCANCÍA COMPRADA EN EL DÍA", section),
        _table(
            ["Producto", "Unidades", f"Total {cur}"],
            [[p["name"][:56], str(p["unidades"]), f"{p['total']:,.2f}"]
             for p in close["compras_detalle"]],
            [4.4, 1.4, 1.6]),
        Spacer(1, 26),
        build_signature_block(lang="es", include_client_side=False),
    ]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, topMargin=90,
                            bottomMargin=54, leftMargin=36, rightMargin=36)
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
