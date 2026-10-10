"""SUN-08-R2 (variante pendiente) — CONFIRMACIÓN GUARDADA CON RESPUESTA PERDIDA.

Bug: la escritura final `committing→committed` (con `result`) vive dentro del
`try`. Si Mongo GUARDA esa escritura pero el driver lanza un error de red al
esperar el ACK, se ejecutaba el `except`, que reclamaba `committing→reversing`
SIN verificar `matched_count` y llamaba igualmente a `reverse_cobro`. Resultado
incoherente: `state=committed` + `result` exitoso apuntando a una venta ANULADA
(stock restaurado, neto 0, voided=True).

Fundamento (PyMongo): un NetworkTimeout durante una escritura NO permite deducir,
solo por la excepción, si la escritura se completó. Por eso la app debe manejar
el error que recibe sin asumir que no hubo escritura.

Fix: el reclamo atómico `committing→reversing` (CAS) es la única fuente de verdad.
- matched_count==1 → la confirmación NO persistió → compensamos (reverse_cobro).
- matched_count==0 → re-leemos el estado real:
    · committed+result → la confirmación SÍ persistió (solo se perdió la
      respuesta): CONSERVAMOS efectos y RECUPERAMOS el result.
    · reversing/reversed/indeterminado → NO compensamos nosotros; 409 coherente.

Criterio de aceptación cubierto: inyectar error DESPUÉS de persistir la
confirmación y también ANTES de persistirla; reintentar con la misma clave.
Debe sobrevivir UN único resultado coherente.
"""
import uuid

import pytest
from fastapi import HTTPException
from pymongo.errors import NetworkTimeout
from starlette.requests import Request

from db_client import db
from routes.pos import pos_cobro, CobroIn, CobroLine
from tests.conftest import ADMIN_TOKEN


async def _mk(stock=10.0, price=100.0, cost=60.0, unit="unidad"):
    pid = f"TEST_R2V_{uuid.uuid4().hex[:8]}"
    await db.products.insert_one({
        "id": pid, "name": pid, "category": "test", "price_usd": price,
        "cost_usd": cost, "stock": stock, "unit": unit, "is_active": True})
    return pid


async def _stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return round(float((p or {}).get("stock") or 0), 3)


async def _fund_net(pid):
    movs = await db.inventory_movements.find(
        {"product_id": pid}, {"_id": 0, "id": 1}).to_list(5000)
    ids = [m["id"] for m in movs]
    rows = await db.company_fund_adjustments.find(
        {"ref_id": {"$in": ids}}, {"_id": 0, "adjustment_type": 1, "amount": 1}
    ).to_list(5000)
    net = 0.0
    for r in rows:
        a = float(r["amount"])
        net += a if r["adjustment_type"] == "inflow" else -a
    return round(net, 2)


async def _cleanup(*pids):
    for pid in pids:
        movs = await db.inventory_movements.find(
            {"product_id": pid}, {"_id": 0, "id": 1, "cobro_id": 1}).to_list(5000)
        mov_ids = [m["id"] for m in movs]
        cobro_ids = [m.get("cobro_id") for m in movs if m.get("cobro_id")]
        await db.company_fund_adjustments.delete_many({"ref_id": {"$in": mov_ids}})
        await db.inventory_movements.delete_many({"product_id": pid})
        for mid in mov_ids:
            await db.stock_ops.delete_many(
                {"op_id": {"$in": [f"invmov:{mid}", f"invmov:{mid}:burn",
                                   f"invmov:{mid}:undo"]}})
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


def _is_confirm(update):
    """La ÚNICA escritura con $set.state == 'committed' es la confirmación."""
    return (((update or {}).get("$set") or {}).get("state")) == "committed"


# ═══ 1) Error DESPUÉS de persistir la confirmación: la respuesta se pierde pero
#        los efectos quedan. Debe RECUPERARSE el result, nunca revertir. ═══════
@pytest.mark.asyncio
async def test_confirm_persisted_then_lost_response_recovers_result(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    Coll = type(db.pos_cobros)
    real_update_one = Coll.update_one

    async def _update_then_drop(self, flt, update=None, *a, **kw):
        res = await real_update_one(self, flt, update, *a, **kw)
        if self.name == "pos_cobros" and _is_confirm(update):
            # La confirmación YA se guardó; el driver pierde el ACK de red.
            raise NetworkTimeout("ACK perdido tras persistir la confirmación")
        return res

    monkeypatch.setattr(Coll, "update_one", _update_then_drop)
    try:
        # La respuesta de Mongo se perdió, pero la confirmación persistió: la
        # petición debe RECUPERAR el resultado coherente, no revertir la venta.
        r = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert r["total"] == 100.0 and r["paid"] == 100.0 and r["change"] == 0.0

        monkeypatch.undo()

        # Estado coherente: committed con result; la venta NO quedó anulada.
        cobro = await db.pos_cobros.find_one({"idempotency_key": idem}, {"_id": 0})
        assert cobro["state"] == "committed" and cobro.get("result")
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v.get("voided") is not True and v.get("cobro_aborted") is not True
        assert await _stock(pid) == S - 1
        assert await _fund_net(pid) == 100.0

        # Reintento con la misma clave: devuelve el MISMO resultado, sin cobrar
        # de nuevo ni duplicar efectos.
        r2 = await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert r2["total"] == 100.0 and r2["change"] == 0.0
        assert await _stock(pid) == S - 1 and await _fund_net(pid) == 100.0
    finally:
        monkeypatch.undo()
        await _cleanup(pid)


# ═══ 2) Error ANTES de persistir la confirmación: la venta NO se confirmó →
#        se revierte entero (neto cero). El reintento reporta revertido. ═══════
@pytest.mark.asyncio
async def test_confirm_fails_before_persist_reverts_whole_cobro(monkeypatch):
    S = 10.0
    pid = await _mk(stock=S, price=100.0)
    idem = str(uuid.uuid4())
    Coll = type(db.pos_cobros)
    real_update_one = Coll.update_one

    async def _raise_before_commit(self, flt, update=None, *a, **kw):
        if self.name == "pos_cobros" and _is_confirm(update):
            # El error llega ANTES de que la confirmación toque la base.
            raise NetworkTimeout("escritura perdida antes de confirmar")
        return await real_update_one(self, flt, update, *a, **kw)

    monkeypatch.setattr(Coll, "update_one", _raise_before_commit)
    try:
        with pytest.raises(NetworkTimeout):
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())

        monkeypatch.undo()

        # El cobro no se confirmó → reverso íntegro, neto cero, sin result.
        assert await _stock(pid) == S
        assert await _fund_net(pid) == 0.0
        cobro = await db.pos_cobros.find_one({"idempotency_key": idem}, {"_id": 0})
        assert cobro["state"] == "reversed"
        assert not cobro.get("result")
        v = await db.inventory_movements.find_one(
            {"product_id": pid, "type": "venta"}, {"_id": 0})
        assert v["voided"] is True and v["cobro_aborted"] is True

        # Reintento con la misma clave: NUNCA un éxito falso; reporta revertido.
        with pytest.raises(HTTPException) as ei:
            await pos_cobro(_payload(pid, 1, 100, idem), _admin_request())
        assert ei.value.status_code == 409
        assert ei.value.detail["code"] == "COBRO_REVERSED"
        assert await _stock(pid) == S and await _fund_net(pid) == 0.0
    finally:
        monkeypatch.undo()
        await _cleanup(pid)
