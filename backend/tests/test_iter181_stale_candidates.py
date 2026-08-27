"""iter181 — Filtrar candidatos "obsoletos" (stale) del diálogo Revisar.

Cuando dos movimientos bancarios distintos comparten el mismo grupo de
órdenes candidatas y uno de ellos ya fue CONFIRMADO manualmente contra
una orden, esa orden NO debe seguir apareciendo como sugerencia en el
segundo movimiento. Caso real reportado por el usuario:
"Peres meneses" ya confirmado seguía saliendo como candidato de otro
movimiento en revisión.

También se filtra:
- Órdenes que ya no están pendientes (aprobadas/canceladas por otra vía).
- vip_batch_items que ya no están pending.
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

PACC_ID = "pacc_test181"
API = f"{BASE_URL}/api/admin/reconciliation"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upload(csv_text, filename):
    return requests.post(
        f"{API}/imports", headers=_h(ADMIN),
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        data={"bank_account_id": PACC_ID, "bank_name": "Sabadell",
              "currency": "EUR"})


def _wait_processed(import_id, timeout=45):
    for _ in range(timeout):
        r = requests.get(f"{API}/imports/{import_id}", headers=_h(ADMIN))
        doc = r.json()
        if doc["processing_status"] not in ("uploaded", "processing"):
            return doc
        time.sleep(1)
    raise TimeoutError("import never finished")


def _mk_order(db, order_id, amount, name):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name, "payment_reference": "",
        "amount_from": float(amount), "amount_to": float(amount) * 1.05,
        "from_code": "EUR", "to_code": "USDT", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Sabadell Test 181",
        "created_at": now, "updated_at": now,
    })


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test181_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord181"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestStaleCandidatesFiltered:
    def setup_method(self):
        _cleanup()

    def test_confirmed_order_removed_from_other_tx_candidates(self):
        """Escenario del usuario: 2 movimientos entran en revisión manual con
        la misma orden como candidato. Al confirmar el 1º contra la orden, el
        2º NO debe seguir mostrando esa orden como sugerencia."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        # Creo 2 órdenes gemelas (mismo nombre, mismo monto) — ambos movimientos
        # las tendrán como candidatas ya que el motor pondrá ambas en review.
        for tag in ("A", "B"):
            _mk_order(
                db, f"ord181_stale_{tag}_{uuid.uuid4().hex[:6]}",
                200.00, "PERES MENESES",
            )
        # 2 movimientos con mismo remitente + monto (descripciones distintas
        # para evitar dedup por fingerprint) → ambos → manual_review con
        # ambas órdenes como candidatas.
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Transferencia inmediata REF001,200.00,PERES MENESES\n"
                    f"{today},Transferencia inmediata REF002,200.00,PERES MENESES\n")
        imp = _wait_processed(_upload(
            csv_text, f"test181_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        txs = list(db.bank_transactions.find(
            {"statement_import_id": imp["id"]}, {"_id": 0})
            .sort("id", 1))
        assert len(txs) == 2
        # Ambos deberían estar en manual_review con ambas órdenes candidatas
        assert all(t["status"] == "manual_review" for t in txs), \
            f"expected manual_review for both, got {[t['status'] for t in txs]}"

        # Confirmo la 1ª tx contra la orden A
        first, second = txs[0], txs[1]
        first_cands = [c["order_id"] for c in first.get("candidates") or []]
        second_cands_before = [c["order_id"] for c in second.get("candidates") or []]
        assert len(second_cands_before) >= 1
        pick = first_cands[0]  # la orden que vamos a "quemar"
        cr = requests.post(
            f"{API}/transactions/{first['id']}/confirm",
            headers=_h(ADMIN), json={"order_id": pick})
        assert cr.status_code == 200, cr.text

        # Ahora pido la lista con status=manual_review y verifico que
        # los candidatos de la segunda tx YA NO incluyen la orden `pick`.
        lr = requests.get(f"{API}/transactions",
                          headers=_h(ADMIN),
                          params={"status": "manual_review"})
        assert lr.status_code == 200
        items = lr.json()["items"]
        second_after = next((it for it in items if it["id"] == second["id"]), None)
        assert second_after is not None, "second tx debería seguir en review"
        second_cands_after = [c["order_id"] for c in second_after.get("candidates") or []]
        assert pick not in second_cands_after, (
            f"la orden ya conciliada {pick} sigue apareciendo en candidatos de otra tx: {second_cands_after}"
        )
        # La otra orden (aún pending) SÍ debe seguir apareciendo si estaba antes
        remaining = [c for c in second_cands_before if c != pick]
        for oid in remaining:
            assert oid in second_cands_after, (
                f"orden aún pending {oid} debería seguir apareciendo"
            )

    def test_candidate_removed_when_order_no_longer_pending(self):
        """Si una orden candidata pasa a estado != pending por vía distinta
        (approved, cancelled…), tampoco debe seguir sugiriéndose."""
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord181_solo_{uuid.uuid4().hex[:6]}"
        _mk_order(db, oid, 155.00, "MARIA GARCIA LOPEZ")
        # Un movimiento con nombre suave (no exact match) → debería quedar
        # como candidato pero en manual_review por bloqueo de apellido.
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Ingreso,155.00,MARIA GARCIA\n")
        imp = _wait_processed(_upload(
            csv_text, f"test181_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        # El caso base — el candidato aparece
        cand_ids = [c["order_id"] for c in tx.get("candidates") or []]
        assert oid in cand_ids

        # Simulo que alguien aprobó/canceló la orden por fuera
        db.orders.update_one({"id": oid}, {"$set": {"status": "cancelled"}})

        # Recargo la lista y espero que ya no aparezca en candidatos
        lr = requests.get(f"{API}/transactions",
                          headers=_h(ADMIN),
                          params={"status": tx["status"]})
        assert lr.status_code == 200
        after = next((it for it in lr.json()["items"] if it["id"] == tx["id"]), None)
        assert after is not None
        cand_after = [c["order_id"] for c in after.get("candidates") or []]
        assert oid not in cand_after
