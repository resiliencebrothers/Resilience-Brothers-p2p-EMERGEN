"""iter263 — Espejo Fondo de Empresa (efectivo) → Caja de Efectivo.

Verifica:
1. Un ajuste manual en efectivo CUP con desglose crea automáticamente un
   movimiento (con billetes) en la caja de empresa «Fondo Resilience».
2. Salida en efectivo → movimiento tipo `salida` (resta balance y billetes).
3. Backfill: los ajustes históricos sin espejo se replican una sola vez
   (idempotente, conserva created_at); monedas sin billetes CUP/USD no aplican.
4. Los movimientos espejados NO se pueden editar ni borrar desde la caja (409).
5. Nomenclatura única: el efectivo cubano es solo «CUP» — ningún otro código
   se trata como billetes CUP (decisión de negocio, Jun 2026).
"""
import asyncio
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER263-TEST"
BOX_NAME = "Fondo Resilience"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    db = _db()
    db.company_fund_adjustments.delete_many({"source_name": MARK})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})


def _adjust(body):
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin(body))


def _company_box():
    return _db().cash_boxes.find_one({"scope": "empresa", "name": BOX_NAME},
                                     {"_id": 0})


def _resumen(box_id, fund):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _base_state(fund):
    box = _company_box()
    if not box:
        return 0.0, {}
    res = _resumen(box["id"], fund)
    return float(res["balance"]), {r["denom"]: r["qty"]
                                   for r in res["denominaciones"]}


def test_cash_inflow_mirrors_to_company_cash_box():
    _cleanup()
    bal0, den0 = _base_state("CUP")
    try:
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 4500, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 3, "500": 2, "100": 5}})
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc.get("cash_box_movement_id"), \
            "el ajuste debe enlazar su movimiento de caja"

        box = _company_box()
        assert box and box.get("is_active"), \
            "la caja de empresa «Fondo Resilience» debe existir"

        mov = _db().cash_box_movements.find_one(
            {"id": doc["cash_box_movement_id"]}, {"_id": 0})
        assert mov, "el movimiento espejo debe existir en la caja"
        assert mov["box_id"] == box["id"]
        assert mov["fund"] == "CUP" and mov["type"] == "entrada"
        assert mov["amount"] == 4500.0
        assert mov["denominations"] == {"1000": 3, "500": 2, "100": 5}
        assert mov["source_adjustment_id"] == doc["id"]
        assert mov["created_at"] == doc["created_at"]
        assert MARK in mov["concept"]

        bal1, den1 = _base_state("CUP")
        assert round(bal1 - bal0, 2) == 4500.0, \
            "el balance de la caja debe subir el monto del ajuste"
        assert den1.get(1000, 0) - den0.get(1000, 0) == 3
        assert den1.get(500, 0) - den0.get(500, 0) == 2
        assert den1.get(100, 0) - den0.get(100, 0) == 5
    finally:
        _cleanup()


def test_cash_outflow_mirrors_salida():
    _cleanup()
    bal0, den0 = _base_state("USD")
    try:
        r = _adjust({"adjustment_type": "outflow", "currency": "USD",
                     "amount": 120, "method": "cash", "source_name": MARK,
                     "denominations": {"100": 1, "20": 1}})
        assert r.status_code == 200, r.text
        doc = r.json()
        mov = _db().cash_box_movements.find_one(
            {"id": doc["cash_box_movement_id"]}, {"_id": 0})
        assert mov and mov["fund"] == "USD" and mov["type"] == "salida"

        bal1, den1 = _base_state("USD")
        assert round(bal1 - bal0, 2) == -120.0, \
            "la salida de capital debe RESTAR de la caja"
        assert den1.get(100, 0) - den0.get(100, 0) == -1
        assert den1.get(20, 0) - den0.get(20, 0) == -1
    finally:
        _cleanup()


