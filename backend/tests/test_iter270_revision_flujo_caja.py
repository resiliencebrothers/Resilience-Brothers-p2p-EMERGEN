"""iter270 — Revisión Flujo de Caja (commit 5912bed): correcciones N01–N07.

N01 un pago que perdió su cerrojo caducado NO puede completar la escritura
    definitiva (cercado `pay_fence` invalidado por el siguiente dueño)
N02 el pago empresarial exige saldo EN la cuenta de origen seleccionada,
    no solo disponible global de la moneda
N03 la cuenta de origen debe estar activa y coincidir en MONEDA con la
    operación (empresa Y clientes) — sin conversión implícita
N04 las transferencias entre cuentas consumen el saldo de origen bajo el
    mismo cerrojo de gasto que los pagos + idempotencia por operation_id
N05 un fallo al incrementar la revisión del fondo se recupera en el
    reintento: el arqueo previo queda invalidado (rev_bumped persistido)
N06 identidad única de la cuenta automática de caja (índice + upsert),
    consolidación de duplicados y traslado interno sin salida física
N07 iter269 + iter270 forman parte de la suite crítica de cada cambio
"""
import asyncio
import uuid
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER270"
CCY = "I270X"
CCY2 = "I270Y"

IDENTITY_INDEX = [("system_purpose", 1), ("currency", 1)]


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
    db.fund_account_transfers.delete_many({"currency": {"$in": [CCY, CCY2]}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    db.cash_box_arqueos.delete_many({"note": {"$regex": MARK}})
    db.fund_accounts.delete_many({"currency": {"$in": [CCY, CCY2]}})
    db.fund_accounts.delete_many({"name": {"$regex": MARK}})
    db.currencies.delete_many({"code": {"$in": [CCY, CCY2]}})
    # el presupuesto se reconstruye desde los retiros reales al primer uso
    db.company_fund_budgets.delete_many({})


def _seed_currency(code):
    _db().currencies.update_one(
        {"code": code},
        {"$setOnInsert": {"code": code, "name": f"Moneda Test 270 {code}",
                          "type": "fiat", "is_active": True}}, upsert=True)


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


def _transfer(body):
    return requests.post(f"{API}/admin/company-funds/accounts/transfer",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _mk_account(name, currency, method):
    r = requests.post(f"{API}/admin/company-funds/accounts",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"name": f"{name} {uuid.uuid4().hex[:4]}",
                            "currency": currency, "method": method})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _adj_doc(currency, amount, account=None, method="transfer"):
    doc = {"id": f"adj{MARK.lower()}_{uuid.uuid4().hex[:10]}",
           "adjustment_type": "inflow", "currency": currency,
           "amount": float(amount), "method": method,
           "source_name": f"{MARK} aporte",
           "created_at": _iso_now(), "cash_box_movement_id": "na"}
    if account:
        doc["account_id"] = account
        doc["account_label"] = "cuenta test"
    return doc


def _fund_row(code):
    r = requests.get(f"{API}/admin/company-funds", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return next((x for x in r.json() if x["currency"] == code), None)


def _breakdown_balances(code):
    r = requests.get(f"{API}/admin/company-funds/accounts/{code}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return {a["id"]: float(a["balance"]) for a in r.json()["accounts"]}


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


def _mk_arqueo(box_id, fund, counted):
    r = requests.post(f"{API}/cashbox/boxes/{box_id}/arqueos",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"fund": fund, "counted": counted, "note": MARK})
    assert r.status_code == 200, r.text
    return r.json()


def _closing_valid(box_id, fund="USD"):
    async def _f():
        from services.cash_box_arqueo import closing_arqueo_status
        return await closing_arqueo_status(box_id, fund)
    return _run(_f)


def _drop_identity_index(db):
    coll = db.fund_accounts
    for name, spec in coll.index_information().items():
        if list(spec.get("key") or []) == IDENTITY_INDEX:
            coll.drop_index(name)


def _restore_identity_index(db):
    db.fund_accounts.create_index(
        IDENTITY_INDEX, unique=True,
        partialFilterExpression={"system_purpose": {"$exists": True}})


def _insert_legacy_pending(db, wid, tag, amount=80, currency=CCY):
    db.company_withdrawals.insert_one({
        "id": wid, "currency": currency, "amount": amount,
        "status": "pending", "beneficiary": f"{MARK} {tag}",
        "created_at": _iso_now()})


class TestN01FencedPayment:
    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)

    def teardown_method(self, _):
        _cleanup()

    def test_stale_lock_owner_cannot_complete_payment(self):
        """Repro del auditor: A valida 80/100 y se pausa; su cerrojo caduca;
        B lo roba y paga 80. A NO puede completar: fondo 20, nunca −60."""
        db = _db()
        db.company_fund_adjustments.insert_one(_adj_doc(CCY, 100))
        w1 = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        w2 = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        _insert_legacy_pending(db, w1, "A")
        _insert_legacy_pending(db, w2, "B")

        def _acquire():
            async def _f():
                from services import company_fund_budget as fb
                return await fb.acquire_pay_lock(CCY)
            return _run(_f)

        token_a = _acquire()
        assert token_a, "A toma el cerrojo de gasto"
        # A validó el disponible y estampó su cercado sobre w1 (igual que
        # hace _pay_company_withdrawal antes de la escritura definitiva)
        db.company_withdrawals.update_one(
            {"id": w1}, {"$set": {"pay_fence": token_a}})
        # el cerrojo de A caduca (reloj adelantado 3 minutos)
        stale = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        db.company_fund_budgets.update_one(
            {"currency": CCY}, {"$set": {"pay_locked_at": stale}})
        # B roba el cerrojo caducado y paga w2 por la vía real
        r = _cw_status(w2, {"status": "paid"})
        assert r.status_code == 200, r.text
        # el robo del cerrojo invalidó el cercado de A
        assert not _db().company_withdrawals.find_one(
            {"id": w1}, {"_id": 0}).get("pay_fence"), \
            "el nuevo dueño limpia los cercados de dueños anteriores"

        # A despierta e intenta su escritura definitiva con la lectura vieja
        def _resume_a():
            async def _f():
                from fastapi import HTTPException
                from routes.admin_company_funds import _claim_cw_transition
                try:
                    await _claim_cw_transition(
                        w1, "pending",
                        {"status": "paid", "paid_at": _iso_now()},
                        fence=token_a)
                    return 200
                except HTTPException as ex:
                    return ex.status_code
            return _run(_f)

        assert _resume_a() == 409, "el dueño antiguo recibe conflicto"
        assert _db().company_withdrawals.find_one(
            {"id": w1}, {"_id": 0})["status"] == "pending"
        row = _fund_row(CCY)
        assert row and float(row["balance"]) == 20.0, \
            f"la suma pagada nunca supera el fondo: {row and row['balance']}"

    def test_lock_ownership_and_fence_cleanup(self):
        db = _db()
        db.company_fund_adjustments.insert_one(_adj_doc(CCY, 100))
        wid = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        _insert_legacy_pending(db, wid, "F", amount=10)

        def _flow():
            async def _f():
                from services import company_fund_budget as fb
                t1 = await fb.acquire_pay_lock(CCY)
                out = {"t1": t1,
                       "holds1": await fb.holds_pay_lock(CCY, t1),
                       "holds_other": await fb.holds_pay_lock(CCY, "otro"),
                       "t2": await fb.acquire_pay_lock(CCY)}
                await fb.release_pay_lock(CCY, t1)
                out["holds_after"] = await fb.holds_pay_lock(CCY, t1)
                return out
            return _run(_f)

        out = _flow()
        assert out["t1"] and out["holds1"] is True
        assert out["holds_other"] is False
        assert out["t2"] is None, "el cerrojo vigente no se puede robar"
        assert out["holds_after"] is False
        # un cercado residual se limpia en la siguiente adquisición
        db.company_withdrawals.update_one(
            {"id": wid}, {"$set": {"pay_fence": "token-viejo"}})

        def _acquire():
            async def _f():
                from services import company_fund_budget as fb
                return await fb.acquire_pay_lock(CCY)
            return _run(_f)

        assert _acquire()
        assert not db.company_withdrawals.find_one(
            {"id": wid}, {"_id": 0}).get("pay_fence")


class TestN02SourceAccountBalance:
    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)

    def teardown_method(self, _):
        _cleanup()

    def test_payment_requires_balance_in_source_account(self):
        """Aceptación del auditor: caja 20 + banco 80 → pagar 80 desde caja
        RECHAZA; tras trasladar 60 banco→caja, el pago de 80 SÍ pasa."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 20, account=caja, method="cash"))
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 80, account=banco))
        cw = _cw_create({"currency": CCY, "amount": 80,
                         "beneficiary": f"{MARK} proveedor", "concept": "x"})
        assert cw.status_code == 200, cw.text
        cwid = cw.json()["id"]
        r = _cw_status(cwid, {"status": "paid", "paid_from_account_id": caja})
        assert r.status_code == 409, \
            f"pagar 80 desde una caja con 20 debe rechazar: {r.text}"
        assert "origen" in r.json()["detail"].lower()
        assert db.company_withdrawals.find_one(
            {"id": cwid}, {"_id": 0})["status"] == "pending"
        bal = _breakdown_balances(CCY)
        assert bal[caja] == 20.0 and bal[banco] == 80.0, \
            "el rechazo no altera ningún saldo"
        # traslado real de 60 banco → caja
        t = _transfer({"currency": CCY, "from_account_id": banco,
                       "to_account_id": caja, "amount": 60})
        assert t.status_code == 200, t.text
        r = _cw_status(cwid, {"status": "paid", "paid_from_account_id": caja})
        assert r.status_code == 200, r.text
        bal = _breakdown_balances(CCY)
        assert bal[caja] == 0.0 and bal[banco] == 20.0, \
            f"cada ubicación conserva su importe correcto: {bal}"
        row = _fund_row(CCY)
        assert row and float(row["balance"]) == 20.0


class TestN03CurrencyMatch:
    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)
        _seed_currency(CCY2)

    def teardown_method(self, _):
        _cleanup()

    def test_company_payment_rejects_other_currency_account(self):
        """Repro del auditor: un retiro en una moneda con cuenta de OTRA
        moneda devuelve error, sin estado pagado ni atribución cruzada."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        otra = _mk_account(f"Caja otra {MARK}", CCY2, "cash")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        cw = _cw_create({"currency": CCY, "amount": 40,
                         "beneficiary": f"{MARK} proveedor", "concept": "x"})
        assert cw.status_code == 200, cw.text
        cwid = cw.json()["id"]
        r = _cw_status(cwid, {"status": "paid", "paid_from_account_id": otra})
        assert r.status_code == 400, r.text
        assert CCY2 in r.json()["detail"]
        doc = db.company_withdrawals.find_one({"id": cwid}, {"_id": 0})
        assert doc["status"] == "pending"
        assert not doc.get("paid_from_account_id")
        assert _breakdown_balances(CCY2).get(otra, 0.0) == 0.0, \
            "nunca se atribuye un −40 a la cuenta de otra moneda"
        # con la cuenta correcta el pago se registra en el origen correcto
        r = _cw_status(cwid, {"status": "paid", "paid_from_account_id": caja})
        assert r.status_code == 200, r.text
        assert _breakdown_balances(CCY)[caja] == 60.0

    def test_inactive_account_rejected(self):
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        r = requests.put(f"{API}/admin/company-funds/accounts/{caja}",
                         headers=_hdr(ADMIN_TOKEN), json={"is_active": False})
        assert r.status_code == 200, r.text
        cw = _cw_create({"currency": CCY, "amount": 10,
                         "beneficiary": f"{MARK} proveedor", "concept": "x"})
        assert cw.status_code == 200, cw.text
        r = _cw_status(cw.json()["id"],
                       {"status": "paid", "paid_from_account_id": caja})
        assert r.status_code == 400, r.text
        assert "desactivada" in r.json()["detail"]

    def test_client_withdrawal_rejects_other_currency_account(self):
        """El camino de pago de retiros de CLIENTES usa el mismo resolutor:
        también exige coincidencia de moneda."""
        db = _db()
        otra = _mk_account(f"Caja otra {MARK}", CCY2, "cash")
        wid = f"w{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_n03_test",
            "user_name": f"{MARK} Cliente", "currency": "USD",
            "amount_usd": 10.0, "method": "cash",
            "cash_delivery_mode": "office_pickup", "status": "approved",
            "created_at": _iso_now()})
        r = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                         headers=_hdr(ADMIN_TOKEN),
                         json=with_totp_admin({
                             "status": "paid",
                             "paid_from_account_id": otra}))
        assert r.status_code == 400, r.text
        assert db.withdrawals.find_one(
            {"id": wid}, {"_id": 0})["status"] == "approved"


