"""E34-05 — cancelar un envío NO debe devolver mercancía a una tienda
eliminada ni sellar éxito cuando el producto fue borrado.

Casos de cierre:
- Despachar → cerrar tienda → cancelar: la mercancía termina en el ALMACÉN
  CENTRAL (ubicación existente y auditable), nunca en un by_store huérfano.
- Despachar → borrar producto → cancelar: la devolución NO se puede aplicar;
  queda INCIDENCIA pendiente, nunca un sello de éxito sin efecto.
"""
import asyncio
import os
import sys
import uuid

import pytest
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import company_inventory as ci  # noqa: E402

CID = "user_test_e3405_company"


def _run(coro):
    """Ejecuta una corutina desde un test SÍNCRONO de forma robusta aunque un
    test async previo (pytest-asyncio) haya cerrado el loop del hilo. El
    fixture autouse de conftest resetea el binding de motor, así que el cliente
    se reenlaza al loop vigente en la primera operación."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _sync_db()
    db.products.delete_many({"company_id": CID})
    db.stores.delete_many({"company_id": CID})
    db.company_inventory_ops.delete_many({"company_id": CID})
    db.company_inventory_moves.delete_many({"company_id": CID})


@pytest.fixture(autouse=True)
def _around():
    _cleanup()
    yield
    _cleanup()


def _q(v):
    return round(float(v or 0), 3)


def test_return_to_deleted_store_lands_in_central():
    """Reservar 2 desde una tienda, borrar la tienda, devolver: el total sube,
    distributed NO sube y NO se crea by_store huérfano → la mercancía queda en
    el central (central = stock − distributed)."""
    db = _sync_db()
    sid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    # Producto con 10 total, 2 distribuidos a la tienda (central=8).
    db.products.insert_one({
        "id": pid, "name": "Prod E3405", "company_id": CID, "owner_id": CID,
        "stock": 10.0, "distributed": 2.0, "by_store": {sid: 2.0}, "is_active": True})
    db.stores.insert_one({"id": sid, "company_id": CID, "name": "Tienda X", "active": True})

    async def run():
        # Despacha 2 desde la tienda (reserva) → total 8, distributed 0, by_store 0.
        r1 = await ci.dispatch_from_store(CID, pid, sid, 2, op_id=f"disp:{uuid.uuid4()}")
        assert r1 == "applied"
        # Cierra/borra la tienda.
        db.stores.delete_one({"id": sid})
        # Devuelve (cancelación): la tienda ya no existe → va al central.
        r2 = await ci.return_dispatch(CID, pid, sid, 2, op_id=f"ret:{pid}:x")
        return r2

    res = _run(run())
    assert res == "applied"
    p = db.products.find_one({"id": pid}, {"_id": 0})
    # total vuelve a 10, distributed sigue 0 (central = 10), SIN by_store huérfano.
    assert _q(p["stock"]) == 10.0
    assert _q(p.get("distributed")) == 0.0
    assert _q((p.get("by_store") or {}).get(sid, 0)) == 0.0
    # central = stock - distributed = 10 (la mercancía está en una ubicación real)
    assert _q(p["stock"]) - _q(p.get("distributed")) == 10.0
    # El movimiento quedó registrado como devolución al central.
    mv = db.company_inventory_moves.find_one({"company_id": CID, "type": "dispatch_return_central"})
    assert mv is not None and _q(mv["qty"]) == 2.0


def test_return_when_product_deleted_reports_not_found():
    """Si el producto fue borrado, la devolución NO se aplica (not_found) →
    el llamador NO debe sellar éxito."""
    db = _sync_db()
    sid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    db.products.insert_one({
        "id": pid, "name": "Prod Del", "company_id": CID, "owner_id": CID,
        "stock": 10.0, "distributed": 2.0, "by_store": {sid: 2.0}, "is_active": True})
    db.stores.insert_one({"id": sid, "company_id": CID, "name": "Tienda Y", "active": True})

    async def run():
        r1 = await ci.dispatch_from_store(CID, pid, sid, 2, op_id=f"disp:{uuid.uuid4()}")
        assert r1 == "applied"
        db.products.delete_one({"id": pid})  # producto borrado
        return await ci.return_dispatch(CID, pid, sid, 2, op_id=f"ret:{pid}:del")

    res = _run(run())
    assert res == "not_found"
    assert db.products.find_one({"id": pid}) is None
