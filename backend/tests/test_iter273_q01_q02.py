"""iter273 — Verificación Flujo de Caja (commit 70d3eaf): pendientes Q01–Q02.

Q01 un espejo huérfano (movimiento con source_transfer_id cuya transferencia
    abortada perdió el vínculo inverso) se recupera: el recuperador
    re-vincula y anula con compensación trazable — nunca se vincula una
    compensación
Q02 re-apuntar un vínculo a la cuenta canónica REEVALÚA la decisión
    histórica «no aplicable a caja» («na»): el espejo se recalcula con la
    identidad canónica sin duplicar movimientos existentes
"""
import uuid
import os
import asyncio
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "ITER273"


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


class TestQ01OrphanAbortedMirror:
    def teardown_method(self, _):
        _cleanup()

    def test_orphan_mirror_of_aborted_transfer_recovered(self):
        """Aceptación Q01: la salida histórica quedó guardada con
        source_transfer_id pero la transferencia abortada perdió el vínculo
        inverso. Tras recuperar: vínculo restablecido, UNA compensación,
        cuenta/caja coinciden y el arqueo previo queda invalidado."""
        _cleanup()
        db = _db()
        _run_backfill()  # drenar pendientes ajenos
        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        # residuo Q01: movimiento vinculado por source_transfer_id; la
        # escritura de la referencia en la transferencia falló
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        mov_id = f"cmovq1{uuid.uuid4().hex[:10]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "salida", "amount": 80.0,
            "concept": f"{MARK} residuo huérfano", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": yesterday, "created_by_id": "system",
            "created_by_name": "Sistema", "source_transfer_id": trid,
            "rev_bumped": True})
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 80.0,
            "from_account_id": usd["id"], "to_account_id": None,
            "from_label": usd["label"], "to_label": "", "note": MARK,
            "status": "aborted", "aborted_reason": "huérfana",
            "created_at": yesterday, "operation_id": trid})
        assert _resumen(box["id"])["balance"] == round(base - 80, 2), \
            "la salida fantasma descuenta 80 antes de recuperar"
        _mk_arqueo(box["id"], _usd_denoms_for(max(int(base - 80), 0)))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr.get("cash_box_movement_id") == mov_id, \
            "el vínculo inverso se recupera (no una compensación)"
        annul_id = f"cmov_annul_{mov_id.replace('-', '')[:24]}"
        annul = db.cash_box_movements.find_one({"id": annul_id}, {"_id": 0})
        assert annul and annul["type"] == "entrada" \
            and annul["amount"] == 80.0
        assert tr.get("mirror_annulled_by") == annul_id
        assert _resumen(box["id"])["balance"] == round(base, 2), \
            "cuenta y caja vuelven a coincidir"
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, "el arqueo previo deja de certificar"
        _run_backfill()  # segunda ejecución: sin correcciones nuevas
        assert db.cash_box_movements.count_documents(
            {"annuls_movement_id": mov_id}) == 1

    def test_relink_never_links_compensation_movements(self):
        """El recuperador jamás vincula una COMPENSACIÓN como espejo de la
        transferencia (evitaría anular la propia anulación)."""
        _cleanup()
        db = _db()
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        box = _auto_box()
        assert box
        # solo existe un movimiento de compensación asociado a la transferencia
        db.cash_box_movements.insert_one({
            "id": f"cmovq1c{uuid.uuid4().hex[:8]}", "box_id": box["id"],
            "fund": "USD", "type": "entrada", "amount": 15.0,
            "concept": f"{MARK} compensación previa", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": _iso_now(), "created_by_id": "system",
            "created_by_name": "Sistema", "source_transfer_id": trid,
            "annuls_movement_id": "cmov_viejo", "rev_bumped": True})
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 15.0,
            "from_account_id": None, "to_account_id": None,
            "from_label": "", "to_label": "", "note": MARK,
            "status": "aborted", "aborted_reason": "huérfana",
            "created_at": _iso_now(), "operation_id": trid})
        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert "cash_box_movement_id" not in tr, \
            "una compensación nunca se vincula como espejo"
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 1, "sin anulaciones nuevas"