def test_backfill_replicates_legacy_stock_once():
    """El stock histórico (ajustes previos a esta función) entra a la caja
    con su fecha original; correr el backfill dos veces nunca duplica."""
    _cleanup()
    db = _db()
    aid = f"cfadj_{uuid.uuid4().hex[:12]}"
    eur_id = f"cfadj_{uuid.uuid4().hex[:12]}"
    legacy_at = "2025-11-15T10:00:00+00:00"
    db.company_fund_adjustments.insert_one({
        "id": aid, "adjustment_type": "inflow", "currency": "CUP",
        "amount": 3000.0, "method": "cash", "source_name": MARK,
        "source_account": "", "note": "", "account_id": "",
        "account_label": "", "denominations": {"1000": 3},
        "actor_id": "u_legacy", "actor_email": "legacy@test.com",
        "actor_name": "Legacy", "created_at": legacy_at})
    # moneda sin billetes CUP/USD — no aplica al espejo
    db.company_fund_adjustments.insert_one({
        "id": eur_id, "adjustment_type": "inflow", "currency": "EUR",
        "amount": 500.0, "method": "cash", "source_name": MARK,
        "source_account": "", "note": "", "account_id": "",
        "account_label": "", "denominations": None,
        "actor_id": "u_legacy", "actor_email": "legacy@test.com",
        "actor_name": "Legacy", "created_at": legacy_at})
    try:
        async def flow():
            from services.cash_box_sync import backfill_cash_adjustments
            n1 = await backfill_cash_adjustments()
            n2 = await backfill_cash_adjustments()
            return n1, n2

        n1, n2 = _run(flow)
        assert n1 >= 1, "el backfill debe replicar el ajuste histórico"
        assert n2 == 0, "el segundo backfill no debe re-procesar nada"

        movs = list(db.cash_box_movements.find(
            {"source_adjustment_id": aid}, {"_id": 0}))
        assert len(movs) == 1, f"exactamente un movimiento por ajuste: {len(movs)}"
        assert movs[0]["created_at"] == legacy_at, \
            "el histórico conserva su fecha original"
        assert movs[0]["denominations"] == {"1000": 3}

        assert db.cash_box_movements.count_documents(
            {"source_adjustment_id": eur_id}) == 0, \
            "EUR no tiene billetes CUP/USD — no entra a la caja"
        eur = db.company_fund_adjustments.find_one({"id": eur_id}, {"_id": 0})
        assert eur.get("cash_box_movement_id") == "na", \
            "los no aplicables se marcan DEFINITIVOS para no re-escanear (V03)"
    finally:
        _cleanup()


def test_mirrored_movement_locked_in_cash_box():
    _cleanup()
    try:
        r = _adjust({"adjustment_type": "inflow", "currency": "CUP",
                     "amount": 1000, "method": "cash", "source_name": MARK,
                     "denominations": {"1000": 1}})
        assert r.status_code == 200, r.text
        doc = r.json()
        box = _company_box()
        mid = doc["cash_box_movement_id"]

        r = requests.put(f"{API}/cashbox/boxes/{box['id']}/movimientos/{mid}",
                         headers=_hdr(ADMIN_TOKEN), json={"amount": 999})
        assert r.status_code == 409, \
            f"editar un movimiento espejado debe dar 409: {r.status_code}"
        r = requests.delete(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mid}",
            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 409, \
            f"borrar un movimiento espejado debe dar 409: {r.status_code}"
        assert _db().cash_box_movements.find_one({"id": mid}), \
            "el movimiento espejado sigue intacto"
    finally:
        _cleanup()


def test_cup_is_the_only_cash_nomenclature():
    """Decisión de negocio: el CUP efectivo usa una sola nomenclatura («CUP»).
    Ningún otro código se mapea a billetes CUP ni exige desglose."""
    from services.cash_box_sync import fund_for_currency
    from routes.admin_company_funds import CASH_DENOMINATIONS
    assert fund_for_currency("CUP") == "CUP"
    assert fund_for_currency("USD") == "USD"
    assert fund_for_currency("CUPE") is None, \
        "CUPE no existe como nomenclatura de efectivo"
    assert fund_for_currency("CUPT") is None
    assert set(CASH_DENOMINATIONS.keys()) == {"CUP", "USD"}
