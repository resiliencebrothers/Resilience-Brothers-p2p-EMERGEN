"""iter269 — Verificación V01–V06 (Caja de Efectivo y Fondos, commit ad7fc79).

V01 la reserva y el pago de retiros de empresa protegen el disponible entre
    retiros DIFERENTES: presupuesto atómico por moneda + cerrojo de gasto
V02 un retiro de CLIENTE pagado desde la cuenta de caja genera su salida
    física (idempotente, con recuperación de históricos)
V03 la cuenta contable de caja se identifica por `system_purpose` persistente
    (renombrarla no rompe los espejos) y los marcadores legados «""» se reparan
V04 editar/eliminar un movimiento anterior al arqueo (o recuperar un
    histórico con fecha antigua) invalida el cierre vigente (fund_revs)
V05 un fallo al crear la caja se PROPAGA: nunca queda un movimiento huérfano
    ni un origen marcado como replicado sin caja persistida
V06 cubierto en test_iter265 (status HTTP comprobado + disponible aislado)
"""
import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER269"
CCY = "I269X"
V05_PURPOSE = "company_cash_iter269_test"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _cleanup():
    db = _db()
    db.company_withdrawals.delete_many({"beneficiary": {"$regex": MARK}})
    db.company_fund_adjustments.delete_many({"source_name": {"$regex": MARK}})
    db.withdrawals.delete_many({"user_name": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"$or": [
        {"concept": {"$regex": MARK}},
        {"source_client_withdrawal_id": {"$regex": MARK.lower()}},
    ]})
    db.cash_box_arqueos.delete_many({"note": {"$regex": MARK}})
    ids = [b["id"] for b in db.cash_boxes.find(
        {"name": {"$regex": MARK}, "system_purpose": {"$exists": False}},
        {"_id": 0, "id": 1})]
    if ids:
        db.cash_box_movements.delete_many({"box_id": {"$in": ids}})
        db.cash_box_arqueos.delete_many({"box_id": {"$in": ids}})
        db.cash_boxes.delete_many({"id": {"$in": ids}})
    db.cash_boxes.delete_many({"system_purpose": V05_PURPOSE})
    db.currencies.delete_many({"code": CCY})
    db.fund_accounts.delete_many({"currency": CCY})
    # el presupuesto se reconstruye desde los retiros reales al primer uso
    db.company_fund_budgets.delete_many({})


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


def _adjust(body):
    return requests.post(f"{API}/admin/company-funds/adjustments",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _cw_create(body):
    return requests.post(f"{API}/admin/company-withdrawals",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _cw_status(cwid, body):
    return requests.put(f"{API}/admin/company-withdrawals/{cwid}/status",
                        headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _resumen(box_id, fund="USD"):
    r = requests.get(f"{API}/cashbox/boxes/{box_id}/resumen",
                     params={"fund": fund}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _auto_box():
    return _db().cash_boxes.find_one({"system_purpose": "company_cash"},
                                     {"_id": 0})


def _cash_account(code="USD"):
    return _db().fund_accounts.find_one(
        {"currency": code, "method": "cash",
         "$or": [{"system_purpose": "company_cash"},
                 {"name": "Fondo Resilience"}]}, {"_id": 0})


def _fund_row(code):
    r = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((x for x in r.json() if x["currency"] == code), None)


def _ensure_usd_available(needed: float):
    """Disponible real USD suficiente tras custodia y reservas del entorno."""
    row = _fund_row("USD") or {}
    avail = float(row.get("balance_available") or 0.0)
    reserved = sum(float(r.get("amount") or 0)
                   for r in _db().company_withdrawals.find(
                       {"currency": "USD",
                        "status": {"$in": ["pending", "approved"]}},
                       {"_id": 0, "amount": 1}))
    missing = round(needed - (avail - reserved), 2)
    if missing > 0:
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": missing, "method": "transfer",
                     "source_name": f"{MARK} topup disponible"})
        assert r.status_code == 200, r.text


def _mk_box():
    r = requests.post(f"{API}/cashbox/boxes", headers=_hdr(ADMIN_TOKEN),
                      json={"name": f"{MARK} {uuid.uuid4().hex[:6]}",
                            "scope": "empresa"})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_mov(box_id, amount, denoms, fund="USD"):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/movimientos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": fund, "type": "entrada", "amount": amount,
                            "concept": f"mov {MARK}", "denominations": denoms})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_arqueo(box_id, fund, counted):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/arqueos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": fund, "counted": counted, "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()


