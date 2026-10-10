"""iter356 — POS / Caja: impresión de ticket y apertura de gaveta (SUNMI T1730).

Todos los endpoints requieren permiso 'products' (staff de tienda). El backend
solo GENERA el ESC/POS determinista; el frontend lo envía por el transporte
elegido (simulación / SUNMI WebSocket / navegador). Ver doc de integración.
"""
import logging
from typing import Any, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from auth_utils import require_permission
from services.receipt_printing import (ReceiptPayload, ReceiptItem, build_receipt,
                                        drawer_kick_escpos, sample_payload)
import base64
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(tags=["POS"])


class CobroLine(BaseModel):
    product_id: str
    quantity: float = Field(..., gt=0, le=1_000_000)


class CobroIn(BaseModel):
    """Cobro real MULTI-LÍNEA en Caja: registra las ventas del carrito + imprime
    UN ticket con total/pagado/cambio + abre la gaveta. Efectivo OBLIGATORIO."""
    items: List[CobroLine] = Field(..., min_length=1)
    paid: float = Field(..., ge=0)         # efectivo recibido (OBLIGATORIO)
    note: str = Field("", max_length=300)
    # SUN-09 — identidad de cobro generada por el cliente ANTES del primer
    # envío. Hace el cobro IDEMPOTENTE: un reintento tras perder la respuesta
    # devuelve el resultado ya registrado en vez de volver a cobrar. Reusar la
    # clave con un carrito distinto produce 409 (conflicto).
    idempotency_key: str = Field("", max_length=80)
    # Estilo del ticket (viene de la configuración de la pestaña Caja).
    business_name: str = "Resilience Brothers"
    business_line2: str = ""
    business_line3: str = ""
    footer: str = "¡Gracias por su compra!"
    currency: str = "CUP"
    width: int = 48
    print_logo: bool = True


_POS_IDEM_INDEX_READY = False


def _cobro_fingerprint(consolidated: list, paid: float, currency: str) -> str:
    """SUN-09 — huella del CONTENIDO del cobro (líneas + efectivo + moneda).
    Reusar la misma clave con otra huella = conflicto (409)."""
    import hashlib
    import json
    canon = {
        "items": sorted([[str(pid), round(float(q), 3)] for pid, q in consolidated]),
        "paid": round(float(paid), 2),
        "currency": (currency or "").upper(),
    }
    raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _ensure_idem_index(db: Any) -> None:
    global _POS_IDEM_INDEX_READY
    if not _POS_IDEM_INDEX_READY:
        await db.pos_cobros.create_index("idempotency_key", unique=True,
                                         sparse=True)
        _POS_IDEM_INDEX_READY = True


