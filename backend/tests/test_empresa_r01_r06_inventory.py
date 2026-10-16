"""R01 — el índice único de idempotencia NO debe romperse con documentos antiguos
sin `client_key`, y R06 — una devolución durante el CIERRE de la tienda va al
CENTRAL (no recrea una estantería huérfana)."""
import uuid

import pytest

from db_client import db
from services import company_inventory as ci
from routes.company import _ensure_cdeliv_index
import routes.company as company_routes

pytestmark = pytest.mark.asyncio

CID = "user_test_empresa_r01r06"


async def _clean():
    await db.products.delete_many({"company_id": CID})
    await db.stores.delete_many({"company_id": CID})
    await db.company_delivery_requests.delete_many({"company_id": CID})
    await db.company_inventory_ops.delete_many({"company_id": CID})


async def test_r01_partial_index_tolerates_legacy_docs_without_client_key():
    await _clean()
    # Reconstruye el índice desde cero para probar la construcción real.
    for name in ("uniq_company_client_key_str", "company_id_1_client_key_1"):
        try:
            await db.company_delivery_requests.drop_index(name)
        except Exception:
            pass
    company_routes._CDELIV_IDX_READY = False
    try:
        # DOS documentos antiguos de la misma empresa SIN client_key: con un
        # índice sparse compuesto colisionarían en ('CID', null) e impedirían
        # crear el índice. Con el índice PARCIAL ($type string) se excluyen.
        await db.company_delivery_requests.insert_many([
            {"id": str(uuid.uuid4()), "company_id": CID, "status": "requested"},
            {"id": str(uuid.uuid4()), "company_id": CID, "status": "requested"},
        ])
        # Construir el índice NO debe fallar sobre esos datos antiguos.
        await _ensure_cdeliv_index()
        # Y las claves VÁLIDAS nuevas siguen siendo únicas por empresa.
        k = "K-UNIQ"
        await db.company_delivery_requests.insert_one(
            {"id": str(uuid.uuid4()), "company_id": CID, "client_key": k,
             "status": "initializing"})
        from pymongo.errors import DuplicateKeyError
        dup = False
        try:
            await db.company_delivery_requests.insert_one(
                {"id": str(uuid.uuid4()), "company_id": CID, "client_key": k,
                 "status": "initializing"})
        except DuplicateKeyError:
            dup = True
        assert dup, "la misma client_key debe seguir siendo única por empresa"
    finally:
        await _clean()


async def test_r06_return_during_store_closing_goes_to_central():
    await _clean()
    sid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    try:
        # Tienda EN CIERRE y producto con 2 uds despachadas (central=stock-distrib).
        await db.stores.insert_one(
            {"id": sid, "company_id": CID, "name": "S", "active": True,
             "status": "closing"})
        await db.products.insert_one({
            "id": pid, "name": "P", "company_id": CID, "owner_id": CID,
            "stock": 8.0, "distributed": 0.0, "by_store": {}, "is_active": True})
        # Devolución de 2 uds: como la tienda está en CIERRE, va al CENTRAL
        # (sube stock, NO recrea by_store ni distributed).
        status = await ci.return_dispatch(CID, pid, sid, 2.0,
                                          op_id=f"ret-{uuid.uuid4().hex}")
        assert status == "applied"
        p = await db.products.find_one({"id": pid}, {"_id": 0})
        assert round(float(p["stock"]), 3) == 10.0
        assert round(float(p.get("distributed") or 0), 3) == 0.0
        assert round(float((p.get("by_store") or {}).get(sid) or 0), 3) == 0.0
    finally:
        await _clean()


async def test_r06_reclaim_sweep_removes_orphan_shelf():
    await _clean()
    sid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    try:
        # Estantería HUÉRFANA residual (by_store con una tienda ya inexistente).
        await db.products.insert_one({
            "id": pid, "name": "P", "company_id": CID, "owner_id": CID,
            "stock": 10.0, "distributed": 2.0, "by_store": {sid: 2.0}, "is_active": True})
        n = await ci.reclaim_store_shelf_to_central(CID, sid)
        assert n == 1
        p = await db.products.find_one({"id": pid}, {"_id": 0})
        assert round(float(p["stock"]), 3) == 10.0  # stock total intacto
        assert round(float(p.get("distributed") or 0), 3) == 0.0  # a central
        assert sid not in (p.get("by_store") or {})  # sin estantería huérfana
        # Idempotente.
        assert await ci.reclaim_store_shelf_to_central(CID, sid) == 0
    finally:
        await _clean()
