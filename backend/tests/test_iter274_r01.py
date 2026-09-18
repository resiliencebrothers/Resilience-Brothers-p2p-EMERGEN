"""iter274 — Revisión Flujo de Caja (commit 591c886): pendiente R01.

R01 (continuación de Q02): un marcador «na» que sobrevivió a una
consolidación ANTERIOR (la versión 70d3eaf re-apuntó el vínculo a la cuenta
canónica SIN retirar «na») queda fuera de todas las consultas del
recuperador: la contabilidad incluye la transferencia pero la caja no. La
reparación reevalúa los «na» cuyos vínculos apuntan HOY a la cuenta de caja
canónica, sin depender de que aún contengan el id del alias.
"""
import uuid
import os
import asyncio
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER274"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _cleanup():
    db = _db()
    db.fund_account_transfers.delete_many({"note": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    db.cash_box_arqueos.delete_many({"note": {"$regex": MARK}})
    db.fund_accounts.delete_many({"name": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.withdrawals.delete_many({"user_name": {"$regex": MARK}})


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


def _run_backfill():
    async def _f():
        from services.cash_box_sync import backfill_cash_operations
        return await backfill_cash_operations()
    return _run(_f)


def _usd_cash():
    async def _f():
        from services.fund_accounts import get_or_create_cash_box
        return await get_or_create_cash_box("USD")
    return _run(_f)


def _resumen(box_id, fund="USD"):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _auto_box():
    return _db().cash_boxes.find_one({"system_purpose": "company_cash"},
                                     {"_id": 0})


def _usd_denoms_for(amount):
    left = max(int(amount), 0)
    out = {}
    for d in (100, 50, 20, 10, 5, 2, 1):
        q, left = divmod(left, d)
        if q:
            out[str(d)] = q
    return out or {"1": 0}


def _mk_arqueo(box_id, counted):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/arqueos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": "USD", "counted": counted, "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()


def _closing_valid(box_id):
    async def _f():
        from services.cash_box_arqueo import closing_arqueo_status
        return await closing_arqueo_status(box_id, "USD")
    return _run(_f)


def _mk_bank(db):
    banco_id = f"facc_{uuid.uuid4().hex[:12]}"
    db.fund_accounts.insert_one({
        "id": banco_id, "name": f"{MARK} banco", "currency": "USD",
        "method": "bank", "is_active": True, "created_at": _iso_now()})
    return banco_id


class TestR01NaSurvivorAfterPriorRepoint:
    def teardown_method(self, _):
        _cleanup()

    def test_na_survivor_recovered_once_and_idempotent(self):
        """Aceptación R01: estado final de 70d3eaf — destino YA canónico,
        transferencia confirmada y marcador «na». Una recuperación deja
        cuenta y caja con la entrada de 40 (exactamente UNA) y el arqueo
        previo invalidado; la segunda conserva los mismos valores."""
        _cleanup()
        db = _db()
        _run_backfill()  # drenar pendientes ajenos
        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        # alias histórico ya fusionado: existe pero NADA lo referencia ya
        alias_id = f"facc_{uuid.uuid4().hex[:12]}"
        db.fund_accounts.insert_one({
            "id": alias_id, "name": f"{MARK} caja renombrada",
            "currency": "USD", "method": "cash", "is_active": False,
            "merged_into": usd["id"], "created_at": _iso_now()})
        banco_id = _mk_bank(db)
        # residuo R01: la versión anterior re-apuntó banco→alias hacia la
        # canónica SIN retirar el marcador «na»
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 40.0,
            "from_account_id": banco_id, "to_account_id": usd["id"],
            "from_label": f"{MARK} banco", "to_label": usd["label"],
            "note": MARK, "status": "confirmed", "created_at": yesterday,
            "operation_id": trid, "cash_box_movement_id": "na"})
        _mk_arqueo(box["id"], _usd_denoms_for(max(int(base), 0)))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr["to_account_id"] == usd["id"], "sigue en la canónica"
        marker = str(tr.get("cash_box_movement_id") or "")
        assert marker.startswith("cmov_tr_"), \
            f"el «na» residual se reevaluó y ahora hay espejo real: {marker}"
        mov = db.cash_box_movements.find_one({"id": marker}, {"_id": 0})
        assert mov and mov["type"] == "entrada" and mov["amount"] == 40.0
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 1, "exactamente UNA entrada"
        assert _resumen(box["id"])["balance"] == round(base + 40, 2), \
            "la caja física registra la entrada de 40"
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, "el arqueo previo deja de certificar"

        _run_backfill()  # segunda recuperación: conserva los mismos valores
        tr2 = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr2.get("cash_box_movement_id") == marker
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 1
        assert _resumen(box["id"])["balance"] == round(base + 40, 2)

    def test_bank_operation_na_stays_non_cash(self):
        """Una transferencia bancaria con «na» residual (ningún extremo es
        la caja) NO se selecciona: conserva «na», cero movimientos y la caja
        no cambia."""
        _cleanup()
        db = _db()
        _run_backfill()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        banco_id = _mk_bank(db)
        banco2_id = f"facc_{uuid.uuid4().hex[:12]}"
        db.fund_accounts.insert_one({
            "id": banco2_id, "name": f"{MARK} banco 2", "currency": "USD",
            "method": "bank", "is_active": True, "created_at": _iso_now()})
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 10.0,
            "from_account_id": banco2_id, "to_account_id": banco_id,
            "from_label": f"{MARK} banco 2", "to_label": f"{MARK} banco",
            "note": MARK, "status": "confirmed", "created_at": _iso_now(),
            "operation_id": trid, "cash_box_movement_id": "na"})
        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr.get("cash_box_movement_id") == "na"
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 0
        assert _resumen(box["id"])["balance"] == round(base, 2)

    def test_aborted_transfer_na_never_reactivated(self):
        """Una transferencia ABORTADA hacia la caja canónica con «na»
        residual queda excluida por estado: sin espejo nuevo ni cambio de
        saldo."""
        _cleanup()
        db = _db()
        _run_backfill()
        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        banco_id = _mk_bank(db)
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 30.0,
            "from_account_id": banco_id, "to_account_id": usd["id"],
            "from_label": f"{MARK} banco", "to_label": usd["label"],
            "note": MARK, "status": "aborted", "aborted_reason": "huérfana",
            "created_at": _iso_now(), "operation_id": trid,
            "cash_box_movement_id": "na"})
        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr.get("cash_box_movement_id") == "na"
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 0
        assert _resumen(box["id"])["balance"] == round(base, 2)

    def test_client_withdrawal_na_residual_recovered(self):
        """El mismo residuo en OTRA fuente: retiro de cliente pagado desde
        la caja canónica con «na» residual → se reevalúa, aparece la salida
        física exactamente una vez."""
        _cleanup()
        db = _db()
        _run_backfill()
        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        wid = f"wd{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.withdrawals.insert_one({
            "id": wid, "user_id": f"u{MARK.lower()}",
            "user_name": f"{MARK} cliente", "currency": "USD",
            "amount_usd": 25.0, "status": "paid", "method": "cash",
            "paid_from_account_id": usd["id"], "paid_at": yesterday,
            "created_at": yesterday, "cash_box_movement_id": "na"})
        _run_backfill()
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        marker = str(w.get("cash_box_movement_id") or "")
        assert marker.startswith("cmov_wd_"), \
            f"el «na» residual del retiro se reevaluó: {marker}"
        mov = db.cash_box_movements.find_one({"id": marker}, {"_id": 0})
        assert mov and mov["type"] == "salida" and mov["amount"] == 25.0
        assert _resumen(box["id"])["balance"] == round(base - 25, 2)
        _run_backfill()  # sin duplicados
        assert db.cash_box_movements.count_documents(
            {"source_client_withdrawal_id": wid}) == 1
        assert _resumen(box["id"])["balance"] == round(base - 25, 2)
