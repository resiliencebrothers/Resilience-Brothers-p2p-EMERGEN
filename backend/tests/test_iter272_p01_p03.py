"""iter272 — Verificación Flujo de Caja (commit 9ea9251): pendientes P01–P03.

P01 protocolo de revocación: el nuevo turno de gasto ABORTA las
    transferencias provisionales del turno anterior — una confirmación
    con saldo vencido ya no puede aplicar (nunca 160 desde 100)
P02 la confirmación verifica matched_count y resuelve el estado persistido:
    jamás se declara éxito desde la copia local; un espejo unido a una
    transferencia abortada se anula con compensación trazable
P03 identidad canónica en TODOS los caminos: transferencias y ajustes
    normalizan alias fusionados antes de validar y persistir; el
    recuperador re-apunta vínculos nuevos que cayeran en un alias
"""
import uuid
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "ITER272"
CCY = "I272X"


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
    db.fund_account_transfers.delete_many({"currency": CCY})
    db.fund_account_transfers.delete_many({"note": {"$regex": MARK}})
    db.cash_box_movements.delete_many({"concept": {"$regex": MARK}})
    db.cash_box_arqueos.delete_many({"note": {"$regex": MARK}})
    db.fund_accounts.delete_many({"currency": CCY})
    db.fund_accounts.delete_many({"name": {"$regex": MARK}})
    db.currencies.delete_many({"code": CCY})
    db.company_fund_budgets.delete_many({})