def _usd_denoms_for(amount):
    left = max(int(amount), 0)
    out = {}
    for d in (100, 50, 20, 10, 5, 2, 1):
        q, left = divmod(left, d)
        if q:
            out[str(d)] = q
    return out or {"1": 0}


class TestV01AtomicBudget:
    def setup_method(self, _):
        _cleanup()
        _db().currencies.update_one(
            {"code": CCY},
            {"$setOnInsert": {"code": CCY, "name": "Moneda Test 269",
                              "type": "fiat", "is_active": True}}, upsert=True)

    def teardown_method(self, _):
        _cleanup()

    def test_concurrent_creations_cannot_overcommit(self):
        """Repro del auditor: dos creaciones concurrentes de 80 contra 100
        no pueden comprometer 160 — exactamente una gana la reserva."""
        r = _adjust({"adjustment_type": "inflow", "currency": CCY,
                     "amount": 100, "method": "transfer",
                     "source_name": f"{MARK} aporte"})
        assert r.status_code == 200, r.text
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_cw_create,
                              {"currency": CCY, "amount": 80,
                               "beneficiary": f"{MARK} {tag}", "concept": "x"})
                    for tag in ("A", "B")]
            codes = sorted(f.result().status_code for f in futs)
        assert codes == [200, 400], f"solo una creación puede pasar: {codes}"
        assert _db().company_withdrawals.count_documents(
            {"currency": CCY, "status": {"$in": ["pending", "approved"]}}) == 1

    def test_concurrent_payments_cannot_exceed_fund(self):
        """Residuo legado: dos pendientes de 80 comprometen 160 contra 100.
        El pago serializa con cerrojo por moneda: nunca se registran 160
        pagados ni el fondo termina en −60."""
        db = _db()
        r = _adjust({"adjustment_type": "inflow", "currency": CCY,
                     "amount": 100, "method": "transfer",
                     "source_name": f"{MARK} aporte"})
        assert r.status_code == 200, r.text
        ids = []
        for tag in ("A", "B"):
            wid = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
            db.company_withdrawals.insert_one({
                "id": wid, "currency": CCY, "amount": 80, "status": "pending",
                "beneficiary": f"{MARK} {tag}", "created_at": _iso_now()})
            ids.append(wid)
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_cw_status, wid, {"status": "paid"})
                    for wid in ids]
            codes = sorted(f.result().status_code for f in futs)
        assert codes == [200, 409], f"solo un pago puede pasar: {codes}"
        assert db.company_withdrawals.count_documents(
            {"currency": CCY, "status": "paid"}) == 1
        row = _fund_row(CCY)
        assert row and float(row["balance"]) == 20.0, \
            f"100 − 80 = 20, nunca −60: {row and row['balance']}"

    def test_reject_releases_reservation_exactly_once(self):
        assert _adjust({"adjustment_type": "inflow", "currency": CCY,
                        "amount": 100, "method": "transfer",
                        "source_name": f"{MARK} aporte"}).status_code == 200
        a = _cw_create({"currency": CCY, "amount": 80,
                        "beneficiary": f"{MARK} A", "concept": "x"})
        assert a.status_code == 200, a.text
        assert _cw_status(a.json()["id"],
                          {"status": "rejected"}).status_code == 200
        # liberada: 90 vuelve a caber
        b = _cw_create({"currency": CCY, "amount": 90,
                        "beneficiary": f"{MARK} B", "concept": "x"})
        assert b.status_code == 200, b.text
        # re-rechazar es no-op idempotente: la reserva NO se libera dos veces
        assert _cw_status(a.json()["id"],
                          {"status": "rejected"}).status_code in (200, 409)
        assert _cw_create({"currency": CCY, "amount": 20,
                           "beneficiary": f"{MARK} C",
                           "concept": "x"}).status_code == 400
        assert _cw_create({"currency": CCY, "amount": 10,
                           "beneficiary": f"{MARK} D",
                           "concept": "x"}).status_code == 200

    def test_paid_consumes_reservation_once(self):
        assert _adjust({"adjustment_type": "inflow", "currency": CCY,
                        "amount": 100, "method": "transfer",
                        "source_name": f"{MARK} aporte"}).status_code == 200
        a = _cw_create({"currency": CCY, "amount": 50,
                        "beneficiary": f"{MARK} A", "concept": "x"})
        assert a.status_code == 200, a.text
        assert _cw_status(a.json()["id"], {"status": "paid"}).status_code == 200
        # tras pagar: disponible 50, reserva 0 → otro de 50 cabe exacto
        b = _cw_create({"currency": CCY, "amount": 50,
                        "beneficiary": f"{MARK} B", "concept": "x"})
        assert b.status_code == 200, b.text
        assert _cw_create({"currency": CCY, "amount": 1,
                           "beneficiary": f"{MARK} C",
                           "concept": "x"}).status_code == 400


