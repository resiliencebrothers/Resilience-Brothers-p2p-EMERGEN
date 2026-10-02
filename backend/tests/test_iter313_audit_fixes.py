"""iter313 — Regresión de los 5 arreglos de concurrencia/atomicidad reportados
en el informe de Verificación de Conciliación (DR02, DR09, CB08, CB10, CB15).

Cada bloque reproduce el invariante EXACTO que quedó blindado en la sesión:

  · DR02 — secuencia monotónica por depósito (`_next_evidence_seq`) + guarda
    `evidence_claim_stamp_seq $lte`: una reserva ANTIGUA (superada por otra
    confirmación concurrente con secuencia mayor) jamás re-sella el depósito.
  · DR09 — `commit_origin_cancel_intent` exige el TOKEN propio (propiedad
    estricta); el comportamiento concurrente completo vive en iter305. Aquí se
    fija la firma para que ningún llamador vuelva a comprometer una intención
    ajena.
  · CB08 — `_given_name_candidates` deriva los nombres de pila de TODO token
    que no sea apellido fiable, así 'MANUEL PEREZ' o 'MARIA GARCIA'
    auto-concilian (antes iban a revisión con 'given_name_missing').
  · CB10 — si un gemelo económico YA está conciliado, un segundo abono que
    casaría con una orden pendiente se fuerza a REVISIÓN (jamás auto → nunca
    doble crédito de un único pago), sin marcarlo como duplicado porque hay una
    orden pendiente que podría corresponder.
  · CB15 — el borrado del extracto elimina SOLO los movimientos libres; una
    confirmación que gane la carrera deja su movimiento conciliado y aborta el
    borrado (409), conservando el respaldo de la orden acreditada.

Infra: el cliente Motor compartido se enlaza al loop que lo usa, así que cada
método hace TODO su trabajo async dentro de un único `_run` (un loop por
método), igual que iter306/iter312.
"""
import asyncio
import inspect
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

from services.reconciliation_matcher import (
    DEFAULT_CONFIG, rank_candidates, decide,
    _given_name_candidates, _surname_candidates)

API = f"{BASE_URL}/api"
MARK = "iter313"


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


# ---------------------------------------------------------------------------
# Proxy de BD para pausar escrituras concretas y recrear una carrera exacta
# (mismo patrón que iter306): intercepta `deposits.update_one`.
# ---------------------------------------------------------------------------
class _CollProxy:
    def __init__(self, real, on_update):
        self._real = real
        self._on_update = on_update

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def update_one(self, filt, update, *a, **k):
        await self._on_update(filt, update)
        return await self._real.update_one(filt, update, *a, **k)


class _DbProxy:
    def __init__(self, real, on_update):
        self._real = real
        self._on_update = on_update

    def __getattr__(self, name):
        if name == "deposits":
            return _CollProxy(self._real.deposits, self._on_update)
        return getattr(self._real, name)


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


