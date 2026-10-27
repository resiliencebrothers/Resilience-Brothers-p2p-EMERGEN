"""EF — "Depósitos sin Confirmar": efectivo RECOGIDO por un mensajero pero aún
NO confirmado por el admin, derivado de REGISTROS REALES de depósitos y expuesto
APARTE del `unreconciled_diff` (residual contable opaco).

Solo cuenta un depósito cuando es `method=cash`, lo recogió un mensajero
(`courier_custody_inflow=True`) y sigue `pending`. Un depósito confirmado o uno
de oficina (sin recogida de mensajero) NO suma. Pruebas por DELTA para ser
robustas frente a datos ya existentes en la BD.
"""
import os

import pytest
from pymongo import MongoClient

from services import courier_cash as cc

_IDS = ["eftest_collected", "eftest_confirmed", "eftest_office"]


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def _currency() -> str:
    curs = sorted(await cc.physical_cash_currencies())
    assert curs, "debe haber al menos una moneda de efectivo físico configurada"
    return curs[0]


@pytest.fixture
def _clean():
    db = _db()
    db.deposits.delete_many({"id": {"$in": _IDS}})
    yield db
    db.deposits.delete_many({"id": {"$in": _IDS}})


@pytest.mark.asyncio
async def test_only_courier_collected_pending_cash_counts(_clean):
    db = _clean
    cur = await _currency()
    base = (await cc.collected_unconfirmed_deposits_by_currency()).get(cur) \
        or {"amount": 0.0, "count": 0}
    # 1) depósito cash recogido por mensajero y pendiente → SÍ cuenta.
    db.deposits.insert_one({
        "id": "eftest_collected", "currency": cur, "amount": 5000.0,
        "method": "cash", "status": "pending", "courier_custody_inflow": True})
    after1 = (await cc.collected_unconfirmed_deposits_by_currency())[cur]
    assert round(after1["amount"] - base["amount"], 2) == 5000.0
    assert after1["count"] - base["count"] == 1
    # 2) confirmado + oficina (sin recogida de mensajero) → NO suman.
    db.deposits.insert_many([
        {"id": "eftest_confirmed", "currency": cur, "amount": 9000.0,
         "method": "cash", "status": "confirmed", "courier_custody_inflow": True},
        {"id": "eftest_office", "currency": cur, "amount": 3000.0,
         "method": "cash", "status": "pending"},
    ])
    after2 = (await cc.collected_unconfirmed_deposits_by_currency())[cur]
    assert round(after2["amount"] - base["amount"], 2) == 5000.0
    assert after2["count"] - base["count"] == 1


@pytest.mark.asyncio
async def test_reconciliation_row_exposes_field_separate_from_unreconciled(_clean):
    db = _clean
    cur = await _currency()
    rows0 = await cc.reconciliation_by_currency()
    r0 = next((r for r in rows0 if r["currency"] == cur), None)
    assert r0 is not None
    base = r0["deposits_collected_unconfirmed"]
    db.deposits.insert_one({
        "id": "eftest_collected", "currency": cur, "amount": 5000.0,
        "method": "cash", "status": "pending", "courier_custody_inflow": True})
    rows = await cc.reconciliation_by_currency()
    r = next((x for x in rows if x["currency"] == cur), None)
    assert r is not None
    # Campo NUEVO presente y SEPARADO del residual opaco.
    assert "deposits_collected_unconfirmed" in r
    assert "deposits_collected_unconfirmed_count" in r
    assert "unreconciled_diff" in r
    assert round(r["deposits_collected_unconfirmed"] - base, 2) == 5000.0
    assert r["deposits_collected_unconfirmed_count"] >= 1