class TestN04TransferAtomicity:
    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)

    def teardown_method(self, _):
        _cleanup()

    def test_concurrent_transfers_cannot_overdraw_source(self):
        """Repro del auditor: dos transferencias de 80 contra origen 100 no
        se aceptan ambas. Origen 20, destino 80, fondo total 100."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        body = {"currency": CCY, "from_account_id": caja,
                "to_account_id": banco, "amount": 80}
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_transfer, dict(body)) for _ in range(2)]
            codes = sorted(f.result().status_code for f in futs)
        assert codes[0] == 200 and codes[1] in (400, 409), \
            f"solo una transferencia puede pasar: {codes}"
        assert db.fund_account_transfers.count_documents(
            {"currency": CCY, "from_account_id": caja}) == 1
        bal = _breakdown_balances(CCY)
        assert bal[caja] == 20.0 and bal[banco] == 80.0, f"saldos: {bal}"
        row = _fund_row(CCY)
        assert row and float(row["balance"]) == 100.0, \
            "una transferencia nunca crea ni elimina capital"

    def test_transfer_operation_id_idempotent(self):
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        op = f"op-{MARK.lower()}-{uuid.uuid4().hex[:10]}"
        body = {"currency": CCY, "from_account_id": caja,
                "to_account_id": banco, "amount": 30, "operation_id": op}
        r1 = _transfer(dict(body))
        assert r1.status_code == 200, r1.text
        r2 = _transfer(dict(body))
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == r1.json()["id"], \
            "repetir el identificador de operación devuelve el mismo traslado"
        assert db.fund_account_transfers.count_documents(
            {"operation_id": op}) == 1
        bal = _breakdown_balances(CCY)
        assert bal[caja] == 70.0 and bal[banco] == 30.0, \
            f"el importe se mueve UNA sola vez: {bal}"

    def test_concurrent_payment_and_transfer_same_source(self):
        """Un pago y una transferencia que usan la misma cuenta de origen
        contienden por el mismo cerrojo: solo uno consume los 100 − 20."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        cw = _cw_create({"currency": CCY, "amount": 80,
                         "beneficiary": f"{MARK} proveedor", "concept": "x"})
        assert cw.status_code == 200, cw.text
        cwid = cw.json()["id"]
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_pay = ex.submit(_cw_status, cwid,
                              {"status": "paid",
                               "paid_from_account_id": caja})
            f_tr = ex.submit(_transfer,
                             {"currency": CCY, "from_account_id": caja,
                              "to_account_id": banco, "amount": 80})
            codes = sorted([f_pay.result().status_code,
                            f_tr.result().status_code])
        assert codes[0] == 200 and codes[1] in (400, 409), \
            f"exactamente una operación consume el saldo de la caja: {codes}"
        bal = _breakdown_balances(CCY)
        assert bal[caja] == 20.0, \
            f"la caja nunca queda en negativo (100 − 80 = 20): {bal}"


