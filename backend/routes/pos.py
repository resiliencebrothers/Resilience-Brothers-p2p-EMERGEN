"""iter356 — POS / Caja: impresión de ticket y apertura de gaveta (SUNMI T1730).

Todos los endpoints requieren permiso 'products' (staff de tienda). El backend
solo GENERA el ESC/POS determinista; el frontend lo envía por el transporte
elegido (simulación / SUNMI WebSocket / navegador). Ver doc de integración.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from auth_utils import require_permission
from services.receipt_printing import (ReceiptPayload, ReceiptItem, build_receipt,
                                        drawer_kick_escpos, sample_payload)
import base64
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(tags=["POS"])


class CobroIn(BaseModel):
    """Cobro real en Caja: registra la venta + imprime ticket + abre la gaveta."""
    product_id: str
    quantity: float = Field(..., gt=0, le=1_000_000)
    unit_price: Optional[float] = Field(None, ge=0)  # None → precio de venta del producto
    note: str = Field("", max_length=300)
    # Estilo del ticket (viene de la configuración de la pestaña Caja).
    business_name: str = "Resilience Brothers"
    business_line2: str = ""
    business_line3: str = ""
    footer: str = "¡Gracias por su compra!"
    currency: str = "CUP"
    width: int = 48
    print_logo: bool = True


@router.post("/admin/pos/receipt/build")
async def pos_build_receipt(payload: ReceiptPayload, request: Request) -> Any:
    """Construye un ticket: devuelve la vista de simulación (plaintext) y el
    flujo ESC/POS en base64 listo para imprimir."""
    await require_permission(request, "products")
    return build_receipt(payload)


@router.get("/admin/pos/receipt/sample")
async def pos_sample_receipt(request: Request, width: int = 48,
                             open_drawer: bool = False,
                             print_logo: bool = True) -> Any:
    """Ticket de ejemplo (para la prueba de simulación).

    Respeta los toggles de la UI: la gaveta solo se incluye si `open_drawer`
    es True; el logo solo si `print_logo` es True."""
    await require_permission(request, "products")
    p = sample_payload()
    p.width = 32 if int(width) == 32 else 48
    p.open_drawer = bool(open_drawer)
    p.print_logo = bool(print_logo)
    return {"payload": p.model_dump(), **build_receipt(p)}


@router.get("/admin/pos/drawer/open")
async def pos_open_drawer(request: Request) -> Any:
    """Devuelve el ESC/POS del pulso de apertura de la gaveta (cash drawer)."""
    await require_permission(request, "products")
    data = drawer_kick_escpos()
    return {"escpos_b64": base64.b64encode(data).decode("ascii"),
            "escpos_len": len(data)}


@router.post("/admin/pos/cobro")
async def pos_cobro(payload: CobroIn, request: Request) -> Any:
    """COBRO REAL: registra la venta (descuenta stock atómicamente por el flujo
    estándar de inventario), construye el ticket y ABRE SIEMPRE la gaveta.

    A diferencia de una reimpresión (que es una copia y NUNCA abre la gaveta),
    este es el evento de caja original: la gaveta se abre siempre, sin depender
    del toggle "Abrir gaveta al imprimir". Autorización: permiso de caja
    'products' (lo valida `create_movement`), sin PIN adicional."""
    # Reutiliza TODO el flujo transaccional/validación/auditoría de inventario
    # (producto existe, no es de vendedor VIP, cantidad entera si no fracciona,
    # descuento de stock atómico con control de stock insuficiente → 400).
    from routes.inventory import create_movement, MovementCreate
    mc = MovementCreate.model_validate({
        "product_id": payload.product_id, "type": "venta",
        "quantity": payload.quantity, "unit_price": payload.unit_price,
        "note": payload.note,
    })
    mov = await create_movement(mc, request)
    rp = ReceiptPayload(
        business_name=payload.business_name, business_line2=payload.business_line2,
        business_line3=payload.business_line3, footer=payload.footer,
        currency=payload.currency,
        width=(32 if int(payload.width) == 32 else 48),
        print_logo=payload.print_logo,
        ticket_no=str(mov["id"])[:8].upper(),
        datetime=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        cashier=mov.get("actor_email", ""),
        items=[ReceiptItem(
            name=mov.get("product_name") or mov["product_id"],
            qty=mov["quantity"], unit=mov.get("unit", ""),
            unit_price=mov.get("unit_price", 0), total=mov.get("total", 0))],
        subtotal=mov.get("total", 0), total=mov.get("total", 0),
        open_drawer=True,   # SIEMPRE en un cobro real (no respeta el toggle).
    )
    return {"movement": mov, **build_receipt(rp)}