class TestV02ClientWithdrawalMirror:
    def teardown_method(self, _):
        _cleanup()

    def test_paid_client_withdrawal_mirrors_to_box(self):
        """Aceptación del auditor: pago de cliente de 40 desde la caja que
        tenía 100 deja cuenta y caja en 60; repetir no duplica salidas."""
        _cleanup()
        db = _db()
        _run_backfill()  # drenar históricos para aislar el delta
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 100, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"100": 1}})
        assert r.status_code == 200, r.text
        box = _auto_box()
        assert box, "la caja del sistema debe existir"
        base = _resumen(box["id"], "USD")["balance"]
        acc = _cash_account("USD")
        assert acc, "la cuenta de caja USD debe existir"
        wid = f"w{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_v02_test",
            "user_name": f"{MARK} Cliente", "currency": "USD",
            "amount_usd": 40.0, "method": "cash", "status": "paid",
            "paid_from_account_id": acc["id"], "paid_at": _iso_now(),
            "created_at": _iso_now()})
        _run_backfill()
        mov = db.cash_box_movements.find_one(
            {"source_client_withdrawal_id": wid}, {"_id": 0})
        assert mov, "el retiro de cliente pagado en efectivo llega a la caja"
        assert mov["type"] == "salida" and mov["amount"] == 40.0
        assert mov["fund"] == "USD"
        assert mov.get("denoms_pending") is True, \
            "sin billetes conocidos el desglose queda PENDIENTE"
        assert db.withdrawals.find_one(
            {"id": wid}, {"_id": 0})["cash_box_movement_id"] == mov["id"]
        assert _resumen(box["id"], "USD")["balance"] == round(base - 40.0, 2)
        # idempotencia: repetir el backfill no duplica la salida
        _run_backfill()
        assert db.cash_box_movements.count_documents(
            {"source_client_withdrawal_id": wid}) == 1
        # el espejo queda bloqueado en la caja (solo desglose completable)
        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov['id']}",
            headers=_hdr(ADMIN_TOKEN), json={"amount": 1})
        assert r.status_code == 409, r.text
        r = requests.delete(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov['id']}",
            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 409, r.text

    def test_pay_route_mirrors_inline(self):
        """El PUT /status a 'paid' refleja la salida física al instante."""
        _cleanup()
        db = _db()
        _run_backfill()
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 60, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"20": 3}})
        assert r.status_code == 200, r.text
        box = _auto_box()
        base = _resumen(box["id"], "USD")["balance"]
        acc = _cash_account("USD")
        wid = f"w{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_v02_test",
            "user_name": f"{MARK} Cliente", "currency": "USD",
            "amount_usd": 25.0, "method": "cash",
            "cash_delivery_mode": "office_pickup", "status": "approved",
            "created_at": _iso_now()})
        r = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin({
                             "status": "paid",
                             "paid_from_account_id": acc["id"]}))
        assert r.status_code == 200, r.text
        assert r.json().get("cash_box_movement_id"), \
            "el pago debe enlazar su movimiento físico en la respuesta"
        assert _resumen(box["id"], "USD")["balance"] == round(base - 25.0, 2)