class TestN05RevisionRecovery:
    def teardown_method(self, _):
        _cleanup()

    def test_failed_rev_bump_recovered_and_arqueo_invalidated(self):
        """Repro del auditor: entrada histórica de 100; falla SOLO el
        incremento de revisión. El reintento completa la invalidación:
        un movimiento único, arqueo previo NO vigente, origen sincronizado."""
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
        bal = _resumen(box["id"], "USD")["balance"]
        _mk_arqueo(box["id"], "USD", _usd_denoms_for(bal))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True, "el arqueo recién creado es el cierre vigente"

        old_adj = _adj_doc("USD", 100, method="cash")
        old_adj["source_name"] = f"{MARK} histórico"
        old_adj["denominations"] = {"100": 1}
        old_adj["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        old_adj.pop("cash_box_movement_id")
        db.company_fund_adjustments.insert_one({**old_adj})

        def _fail_mirror():
            async def _f():
                from services import cash_box_sync as sync
                orig = sync._bump_fund_rev

                async def boom(box_id, fund):
                    raise RuntimeError("fallo inyectado en fund_revs")

                sync._bump_fund_rev = boom
                try:
                    try:
                        await sync.mirror_adjustment_to_cash_box(old_adj)
                        return "no-falló"
                    except RuntimeError:
                        return "falló"
                finally:
                    sync._bump_fund_rev = orig
            return _run(_f)

        assert _fail_mirror() == "falló"
        mov_id = f"cmov_adj_{old_adj['id'].replace('-', '')[:20]}"
        assert db.cash_box_movements.count_documents({"id": mov_id}) == 1
        src = db.company_fund_adjustments.find_one({"id": old_adj["id"]},
                                                   {"_id": 0})
        assert "cash_box_movement_id" not in src, \
            "el origen NO se declara sincronizado si falta la invalidación"

        _run_backfill()  # recuperador
        assert db.cash_box_movements.count_documents({"id": mov_id}) == 1, \
            "un solo movimiento por 100, sin duplicados"
        src = db.company_fund_adjustments.find_one({"id": old_adj["id"]},
                                                   {"_id": 0})
        assert src.get("cash_box_movement_id") == mov_id
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, \
            "el arqueo previo queda invalidado tras recuperar el histórico"
        assert _resumen(box["id"], "USD")["balance"] == round(bal + 100, 2)


class TestN06AccountIdentity:
    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)

    def teardown_method(self, _):
        _cleanup()

    def test_concurrent_first_use_single_identity(self):
        """Aceptación del auditor: dos primeras solicitudes concurrentes
        devuelven el MISMO identificador de cuenta."""
        db = _db()
        db.fund_accounts.delete_many({"currency": CCY})

        def _pair():
            async def _f():
                from services.fund_accounts import get_or_create_cash_box
                return await asyncio.gather(get_or_create_cash_box(CCY),
                                            get_or_create_cash_box(CCY))
            return _run(_f)

        a, b = _pair()
        assert a["id"] == b["id"], "una sola identidad de caja por moneda"
        assert db.fund_accounts.count_documents(
            {"currency": CCY, "system_purpose": "company_cash"}) == 1

    def test_duplicates_consolidated_preserving_links(self):
        """Los duplicados históricos se concilian sin perder movimientos:
        todos los vínculos pasan a la cuenta canónica (la más antigua)."""
        db = _db()
        _drop_identity_index(db)
        try:
            db.fund_accounts.delete_many({"currency": CCY})
            t0 = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            can_id = f"facc_{uuid.uuid4().hex[:12]}"
            dup_id = f"facc_{uuid.uuid4().hex[:12]}"
            for fid, ts in ((can_id, t0), (dup_id, _iso_now())):
                db.fund_accounts.insert_one({
                    "id": fid, "name": "Fondo Resilience", "currency": CCY,
                    "method": "cash", "system_purpose": "company_cash",
                    "is_active": True, "created_at": ts})
            db.company_fund_adjustments.insert_one(
                _adj_doc(CCY, 100, account=dup_id, method="cash"))
            trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
            db.fund_account_transfers.insert_one({
                "id": trid, "currency": CCY, "amount": 40,
                "from_account_id": dup_id, "to_account_id": can_id,
                "from_label": "dup", "to_label": "can",
                "note": MARK, "created_at": _iso_now()})
            cwid = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
            db.company_withdrawals.insert_one({
                "id": cwid, "currency": CCY, "amount": 10, "status": "paid",
                "beneficiary": f"{MARK} pagado", "paid_from_account_id": dup_id,
                "cash_box_movement_id": "na", "created_at": _iso_now()})

            def _consolidate():
                async def _f():
                    from services.fund_accounts import (
                        consolidate_duplicate_cash_accounts,
                    )
                    return await consolidate_duplicate_cash_accounts()
                return _run(_f)

            assert _consolidate() >= 1
            assert db.company_fund_adjustments.find_one(
                {"source_name": f"{MARK} aporte"},
                {"_id": 0})["account_id"] == can_id
            tr = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
            assert tr["from_account_id"] == can_id
            assert tr["to_account_id"] == can_id, \
                "el traslado entre duplicados queda neto en cero"
            assert db.company_withdrawals.find_one(
                {"id": cwid}, {"_id": 0})["paid_from_account_id"] == can_id
            dup = db.fund_accounts.find_one({"id": dup_id}, {"_id": 0})
            assert dup["is_active"] is False
            assert dup["merged_into"] == can_id
            assert "system_purpose" not in dup
            # saldos preservados: +100 (adj) − 10 (retiro) = 90 en la canónica
            bal = _breakdown_balances(CCY)
            assert bal[can_id] == 90.0 and bal.get(dup_id, 0.0) == 0.0
        finally:
            _restore_identity_index(db)

    def test_internal_transfer_between_duplicate_cash_accounts_no_outflow(self):
        """Aceptación del auditor: un traslado entre registros de la MISMA
        caja física no reduce el efectivo físico (no se refleja salida)."""
        db = _db()

        def _usd_account():
            async def _f():
                from services.fund_accounts import get_or_create_cash_box
                return await get_or_create_cash_box("USD")
            return _run(_f)

        usd = _usd_account()
        _drop_identity_index(db)
        dup_id = f"facc_{uuid.uuid4().hex[:12]}"
        try:
            db.fund_accounts.insert_one({
                "id": dup_id, "name": f"{MARK} dup", "currency": "USD",
                "method": "cash", "system_purpose": "company_cash",
                "is_active": True, "created_at": _iso_now()})
            tr = {"id": f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}",
                  "currency": "USD", "amount": 40,
                  "from_account_id": dup_id, "to_account_id": usd["id"],
                  "from_label": f"{MARK} dup", "to_label": usd["label"],
                  "created_at": _iso_now()}

            def _mirror():
                async def _f():
                    from services.cash_box_sync import (
                        mirror_fund_transfer_to_cash_box,
                    )
                    return await mirror_fund_transfer_to_cash_box(tr)
                return _run(_f)

            assert _mirror() is None, \
                "ambos extremos son la misma caja física: sin salida neta"
            assert db.cash_box_movements.count_documents(
                {"source_transfer_id": tr["id"]}) == 0
        finally:
            db.fund_accounts.delete_many({"id": dup_id})
            _restore_identity_index(db)