class TestQ02NaMarkerReevaluated:
    def teardown_method(self, _):
        _cleanup()

    def test_na_marker_reevaluated_after_repoint(self):
        """Aceptación Q02: un traslado histórico hacia un alias renombrado y
        fusionado quedó marcado «na». Una recuperación re-apunta a la
        canónica, RECALCULA el espejo (entrada física) e invalida el arqueo;
        una segunda no duplica la entrada."""
        _cleanup()
        db = _db()
        _run_backfill()  # drenar pendientes ajenos
        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"])["balance"]
        # alias residual: duplicado renombrado ya fusionado (sin propósito ni
        # nombre automático)
        alias_id = f"facc_{uuid.uuid4().hex[:12]}"
        banco_id = f"facc_{uuid.uuid4().hex[:12]}"
        db.fund_accounts.insert_one({
            "id": alias_id, "name": f"{MARK} caja secundaria",
            "currency": "USD", "method": "cash", "is_active": False,
            "merged_into": usd["id"], "created_at": _iso_now()})
        db.fund_accounts.insert_one({
            "id": banco_id, "name": f"{MARK} banco", "currency": "USD",
            "method": "bank", "is_active": True, "created_at": _iso_now()})
        # traslado histórico banco→alias clasificado como ajeno a caja («na»)
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 40.0,
            "from_account_id": banco_id, "to_account_id": alias_id,
            "from_label": f"{MARK} banco", "to_label": f"{MARK} caja secundaria",
            "note": MARK, "status": "confirmed", "created_at": yesterday,
            "operation_id": trid, "cash_box_movement_id": "na"})
        _mk_arqueo(box["id"], _usd_denoms_for(max(int(base), 0)))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr["to_account_id"] == usd["id"], "identidad canónica"
        marker = str(tr.get("cash_box_movement_id") or "")
        assert marker.startswith("cmov_tr_"), \
            f"la decisión «na» se reevaluó y ahora hay espejo real: {marker}"
        mov = db.cash_box_movements.find_one({"id": marker}, {"_id": 0})
        assert mov and mov["type"] == "entrada" and mov["amount"] == 40.0
        assert _resumen(box["id"])["balance"] == round(base + 40, 2), \
            "la caja física registra la entrada de 40"
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, "el arqueo sustentado en el saldo anterior cae"
        _run_backfill()  # segunda ejecución: sin duplicados
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 1

    def test_na_marker_restored_when_still_not_applicable(self):
        """Si tras re-apuntar la operación sigue siendo ajena a caja (ambos
        extremos no-caja), la reevaluación vuelve a marcar «na» sin crear
        movimientos."""
        _cleanup()
        db = _db()
        usd = _usd_cash()
        alias_id = f"facc_{uuid.uuid4().hex[:12]}"
        banco_id = f"facc_{uuid.uuid4().hex[:12]}"
        banco2_id = f"facc_{uuid.uuid4().hex[:12]}"
        db.fund_accounts.insert_one({
            "id": alias_id, "name": f"{MARK} banco viejo", "currency": "USD",
            "method": "bank", "is_active": False, "merged_into": banco_id,
            "created_at": _iso_now()})
        for fid, nm in ((banco_id, "banco"), (banco2_id, "banco 2")):
            db.fund_accounts.insert_one({
                "id": fid, "name": f"{MARK} {nm}", "currency": "USD",
                "method": "bank", "is_active": True,
                "created_at": _iso_now()})
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 10.0,
            "from_account_id": banco2_id, "to_account_id": alias_id,
            "from_label": f"{MARK} banco 2", "to_label": f"{MARK} banco viejo",
            "note": MARK, "status": "confirmed", "created_at": _iso_now(),
            "operation_id": trid, "cash_box_movement_id": "na"})
        _run_backfill()
        tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert tr["to_account_id"] == banco_id
        assert tr.get("cash_box_movement_id") == "na", \
            "sigue siendo ajena a caja: vuelve a «na» sin movimientos"
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 0
        assert usd["id"], "la caja canónica no interviene"
