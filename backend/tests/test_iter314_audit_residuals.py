"""iter314 — Residuales del informe de verificación del 02/10/2026 sobre el
commit iter313 DESPLEGADO (reales, no código viejo):

  · CB08 (ALTA) — dos apellidos sin nombre pasaban como nombre+apellido. Ahora
    los nombres de pila se infieren por EVIDENCIA POSITIVA (primer token +
    nombres conocidos + palabras de doble función), nunca por descarte.
  · CB10 (CRÍTICO) — doble crédito cuando la reimportación llega ANTES de cerrar
    el primer crédito. El gemelo económico ahora detecta también créditos YA
    comprometidos sin estado final (`credit_backing_order`), y el crédito
    automático reserva ATÓMICAMENTE la identidad económica compartida entre
    representaciones del mismo pago.
  · DR02 (MEDIA) — la evidencia confirmada y la reserva activa apuntaban a
    movimientos distintos. La confirmación final exige ahora la GENERACIÓN
    vigente de la reserva (`evidence_claim_seq_next`), bumpeada atómicamente al
    mover la reserva.
  · CB15 (MEDIA) — un extracto compuesto solo de duplicados (sin respaldo
    propio) quedaba bloqueado al borrarse con un mensaje erróneo. Ahora los
    duplicados sin reclamo/orden/crédito se borran; el 409 solo aparece cuando
    de verdad hay respaldo.

Infra: un loop por método (el cliente Motor se enlaza al loop que lo usa).
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

from services.reconciliation_matcher import (
    DEFAULT_CONFIG, rank_candidates, decide, _given_name_candidates)

API = f"{BASE_URL}/api"
MARK = "iter314"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


# --- proxy de BD para pausar escrituras concretas y recrear carreras exactas ---
class _CollProxy:
    def __init__(self, real, on_update):
        self._real = real
        self._on_update = on_update

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def update_one(self, filt, update, *a, **k):
        await self._on_update(self._name, filt, update)
        return await self._real.update_one(filt, update, *a, **k)


class _DbProxy:
    def __init__(self, real, on_update, targets):
        self._real = real
        self._on_update = on_update
        self._targets = targets

    def __getattr__(self, name):
        if name in self._targets:
            p = _CollProxy(getattr(self._real, name), self._on_update)
            p._name = name
            return p
        return getattr(self._real, name)


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^btx{MARK}"}})
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^imp{MARK}"}})
    db.deposits.delete_many({"id": {"$regex": f"^dep{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.users.delete_many({"user_id": {"$regex": f"^u{MARK}"}})
    db.economic_credit_claims.delete_many({"tx_id": {"$regex": f"^btx{MARK}"}})


# ---------------------------------------------------------------------------
# CB08 — nombre de pila por evidencia positiva (dos apellidos sin nombre fallan).
# ---------------------------------------------------------------------------
class TestCB08PositiveGivenName:
    def _decision(self, holder, sender, amt=100.0):
        tx = {"id": "tx_x", "status": "manual_review", "direction": "credit",
              "amount": amt, "currency": "EUR", "sender_name": sender,
              "transaction_date": "2026-03-10"}
        order = {"id": "ord_1", "status": "pending", "kind": "order",
                 "from_code": "EUR", "currency": "EUR", "amount_from": amt,
                 "user_name": holder, "sender_name": holder,
                 "created_at": "2026-03-10"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        return decide(tx, ranked, DEFAULT_CONFIG, "", pool_complete=True)[
            "decision"]

    def test_unknown_first_surname_is_not_a_given_name(self):
        # BARO (primer apellido desconocido) ya NO se interpreta como nombre;
        # queda fuera del conjunto de nombres de pila (evidencia positiva).
        assert _given_name_candidates("RAYDEL BARO QUIAN") == {"RAYDEL"}
        assert "BARO" not in _given_name_candidates("RAYDEL BARO QUIAN")
        assert _given_name_candidates("MELISSA ZALDIVAR OLIVER") == {"MELISSA"}

    def test_two_surnames_without_given_name_go_to_review(self):
        assert self._decision("RAYDEL BARO QUIAN", "BARO QUIAN") != "auto"
        assert self._decision("MELISSA ZALDIVAR OLIVER", "ZALDIVAR OLIVER") \
            != "auto"

    def test_accepted_partial_names_still_autovalidate(self):
        assert self._decision("JOSE MANUEL PEREZ", "MANUEL PEREZ") == "auto"
        assert self._decision("ANA MARIA GARCIA", "MARIA GARCIA") == "auto"
        assert self._decision("PEDRO LEON PEREZ", "PEDRO LEON") == "auto"
        assert self._decision("PEDRO CRUZ GARCIA", "PEDRO CRUZ") == "auto"

    def test_second_given_name_prefix_rules_preserved(self):
        # Controles del informe: nombre+primer-apellido-desconocido sin apellido
        # real presente → revisión; nombre completo → auto.
        assert self._decision("JOSE YUNIER PEREZ", "JOSE YUNIER") != "auto"
        assert self._decision("JOSE YUNIER PEREZ", "JOSE YUNIER PEREZ") == "auto"
        assert self._decision("MARIA GARCIA LOPEZ", "MARIA GARCIA") == "auto"


# ---------------------------------------------------------------------------
# CB10 — doble crédito antes de cerrar la primera conciliación.
# ---------------------------------------------------------------------------
class TestCB10DoubleCreditBeforeClose:
    def setup_method(self, method):
        _cleanup()  # aislamiento: cada método parte sin gemelos de otros tests

    def _mk_order(self, oid, amount=137.0, name="ANA PEREZ GARCIA",
                  status="pending"):
        _db().orders.insert_one({
            "id": oid, "user_id": f"u{MARK}{oid}", "user_name": name,
            "user_email": f"{oid[:12]}@t.com", "sender_name": name,
            "amount_from": float(amount), "amount_to": float(amount) * 300,
            "from_code": "USD", "to_code": "CUP", "status": status,
            "payment_account_id": None, "payment_account_label": "Zelle",
            "created_at": _now(), "updated_at": _now()})

    def _mk_tx(self, suffix, amount=137.0, sender="ANA PEREZ GARCIA",
               description=None, status="unmatched", **extra):
        doc = {
            "id": f"btx{MARK}{suffix}",
            "statement_import_id": f"{MARK}_imp_{suffix}",
            "bank_account_id": None, "bank_name": "Test Bank",
            "currency": "USD", "direction": "credit", "amount": float(amount),
            "transaction_date": _today(), "sender_name": sender,
            "description": description, "reference": None,
            "fingerprint": f"fp_{uuid.uuid4().hex}",
            "fingerprint_original": f"fpo_{suffix}_{uuid.uuid4().hex[:8]}",
            "status": status, "confidence_score": None,
            "matched_order_id": None, "match_details": None, "candidates": [],
            "created_at": _now(), "updated_at": _now()}
        doc.update(extra)
        _db().bank_transactions.insert_one(dict(doc))
        return doc

    def test_twin_detects_committed_but_unclosed_credit(self):
        """El gemelo económico detecta un movimiento con crédito YA comprometido
        (`credit_backing_order`) aunque su estado final aún no esté escrito
        (sigue `unmatched`) — el agujero exacto que causaba el doble crédito."""
        from services.reconciliation_matcher import find_reconciled_economic_twin
        committed = self._mk_tx("pdfA", status="unmatched",
                                credit_backing_order=f"ord{MARK}A",
                                matching_claim={"order_id": f"ord{MARK}A"})
        probe = self._mk_tx("xlsA", description="Abono")
        twin = _run(find_reconciled_economic_twin(probe))
        assert twin is not None and twin["id"] == committed["id"]

    def test_economic_identity_claim_is_atomic(self):
        """Compare-and-set de identidad económica: la 1ª representación la toma,
        la 2ª (otro movimiento, misma identidad) pierde; liberar la devuelve."""
        from services.reconciliation_matcher import (
            claim_economic_identity, release_economic_identity)

        async def flow():
            key = f"econ|{MARK}|USD|credit|137.00|{_today()}|ANA PEREZ GARCIA"
            first = await claim_economic_identity(key, f"btx{MARK}c1")
            second = await claim_economic_identity(key, f"btx{MARK}c2")
            again_same = await claim_economic_identity(key, f"btx{MARK}c1")
            await release_economic_identity(key, f"btx{MARK}c1")
            after_release = await claim_economic_identity(key, f"btx{MARK}c2")
            return first, second, again_same, after_release

        first, second, again_same, after_release = _run(flow())
        assert first is True
        assert second is False, "otra representación NO puede re-tomar la identidad"
        assert again_same is True, "el mismo movimiento es idempotente"
        assert after_release is True, "tras liberar, otra representación la toma"

    def test_reimport_before_close_forced_to_review_single_credit(self):
        """Reproductor `cb_economic_twin_before_close`: el primer abono acreditó
        y comprometió su respaldo (`credit_backing_order`) pero su conciliación
        aún no cerró (estado todavía `unmatched`). Llega la 2ª representación del
        MISMO pago (otra huella) con una orden pendiente B compatible → NUNCA
        auto-acredita: va a REVISIÓN. Un único crédito; B no se aprueba."""
        from services.reconciliation_matcher import run_matching
        db = _db()
        self._mk_order(f"ord{MARK}B")  # orden pendiente compatible
        # Estado "comprometido pero sin cerrar" del primer abono (PDF).
        self._mk_tx("pdfC", status="unmatched",
                    credit_backing_order=f"ord{MARK}A",
                    matching_claim={"order_id": f"ord{MARK}A"})
        tx_xls = self._mk_tx("xlsC", description="Abono transferencia")

        async def flow():
            return await run_matching(
                {"currency": "USD", "bank_account_id": None}, [tx_xls])
        counts = _run(flow())

        assert counts["auto"] == 0, counts
        assert counts["review"] == 1, counts
        fb = db.bank_transactions.find_one({"id": tx_xls["id"]})
        assert fb["status"] == "manual_review"
        assert fb.get("duplicate_of") == f"btx{MARK}pdfC"
        assert db.orders.find_one({"id": f"ord{MARK}B"})["status"] == "pending", \
            "la 2ª orden NUNCA se aprueba: un único pago no acredita dos"

    def test_concurrent_representations_credit_once(self):
        """Dos representaciones SIMULTÁNEAS del mismo pago (ambas pasan la
        lectura de gemelo antes de que ninguna comprometa): la reserva atómica
        de identidad económica serializa el crédito — exactamente una acredita
        (auto) y la otra cae a revisión. Jamás 200 por un pago de 100."""
        from services.reconciliation_matcher import _apply_auto_match
        db = _db()
        self._mk_order(f"ord{MARK}P")
        self._mk_order(f"ord{MARK}Q")
        tx1 = self._mk_tx("conc1")
        tx2 = self._mk_tx("conc2")
        best1 = {"order_id": f"ord{MARK}P", "score": 100, "breakdown": {}}
        best2 = {"order_id": f"ord{MARK}Q", "score": 100, "breakdown": {}}

        async def flow():
            pool = [db.orders.find_one({"id": f"ord{MARK}P"}, {"_id": 0}),
                    db.orders.find_one({"id": f"ord{MARK}Q"}, {"_id": 0})]
            d1 = await _apply_auto_match(tx1, best1, pool, {}, set(),
                                         {"user_id": "sys", "role": "admin"},
                                         "unmatched")
            d2 = await _apply_auto_match(tx2, best2, pool, {}, set(),
                                         {"user_id": "sys", "role": "admin"},
                                         "unmatched")
            return d1, d2
        d1, d2 = _run(flow())
        assert sorted([d1, d2]) == ["auto", "review"], (d1, d2)


# ---------------------------------------------------------------------------
# DR02 — generación vigente gobierna la confirmación.
# ---------------------------------------------------------------------------
class TestDR02GenerationGovernsConfirm:
    def test_old_confirm_loses_when_reservation_moved_before_new_stamp(self):
        """Reproductor `dr_move_before_new_stamp`: A reserva/sella log:0 (seq 1)
        y se pausa ANTES de confirmar. B mueve la reserva a log:1 (seq 2) y se
        pausa ANTES de escribir el sello nuevo. A reanuda: su confirmación exige
        la GENERACIÓN vigente (`evidence_claim_seq_next == 1`), pero el 'move' de
        B ya la bumpeó a 2 atómicamente → A recibe 409. B confirma log:1.
        CIERRE: depósito confirmado, sello y reserva activa coinciden (log:1),
        crédito único."""
        import routes.deposits as dep
        real_db = dep.db
        client = f"u{MARK}dr02"
        _db().users.update_one(
            {"user_id": client},
            {"$set": {"user_id": client, "email": f"{client}@t.com",
                      "name": client, "role": "vip",
                      "vip_balances": {"USDT": 0.0}, "vip_balance_usd": 0.0,
                      "applied_credit_ops": []}}, upsert=True)
        dep_id = f"dep{MARK}dr02"
        _db().deposits.insert_one({
            "id": dep_id, "user_id": client, "user_email": f"{client}@t.com",
            "user_name": client, "user_role": "vip", "currency": "USDT",
            "amount": 100.0, "method": "crypto", "network": "BEP20",
            "tx_hash": f"{MARK}dr02_hash", "status": "pending",
            "created_at": _now(), "updated_at": _now()})

        async def flow():
            staff = await real_db.users.find_one(
                {"user_id": "user_test_admin01"}, {"_id": 0}) or {
                "user_id": "user_test_admin01", "role": "admin",
                "email": "admin.test@resilience.com"}
            a_confirm_reached, a_confirm_gate = asyncio.Event(), asyncio.Event()
            b_stamp_reached, b_stamp_gate = asyncio.Event(), asyncio.Event()

            async def on_update(coll, filt, update):
                if coll != "deposits":
                    return
                sets = update.get("$set", {}) if isinstance(update, dict) else {}
                task = asyncio.current_task().get_name()
                if task == "A" and sets.get("status") == "confirmed":
                    a_confirm_reached.set()
                    await a_confirm_gate.wait()
                if (task == "B" and "evidence_claim_movement" in sets
                        and "status" not in sets
                        and sets.get("evidence_claim_movement") == "log:1"):
                    b_stamp_reached.set()
                    await b_stamp_gate.wait()

            dep.db = _DbProxy(real_db, on_update, {"deposits"})
            try:
                dA = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tA = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA), staff, "log:0"), name="A")
                await asyncio.wait_for(a_confirm_reached.wait(), 15)
                dB = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tB = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dB), staff, "log:1"), name="B")
                await asyncio.wait_for(b_stamp_reached.wait(), 15)
                a_confirm_gate.set()
                rA = (await asyncio.gather(tA, return_exceptions=True))[0]
                b_stamp_gate.set()
                rB = (await asyncio.gather(tB, return_exceptions=True))[0]
                return rA, rB
            finally:
                dep.db = real_db

        from fastapi import HTTPException
        rA, rB = _run(flow())
        assert isinstance(rA, HTTPException) and rA.status_code == 409, rA
        assert isinstance(rB, dict) and rB.get("status") == "confirmed", rB
        fresh = _db().deposits.find_one({"id": dep_id})
        active = _db().crypto_evidence_claims.find_one(
            {"deposit_id": dep_id, "superseded": {"$ne": True}},
            {"_id": 0, "movement_id": 1})
        u = _db().users.find_one({"user_id": client}, {"_id": 0,
                                                       "vip_balances": 1})
        assert fresh["evidence_movement_id"] == "log:1"
        assert fresh["evidence_claim_movement"] == "log:1"
        assert (active or {}).get("movement_id") == "log:1"
        assert float((u.get("vip_balances") or {}).get("USDT") or 0) == 100.0
        _db().users.delete_many({"user_id": client})


# ---------------------------------------------------------------------------
# CB15 — borrado de un extracto solo-duplicados.
# ---------------------------------------------------------------------------
class TestCB15DeleteDuplicateOnly:
    def _mk_import(self, suffix):
        imp_id = f"imp{MARK}{suffix}"
        _db().bank_statement_imports.insert_one({
            "id": imp_id, "bank_name": "Test Bank", "currency": "USD",
            "original_file_name": f"{suffix}.pdf", "stored_file_url": "",
            "processing_status": "done", "created_at": _now()})
        return imp_id

    def _mk_tx(self, imp_id, suffix, **extra):
        doc = {
            "id": f"btx{MARK}{suffix}", "statement_import_id": imp_id,
            "bank_account_id": None, "bank_name": "Test Bank",
            "currency": "USD", "direction": "credit", "amount": 50.0,
            "transaction_date": _today(), "sender_name": "X",
            "fingerprint": f"fp_{MARK}_{suffix}_{uuid.uuid4().hex}",
            "status": "unmatched", "matched_order_id": None,
            "created_at": _now(), "updated_at": _now()}
        doc.update(extra)
        _db().bank_transactions.insert_one(dict(doc))
        return doc["id"]

    def test_duplicate_only_import_deletes_cleanly(self):
        """Un extracto cuyo único movimiento es un `duplicate` sin respaldo
        propio (sin reclamo, sin orden, sin crédito) se borra por completo
        (200) — ya NO se bloquea con el mensaje erróneo de 'confirmación'."""
        db = _db()
        imp_id = self._mk_import("dup")
        self._mk_tx(imp_id, "dup1", status="duplicate",
                    duplicate_of="external-bank-tx")
        r = requests.delete(f"{API}/admin/reconciliation/imports/{imp_id}",
                            headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert r.json()["removed_transactions"] == 1, r.text
        assert db.bank_statement_imports.find_one({"id": imp_id}) is None
        assert db.bank_transactions.count_documents(
            {"statement_import_id": imp_id}) == 0

    def test_free_unmatched_import_still_deletes(self):
        db = _db()
        imp_id = self._mk_import("free")
        self._mk_tx(imp_id, "free1")
        r = requests.delete(f"{API}/admin/reconciliation/imports/{imp_id}",
                            headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert db.bank_statement_imports.find_one({"id": imp_id}) is None

    def test_reconciled_import_blocked_with_accurate_message(self):
        """Un movimiento que SÍ respalda una acreditación conserva el bloqueo
        409, ahora con un mensaje preciso (respaldo), no el falso de carrera."""
        db = _db()
        imp_id = self._mk_import("recon")
        self._mk_tx(imp_id, "recon1", status="auto_matched",
                    matched_order_id="ordZ")
        r = requests.delete(f"{API}/admin/reconciliation/imports/{imp_id}",
                            headers=_h(ADMIN))
        assert r.status_code == 409, r.text
        assert "conciliados o en curso" in r.json().get("detail", "")
        assert db.bank_statement_imports.find_one({"id": imp_id}) is not None