async def _resolve_existing_cobro(db: Any, idem: str, fp: str) -> Any:
    """SUN-09 — resuelve un cobro que ya existe para esta clave:
    - huella distinta → 409 (clave reusada con otro carrito).
    - 'committed' con resultado → lo DEVUELVE (recupera la respuesta perdida).
    - 'reversed' → 409 (el intento anterior no se completó; usa carrito nuevo).
    - 'committing'/'reversing' (concurrente) → espera breve y, si no termina,
      409 'en proceso'. Dos concurrentes con la misma clave => UNA sola venta.
    """
    import asyncio
    existing = await db.pos_cobros.find_one({"idempotency_key": idem}, {"_id": 0})
    for _ in range(26):   # ~10 s de espera para el perdedor de la carrera
        if not existing:
            break
        if fp and existing.get("fingerprint") and existing["fingerprint"] != fp:
            raise HTTPException(status_code=409, detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": ("Esta clave de cobro ya se usó con un carrito "
                            "distinto. Vacía el carrito y vuelve a intentar.")})
        state = existing.get("state")
        if state == "committed" and existing.get("result"):
            return existing["result"]
        if state == "reversed":
            raise HTTPException(status_code=409, detail={
                "code": "COBRO_REVERSED",
                "message": (existing.get("reverse_reason")
                            or "El cobro anterior con esta clave no se completó. "
                               "Revisa el carrito e inténtalo de nuevo.")})
        await asyncio.sleep(0.4)
        existing = await db.pos_cobros.find_one(
            {"idempotency_key": idem}, {"_id": 0})
    raise HTTPException(status_code=409, detail={
        "code": "COBRO_IN_PROGRESS",
        "message": ("Un cobro con esta clave está en proceso. "
                    "Reintenta en unos segundos.")})




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
    """COBRO REAL multi-línea: registra todas las ventas del carrito (descuento
    de stock ATÓMICO por línea), construye UN ticket con el total combinado, el
    efectivo recibido y el cambio, y ABRE SIEMPRE la gaveta.

    Reglas:
    - El efectivo recibido es OBLIGATORIO y debe cubrir el total (si no → 400).
    - PRE-VALIDA todo el carrito (producto, VIP, cantidad entera, stock) ANTES de
      registrar nada: si una línea falla, NO se cobra nada.
    - Ante un fallo durante el registro (p.ej. carrera de stock), se REVIERTE el
      stock de las líneas ya aplicadas para no dejar un cobro parcial.
    - Reimpresión ≠ cobro: la gaveta se abre siempre aquí; en reimpresiones no.
    Autorización: permiso de caja 'products', sin PIN."""
    actor = await require_permission(request, "products")
    from routes.inventory import _create_movement_impl, MovementCreate
    from services.inventory import (norm_qty, sells_fraction, qnum,
                                     reverse_cobro)
    from db_client import db
    from pymongo.errors import DuplicateKeyError
    import uuid

    # ── 0) CONSOLIDAR líneas repetidas del mismo producto (SUN-08) ──
    # La UI combina duplicados, pero la API no puede confiar en ello: dos
    # líneas de 1u de un producto con stock=1 pasarían la prevalidación
    # individual y dejarían un cobro parcial al fallar la segunda aplicación.
    agg: dict = {}
    order: list = []
    for ln in payload.items:
        if ln.product_id not in agg:
            agg[ln.product_id] = 0.0
            order.append(ln.product_id)
        agg[ln.product_id] += float(ln.quantity)
    consolidated = [(pid, agg[pid]) for pid in order]

    # ── SUN-09: IDEMPOTENCIA. La huella del contenido + la clave del cliente
    #   hacen que un reintento tras perder la respuesta devuelva el resultado
    #   ya registrado (no vuelve a cobrar). Chequeo temprano: si la clave ya
    #   existe, resolvemos SIN re-ejecutar la prevalidación (el stock pudo
    #   cambiar; un cobro ya confirmado debe recuperarse igual). ──
    idem = (payload.idempotency_key or "").strip()
    fp = _cobro_fingerprint(consolidated, payload.paid, payload.currency)
    if idem:
        await _ensure_idem_index(db)
        if await db.pos_cobros.find_one({"idempotency_key": idem}, {"_id": 1}):
            return await _resolve_existing_cobro(db, idem, fp)

    # ── 1) PRE-VALIDACIÓN de TODO el carrito (aún no registra nada) ──
    lines: list = []
    for pid, raw_q in consolidated:
        product = await db.products.find_one({"id": pid}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404,
                                detail=f"Producto no encontrado: {pid}")
        name = product.get("name", "")
        if product.get("owner_id"):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' es de un vendedor VIP y no entra al inventario de la empresa")
        if raw_q <= 0:
            raise HTTPException(status_code=400, detail=f"Cantidad inválida para '{name}'")
        # La fracción se valida sobre la cantidad CRUDA (igual que create_movement):
        # norm_qty redondearía 1.5→2 y ocultaría el error.
        if not sells_fraction(product) and raw_q != int(raw_q):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' se vende por unidad: la cantidad debe ser un número entero")
        qty = norm_qty(product, raw_q)   # normalizada para comparar con el stock
        stock = float(product.get("stock") or 0)
        if qty > stock:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente de '{name}' (disponible {qnum(stock)}, pedido {qnum(qty)})")
        lines.append((product, raw_q, qty))

    # El efectivo recibido es OBLIGATORIO y debe cubrir el total estimado.
    est_total = round(sum(float(p.get("price_usd") or 0) * q for p, _raw, q in lines), 2)
    paid = round(float(payload.paid), 2)
    if paid < est_total:
        raise HTTPException(
            status_code=400,
            detail=(f"Efectivo insuficiente: recibido {paid:,.2f}, "
                    f"total {est_total:,.2f} {payload.currency}"))

    # ── 2) RECLAMAR la operación de cobro (SUN-09). El índice único sobre
    #   `idempotency_key` garantiza que dos envíos concurrentes con la misma
    #   clave sólo creen UNA venta lógica: el ganador cobra, el perdedor
    #   recupera su resultado. Sin clave (llamador directo de API) se registra
    #   sin dedup. La operación es también recuperable ante fallos (SUN-08). ──
    cobro_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {"id": cobro_id, "state": "committing", "mov_ids": [],
           "fingerprint": fp,
           "actor_id": (actor or {}).get("user_id", ""),
           "actor_email": (actor or {}).get("email", ""),
           "created_at": now_iso, "updated_at": now_iso}
    if idem:
        doc["idempotency_key"] = idem
        try:
            await db.pos_cobros.insert_one(doc)
        except DuplicateKeyError:
            # Carrera: otro envío con la misma clave ganó el reclamo.
            return await _resolve_existing_cobro(db, idem, fp)
    else:
        await db.pos_cobros.insert_one(doc)

    committed: list = []
    try:
        for product, raw_q, _qty in lines:
            mc = MovementCreate.model_validate({
                "product_id": product["id"], "type": "venta",
                "quantity": raw_q, "note": payload.note})
            mov = await _create_movement_impl(mc, request, actor,
                                              cobro_id=cobro_id)
            committed.append(mov)
            await db.pos_cobros.update_one(
                {"id": cobro_id},
                {"$push": {"mov_ids": mov["id"]},
                 "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}})
    except Exception as exc:
        reason = str(getattr(exc, "detail", "") or exc)[:300]
        await db.pos_cobros.update_one(
            {"id": cobro_id},
            {"$set": {"state": "reversing",
                      "updated_at": datetime.now(timezone.utc).isoformat()}})
        try:
            await reverse_cobro(cobro_id, actor)
            await db.pos_cobros.update_one(
                {"id": cobro_id},
                {"$set": {"state": "reversed", "reverse_reason": reason,
                          "updated_at": datetime.now(timezone.utc).isoformat()}})
        except Exception as e:  # noqa: BLE001
            # Compensación interrumpida: `heal_pending_cobros` la completará.
            logger.error(f"cobro {cobro_id} reversal incomplete: {e}")
        raise

    movs = committed
    total = round(sum(float(m.get("total") or 0) for m in movs), 2)
    change = round(paid - total, 2)
    rp = ReceiptPayload(
        business_name=payload.business_name, business_line2=payload.business_line2,
        business_line3=payload.business_line3, footer=payload.footer,
        currency=payload.currency,
        width=(32 if int(payload.width) == 32 else 48),
        print_logo=payload.print_logo,
        ticket_no=str(movs[0]["id"])[:8].upper(),
        datetime=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        cashier=(actor or {}).get("email", ""),
        items=[ReceiptItem(
            name=m.get("product_name") or m["product_id"],
            qty=m["quantity"], unit=m.get("unit", ""),
            unit_price=m.get("unit_price", 0), total=m.get("total", 0)) for m in movs],
        subtotal=total, total=total, paid=paid, change=change,
        open_drawer=True,   # SIEMPRE en un cobro real (no respeta el toggle).
    )
    result = {"movements": movs, "total": total, "paid": paid, "change": change,
              **build_receipt(rp)}
    # SUN-09 — marca 'committed' y CACHEA el resultado en una sola escritura
    # durable: un reintento con la misma clave recupera exactamente esta
    # respuesta sin volver a cobrar.
    await db.pos_cobros.update_one(
        {"id": cobro_id},
        {"$set": {"state": "committed", "result": result,
                  "updated_at": datetime.now(timezone.utc).isoformat()}})
    return result
