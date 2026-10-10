"""SUN-10 — El total validado debe ser EXACTAMENTE el total registrado.

Bug: el efectivo se comparaba contra un total ESTIMADO en la prevalidación,
pero el registro releía el precio del producto y redondeaba cada importe por
separado. El total final podía ser mayor que el validado → éxito con cambio
NEGATIVO.

  Caso A (precio concurrente): prevalida a 100 CUP y recibido 100; el precio
  sube a 200 antes de releer → se registra ingreso 200, change=-100.
  Caso B (redondeo): dos productos por kg a 1,75/kg, 0,5 kg c/u. Validaba
  round(0,875+0,875,2)=1,75 pero registraba 0,88+0,88=1,76 → change=-0,01.

Fix: se FIJA del lado servidor el precio, la cantidad normalizada y el importe
de cada línea; una sola política monetaria (redondeo por línea) para validar,
registrar y el ticket. Precio fijado pasado a record_movement → un cambio
concurrente no altera el total aprobado. Criterio de cierre: paid >= total y
change >= 0 para todo cobro aprobado.
"""
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN
import routes.inventory as inv_mod


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_SUN10_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return float((p or {}).get("stock") or 0)


async def _ventas(pid):
    return await db.inventory_movements.count_documents(
        {"product_id": pid, "type": "venta", "voided": {"$ne": True}})


async def _cleanup(*pids):
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
        mov_ids = [m["id"] for m in movs]
        cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mov_ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        await db.products.delete_many({"id": pid})
        await db.inventory_lots.delete_many({"product_id": pid})
        if cobro_ids:
            await db.pos_cobros.delete_many({"id": {"$in": cobro_ids}})


def _admin_request():
    scope = {
        "type": "http", "method": "POST", "path": "/api/admin/pos/cobro",
        "raw_path": b"/api/admin/pos/cobro", "query_string": b"",
        "headers": [(b"authorization", f"Bearer {ADMIN_TOKEN}".encode())],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 12345),
    }
    return Request(scope)


# ═══════════════ Caso A — cambio de precio concurrente no sobre-cobra ═══════
@pytest.mark.asyncio
async def test_case_a_concurrent_price_change_keeps_approved_total(monkeypatch):
    pid = await _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad")
    real = inv_mod._create_movement_impl

    async def _bump_then(payload, request, actor, *, cobro_id=""):
        # Simula cambio de precio concurrente ENTRE prevalidación y registro.
        await db.products.update_one({"id": payload.product_id},
                                     {"$set": {"price_usd": 200.0}})
        return await real(payload, request, actor, cobro_id=cobro_id)

    monkeypatch.setattr(inv_mod, "_create_movement_impl", _bump_then)
    try:
        payload = CobroIn(items=[CobroLine(product_id=pid, quantity=1)], paid=100)
        r = await pos_cobro(payload, _admin_request())
        # El precio FIJADO (100, el aprobado) se registra, NO los 200 concurrentes.
        assert r["total"] == 100.0
        assert r["paid"] == 100.0
        assert r["change"] == 0.0 and r["change"] >= 0   # nunca negativo
        assert r["movements"][0]["unit_price"] == 100.0
        assert r["movements"][0]["total"] == 100.0
    finally:
        await _cleanup(pid)


# ═══════════════ Caso B — redondeo por línea: rechaza pago insuficiente ═════
@pytest.mark.asyncio
async def test_case_b_rounding_rejects_underpayment_before_effects():
    a = await _mk(stock=10.0, price=1.75, cost=0.0, unit="kg")
    b = await _mk(stock=10.0, price=1.75, cost=0.0, unit="kg")
    try:
        # 0,88 + 0,88 = 1,76; recibir 1,75 ya NO alcanza (antes pasaba).
        payload = CobroIn(items=[CobroLine(product_id=a, quantity=0.5),
                                 CobroLine(product_id=b, quantity=0.5)], paid=1.75)
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(payload, _admin_request())
        assert ei.value.status_code == 400
        assert "insuficiente" in str(ei.value.detail).lower()
        # Rechazado ANTES de cualquier efecto: sin ventas, sin descuento.
        assert await _stock(a) == 10.0 and await _stock(b) == 10.0
        assert await _ventas(a) == 0 and await _ventas(b) == 0
    finally:
        await _cleanup(a, b)


# ═══════════════ Caso B — pago exacto: aprobado con cambio no negativo ══════
@pytest.mark.asyncio
async def test_case_b_rounding_accepts_exact_change_nonnegative():
    a = await _mk(stock=10.0, price=1.75, cost=0.0, unit="kg")
    b = await _mk(stock=10.0, price=1.75, cost=0.0, unit="kg")
    try:
        payload = CobroIn(items=[CobroLine(product_id=a, quantity=0.5),
                                 CobroLine(product_id=b, quantity=0.5)], paid=1.76)
        r = await pos_cobro(payload, _admin_request())
        assert r["total"] == 1.76           # 0,88 + 0,88 (misma política)
        assert r["paid"] == 1.76
        assert r["change"] == 0.0 and r["change"] >= 0
        # El total registrado == total validado.
        reg = round(sum(float(m["total"]) for m in r["movements"]), 2)
        assert reg == r["total"] == 1.76
        assert await _stock(a) == 9.5 and await _stock(b) == 9.5
    finally:
        await _cleanup(a, b)
