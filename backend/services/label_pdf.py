"""iter228 — PDF de etiquetas con código de barras para la tienda física.

Hoja A4 con rejilla 3×8 (24 etiquetas de 63.5×33.9 mm, formato adhesivo
estándar). Cada etiqueta: nombre, precio y código de barras (EAN-13 para
códigos numéricos de 12/13 dígitos, Code128 para el resto).
"""
from io import BytesIO
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

LABEL_W = 63.5 * mm
LABEL_H = 33.9 * mm
COLS, ROWS = 3, 8
PAGE_W, PAGE_H = A4
MARGIN_X = (PAGE_W - COLS * LABEL_W) / 2
MARGIN_Y = (PAGE_H - ROWS * LABEL_H) / 2


def _barcode_drawing(code: str) -> Any:
    if code.isdigit() and len(code) in (12, 13):
        return createBarcodeDrawing("EAN13", value=code[:12],
                                    barHeight=14 * mm, humanReadable=True)
    return createBarcodeDrawing("Code128", value=code[:30],
                                barHeight=14 * mm, humanReadable=True,
                                fontSize=6)


def _draw_label(c: canvas.Canvas, x: float, y: float,
                name: str, price: float, code: str) -> None:
    c.setLineWidth(0.3)
    c.setDash(1, 2)
    c.rect(x + 0.5 * mm, y + 0.5 * mm, LABEL_W - 1 * mm, LABEL_H - 1 * mm)
    c.setDash()
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(x + LABEL_W / 2, y + LABEL_H - 3.5 * mm, name[:42])
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + LABEL_W / 2, y + LABEL_H - 7.5 * mm,
                        f"$ {price:g}")
    d = _barcode_drawing(code)
    avail = LABEL_W - 6 * mm
    if d.width > avail:
        f = avail / d.width
        d.scale(f, f)
        d.width *= f
        d.height *= f
    renderPDF.draw(d, c, x + (LABEL_W - d.width) / 2, y + 1.5 * mm)


def build_labels_pdf(items: list, copies: int = 1) -> bytes:
    """items: dicts con name, price_usd y barcode (ya asignado)."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    slot = 0
    for item in items:
        for _ in range(max(1, copies)):
            if slot == COLS * ROWS:
                c.showPage()
                slot = 0
            col, row = slot % COLS, slot // COLS
            x = MARGIN_X + col * LABEL_W
            y = PAGE_H - MARGIN_Y - (row + 1) * LABEL_H
            _draw_label(c, x, y, item.get("name", ""),
                        float(item.get("price_usd") or 0),
                        item.get("barcode", ""))
            slot += 1
    c.showPage()
    c.save()
    return buf.getvalue()
