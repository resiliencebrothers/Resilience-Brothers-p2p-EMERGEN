"""iter177 — Scoring V2 (sin referencia/método en el total) + drill-down.

Cambios pedidos por el usuario:
  - Los VIP no pueden poner referencia en el concepto → la referencia sale
    del total (queda solo como desempate) y el método desaparece.
  - Puntos redistribuidos: monto 55/35 · nombre 30/27/23/17/9 · apellido +5.
  - Mismo remitente cumpliendo todo en órdenes de DOS usuarios distintos →
    revisión manual (same_sender_multiple_users).
  - GET /dashboard/details → drill-down de las tarjetas del dashboard.
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP

PACC_ID = "pacc_test177"
API = f"{BASE_URL}/api/admin/reconciliation"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _upload(csv_text, filename):
    return requests.post(
        f"{API}/imports", headers=_h(ADMIN),
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        data={"bank_account_id": PACC_ID, "bank_name": "Wells Fargo",
              "currency": "USD"})


def _wait_processed(import_id, timeout=45):
    for _ in range(timeout):
        r = requests.get(f"{API}/imports/{import_id}", headers=_h(ADMIN))
        doc = r.json()
        if doc["processing_status"] not in ("uploaded", "processing"):
            return doc
        time.sleep(1)
    raise TimeoutError("import never finished")


def _mk_order(db, order_id, amount, name, user_id="user_test_normal01", ref=""):
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.orders.insert_one({
        "id": order_id, "user_id": user_id,
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": name, "payment_reference": ref,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Test 177",
        "created_at": now, "updated_at": now,
    })


def _cleanup():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test177_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord177"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


class TestScorePairV2:
    def _score(self, tx, order):
        from services.reconciliation_matcher import score_pair, DEFAULT_CONFIG
        return score_pair(tx, order, dict(DEFAULT_CONFIG))

    def test_full_match_reaches_110_without_reference(self):
        today = time.strftime("%Y-%m-%d")
        s = self._score(
            {"amount": 500.0, "sender_name": "ROBERTO FERNANDEZ AGUILAR",
             "transaction_date": today},
            {"amount_from": 500.0, "sender_name": "Roberto Fernandez Aguilar",
             "user_name": "Roberto Fernandez Aguilar", "created_at": today})
        b = s["breakdown"]
        assert b["amount_score"] == 55
        assert b["name_score"] == 30
        assert b["surname_score"] == 5
        assert b["date_score"] == 10
        assert s["score"] == 110
        assert "payment_method_score" not in b

    def test_reference_does_not_add_to_total(self):
        today = time.strftime("%Y-%m-%d")
        base = {"amount_from": 500.0, "sender_name": "Roberto Fernandez Aguilar",
                "user_name": "", "created_at": today,
                "payment_reference": "RB-731942"}
        with_ref = self._score(
            {"amount": 500.0, "sender_name": "ROBERTO FERNANDEZ AGUILAR",
             "transaction_date": today, "description": "Pago RB-731942"}, base)
        assert with_ref["breakdown"]["reference_score"] == 20
        assert with_ref["score"] == 110  # ref no suma

    def test_surname_distinguishes_same_first_name(self):
        today = time.strftime("%Y-%m-%d")
        wrong = self._score(
            {"amount": 100.0, "sender_name": "JUAN PEREZ",
             "transaction_date": today},
            {"amount_from": 100.0, "sender_name": "Juan Gomez",
             "user_name": "", "created_at": today})
        right = self._score(
            {"amount": 100.0, "sender_name": "JUAN PEREZ",
             "transaction_date": today},
            {"amount_from": 100.0, "sender_name": "Juan Perez Garcia",
             "user_name": "", "created_at": today})
        assert wrong["breakdown"]["surname_score"] == 0
        assert right["breakdown"]["surname_score"] == 5


class TestAutoMatchWithoutReference:
    def setup_method(self):
        _cleanup()

    def test_vip_scenario_no_reference_auto_confirms(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        oid = f"ord177a_{uuid.uuid4().hex[:8]}"
        _mk_order(db, oid, 500.00, "Roberto Fernandez Aguilar")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment,500.00,ROBERTO FERNANDEZ AGUILAR\n")
        imp = _wait_processed(_upload(
            csv_text, f"test177_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        assert db.orders.find_one({"id": oid})["status"] == "approved"
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "auto_matched"
        assert tx["confidence_score"] >= 110
        assert tx["algorithm_version"] == "RECON_V2.0"

    def test_same_sender_two_users_goes_to_review(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        o1 = f"ord177b_{uuid.uuid4().hex[:8]}"
        o2 = f"ord177c_{uuid.uuid4().hex[:8]}"
        _mk_order(db, o1, 730.00, "Sandra Milena Ortiz", user_id="user_t177_a")
        _mk_order(db, o2, 730.00, "Sandra Milena Ortiz", user_id="user_t177_b")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Zelle payment,730.00,SANDRA MILENA ORTIZ\n")
        imp = _wait_processed(_upload(
            csv_text, f"test177_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 0, imp
        assert imp["total_manual_review"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "manual_review"
        assert "same_sender_multiple_users" in tx["auto_block_reasons"]
        assert db.orders.find_one({"id": o1})["status"] == "pending"
        assert db.orders.find_one({"id": o2})["status"] == "pending"

    def test_reference_breaks_tie_between_twin_orders(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        o_ref = f"ord177d_{uuid.uuid4().hex[:8]}"
        o_other = f"ord177e_{uuid.uuid4().hex[:8]}"
        _mk_order(db, o_ref, 940.00, "Pavel Dominguez Rojo", ref="RB-111177")
        _mk_order(db, o_other, 940.00, "Pavel Dominguez Rojo", ref="RB-222177")
        csv_text = ("Date,Description,Amount,Sender\n"
                    f"{today},Pago concepto RB-111177,940.00,PAVEL DOMINGUEZ ROJO\n")
        imp = _wait_processed(_upload(
            csv_text, f"test177_{uuid.uuid4().hex[:6]}.csv").json()["id"])
        assert imp["total_auto_matched"] == 1, imp
        tx = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] == "auto_matched"
        assert tx["matched_order_id"] == o_ref
        assert db.orders.find_one({"id": o_ref})["status"] == "approved"
        assert db.orders.find_one({"id": o_other})["status"] == "pending"


class TestDashboardDetails:
    def test_buckets_shape(self):
        for bucket, kind in (("reconciled", "transactions"),
                             ("manual_review", "transactions"),
                             ("unmatched", "transactions"),
                             ("duplicate", "transactions"),
                             ("error", "transactions"),
                             ("rollbacks", "audit"),
                             ("imports", "imports")):
            r = requests.get(f"{API}/dashboard/details", headers=_h(ADMIN),
                             params={"bucket": bucket, "days": 30})
            assert r.status_code == 200, (bucket, r.text)
            body = r.json()
            assert body["kind"] == kind and isinstance(body["items"], list)

    def test_invalid_bucket_and_permission(self):
        r = requests.get(f"{API}/dashboard/details", headers=_h(ADMIN),
                         params={"bucket": "bogus"})
        assert r.status_code == 400
        r2 = requests.get(f"{API}/dashboard/details", headers=_h(VIP),
                          params={"bucket": "reconciled"})
        assert r2.status_code == 403
