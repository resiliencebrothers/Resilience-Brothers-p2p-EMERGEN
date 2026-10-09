"""iter356 — POS / Caja: impresión de ticket y apertura de gaveta (SUNMI T1730).

Todos los endpoints requieren permiso 'products' (staff de tienda). El backend
solo GENERA el ESC/POS determinista; el frontend lo envía por el transporte
elegido (simulación / SUNMI WebSocket / navegador). Ver doc de integración.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request

from auth_utils import require_permission
from services.receipt_printing import (ReceiptPayload, build_receipt,
                                        drawer_kick_escpos, sample_payload)
import base64

logger = logging.getLogger(__name__)
router = APIRouter(tags=["POS"])


@router.post("/admin/pos/receipt/build")
async def pos_build_receipt(payload: ReceiptPayload, request: Request) -> Any:
    """Construye un ticket: devuelve la vista de simulación (plaintext) y el
    flujo ESC/POS en base64 listo para imprimir."""
    await require_permission(request, "products")
    return build_receipt(payload)


@router.get("/admin/pos/receipt/sample")
async def pos_sample_receipt(request: Request, width: int = 48) -> Any:
    """Ticket de ejemplo (para la prueba de simulación)."""
    await require_permission(request, "products")
    p = sample_payload()
    p.width = 32 if int(width) == 32 else 48
    return {"payload": p.model_dump(), **build_receipt(p)}


@router.get("/admin/pos/drawer/open")
async def pos_open_drawer(request: Request) -> Any:
    """Devuelve el ESC/POS del pulso de apertura de la gaveta (cash drawer)."""
    await require_permission(request, "products")
    data = drawer_kick_escpos()
    return {"escpos_b64": base64.b64encode(data).decode("ascii"),
            "escpos_len": len(data)}
