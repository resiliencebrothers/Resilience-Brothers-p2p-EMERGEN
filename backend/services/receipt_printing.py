"""iter356 — Impresión de ticket + apertura de GAVETA para SUNMI D3 Mini T1730.

El backend genera, de forma DETERMINISTA y testeable sin hardware:
  • `plaintext` — el ticket renderizado en monoespaciado (vista de SIMULACIÓN,
    idéntica a lo que imprimiría físicamente),
  • `escpos` — el flujo de comandos ESC/POS (estándar de impresoras térmicas)
    listo para enviar a la impresora de la SUNMI por el transporte elegido,
    incluyendo, si se pide, el pulso de apertura de la gaveta (cash drawer kick).

La SUNMI T1730 lleva impresora térmica de 80 mm (48 col) o 58 mm (32 col) y su
gaveta se dispara por el conector RJ de la impresora mediante el comando ESC p.

NOTA DE VERIFICACIÓN FÍSICA: los BYTES ESC/POS son estándar y están verificados
por simulación/tests. Lo único que debe confirmarse con el equipo real es el
TRANSPORTE (cómo llega el byte array a la impresora: p.ej. middleware SUNMI
"JS USDK" por WebSocket) y la página de códigos para acentos. Ver
/app/memory/SUNMI_T1730_INTEGRATION.md.
"""
import base64
import unicodedata
from typing import List, Optional

from pydantic import BaseModel, Field

# ── Comandos ESC/POS ──────────────────────────────────────────────────────
ESC = b"\x1b"
GS = b"\x1d"
INIT = ESC + b"@"                      # inicializa la impresora
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
ALIGN_RIGHT = ESC + b"a\x02"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
SIZE_DOUBLE = GS + b"!\x11"            # alto y ancho x2
SIZE_NORMAL = GS + b"!\x00"
FULL_CUT = GS + b"V\x00"               # corte total (autocortador del modelo 80mm)
# Pulso de la gaveta: ESC p m t1 t2 — pin 0 (conector estándar), 25ms on, 250ms off.
DRAWER_KICK = ESC + b"p\x00\x19\xfa"

WIDTH_80MM = 48   # columnas de la impresora de 80 mm
WIDTH_58MM = 32   # columnas de la impresora de 58 mm


class ReceiptItem(BaseModel):
    name: str
    qty: float = 1
    unit: str = ""
    unit_price: float = 0
    total: float = 0


class ReceiptPayload(BaseModel):
    business_name: str = "Resilience Brothers"
    business_line2: str = ""            # dirección
    business_line3: str = ""            # teléfono / RNC
    ticket_no: str = ""
    datetime: str = ""
    cashier: str = ""
    items: List[ReceiptItem] = Field(default_factory=list)
    currency: str = "CUP"
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    tax: Optional[float] = None
    total: float = 0
    paid: Optional[float] = None
    change: Optional[float] = None
    footer: str = "¡Gracias por su compra!"
    width: int = WIDTH_80MM             # 48 (80mm) o 32 (58mm)
    open_drawer: bool = True            # añadir el pulso de gaveta al ticket


