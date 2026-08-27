"""iter179 — Restaurar movimientos ignorados.

POST /transactions/{id}/restore: ignored → unmatched + rematch inmediato.
Caso real del usuario: un operador ignoró un abono que con el motor V2
auto-conciliaría; sin esto el movimiento quedaba atrapado para siempre
(el rematch solo procesa unmatched/manual_review).
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

PACC_ID = "pacc_test179"
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
        "payment_account_label": "Sabadell Test 179",
        "created_at": now, "updated_at": now,
    })


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test179_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord179"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestRestoreIgnored:
    def setup_method(self):
        _cleanup()

    def test_restore_then_auto_match(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        # 1. importar SIN orden que matchee → unmatched
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Abono transferencia,342.57,LIANET FUMERO CASTRO\n")
        imp = _wait_processed(_upload(
            csv_text, f"test179_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "unmatched"

        # 2. operador lo ignora
        ri = requests.post(f"{API}/transactions/{tx['id']}/ignore",
                           headers=_h(ADMIN), json={"note": "test"})
        assert ri.status_code == 200 and ri.json()["status"] == "ignored"

        # 3. la orden se crea DESPUÉS (insert directo — no dispara hooks)
        oid = f"ord179a_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 342.57, "Lianet Fumero Castro")

        # 4. restaurar → rematch inmediato → auto-conciliado
        rr = requests.post(f"{API}/transactions/{tx['id']}/restore",
                           headers=_h(ADMIN), json={})
        assert rr.status_code == 200, rr.text
        assert rr.json()["status"] == "auto_matched"
        assert db.orders.find_one({"id": oid})["status"] == "approved"
        assert db.reconciliation_audit_log.count_documents(
            {"bank_transaction_id": tx["id"],
             "action": "TRANSACTION_RESTORED"}) == 1

        # 5. restaurar de nuevo → 409 (ya no está ignorado)
        rr2 = requests.post(f"{API}/transactions/{tx['id']}/restore",
                            headers=_h(ADMIN), json={})
        assert rr2.status_code == 409

    def test_restore_debit_blocked(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Comision mensual,-19.43,BANCO\n")
        imp = _wait_processed(_upload(
            csv_text, f"test179_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "ignored" and tx["direction"] == "debit"
        rr = requests.post(f"{API}/transactions/{tx['id']}/restore",
                           headers=_h(ADMIN), json={})
        assert rr.status_code == 409

    def test_restore_requires_ignored_status(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Abono transferencia,88.12,PERSONA SIN ORDEN XYZ\n")
        imp = _wait_processed(_upload(
            csv_text, f"test179_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "unmatched"
        rr = requests.post(f"{API}/transactions/{tx['id']}/restore",
                           headers=_h(ADMIN), json={})
        assert rr.status_code == 409