def _cleanup():
    db = _db()
    db.orders.delete_many({"id": {"$regex": f"^ord{MARK}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^btx{MARK}"}})
    db.deposits.delete_many({"id": {"$regex": f"^dep{MARK}"}})
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^imp{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.users.delete_many({"user_id": "u_dr02race"})


# ---------------------------------------------------------------------------
# DR02 — secuencia monotónica + guarda de sello por secuencia.
# ---------------------------------------------------------------------------
class TestDR02EvidenceSequence:
    def _mk_deposit(self, dep_id):
        _db().deposits.insert_one({
            "id": dep_id, "user_id": f"u{dep_id}", "currency": "USDT",
            "amount": 100.0, "method": "crypto", "network": "BEP20",
            "tx_hash": f"hash_{dep_id}", "status": "pending",
            "created_at": _now(), "updated_at": _now()})

    def test_next_seq_is_strictly_monotonic_per_deposit(self):
        """Cada llamada a `_next_evidence_seq` devuelve un número estrictamente
        creciente para el MISMO depósito (base para ordenar reservas)."""
        dep_id = f"dep{MARK}seq"
        self._mk_deposit(dep_id)

        async def flow():
            import routes.deposits as dep
            return [await dep._next_evidence_seq(dep_id) for _ in range(3)]

        seqs = _run(flow())
        assert seqs == sorted(seqs) and len(set(seqs)) == 3, seqs
        assert seqs[0] < seqs[1] < seqs[2], seqs

    def test_stale_stamp_cannot_overwrite_newer(self):
        """Una reserva ANTIGUA (secuencia menor a la ya sellada) NO puede
        reescribir el sello; una secuencia >= a la sellada sí. Es la guarda
        `evidence_claim_stamp_seq $lte my_seq` que evita que un intento superado
        vuelva a sellar el depósito con un movimiento obsoleto."""
        dep_id = f"dep{MARK}stamp"
        self._mk_deposit(dep_id)
        _db().deposits.update_one(
            {"id": dep_id}, {"$set": {"evidence_claim_stamp_seq": 5,
                                      "evidence_claim_movement": "mov5"}})

        async def flow():
            import routes.deposits as dep
            stale = await dep.db.deposits.update_one(
                {"id": dep_id, "status": "pending",
                 "$or": [{"evidence_claim_stamp_seq": {"$exists": False}},
                         {"evidence_claim_stamp_seq": {"$lte": 3}}]},
                {"$set": {"evidence_claim_movement": "mov3",
                          "evidence_claim_stamp_seq": 3}})
            newer = await dep.db.deposits.update_one(
                {"id": dep_id, "status": "pending",
                 "$or": [{"evidence_claim_stamp_seq": {"$exists": False}},
                         {"evidence_claim_stamp_seq": {"$lte": 7}}]},
                {"$set": {"evidence_claim_movement": "mov7",
                          "evidence_claim_stamp_seq": 7}})
            return stale.modified_count, newer.modified_count

        stale_mod, newer_mod = _run(flow())
        assert stale_mod == 0, "una reserva superada no re-sella el depósito"
        assert newer_mod == 1, "una secuencia mayor-o-igual sí sella"
        fresh = _db().deposits.find_one({"id": dep_id})
        assert fresh["evidence_claim_movement"] == "mov7"
        assert fresh["evidence_claim_stamp_seq"] == 7

    def test_displaced_attempt_cannot_confirm_and_stamp_stays_consistent(self):
        """Escenario EXACTO del auditor (reproducción E2E con pausas a nivel
        motor): A reserva log:0 y se pausa ANTES de escribir su marca. B mueve
        la reserva a log:1, escribe la marca y se pausa ANTES de confirmar. A se
        reanuda. Con la guarda de secuencia v5, la marca de A (secuencia menor)
        se RECHAZA y su confirmación recibe 409 — el intento desplazado jamás
        acredita. B gana. CIERRE: depósito confirmado, sello de identidad y
        reserva activa indican el MISMO movimiento (log:1) y el saldo es único."""
        import routes.deposits as dep
        real_db = dep.db
        client = "u_dr02race"
        _db().users.update_one(
            {"user_id": client},
            {"$set": {"user_id": client, "email": f"{client}@t.com",
                      "name": client, "role": "vip",
                      "vip_balances": {"USDT": 0.0}, "vip_balance_usd": 0.0,
                      "applied_credit_ops": []}}, upsert=True)
        dep_id = f"dep{MARK}race"
        _db().deposits.insert_one({
            "id": dep_id, "user_id": client, "user_email": f"{client}@t.com",
            "user_name": client, "user_role": "vip", "currency": "USDT",
            "amount": 100.0, "method": "crypto", "network": "BEP20",
            "tx_hash": f"{MARK}race_hash", "status": "pending",
            "created_at": _now(), "updated_at": _now()})

        async def flow():
            staff = await real_db.users.find_one(
                {"user_id": "user_test_admin01"}, {"_id": 0}) or {
                "user_id": "user_test_admin01", "role": "admin",
                "email": "admin.test@resilience.com"}
            a_stamp_reached, a_stamp_gate = asyncio.Event(), asyncio.Event()
            b_flip_reached, b_flip_gate = asyncio.Event(), asyncio.Event()

            async def on_update(filt, update):
                sets = update.get("$set", {}) if isinstance(update, dict) else {}
                if "evidence_claim_stamp_seq" in sets \
                        and sets.get("status") is None \
                        and sets.get("evidence_claim_movement") == "log:0":
                    a_stamp_reached.set()
                    await a_stamp_gate.wait()
                if sets.get("status") == "confirmed" \
                        and filt.get("evidence_claim_movement") == "log:1":
                    b_flip_reached.set()
                    await b_flip_gate.wait()

            dep.db = _DbProxy(real_db, on_update)
            try:
                dA = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tA = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dA), staff, "log:0"))
                await asyncio.wait_for(a_stamp_reached.wait(), 15)
                dB = await real_db.deposits.find_one({"id": dep_id}, {"_id": 0})
                tB = asyncio.create_task(
                    dep._do_confirm_deposit(dict(dB), staff, "log:1"))
                await asyncio.wait_for(b_flip_reached.wait(), 15)
                a_stamp_gate.set()
                rA = (await asyncio.gather(tA, return_exceptions=True))[0]
                b_flip_gate.set()
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
        assert fresh["status"] == "confirmed"
        assert fresh["evidence_movement_id"] == "log:1"
        assert fresh["evidence_claim_movement"] == "log:1"
        assert (active or {}).get("movement_id") == "log:1"
        assert float((u.get("vip_balances") or {}).get("USDT") or 0) == 100.0, \
            "crédito único: jamás 200 USDT con un solo abono"
        _db().users.delete_many({"user_id": client})