class TestN07CriticalSuite:
    def test_makefile_runs_cash_regressions_on_every_change(self):
        """N07 — las regresiones de caja (iter269 + iter270) forman parte de
        la suite crítica que corre en cada push/PR. M06 — la ruta del repo se
        deriva del propio test (portable a CI, sin depender de /app)."""
        repo_root = Path(__file__).resolve().parents[2]
        text = (repo_root / "Makefile").read_text()
        section = text.split("test-critical:")[1].split("test-all:")[0]
        assert "tests/test_iter269_verificacion_caja_fixes.py" in section
        assert "tests/test_iter270_revision_flujo_caja.py" in section


class TestCashOnlyCupUsd:
    """iter271 — el método Efectivo solo existe en CUP y USD (pedido del
    operador): otra moneda con method=cash se rechaza en el servidor."""

    def setup_method(self, _):
        _cleanup()
        _seed_currency(CCY)

    def teardown_method(self, _):
        _cleanup()

    def test_cash_adjustment_rejects_non_cash_currency(self):
        r = _adjust({"adjustment_type": "inflow", "currency": CCY,
                     "amount": 50, "method": "cash",
                     "source_name": f"{MARK} aporte"})
        assert r.status_code == 400, r.text
        assert "CUP y USD" in r.json()["detail"]
        assert _db().company_fund_adjustments.count_documents(
            {"currency": CCY}) == 0

    def test_cash_adjustment_usd_still_works(self):
        r = _adjust({"adjustment_type": "inflow", "currency": "USD",
                     "amount": 40, "method": "cash",
                     "source_name": f"{MARK} aporte",
                     "denominations": {"20": 2}})
        assert r.status_code == 200, r.text
        assert r.json()["account_label"] == "Fondo Resilience"
