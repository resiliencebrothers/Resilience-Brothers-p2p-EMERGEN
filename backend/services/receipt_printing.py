"""iter356/iter357 — Impresión de ticket + apertura de GAVETA para SUNMI D3 Mini T1730.

El backend genera, de forma DETERMINISTA y testeable sin hardware:
  • `plaintext` — el ticket renderizado en monoespaciado (vista de SIMULACIÓN,
    idéntica a lo que imprimiría físicamente),
  • `escpos` — el flujo de comandos ESC/POS (estándar de impresoras térmicas)
    listo para enviar a la impresora de la SUNMI por el transporte elegido,
    incluyendo el LOGO del negocio en la cabecera (bitmap ESC/POS `GS v 0`) y,
    si se pide, el pulso de apertura de la gaveta (cash drawer kick).

La SUNMI T1730 lleva impresora térmica de 80 mm (48 col) o 58 mm (32 col) y su
gaveta se dispara por el conector RJ de la impresora mediante el comando ESC p.

NOTA DE VERIFICACIÓN FÍSICA: los BYTES ESC/POS son estándar y están verificados
por simulación/tests. El TRANSPORTE al equipo real usa el JS USDK oficial de
SUNMI (puente JS → `sendEscCommand`). Ver /app/memory/SUNMI_T1730_INTEGRATION.md.
"""
import base64
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

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
RASTER_HEADER = GS + b"v0"             # GS v 0: imagen rasterizada (logo)
# Pulso de la gaveta: ESC p m t1 t2 — pin 0 (conector estándar), 25ms on, 250ms off.
DRAWER_KICK = ESC + b"p\x00\x19\xfa"

WIDTH_80MM = 48   # columnas de la impresora de 80 mm
WIDTH_58MM = 32   # columnas de la impresora de 58 mm

# ── Logo del negocio para la cabecera del ticket ──────────────────────────
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_SOURCE = _ASSETS_DIR / "logo_original_black_bg.png"  # claro sobre fondo negro
_LOGO_CACHE: Dict[int, bytes] = {}


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
    # SEGURIDAD: la gaveta solo se abre cuando se pide EXPLÍCITAMENTE. Por defecto
    # NO (antes iba en True y abría la gaveta en tickets de prueba/reimpresiones).
    open_drawer: bool = False
    print_logo: bool = True             # imprimir el logo del negocio en cabecera


def _ascii(text: str) -> str:
    """Translitera a ASCII seguro (sin acentos) y ELIMINA bytes de control.

    1) Los acentos/ñ/¡ se transliteran (Café→Cafe) para que el PRIMER ticket
       físico salga legible sea cual sea la página de códigos del equipo.
    2) Se eliminan los caracteres de control (<0x20 y 0x7f): así ningún campo
       de texto de usuario puede inyectar comandos de impresora (ESC/GS) ni un
       pulso de gaveta. Solo sobrevive ASCII imprimible (0x20–0x7e)."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    out = norm.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in out if 0x20 <= ord(ch) <= 0x7e)


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


def _num(v: float) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


# ── Logo → bitmap ESC/POS (GS v 0) ────────────────────────────────────────
def _paper_dots(width_cols: int) -> int:
    """Puntos imprimibles del cabezal: 58 mm ≈ 384, 80 mm ≈ 576."""
    return 384 if width_cols == WIDTH_58MM else 576


def _render_logo_escpos(paper_dots: int) -> bytes:
    """Rasteriza el logo del negocio a ESC/POS `GS v 0` centrado en cabecera.

    El logo es CLARO sobre fondo negro: lo invertimos para que las zonas claras
    (letras/monograma) impriman como TINTA, y tramamos (dithering) para conservar
    las texturas. Determinista para una misma imagen de origen."""
    from PIL import Image, ImageOps  # import diferido (Pillow)

    img = Image.open(LOGO_SOURCE).convert("L")
    # Recorta el borde negro (fondo oscuro) para que el logo llene el ancho.
    bbox = img.point(lambda p: 255 if p > 30 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    # Escala al ~70% del ancho del papel (múltiplo de 8), con tope de altura.
    target_w = max(8, (int(paper_dots * 0.70) // 8) * 8)
    w, h = img.size
    target_h = max(1, round(h * target_w / w))
    max_h = 190
    if target_h > max_h:
        target_h = max_h
        target_w = max(8, (round(w * target_h / h) // 8) * 8)
    img = img.resize((target_w, target_h))
    bw = ImageOps.invert(img).convert("1")   # dithering; 0 = tinta, 255 = vacío
    bytes_per_row = target_w // 8            # target_w siempre múltiplo de 8
    # `tobytes()` de modo "1": blanco→bit1, negro→bit0, MSB primero y sin relleno
    # (fila alineada a byte). Invertimos (XOR 0xFF) para que la TINTA (negro) sea
    # bit=1 = punto impreso, como exige GS v 0.
    body = bytes(b ^ 0xFF for b in bw.tobytes())
    header = RASTER_HEADER + bytes([
        0x00,
        bytes_per_row & 0xFF, (bytes_per_row >> 8) & 0xFF,
        target_h & 0xFF, (target_h >> 8) & 0xFF,
    ])
    return bytes(header) + bytes(body)


def logo_raster(width_cols: int) -> bytes:
    """ESC/POS del logo (cacheado). Devuelve b'' si no hay logo o Pillow falla;
    la impresión NUNCA debe romperse por el logo (es decorativo)."""
    if width_cols in _LOGO_CACHE:
        return _LOGO_CACHE[width_cols]
    try:
        data = _render_logo_escpos(_paper_dots(width_cols))
    except Exception:  # pragma: no cover - el logo es decorativo
        data = b""
    _LOGO_CACHE[width_cols] = data
    return data


def render_plaintext(p: ReceiptPayload) -> str:
    """Vista de SIMULACIÓN: exactamente lo que imprimiría la térmica (ASCII)."""
    w = p.width
    sep = "-" * w
    lines: List[str] = []
    if p.print_logo and logo_raster(p.width):
        lines.append(_center("[ LOGO ]", w))
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
    for amt_label, amt in (("Subtotal", p.subtotal), ("Descuento", p.discount),
                           ("Impuesto", p.tax)):
        if amt is not None:
            lines.append(_two_col(amt_label, _money(amt, p.currency), w))
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


def _line(text: str) -> bytes:
    return _ascii(text).encode("ascii", "replace") + b"\n"


def build_escpos(p: ReceiptPayload) -> bytes:
    """Flujo ESC/POS determinista del ticket (logo + pulso de gaveta opcional)."""
    w = p.width
    out = bytearray()
    out += INIT
    # Logo del negocio (bitmap) centrado en la cabecera, si está activo.
    if p.print_logo:
        logo = logo_raster(p.width)
        if logo:
            out += ALIGN_CENTER + logo + b"\n"
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
    for amt_label, amt in (("Subtotal", p.subtotal), ("Descuento", p.discount),
                           ("Impuesto", p.tax)):
        if amt is not None:
            out += _line(_two_col(amt_label, _money(amt, p.currency), w))
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
        "print_logo": payload.print_logo,
        "has_logo": bool(payload.print_logo and logo_raster(payload.width)),
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
        currency="CUP", open_drawer=False,
    )