def _seed_currency():
    _db().currencies.update_one(
        {"code": CCY},
        {"$setOnInsert": {"code": CCY, "name": f"Moneda Test 272 {CCY}",
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


def _transfer(body):
    return requests.post(f"{API}/admin/company-funds/accounts/transfer",
                         headers=_hdr(ADMIN_TOKEN), json=with_totp_admin(body))


def _adjust(body):
    return requests.post(f"{API}/admin/company-funds/adjustments",
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


def _balances(code):
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


def _mk_alias(canonical_id, currency=CCY):
    alias_id = f"facc_{uuid.uuid4().hex[:12]}"
    _db().fund_accounts.insert_one({
        "id": alias_id, "name": f"{MARK} alias", "currency": currency,
        "method": "cash", "is_active": False, "merged_into": canonical_id,
        "created_at": _iso_now()})
    return alias_id


class TestP01RevokedPendingCannotConfirm:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_stale_transfer_cannot_confirm_after_lock_steal(self):
        """Repro P01: A inserta su provisional y SUPERA la autorización; su
        cerrojo caduca y B ejecuta un traslado real. La provisional de A
        queda revocada: su confirmación no aplica y solo salen 80 de 100."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        # A: toma el cerrojo, inserta su provisional y la AUTORIZA
        token_a = _acquire_lock()
        assert token_a
        tra = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        db.fund_account_transfers.insert_one({
            "id": tra, "currency": CCY, "amount": 80,
            "from_account_id": caja, "to_account_id": banco,
            "from_label": "caja", "to_label": "banco", "note": MARK,
            "status": "pending", "created_at": _iso_now(),
            "operation_id": tra})
        assert _authority(CCY, token_a, tra) is True, \
            "A superó la autorización antes de pausarse"
        # su cerrojo caduca; B ejecuta una transferencia real de 80
        stale = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        db.company_fund_budgets.update_one(
            {"currency": CCY}, {"$set": {"pay_locked_at": stale}})
        r = _transfer({"currency": CCY, "from_account_id": caja,
                       "to_account_id": banco, "amount": 80})
        assert r.status_code == 200, r.text
        # el nuevo turno REVOCÓ la provisional de A
        doc_a = db.fund_account_transfers.find_one({"id": tra}, {"_id": 0})
        assert doc_a["status"] == "aborted", \
            "el nuevo dueño del turno aborta las provisionales anteriores"
        assert doc_a["aborted_reason"] == "turno de gasto transferido"
        # A reanuda: su confirmación exige status=pending → no aplica
        res = db.fund_account_transfers.update_one(
            {"id": tra, "status": "pending"},
            {"$set": {"status": "confirmed"}})
        assert res.matched_count == 0, \
            "el escritor antiguo no puede confirmar un saldo vencido"
        bal = _balances(CCY)
        assert bal[caja] == 20.0 and bal[banco] == 80.0, \
            f"solo una transferencia de 80 cuenta sobre los 100: {bal}"
        assert db.fund_account_transfers.count_documents(
            {"currency": CCY, "status": "confirmed"}) == 1
        assert db.cash_box_movements.count_documents(
            {"source_transfer_id": tra}) == 0, \
            "la operación perdedora no genera espejo"

    def test_concurrent_same_operation_id_single_transfer(self):
        """Aceptación P01: un reintento concurrente con el mismo operation_id
        produce UNA sola transferencia (el segundo recibe la ya confirmada)."""
        db = _db()
        caja = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=caja, method="cash"))
        op = f"op-{MARK.lower()}-{uuid.uuid4().hex[:8]}"
        body = {"currency": CCY, "from_account_id": caja,
                "to_account_id": banco, "amount": 40, "operation_id": op}
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_transfer, dict(body)) for _ in range(2)]
            results = [f.result() for f in futs]
        assert sorted(r.status_code for r in results) == [200, 200], \
            [r.text for r in results]
        ids = {r.json()["id"] for r in results}
        assert len(ids) == 1, "ambas respuestas devuelven el MISMO traslado"
        assert db.fund_account_transfers.count_documents(
            {"operation_id": op, "status": "confirmed"}) == 1
        bal = _balances(CCY)
        assert bal[caja] == 60.0 and bal[banco] == 40.0, \
            f"el importe se mueve una sola vez: {bal}"


class TestP02VerifiedConfirmation:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_route_checks_confirmation_result(self):
        """La ruta comprueba matched_count de pending→confirmed y resuelve el
        estado persistido: nunca declara éxito desde la copia local."""
        def _src():
            async def _f():
                import inspect
                from routes import company_fund_accounts as cfa
                return inspect.getsource(cfa.transfer_between_fund_accounts)
            return _run(_f)

        tr_src = _src()
        i_auth = tr_src.index("assert_spend_authority")
        tail = tr_src[i_auth:]
        assert "matched_count" in tail, \
            "la confirmación definitiva se verifica, no se asume"
        assert tail.index("matched_count") < tail.index('doc["status"] = "confirmed"')

    def test_mirror_tied_to_aborted_transfer_is_annulled(self):
        """Aceptación P02: un espejo físico que quedó unido a una
        transferencia abortada se anula con compensación trazable; cuenta y
        caja vuelven a coincidir y otro ciclo no duplica correcciones."""
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
        # residuo P02: transferencia ABORTADA cuyo espejo (salida 80) se creó
        # desde la copia local antes de este fix
        trid = f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}"
        mov_id = f"cmovp2{uuid.uuid4().hex[:10]}"
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.cash_box_movements.insert_one({
            "id": mov_id, "box_id": box["id"], "fund": "USD",
            "type": "salida", "amount": 80.0,
            "concept": f"{MARK} residuo abortada", "responsible": "Sistema",
            "denominations": None, "denoms_pending": True,
            "created_at": yesterday, "created_by_id": "system",
            "created_by_name": "Sistema", "source_transfer_id": trid,
            "rev_bumped": True})
        db.fund_account_transfers.insert_one({
            "id": trid, "currency": "USD", "amount": 80.0,
            "from_account_id": usd["id"], "to_account_id": None,
            "from_label": usd["label"], "to_label": "", "note": MARK,
            "status": "aborted", "aborted_reason": "huérfana",
            "created_at": yesterday, "operation_id": trid,
            "cash_box_movement_id": mov_id})
        assert _resumen(box["id"], "USD")["balance"] == round(base - 80, 2)

        _run_backfill()
        annul_id = f"cmov_annul_{mov_id.replace('-', '')[:24]}"
        annul = db.cash_box_movements.find_one({"id": annul_id}, {"_id": 0})
        assert annul and annul["type"] == "entrada" \
            and annul["amount"] == 80.0
        assert db.fund_account_transfers.find_one(
            {"id": trid}, {"_id": 0})["mirror_annulled_by"] == annul_id
        assert _resumen(box["id"], "USD")["balance"] == round(base, 2), \
            "cuenta y caja vuelven a coincidir"
        _run_backfill()  # otro ciclo: sin duplicados
        assert db.cash_box_movements.count_documents(
            {"annuls_movement_id": mov_id}) == 1


class TestP03CanonicalIdentityEverywhere:
    def setup_method(self, _):
        _cleanup()
        _seed_currency()

    def teardown_method(self, _):
        _cleanup()

    def test_transfer_to_alias_lands_on_canonical(self):
        """Repro del auditor: banco→alias tras la migración termina en la
        cuenta canónica; el alias queda sin saldo."""
        db = _db()
        can = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        alias = _mk_alias(can)
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=banco))
        r = _transfer({"currency": CCY, "from_account_id": banco,
                       "to_account_id": alias, "amount": 40})
        assert r.status_code == 200, r.text
        assert r.json()["to_account_id"] == can, \
            "se persiste la identidad canónica, no el alias"
        bal = _balances(CCY)
        assert bal[can] == 40.0 and bal[banco] == 60.0
        assert bal.get(alias, 0.0) == 0.0, "el alias jamás acumula saldo"

    def test_transfer_from_alias_and_equivalent_endpoints(self):
        db = _db()
        can = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        alias = _mk_alias(can)
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 100, account=can, method="cash"))
        # origen alias → consume el saldo de la canónica
        r = _transfer({"currency": CCY, "from_account_id": alias,
                       "to_account_id": banco, "amount": 30})
        assert r.status_code == 200, r.text
        assert r.json()["from_account_id"] == can
        bal = _balances(CCY)
        assert bal[can] == 70.0 and bal[banco] == 30.0
        # extremos equivalentes (alias → su canónica) = misma cuenta → 400
        r = _transfer({"currency": CCY, "from_account_id": alias,
                       "to_account_id": can, "amount": 10})
        assert r.status_code == 400, r.text
        assert "iguales" in r.json()["detail"]

    def test_adjustment_to_alias_attributed_to_canonical(self):
        db = _db()
        can = _mk_account(f"Caja {MARK}", CCY, "cash")
        alias = _mk_alias(can)
        r = _adjust({"adjustment_type": "inflow", "currency": CCY,
                     "amount": 50, "method": "transfer",
                     "source_name": f"{MARK} aporte alias",
                     "account_id": alias})
        assert r.status_code == 200, r.text
        assert r.json()["account_id"] == can, \
            "el resolutor de ajustes atribuye a la canónica"
        doc = db.company_fund_adjustments.find_one(
            {"source_name": f"{MARK} aporte alias"}, {"_id": 0})
        assert doc["account_id"] == can
        assert _balances(CCY)[can] == 50.0

    def test_backfill_repoints_links_saved_on_alias(self):
        """Vínculos NUEVOS que hubieran caído en un alias fusionado se
        re-apuntan a la canónica en la recuperación."""
        db = _db()
        can = _mk_account(f"Caja {MARK}", CCY, "cash")
        banco = _mk_account(f"Banco {MARK}", CCY, "bank")
        alias = _mk_alias(can)
        db.company_fund_adjustments.insert_one(
            _adj_doc(CCY, 90, account=alias))
        db.fund_account_transfers.insert_one({
            "id": f"tr{MARK.lower()}_{uuid.uuid4().hex[:8]}",
            "currency": CCY, "amount": 15, "from_account_id": banco,
            "to_account_id": alias, "note": MARK, "status": "confirmed",
            "created_at": _iso_now(),
            "operation_id": uuid.uuid4().hex,
            "cash_box_movement_id": "na"})
        _run_backfill()
        adj = db.company_fund_adjustments.find_one(
            {"source_name": f"{MARK} aporte", "currency": CCY}, {"_id": 0})
        assert adj["account_id"] == can
        tr = db.fund_account_transfers.find_one(
            {"note": MARK, "currency": CCY}, {"_id": 0})
        assert tr["to_account_id"] == can
        bal = _balances(CCY)
        assert bal[can] == 105.0 and bal.get(alias, 0.0) == 0.0, \
            f"todo el saldo vive en la canónica: {bal}"