class TestV03AccountIdentity:
    def teardown_method(self, _):
        _cleanup()

    def test_renamed_account_keeps_mirroring(self):
        """Repro del auditor: renombrar la cuenta contable a «Caja oficina»
        y pagar 40 desde su mismo id → cuenta y caja bajan juntas."""
        _cleanup()
        db = _db()
        _run_backfill()
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 100, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"100": 1}})
        assert r.status_code == 200, r.text
        acc = _cash_account("USD")
        assert acc, "la cuenta de caja USD debe existir"
        original_name = acc.get("name") or "Fondo Resilience"
        box = _auto_box()
        base = _resumen(box["id"], "USD")["balance"]
        _ensure_usd_available(45)
        try:
            r = requests.put(
                f"{API}/admin/company-funds/accounts/{acc['id']}",
                headers=_hdr(ADMIN_TOKEN),
                json={"name": f"Caja oficina {MARK}"})
            assert r.status_code == 200, r.text
            cwr = _cw_create({"currency": "USD", "amount": 40,
                              "beneficiary": f"{MARK} proveedor",
                              "concept": "x"})
            assert cwr.status_code == 200, cwr.text
            pay = _cw_status(cwr.json()["id"],
                             {"status": "paid",
                              "paid_from_account_id": acc["id"]})
            assert pay.status_code == 200, pay.text
            assert pay.json().get("cash_box_movement_id"), \
                "la cuenta renombrada sigue reconociéndose como caja (V03)"
            assert _resumen(box["id"], "USD")["balance"] == \
                round(base - 40.0, 2), "cuenta y caja cuentan la misma historia"
        finally:
            requests.put(f"{API}/admin/company-funds/accounts/{acc['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"name": original_name})

    def test_empty_marker_gets_repaired(self):
        """Los docs marcados con cadena vacía por versiones anteriores se
        reintentan: identidad no resuelta ≠ definitivamente ajena a caja."""
        _cleanup()
        db = _db()
        _run_backfill()
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 50, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"50": 1}})
        assert r.status_code == 200, r.text
        acc = _cash_account("USD")
        box = _auto_box()
        base = _resumen(box["id"], "USD")["balance"]
        cwid = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.company_withdrawals.insert_one({
            "id": cwid, "currency": "USD", "amount": 15.0, "status": "paid",
            "beneficiary": f"{MARK} legado",
            "paid_from_account_id": acc["id"], "paid_at": _iso_now(),
            "created_at": _iso_now(),
            "cash_box_movement_id": ""})  # marcador legado del bug V03
        _run_backfill()
        doc = db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
        assert str(doc["cash_box_movement_id"]).startswith("cmov_"), doc
        assert _resumen(box["id"], "USD")["balance"] == round(base - 15.0, 2)


class TestV04ArqueoRevision:
    def teardown_method(self, _):
        _cleanup()

    def test_edit_after_count_invalidates_closing(self):
        """Repro del auditor: aporte 100 + arqueo 100 → editar el movimiento
        a 200 conserva su fecha, pero el cierre deja de valer."""
        _cleanup()
        box = _mk_box()
        mov = _mk_mov(box["id"], 100, {"100": 1})
        _mk_arqueo(box["id"], "USD", {"100": 1})
        res = _resumen(box["id"], "USD")
        assert res["arqueo_today"] and res["arqueo_today"]["superseded"] is False
        assert res["needs_arqueo"] is False
        r = requests.put(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov['id']}",
            headers=_hdr(ADMIN_TOKEN),
            json={"amount": 200, "denominations": {"100": 2}})
        assert r.status_code == 200, r.text
        res = _resumen(box["id"], "USD")
        assert res["arqueo_today"]["superseded"] is True, \
            "editar un movimiento anterior invalida el cierre (V04)"
        assert res["needs_arqueo"] is True, "la caja pide nuevo arqueo"
        # un nuevo conteo vuelve a certificar el cierre
        _mk_arqueo(box["id"], "USD", {"100": 2})
        res = _resumen(box["id"], "USD")
        assert res["needs_arqueo"] is False
        assert res["arqueo_today"]["superseded"] is False

    def test_delete_after_count_invalidates_closing(self):
        _cleanup()
        box = _mk_box()
        _mk_mov(box["id"], 100, {"100": 1})
        mov2 = _mk_mov(box["id"], 50, {"50": 1})
        _mk_arqueo(box["id"], "USD", {"100": 1, "50": 1})
        r = requests.delete(
            f"{API}/cashbox/boxes/{box['id']}/movimientos/{mov2['id']}",
            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        res = _resumen(box["id"], "USD")
        assert res["arqueo_today"]["superseded"] is True
        assert res["needs_arqueo"] is True, \
            "tras borrar un movimiento contado se pide nuevo arqueo (V04)"

    def test_late_recovered_movement_invalidates_closing(self):
        """Recuperación tardía con fecha económica ANTIGUA: el saldo que
        sustentaba el cierre cambia y el arqueo deja de valer (V04)."""
        _cleanup()
        db = _db()
        _run_backfill()
        box = _auto_box()
        if not box:
            r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                         "amount": 1, "method": "cash",
                         "source_name": f"{MARK} seed",
                         "denominations": {"1": 1}})
            assert r.status_code == 200, r.text
            box = _auto_box()
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], "USD", _usd_denoms_for(bal))
        res = _resumen(box["id"], "USD")
        assert res["needs_arqueo"] is False
        # ajuste histórico (ayer) que aún no estaba en la caja
        aid = f"adj{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        yesterday = (datetime.now(timezone.utc)
                     - timedelta(days=1)).isoformat()
        db.company_fund_adjustments.insert_one({
            "id": aid, "currency": "USD", "method": "cash",
            "adjustment_type": "inflow", "amount": 20.0,
            "source_name": f"{MARK} histórico",
            "denominations": {"20": 1}, "created_at": yesterday})
        _run_backfill()
        mov = db.cash_box_movements.find_one(
            {"source_adjustment_id": aid}, {"_id": 0})
        assert mov, "el histórico recuperado entra en la caja"
        assert mov["created_at"] == yesterday, "fecha económica respetada"
        res = _resumen(box["id"], "USD")
        assert res["arqueo_today"]["superseded"] is True
        assert res["needs_arqueo"] is True, \
            "el histórico recuperado también cambia el saldo del cierre"