def _ascii(text: str) -> str:
    """Translitera a ASCII seguro (sin acentos) para garantizar que el PRIMER
    ticket físico salga legible sea cual sea la página de códigos del equipo.
    El soporte pleno de acentos/página de códigos es un ajuste de verificación
    física (ver doc). La vista de simulación usa ESTE mismo texto para ser fiel."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    out = norm.encode("ascii", "ignore").decode("ascii")
    return out


def _money(v: Optional[float], currency: str) -> str:
    if v is None:
        return ""
    return f"{v:,.2f} {currency}"


def _two_col(left: str, right: str, width: int) -> str:
    """Dos columnas: `left` a la izquierda, `right` pegado a la derecha."""
    left = _ascii(left)
    right = _ascii(right)
    if len(left) + len(right) + 1 > width:
        left = left[: max(0, width - len(right) - 1)]
    pad = max(1, width - len(left) - len(right))
    return left + (" " * pad) + right


def _wrap(text: str, width: int) -> List[str]:
    text = _ascii(text)
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w[:width]
    if cur:
        lines.append(cur)
    return lines or [""]


def _center(text: str, width: int) -> str:
    text = _ascii(text)
    if len(text) >= width:
        return text[:width]
    pad = (width - len(text)) // 2
    return (" " * pad) + text


def render_plaintext(p: ReceiptPayload) -> str:
    """Vista de SIMULACIÓN: exactamente lo que imprimiría la térmica (ASCII)."""
    w = p.width
    sep = "-" * w
    lines: List[str] = []
    lines.append(_center(p.business_name, w))
    for extra in (p.business_line2, p.business_line3):
        if extra:
            lines.append(_center(extra, w))
    lines.append(sep)
    if p.ticket_no:
        lines.append(_two_col("Ticket:", p.ticket_no, w))
    if p.datetime:
        lines.append(_two_col("Fecha:", p.datetime, w))
    if p.cashier:
        lines.append(_two_col("Atendio:", p.cashier, w))
    lines.append(sep)
    for it in p.items:
        lines.append(_ascii(it.name)[:w])
        qty_unit = f"{_num(it.qty)}{(' ' + it.unit) if it.unit else ''}"
        detail = f"{qty_unit} x {_money(it.unit_price, p.currency)}"
        lines.append(_two_col("  " + detail, _money(it.total, p.currency), w))
    lines.append(sep)
    for label, val in (("Subtotal", p.subtotal), ("Descuento", p.discount),
                       ("Impuesto", p.tax)):
        if val is not None:
            lines.append(_two_col(label, _money(val, p.currency), w))
    lines.append(_two_col("TOTAL", _money(p.total, p.currency), w))
    if p.paid is not None:
        lines.append(_two_col("Pagado", _money(p.paid, p.currency), w))
    if p.change is not None:
        lines.append(_two_col("Cambio", _money(p.change, p.currency), w))
    lines.append(sep)
    if p.footer:
        for fl in _wrap(p.footer, w):
            lines.append(_center(fl, w))
    return "\n".join(lines)


def _num(v: float) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def build_escpos(p: ReceiptPayload) -> bytes:
    """Flujo ESC/POS determinista del ticket (+ pulso de gaveta opcional)."""
    w = p.width
    out = bytearray()
    out += INIT
    # Cabecera centrada y en negrita grande el nombre del negocio.
    out += ALIGN_CENTER
    out += BOLD_ON + SIZE_DOUBLE + _line(p.business_name) + SIZE_NORMAL + BOLD_OFF
    for extra in (p.business_line2, p.business_line3):
        if extra:
            out += _line(extra)
    out += ALIGN_LEFT
    out += _line("-" * w)
    for label, val in (("Ticket:", p.ticket_no), ("Fecha:", p.datetime),
                       ("Atendio:", p.cashier)):
        if val:
            out += _line(_two_col(label, val, w))
    out += _line("-" * w)
    for it in p.items:
        out += _line(_ascii(it.name)[:w])
        qty_unit = f"{_num(it.qty)}{(' ' + it.unit) if it.unit else ''}"
        detail = f"  {qty_unit} x {_money(it.unit_price, p.currency)}"
        out += _line(_two_col(detail, _money(it.total, p.currency), w))
    out += _line("-" * w)
    for label, val in (("Subtotal", p.subtotal), ("Descuento", p.discount),
                       ("Impuesto", p.tax)):
        if val is not None:
            out += _line(_two_col(label, _money(val, p.currency), w))
    out += BOLD_ON + _line(_two_col("TOTAL", _money(p.total, p.currency), w)) + BOLD_OFF
    if p.paid is not None:
        out += _line(_two_col("Pagado", _money(p.paid, p.currency), w))
    if p.change is not None:
        out += _line(_two_col("Cambio", _money(p.change, p.currency), w))
    out += _line("-" * w)
    out += ALIGN_CENTER
    if p.footer:
        for fl in _wrap(p.footer, w):
            out += _line(fl)
    out += ALIGN_LEFT
    out += b"\n\n\n"            # avance antes del corte
    out += FULL_CUT
    if p.open_drawer:
        out += DRAWER_KICK
    return bytes(out)


def _line(text: str) -> bytes:
    return _ascii(text).encode("ascii", "replace") + b"\n"


def drawer_kick_escpos() -> bytes:
    """Solo abrir la gaveta (sin imprimir). INIT + pulso de gaveta."""
    return INIT + DRAWER_KICK


def build_receipt(payload: ReceiptPayload) -> dict:
    """Devuelve la vista de simulación y el ESC/POS en base64 para el transporte."""
    escpos = build_escpos(payload)
    return {
        "plaintext": render_plaintext(payload),
        "escpos_b64": base64.b64encode(escpos).decode("ascii"),
        "escpos_len": len(escpos),
        "width": payload.width,
        "open_drawer": payload.open_drawer,
    }


def sample_payload() -> ReceiptPayload:
    """Ticket de ejemplo para la prueba de simulación."""
    from datetime import datetime, timezone
    return ReceiptPayload(
        business_name="Resilience Brothers",
        business_line2="Mercado & Inventario",
        business_line3="Tel: +53 5 000 0000",
        ticket_no="TEST-0001",
        datetime=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        cashier="admin",
        items=[
            ReceiptItem(name="Café molido Premium", qty=2, unit="lb",
                        unit_price=350.0, total=700.0),
            ReceiptItem(name="Azúcar refino", qty=1, unit="kg",
                        unit_price=180.0, total=180.0),
        ],
        subtotal=880.0, total=880.0, paid=1000.0, change=120.0,
        currency="CUP", open_drawer=True,
    )
