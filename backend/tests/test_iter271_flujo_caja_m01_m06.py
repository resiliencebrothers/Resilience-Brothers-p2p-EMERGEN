"""iter271 — Revisión Flujo de Caja (commit dd10586): correcciones M01–M06.

M01 autoridad de gasto INDIVISIBLE en el presupuesto: un dueño antiguo que
    repone su propio cercado tras perder el cerrojo no puede pagar
M02 transferencias en dos fases (pending → autoridad → confirmed): las
    provisionales/abortadas son invisibles para saldos y espejos; el rechazo
    queda trazable (aborted) y las huérfanas se abortan en el recuperador
M03 una cuenta fusionada (merged_into) nunca recupera la identidad
    automática; los resolutores siguen el alias hasta la canónica
M04 los espejos internos erróneos del histórico se anulan con una
    compensación trazable (nunca un aporte) y el arqueo queda invalidado
M05 el origen de un retiro de cliente YA PAGADO no puede cambiarse
M06 la comprobación de la suite crítica es portable (sin rutas absolutas)
"""
import asyncio
import uuid
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER271"
CCY = "I271X"

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
    db.fund_account_transfers.delete_many({"currency": CCY})
    db.fund_account_transfers.delete_many({"note": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    db.cash_box_arqueos.delete_many({"note": {"$regex": MARK}})
    db.fund_accounts.delete_many({"currency": CCY})
    db.fund_accounts.delete_many({"name": {"$regex": MARK}})
    db.currencies.delete_many({"code": CCY})
    db.company_fund_budgets.delete_many({})


def _seed_currency(code=CCY):
    _db().currencies.update_one(
        {"code": code},
        {"$setOnInsert": {"code": code, "name": f"Moneda Test 271 {code}",
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


def _cw_create(body):
    return requests.post(f"{API}/admin/company-withdrawals",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _cw_status(cwid, body):
    return requests.put(f"{API}/admin/company-withdrawals/{cwid}/status",
                        headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _w_status(wid, body):
    return requests.put(f"{API}/admin/withdrawals/{wid}/status",
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


def _breakdown(code):
    r = requests.get(f"{API}/admin/company-funds/accounts/{code}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _balances(code):
    return {a["id"]: float(a["balance"]) for a in _breakdown(code)["accounts"]}


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


def _acquire_lock(code=CCY):
    async def _f():
        from services import company_fund_budget as fb
        return await fb.acquire_pay_lock(code)
    return _run(_f)


def _authority(code, token, ref):
    async def _f():
        from services import company_fund_budget as fb
        return await fb.assert_spend_authority(code, token, ref)
    return _run(_f)


class TestM01SpendAuthority:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_stale_owner_cannot_reauthorize_after_losing_lock(self):
        """Repro M01: A pierde el cerrojo ANTES de estampar su cercado; al
        reanudarse repone su token en el retiro, pero la autoridad indivisible
        del presupuesto lo corta: nunca se pagan 160 sobre 100."""
        db = _db()
        db.company_fund_adjustments.insert_one(_adj_doc(CCY, 100))
        w1 = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        w2 = f"cw{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        for wid, tag in ((w1, "A"), (w2, "B")):
            db.company_withdrawals.insert_one({
                "id": wid, "currency": CCY, "amount": 80,
                "status": "pending", "beneficiary": f"{MARK} {tag}",
                "created_at": _iso_now()})
        token_a = _acquire_lock()
        assert token_a, "A toma el cerrojo y se pausa ANTES de estampar"
        stale = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        db.company_fund_budgets.update_one(
            {"currency": CCY}, {"$set": {"pay_locked_at": stale}})
        # B roba el cerrojo caducado y paga w2 por la vía real
        r = _cw_status(w2, {"status": "paid"})
        assert r.status_code == 200, r.text
        # A reanuda: REPONE su cercado (lo que su código haría al estampar)…
        db.company_withdrawals.update_one(
            {"id": w1}, {"$set": {"pay_fence": token_a}})
        # …pero la autoridad indivisible del presupuesto exige el cerrojo
        # VIGENTE: la ruta abortaría con 409 sin llegar a la transición.
        assert _authority(CCY, token_a, w1) is False, \
            "el dueño antiguo no puede re-autorizarse"
        assert db.company_withdrawals.find_one(
            {"id": w1}, {"_id": 0})["status"] == "pending"
        row = _fund_row(CCY)
        assert row and float(row["balance"]) == 20.0, \
            f"nunca se pagan 160 sobre 100: {row and row['balance']}"

    def test_spend_authority_follows_lock_ownership(self):
        db = _db()
        db.company_fund_adjustments.insert_one(_adj_doc(CCY, 100))
        t1 = _acquire_lock()
        assert t1
        assert _authority(CCY, t1, "op1") is True
        budget = db.company_fund_budgets.find_one({"currency": CCY}, {"_id": 0})
        assert budget["pay_authority"]["ref"] == "op1"
        assert _authority(CCY, "token-falso", "op2") is False

        def _release():
            async def _f():
                from services import company_fund_budget as fb
                await fb.release_pay_lock(CCY, t1)
            return _run(_f)

        _release()
        assert _authority(CCY, t1, "op3") is False, \
            "sin cerrojo no hay autoridad de gasto"

    def test_routes_wire_authority_before_definitive_writes(self):
        """El protocolo vive en las rutas reales: autoridad ANTES de la
        transición del pago, y pending→autoridad→confirmed en transferencias."""
        def _srcs():
            async def _f():
                import inspect
                from routes import admin_company_funds as acf
                from routes import company_fund_accounts as cfa
                return (inspect.getsource(acf._pay_company_withdrawal),
                        inspect.getsource(cfa.transfer_between_fund_accounts))
            return _run(_f)

        pay_src, tr_src = _srcs()
        assert pay_src.index("assert_spend_authority") \
            < pay_src.index("_claim_cw_transition(")
        i_ins = tr_src.index("insert_one")
        i_auth = tr_src.index("assert_spend_authority")
        i_conf = tr_src.index('"confirmed"')
        assert i_ins < i_auth < i_conf, \
            "la transferencia nace provisional y se confirma tras la autoridad"


class TestM02TwoPhaseTransfers:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_transfer_confirms_and_counts_only_confirmed(self):
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        t = _transfer({"currency": CCY, "from_account_id": caja,
                       "to_account_id": banco, "amount": 60})
        assert t.status_code == 200, t.text
        assert t.json()["status"] == "confirmed"
        bal = _balances(CCY)
        assert bal[caja] == 40.0 and bal[banco] == 60.0

    def test_pending_and_aborted_are_invisible_and_orphans_abort(self):
        """Una provisional no cuenta para saldos ni aparece en el historial;
        si su proceso murió, el recuperador la aborta de forma trazable."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": CCY, "amount": 50,
            "from_account_id": caja, "to_account_id": banco,
            "from_label": "caja", "to_label": "banco", "note": MARK,
            "status": "pending", "created_at": old,
            "operation_id": trid})
        bal = _balances(CCY)
        assert bal[caja] == 100.0 and bal.get(banco, 0.0) == 0.0, \
            "una provisional no mueve saldos"
        data = _breakdown(CCY)
        assert all(x["id"] != trid for x in data["transfers"]), \
            "una provisional no aparece en el historial"
        _run_backfill()
        doc = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert doc["status"] == "aborted" and doc.get("aborted_reason")
        assert "cash_box_movement_id" not in doc, "sin espejo físico"
        bal = _balances(CCY)
        assert bal[caja] == 100.0 and bal.get(banco, 0.0) == 0.0

    def test_pending_transfer_never_mirrored_until_confirmed(self):
        """Aceptación M02: el recuperador intercalado no registra la salida
        física de una transferencia aún provisional; tras confirmarse, sí."""
        db = _db()

        def _usd_cash():
            async def _f():
                from services.fund_accounts import get_or_create_cash_box
                return await get_or_create_cash_box("USD")
            return _run(_f)

        usd = _usd_cash()
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 25,
            "from_account_id": usd["id"], "to_account_id": None,
            "from_label": f"{MARK} origen", "to_label": "",
            "note": MARK, "status": "pending", "created_at": _iso_now(),
            "operation_id": trid})
        _run_backfill()  # recuperador intercalado: la ve pero NO la toca
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid}) == 0
        doc = db.fund_account_transfers.find_one({"id": trid}, {"_id": 0})
        assert "cash_box_movement_id" not in doc
        # se confirma (autoridad demostrada) → ahora sí se refleja UNA vez
        db.fund_account_transfers.update_one(
            {"id": trid}, {"$set": {"status": "confirmed"}})
        _run_backfill()
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": trid, "type": "salida"}) == 1

    def test_aborted_is_traceable_and_operation_id_retryable(self):
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        op = f"op-{MARK.lower()}-{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}",
            "currency": CCY, "amount": 30, "from_account_id": caja,
            "to_account_id": banco, "note": MARK, "status": "aborted",
            "aborted_reason": "cerrojo de gasto perdido",
            "created_at": _iso_now(), "operation_id": op})
        r = _transfer({"currency": CCY, "from_account_id": caja,
                       "to_account_id": banco, "amount": 30,
                       "operation_id": op})
        assert r.status_code == 200, \
            f"una abortada no bloquea el reintento: {r.text}"
        assert r.json()["status"] == "confirmed"
        assert db.fund_account_transfers.count_documents(
            {"operation_id": op, "status": "confirmed"}) == 1
        assert db.fund_account_transfers.count_documents(
            {"operation_id": op, "status": "aborted"}) == 1, \
            "la abortada sigue trazable"
        bal = _balances(CCY)
        assert bal[caja] == 70.0 and bal[banco] == 30.0, \
            "solo la confirmada cuenta"


class TestM03MergedAliases:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_backfill_never_restamps_merged_duplicate(self):
        """Aceptación M03: consolidar, instalar el índice y ejecutar el
        recuperador dos veces — sin colisiones, una sola identidad y los
        ajustes pendientes reflejados exactamente una vez."""
        db = _db()
        real = db.fund_accounts.find_one(
            {"currency": "USD", "system_purpose": "company_cash"}, {"_id": 0})
        assert real, "la cuenta de caja USD canónica debe existir"
        dup_id = f"facc_{uuid.uuid4().hex[:12]}"
        _drop_identity_index(db)
        try:
            db.fund_accounts.insert_one({
                "id": dup_id, "name": "Fondo Resilience", "currency": "USD",
                "method": "cash", "system_purpose": "company_cash",
                "is_active": True, "created_at": _iso_now()})

            def _consolidate():
                async def _f():
                    from services.fund_accounts import (
                        consolidate_duplicate_cash_accounts,
                    )
                    return await consolidate_duplicate_cash_accounts()
                return _run(_f)

            assert _consolidate() >= 1
        finally:
            _restore_identity_index(db)
        dup = db.fund_accounts.find_one({"id": dup_id}, {"_id": 0})
        assert dup["merged_into"] == real["id"]
        assert "system_purpose" not in dup
        # ajuste pendiente + recuperador COMPLETO dos veces: sin colisión de
        # índice y el ajuste llega a caja exactamente una vez
        adj_id = f"adj{MARK.lower()}_{uuid.uuid4().hex[:10]}"
        try:
            db.company_fund_adjustments.insert_one({
                "id": adj_id, "adjustment_type": "inflow", "currency": "USD",
                "amount": 40.0, "method": "cash",
                "source_name": f"{MARK} pendiente",
                "denominations": {"20": 2}, "created_at": _iso_now()})
            _run_backfill()
            src = db.company_fund_adjustments.find_one({"id": adj_id},
                                                       {"_id": 0})
            assert str(src.get("cash_box_movement_id") or "").startswith(
                "cmov_adj_"), "el ajuste pendiente SÍ llegó a caja"
            _run_backfill()
            assert db.cash_box_movements.count_documents(
                {"source_adjustment_id": adj_id}) == 1
            dup = db.fund_accounts.find_one({"id": dup_id}, {"_id": 0})
            assert "system_purpose" not in dup, \
                "el estampador nunca re-marca una cuenta fusionada"
        finally:
            db.fund_accounts.delete_many({"id": dup_id})

    def test_resolver_and_payment_follow_merged_alias(self):
        """Un alias fusionado remite a la canónica: pagar seleccionando el id
        antiguo atribuye a la cuenta canónica, nunca al alias."""
        db = _db()
        can = _mk_account(f"Caja {MARK}", CCY, "cash")
        alias_id = f"facc_{uuid.uuid4().hex[:12]}"
        db.fund_accounts.insert_one({
            "id": alias_id, "name": f"{MARK} alias", "currency": CCY,
            "method": "cash", "is_active": False, "merged_into": can,
            "created_at": _iso_now()})
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=can, method="cash"))

        def _resolve():
            async def _f():
                from services.fund_accounts import resolve_fund_account
                return await resolve_fund_account(alias_id)
            return _run(_f)

        resolved = _resolve()
        assert resolved and resolved["id"] == can

        cw = _cw_create({"currency": CCY, "amount": 30,
                         "beneficiary": f"{MARK} proveedor", "concept": "x"})
        assert cw.status_code == 200, cw.text
        r = _cw_status(cw.json()["id"],
                       {"status": "paid", "paid_from_account_id": alias_id})
        assert r.status_code == 200, r.text
        doc = db.company_withdrawals.find_one({"id": cw.json()["id"]},
                                              {"_id": 0})
        assert doc["paid_from_account_id"] == can, \
            "la atribución cae en la canónica, no en el alias"
        assert _balances(CCY)[can] == 70.0


class TestM04InternalMirrorRepair:
    def teardown_method(self, _):
        _cleanup()

    def test_phantom_outflow_is_annulled_traceably(self):
        """Aceptación M04: el residuo histórico (traslado interno con salida
        física errónea) se repara con una compensación trazable — cuenta y
        caja terminan iguales, el cierre previo se invalida y repetir no
        añade otras correcciones."""
        _cleanup()
        db = _db()
        _run_backfill()  # drenar pendientes ajenos

        def _usd_cash():
            async def _f():
                from services.fund_accounts import get_or_create_cash_box
                return await get_or_create_cash_box("USD")
            return _run(_f)

        usd = _usd_cash()
        box = _auto_box()
        assert box
        base = _resumen(box["id"], "USD")["balance"]
        # residuo: traslado interno (mismo origen y destino tras consolidar)
        # cuyo espejo de la versión anterior descontó 40 de la caja
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        mov_id = f"cmovm4{uuid.uuid4().hex[:10]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "salida", "amount": 40.0,
            "concept": f"{MARK} residuo interno", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": yesterday, "created_by_id": "system",
            "created_by_name": "Sistema", "source_transfer_id": trid,
            "rev_bumped": True})
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 40.0,
            "from_account_id": usd["id"], "to_account_id": usd["id"],
            "from_label": usd["label"], "to_label": usd["label"],
            "note": MARK, "status": "confirmed", "created_at": yesterday,
            "operation_id": trid, "cash_box_movement_id": mov_id})
        assert _resumen(box["id"], "USD")["balance"] == round(base - 40, 2), \
            "la salida fantasma descuenta 40 antes de la reparación"
        _mk_arqueo(box["id"], "USD",
                   _usd_denoms_for(max(int(base - 40), 0)))
        _, vigente = _closing_valid(box["id"])
        assert vigente is True

        _run_backfill()
        annul_id = f"cmov_annul_{mov_id.replace('-', '')[:24]}"
        annul = db.cash_box_movements.find_one({"id": annul_id}, {"_id": 0})
        assert annul and annul["type"] == "entrada" \
            and annul["amount"] == 40.0
        assert annul["annuls_movement_id"] == mov_id
        assert db.cash_box_movements.find_one(
            {"id": mov_id}, {"_id": 0})["annulled_by"] == annul_id
        assert db.fund_account_transfers.find_one(
            {"id": trid}, {"_id": 0})["mirror_annulled_by"] == annul_id
        assert _resumen(box["id"], "USD")["balance"] == round(base, 2), \
            "caja recuperada sin inventar capital"
        _, vigente = _closing_valid(box["id"])
        assert vigente is False, "el cierre previo deja de certificar"
        _run_backfill()  # idempotente
        assert db.cash_box_movements.count_documents(
            {"annuls_movement_id": mov_id}) == 1


class TestM05PaidOriginLocked:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_paid_client_withdrawal_origin_cannot_change(self):
        """Aceptación M05: cambiar el origen (caja→banco) de un retiro ya
        pagado se RECHAZA sin cambios; los reintentos no re-atribuyen."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=banco))
        wid = f"w{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.withdrawals.insert_one({
            "id": wid, "user_id": "user_m05", "user_name": f"{MARK} Cliente",
            "currency": CCY, "amount_usd": 40.0, "method": "cash",
            "cash_delivery_mode": "office_pickup", "status": "approved",
            "created_at": _iso_now()})
        r = _w_status(wid, {"status": "paid", "paid_from_account_id": caja})
        assert r.status_code == 200, r.text
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["paid_from_account_id"] == caja
        bal = _balances(CCY)
        assert bal[caja] == 60.0 and bal[banco] == 100.0
        # cambiar el origen a banco → rechazo sin cambios
        r = _w_status(wid, {"status": "paid", "paid_from_account_id": banco})
        assert r.status_code == 409, r.text
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["paid_from_account_id"] == caja
        bal = _balances(CCY)
        assert bal[caja] == 60.0 and bal[banco] == 100.0, \
            "contabilidad intacta tras el rechazo"
        # reintento sin cuenta: JAMÁS re-atribuye a otra cuenta
        r = _w_status(wid, {"status": "paid"})
        assert r.status_code in (200, 409), r.text
        w = db.withdrawals.find_one({"id": wid}, {"_id": 0})
        assert w["paid_from_account_id"] == caja


class TestM06PortableCriticalSuite:
    def test_critical_suite_check_is_portable(self):
        """M06 — la comprobación de la suite crítica deriva la ruta del repo
        del propio test: funciona en local, Emergent y GitHub Actions."""
        repo_root = Path(__file__).resolve().parents[2]
        text = (repo_root / "Makefile").read_text()
        section = text.split("test-critical:")[1].split("test-all:")[0]
        for fname in ("test_iter269_verificacion_caja_fixes.py",
                      "test_iter270_revision_flujo_caja.py",
                      "test_iter271_flujo_caja_m01_m06.py"):
            assert f"tests/{fname}" in section
        peer = Path(__file__).resolve().parent / \
            "test_iter270_revision_flujo_caja.py"
        assert '"/app/Makefile"' not in peer.read_text(), \
            "sin rutas absolutas en las comprobaciones de CI"
