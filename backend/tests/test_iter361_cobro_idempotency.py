"""SUN-09 — Repetir un cobro tras perder la respuesta NO debe duplicar efectos.

Bug: `POST /admin/pos/cobro` no tenía identidad persistente ni clave de
idempotencia; cada ejecución creaba movimientos con UUID nuevos, así que un
reintento tras una respuesta perdida registraba una SEGUNDA venta (stock −2,
ingreso ×2) para la misma intención de cobro.

Fix: el cliente genera una `idempotency_key` antes del primer envío; el backend
la registra de forma única (índice único) y en los reintentos devuelve el
resultado ya registrado. Reusar la clave con otro contenido => 409.

Criterio de cierre (cubierto aquí, en proceso sobre productos desechables):
  - Dos solicitudes CONSECUTIVAS con la misma clave → una sola venta.
  - Dos solicitudes CONCURRENTES con la misma clave → una sola venta.
  - Reusar la clave con contenido distinto → 409 (conflicto).
  - Una respuesta perdida es recuperable sin duplicación (mismo resultado).
"""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from db_client import db
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN
import routes.inventory as inv_mod


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_SUN09_{uuid.uuid4().hex[:8]}"
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


async def _inflow_total(pid):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1}).to_list(5000)
    ids = [m["id"] for m in movs]
    rows = await db.company_fund_adjustments.find(
        {"ref_id": {"$in": ids}, "adjustment_type": "inflow"},
        {"_id": 0, "amount": 1}).to_list(5000)
    return round(sum(float(r["amount"]) for r in rows), 2)


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


def _payload(pid, qty=1, paid=100, idem=""):
    return CobroIn(items=[CobroLine(product_id=pid, quantity=qty)],
                   paid=paid, idempotency_key=idem)


# ═══════════════ 1) Dos solicitudes CONSECUTIVAS (respuesta perdida) ════════
@pytest.mark.asyncio
async def test_same_key_consecutive_requests_charge_once():
    pid = await _mk(stock=10.0, price=100.0)
    idem = str(uuid.uuid4())
    try:
        r1 = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        # El cliente "pierde" la respuesta y reenvía EL MISMO cuerpo + clave.
        r2 = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        # Mismo resultado recuperado (mismo movimiento), no una venta nueva.
        assert r1["movements"][0]["id"] == r2["movements"][0]["id"]
        assert r1["total"] == r2["total"] == 100.0
        assert await _stock(pid) == 9.0          # un solo descuento
        assert await _ventas(pid) == 1           # una sola venta
        assert await _inflow_total(pid) == 100.0  # un solo ingreso
    finally:
        await _cleanup(pid)


# ═══════════════ 2) Dos solicitudes CONCURRENTES con la misma clave ═════════
@pytest.mark.asyncio
async def test_same_key_concurrent_requests_charge_once():
    pid = await _mk(stock=10.0, price=100.0)
    idem = str(uuid.uuid4())
    try:
        res = await asyncio.gather(
            pos_cobro(_payload(pid, 1, 100, idem), _admin_request()),
            pos_cobro(_payload(pid, 1, 100, idem), _admin_request()),
            return_exceptions=True)
        oks = [r for r in res if isinstance(r, dict)]
        errs = [r for r in res if isinstance(r, Exception)]
        # Al menos uno devuelve el cobro; el otro recupera el mismo o reporta
        # 'en proceso' (409) — nunca una segunda venta.
        assert oks, f"ningún éxito: {res}"
        for e in errs:
            assert isinstance(e, HTTPException) and e.status_code == 409
        assert await _stock(pid) == 9.0          # un solo descuento
        assert await _ventas(pid) == 1           # una sola venta lógica
        assert await _inflow_total(pid) == 100.0  # un solo ingreso
    finally:
        await _cleanup(pid)


# ═══════════════ 3) Misma clave, contenido distinto → 409 conflicto ════════
@pytest.mark.asyncio
async def test_same_key_different_content_conflicts():
    pid = await _mk(stock=10.0, price=100.0)
    idem = str(uuid.uuid4())
    try:
        await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        with pytest.raises(HTTPException) as ei:
            # Misma clave pero carrito distinto (2u / 200).
            await pos_cobro(_payload(pid, 2, 200, idem), _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "IDEMPOTENCY_KEY_CONFLICT"
        # El conflicto NO registra una segunda venta.
        assert await _stock(pid) == 9.0
        assert await _ventas(pid) == 1
    finally:
        await _cleanup(pid)


# ═══════════════ 4) Reintento de un cobro REVERTIDO no vuelve a cobrar ══════
@pytest.mark.asyncio
async def test_reversed_cobro_retry_is_not_recharged(monkeypatch):
    pid = await _mk(stock=10.0, price=100.0)
    idem = str(uuid.uuid4())
    real_impl = inv_mod._create_movement_impl

    async def _always_fail(payload, request, actor, *, cobro_id=""):
        raise HTTPException(status_code=400, detail="simulated failure")

    try:
        # Primer intento: falla a mitad → se revierte la operación entera.
        monkeypatch.setattr(inv_mod, "_create_movement_impl", _always_fail)
        with pytest.raises(HTTPException):
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        # Reintento con la MISMA clave (aunque ahora funcionara el registro):
        # debe reconocer que ese cobro ya terminó (revertido), no re-cobrar.
        monkeypatch.setattr(inv_mod, "_create_movement_impl", real_impl)
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "COBRO_REVERSED"
        assert await _stock(pid) == 10.0         # nunca se descontó nada
        assert await _ventas(pid) == 0
    finally:
        await _cleanup(pid)