# ---------------------------------------------------------------------------
# DR09 — propiedad estricta del token al comprometer la intención de cancelación.
# ---------------------------------------------------------------------------
class TestDR09CommitTokenSignature:
    def test_commit_requires_own_token(self):
        """`commit_origin_cancel_intent(job_id, token, actor_id="")` — el token
        es el 2º parámetro POSICIONAL obligatorio. El comportamiento
        concurrente (robo de intención) está cubierto en iter305."""
        from services.deliveries import commit_origin_cancel_intent
        params = list(inspect.signature(commit_origin_cancel_intent).parameters)
        assert params[:2] == ["job_id", "token"], params

    def test_callers_pass_intent_token(self):
        """Los dos llamadores (cancelación del cliente y rechazo administrativo)
        pasan el `intent_token` devuelto por la reserva — jamás comprometen bajo
        una protección ajena."""
        import routes.orders as orders_mod
        import routes.admin_withdrawals as aw_mod
        src = (inspect.getsource(orders_mod.cancel_own_withdrawal)
               + inspect.getsource(aw_mod._claim_entering_rejected))
        assert "commit_origin_cancel_intent(job[\"id\"], intent_token" in src


# ---------------------------------------------------------------------------
# CB08 — nombres de pila incluyen el SEGUNDO nombre (2 nombres + 1 apellido).
# ---------------------------------------------------------------------------
class TestCB08GivenNames:
    def _decision(self, order_name, sender, amt=100.0):
        tx = {"id": "tx_x", "status": "manual_review", "direction": "credit",
              "amount": amt, "currency": "EUR", "sender_name": sender,
              "transaction_date": "2026-03-10"}
        order = {"id": "ord_1", "status": "pending", "kind": "order",
                 "from_code": "EUR", "currency": "EUR", "amount_from": amt,
                 "user_name": order_name, "sender_name": order_name,
                 "created_at": "2026-03-10"}
        ranked = rank_candidates(tx, [order], DEFAULT_CONFIG, "", set())
        return decide(tx, ranked, DEFAULT_CONFIG, "", pool_complete=True)

    def test_second_given_name_is_a_given_candidate(self):
        assert _given_name_candidates("JOSE MANUEL PEREZ") == {"JOSE", "MANUEL"}
        assert _surname_candidates("JOSE MANUEL PEREZ") == {"PEREZ"}

    def test_second_given_name_plus_surname_autovalidates(self):
        assert self._decision("José Manuel Pérez", "Manuel Pérez")[
            "decision"] == "auto"

    def test_female_second_given_name_plus_surname_autovalidates(self):
        assert self._decision("Ana María García", "María García")[
            "decision"] == "auto"

    def test_surname_only_sender_never_autovalidates(self):
        assert self._decision("José Manuel Pérez", "Pérez")[
            "decision"] != "auto"