class TestV05FailedBoxCreation:
    def teardown_method(self, _):
        _cleanup()

    def test_failed_creation_propagates_then_heals(self):
        """Repro del auditor: fallo inyectado en el upsert de cash_boxes →
        el fallo se PROPAGA (ni movimiento huérfano ni origen marcado);
        al reintentar existe exactamente una caja y un movimiento válido."""
        _cleanup()
        db = _db()
        aid = f"adjv05_{uuid.uuid4().hex[:8]}"
        adj = {"id": aid, "currency": "USD", "method": "cash",
               "adjustment_type": "inflow", "amount": 30.0,
               "source_name": f"{MARK} v05", "denominations": {"10": 3},
               "created_at": _iso_now()}
        db.company_fund_adjustments.insert_one({**adj})

        async def flow():
            import services.cash_box_sync as sync
            real_db = sync.db
            orig_purpose = sync.SYSTEM_PURPOSE

            class _FailingBoxes:
                def __init__(self, real):
                    self._real = real

                def __getattr__(self, k):
                    return getattr(self._real, k)

                async def update_one(self, q, u, **kw):
                    if "$setOnInsert" in u:
                        raise RuntimeError("fallo simulado del upsert")
                    return await self._real.update_one(q, u, **kw)

            class _Proxy:
                def __init__(self, real):
                    self._real = real

                def __getattr__(self, k):
                    coll = getattr(self._real, k)
                    return _FailingBoxes(coll) if k == "cash_boxes" else coll

            sync.SYSTEM_PURPOSE = V05_PURPOSE
            try:
                sync.db = _Proxy(real_db)
                raised = False
                try:
                    await sync.mirror_adjustment_to_cash_box(adj)
                except RuntimeError:
                    raised = True
                finally:
                    sync.db = real_db
                # estado tras el fallo, ANTES del reintento
                boxes_fail = await real_db.cash_boxes.count_documents(
                    {"system_purpose": V05_PURPOSE})
                orphans = await real_db.cash_box_movements.count_documents(
                    {"source_adjustment_id": aid})
                marked = await real_db.company_fund_adjustments.find_one(
                    {"id": aid, "cash_box_movement_id": {"$exists": True}},
                    {"_id": 1})
                # reintento tras "recuperar la base"
                mov_id = await sync.mirror_adjustment_to_cash_box(adj)
                return raised, boxes_fail, orphans, marked, mov_id
            finally:
                sync.SYSTEM_PURPOSE = orig_purpose
                sync.db = real_db

        raised, boxes_fail, orphans, marked, mov_id = _run(flow)
        assert raised, "el fallo de creación de caja debe PROPAGARSE (V05)"
        assert boxes_fail == 0, "sin caja fantasma tras el fallo"
        assert orphans == 0, "sin movimiento huérfano tras el fallo"
        assert marked is None, \
            "el origen NO puede quedar marcado como replicado sin caja"
        assert mov_id, "el reintento debe crear el espejo"
        boxes = list(db.cash_boxes.find({"system_purpose": V05_PURPOSE}))
        assert len(boxes) == 1, "exactamente UNA caja tras el reintento"
        movs = list(db.cash_box_movements.find(
            {"source_adjustment_id": aid}, {"_id": 0}))
        assert len(movs) == 1 and movs[0]["box_id"] == boxes[0]["id"]
        assert db.company_fund_adjustments.find_one(
            {"id": aid}, {"_id": 0})["cash_box_movement_id"] == mov_id