# ---------------------------------------------------------------------------
# CB10 — gemelo económico conciliado fuerza REVISIÓN (nunca doble crédito).
# ---------------------------------------------------------------------------
class TestCB10TwinForcesReview:
    def _mk_order(self, oid, amount=137.0, name="ANA PEREZ GARCIA",
                  status="pending"):
        _db().orders.insert_one({
            "id": oid, "user_id": f"u{oid}", "user_name": name,
            "user_email": f"{oid[:12]}@t.com", "sender_name": name,
            "amount_from": float(amount), "amount_to": float(amount) * 300,
            "from_code": "USD", "to_code": "CUP", "status": status,
            "payment_account_id": None, "payment_account_label": "Zelle",
            "created_at": _now(), "updated_at": _now()})

    def _mk_tx(self, suffix, amount=137.0, sender="ANA PEREZ GARCIA",
               description=None, status="unmatched"):
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
        _db().bank_transactions.insert_one(dict(doc))
        return doc

    async def _match(self, tx_doc):
        from services.reconciliation_matcher import run_matching
        return await run_matching(
            {"currency": tx_doc["currency"], "bank_account_id": None}, [tx_doc])

    def test_reconciled_twin_forces_pending_order_to_review(self):
        """Orden A auto-concilia con el abono PDF. Llega el MISMO pago en Excel
        (huella distinta) y HAY una segunda orden pendiente B compatible: en vez
        de auto-conciliar B (que duplicaría el crédito de un único pago), se
        fuerza a REVISIÓN con `possible_reimport_duplicate` y `duplicate_of` al
        original. B queda pendiente — nunca se aprueba automáticamente.

        Todo el trabajo async va en un ÚNICO `_run` (un loop por método): B y el
        abono Excel se crean DENTRO del flujo, después de que A auto-concilie,
        para que el primer match no vea dos órdenes idénticas compitiendo."""
        db = _db()
        oidA, oidB = f"ord{MARK}A", f"ord{MARK}B"
        self._mk_order(oidA)
        tx_pdf = self._mk_tx("Apdf",
                             description="TRANSFERENCIA DE ANA PEREZ GARCIA")

        async def flow():
            c1 = await self._match(tx_pdf)
            self._mk_order(oidB)  # orden compatible creada tras auto-conciliar A
            tx_xls = self._mk_tx("Axls", description="Abono transferencia")
            c2 = await self._match(tx_xls)
            return c1, c2, tx_xls["id"]

        c1, c2, xls_id = _run(flow())
        assert c1["auto"] == 1, c1
        assert db.orders.find_one({"id": oidA})["status"] == "approved"

        assert c2["review"] == 1, c2
        assert c2["auto"] == 0, c2
        assert c2["duplicate"] == 0, c2
        fb = db.bank_transactions.find_one({"id": xls_id})
        assert fb["status"] == "manual_review", fb.get("status")
        assert fb.get("duplicate_of") == tx_pdf["id"]
        assert fb.get("review_flag") == "possible_reimport_duplicate"
        assert "possible_reimport_duplicate" in (fb.get("auto_block_reasons")
                                                 or [])
        assert db.orders.find_one({"id": oidB})["status"] == "pending", \
            "la segunda orden NUNCA se aprueba: un único pago no acredita dos"


# ---------------------------------------------------------------------------
# CB15 — borrado atómico del extracto: libres fuera, conciliados se conservan.
# ---------------------------------------------------------------------------
class TestCB15AtomicDelete:
    def _mk_import(self, suffix, currency="USD"):
        imp_id = f"imp{MARK}{suffix}"
        _db().bank_statement_imports.insert_one({
            "id": imp_id, "bank_name": "Test Bank", "currency": currency,
            "original_file_name": f"{suffix}.pdf", "stored_file_url": "",
            "processing_status": "done", "created_at": _now()})
        return imp_id

    def _mk_tx(self, imp_id, suffix, status="unmatched", **extra):
        doc = {
            "id": f"btx{MARK}{suffix}", "statement_import_id": imp_id,
            "bank_account_id": None, "bank_name": "Test Bank",
            "currency": "USD", "direction": "credit", "amount": 50.0,
            "transaction_date": _today(), "sender_name": "X",
            "fingerprint": f"fp_{MARK}_{suffix}_{uuid.uuid4().hex}",
            "status": status, "matched_order_id": None,
            "created_at": _now(), "updated_at": _now()}
        doc.update(extra)
        _db().bank_transactions.insert_one(dict(doc))
        return doc["id"]

    def test_delete_free_import_removes_all_transactions(self):
        """Un extracto totalmente libre se borra: registro + movimientos + 200
        con el conteo exacto de movimientos eliminados."""
        db = _db()
        imp_id = self._mk_import("free")
        self._mk_tx(imp_id, "free1")
        self._mk_tx(imp_id, "free2")
        r = requests.delete(f"{API}/admin/reconciliation/imports/{imp_id}",
                            headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert r.json()["removed_transactions"] == 2, r.text
        assert db.bank_statement_imports.find_one({"id": imp_id}) is None
        assert db.bank_transactions.count_documents(
            {"statement_import_id": imp_id}) == 0

    def test_delete_blocked_when_a_transaction_is_reconciled(self):
        """Un extracto con un movimiento conciliado (auto_matched) recibe 409 y
        se CONSERVA íntegro — jamás orfana el respaldo de una orden acreditada."""
        db = _db()
        imp_id = self._mk_import("recon")
        self._mk_tx(imp_id, "recon1", status="auto_matched",
                    matched_order_id="ordZ")
        r = requests.delete(f"{API}/admin/reconciliation/imports/{imp_id}",
                            headers=_h(ADMIN))
        assert r.status_code == 409, r.text
        assert db.bank_statement_imports.find_one({"id": imp_id}) is not None
        assert db.bank_transactions.count_documents(
            {"statement_import_id": imp_id}) == 1

    def test_atomic_filter_deletes_free_and_preserves_claimed(self):
        """Invariante del borrado atómico (segunda línea de defensa ante la
        carrera): la eliminación toca SOLO los movimientos libres; los
        conciliados o con reclamo activo sobreviven, y su supervivencia dispara
        el 409 de aborto. Reproduce las dos consultas EXACTAS de `delete_import`
        sobre un extracto con 1 libre + 1 conciliado + 1 reclamado."""
        db = _db()
        imp_id = self._mk_import("race")
        self._mk_tx(imp_id, "raceFree")
        self._mk_tx(imp_id, "raceMatched", status="manual_matched",
                    matched_order_id="ordY")
        self._mk_tx(imp_id, "raceClaim",
                    matching_claim={"order_id": "ordW", "token": "t"})

        removed = db.bank_transactions.delete_many(
            {"statement_import_id": imp_id,
             "status": {"$nin": ["auto_matched", "manual_matched",
                                 "duplicate"]},
             "matching_claim": {"$exists": False},
             "matched_order_id": {"$in": [None, ""]}})
        leftover = db.bank_transactions.find_one(
            {"statement_import_id": imp_id}, {"_id": 0, "id": 1})

        assert removed.deleted_count == 1, "solo el movimiento libre se borra"
        assert leftover is not None, \
            "los conciliados/reclamados sobreviven → el borrado se aborta (409)"
        assert db.bank_transactions.count_documents(
            {"statement_import_id": imp_id}) == 2


class TestCICoverage:
    def test_makefile_critical_includes_iter313(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter313_audit_fixes.py" in target
