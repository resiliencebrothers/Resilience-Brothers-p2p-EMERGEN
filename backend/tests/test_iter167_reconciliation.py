"""iter167 — Conciliación Bancaria (spec compliance tests).

Covers: permission gate, CSV import → auto-match (§11-§12), partial payment
flag (§46), unmatched, debit ignored, duplicate file (§48), duplicate rows
(§8), manual confirm (§21), rollback (§25), config validation (§43), audit
trail (§23).
"""
import io
import os
import time
import uuid

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP

EMP_RECON_ID = "user_test_emp167_rec"
EMP_RECON_TOKEN = f"test_session_{uuid.uuid4().hex}"
EMP_OTHER_ID = "user_test_emp167_oth"
EMP_OTHER_TOKEN = f"test_session_{uuid.uuid4().hex}"
PACC_ID = "pacc_test167"

API = f"{BASE_URL}/api/admin/reconciliation"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mk_order(db, order_id, amount, name, sender=None, created_at=None):
    from datetime import datetime, timezone
    db.orders.insert_one({
        "id": order_id, "user_id": "user_test_normal01",
        "user_name": name, "user_email": f"{order_id[:6]}@test.com",
        "sender_name": sender or name,
        "amount_from": float(amount), "amount_to": float(amount) * 300,
        "from_code": "USD", "to_code": "CUP", "status": "pending",
        "payment_account_id": PACC_ID,
        "payment_account_label": "Zelle Wells Fargo · Test",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": created_at or datetime.now(timezone.utc).isoformat(),
    })


def setup_module():
    db = _db()
    for uid, tok, perms in (
        (EMP_RECON_ID, EMP_RECON_TOKEN, ["reconciliation"]),
        (EMP_OTHER_ID, EMP_OTHER_TOKEN, ["orders"]),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com", "name": uid,
                      "role": "employee", "allowed_permissions": perms,
                      "totp_enabled": True}},
            upsert=True)
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True)


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [EMP_RECON_ID, EMP_OTHER_ID]}})
    db.user_sessions.delete_many({"session_token": {"$in": [EMP_RECON_TOKEN, EMP_OTHER_TOKEN]}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    imps = [i["id"] for i in db.bank_statement_imports.find(
        {"original_file_name": {"$regex": "^test167_"}}, {"id": 1})]
    db.bank_transactions.delete_many({"statement_import_id": {"$in": imps}})
    db.bank_statement_imports.delete_many({"id": {"$in": imps}})
    db.statement_files.delete_many({"id": {"$in": imps}})
    db.reconciliation_audit_log.delete_many({"statement_import_id": {"$in": imps}})
    db.orders.delete_many({"id": {"$regex": "^ord167"}})
    db.settings.delete_one({"id": "reconciliation_config"})


def _upload(csv_text, filename, token=ADMIN, currency="USD", bank="Wells Fargo"):
    return requests.post(
        f"{API}/imports", headers=_h(token),
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
        data={"bank_account_id": PACC_ID, "bank_name": bank, "currency": currency})


def _wait_processed(import_id, timeout=45):
    for _ in range(timeout):
        r = requests.get(f"{API}/imports/{import_id}", headers=_h(ADMIN))
        doc = r.json()
        if doc["processing_status"] not in ("uploaded", "processing"):
            return doc
        time.sleep(1)
    raise TimeoutError("import never finished")


class TestPermissionGate:
    def test_gates(self):
        r = requests.get(f"{API}/imports", headers=_h(EMP_RECON_TOKEN))
        assert r.status_code == 200, r.text
        for tok in (EMP_OTHER_TOKEN, VIP):
            r2 = requests.get(f"{API}/imports", headers=_h(tok))
            assert r2.status_code == 403, r2.text
        assert requests.get(f"{API}/imports").status_code == 401
        assert requests.get(f"{API}/config", headers=_h(EMP_RECON_TOKEN)).status_code == 200
        assert requests.get(f"{API}/summary", headers=_h(EMP_RECON_TOKEN)).status_code == 200


class TestCsvImportFlow:
    def setup_method(self):
        _cleanup_data()

    def test_full_pipeline(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        o_auto = f"ord167a_{uuid.uuid4().hex[:8]}"
        o_partial = f"ord167b_{uuid.uuid4().hex[:8]}"
        _mk_order(db, o_auto, 250.00, "Juan Perez Garcia")
        _mk_order(db, o_partial, 300.00, "Maria Lopez Diaz")

        csv_text = (
            "Date,Description,Amount,Sender,Reference\n"
            f"{today},Zelle payment received,250.00,JUAN PEREZ GARCIA,{o_auto[:8]}\n"
            f"{today},Zelle payment received,299.00,MARIA LOPEZ DIAZ,{o_partial[:8]}\n"
            f"{today},Wire transfer inbound,999.99,UNKNOWN COMPANY LLC,ZZZ111\n"
            f"{today},Monthly fee,-25.00,BANK FEE,FEE01\n"
        )
        r = _upload(csv_text, f"test167_{uuid.uuid4().hex[:6]}.csv", token=EMP_RECON_TOKEN)
        assert r.status_code == 200, r.text
        imp = _wait_processed(r.json()["id"])
        assert imp["processing_status"] == "processed", imp
        assert imp["total_transactions_detected"] == 4
        assert imp["total_credits_detected"] == 3
        assert imp["total_debits_detected"] == 1
        assert imp["total_auto_matched"] == 1, imp
        assert imp["total_manual_review"] == 1, imp
        assert imp["total_unmatched"] == 1, imp

        # §18 — auto-matched order was approved with reconciliation stamps.
        order = db.orders.find_one({"id": o_auto}, {"_id": 0})
        assert order["status"] == "approved"
        assert order["payment_confirmation_source"] == "BANK_RECONCILIATION"
        assert order["reconciliation"]["auto"] is True

        # §46 — partial payment flagged for review, order untouched.
        tx_partial = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"], "amount": 299.00}, {"_id": 0})
        assert tx_partial["status"] == "manual_review"
        assert tx_partial["review_flag"] == "possible_partial_payment"
        assert db.orders.find_one({"id": o_partial})["status"] == "pending"

        # debit → ignored; unknown credit → unmatched
        assert db.bank_transactions.find_one(
            {"statement_import_id": imp["id"], "amount": 25.00})["status"] == "ignored"
        assert db.bank_transactions.find_one(
            {"statement_import_id": imp["id"], "amount": 999.99})["status"] == "unmatched"

        # §24 — explainable breakdown persisted.
        tx_auto = db.bank_transactions.find_one(
            {"statement_import_id": imp["id"], "amount": 250.00}, {"_id": 0})
        bd = tx_auto["match_details"]["breakdown"]
        assert bd["amount_score"] == 45 and bd["reference_score"] >= 10

        # §23 — dedicated audit rows exist.
        assert db.reconciliation_audit_log.count_documents(
            {"statement_import_id": imp["id"]}) >= 2

        # §48 — same file again → 409
        r_dup = _upload(csv_text, f"test167_{uuid.uuid4().hex[:6]}.csv")
        assert r_dup.status_code == 409, r_dup.text

        # §8 — same rows in a *different* file → row-level duplicates.
        csv_text2 = csv_text + f"{today},New credit,42.42,PEDRO NUEVO,ABC99\n"
        r2 = _upload(csv_text2, f"test167_{uuid.uuid4().hex[:6]}.csv")
        assert r2.status_code == 200, r2.text
        imp2 = _wait_processed(r2.json()["id"])
        assert imp2["total_duplicates"] == 4, imp2

    def test_manual_confirm_and_rollback(self):
        db = _db()
        today = time.strftime("%Y-%m-%d")
        o_manual = f"ord167m_{uuid.uuid4().hex[:8]}"
        _mk_order(db, o_manual, 500.00, "Carlos Ruiz Ferrer")
        csv_text = ("Date,Description,Amount,Sender,Reference\n"
                    f"{today},ACH credit,500.00,C RUIZ,NOREF\n")
        r = _upload(csv_text, f"test167_{uuid.uuid4().hex[:6]}.csv")
        imp = _wait_processed(r.json()["id"])
        tx = db.bank_transactions.find_one({"statement_import_id": imp["id"]}, {"_id": 0})
        assert tx["status"] in ("manual_review", "unmatched")

        rc = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                           headers=_h(EMP_RECON_TOKEN), json={"order_id": o_manual})
        assert rc.status_code == 200, rc.text
        assert rc.json()["status"] == "manual_matched"
        assert db.orders.find_one({"id": o_manual})["status"] == "approved"

        # double-confirm guard (§19)
        rc2 = requests.post(f"{API}/transactions/{tx['id']}/confirm",
                            headers=_h(ADMIN), json={"order_id": o_manual})
        assert rc2.status_code == 409

        # §25 — rollback (reason mandatory)
        rb_bad = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                               headers=_h(ADMIN), json={"reason": "x"})
        assert rb_bad.status_code == 422
        rb = requests.post(f"{API}/transactions/{tx['id']}/rollback",
                           headers=_h(ADMIN), json={"reason": "monto en disputa"})
        assert rb.status_code == 200, rb.text
        order = db.orders.find_one({"id": o_manual}, {"_id": 0})
        assert order["status"] == "pending"
        assert "reconciliation" not in order
        assert db.reconciliation_audit_log.count_documents(
            {"bank_transaction_id": tx["id"], "action": "ROLLBACK"}) == 1

    def test_unsupported_format_and_empty(self):
        r = requests.post(
            f"{API}/imports", headers=_h(ADMIN),
            files={"file": ("test167_x.txt", io.BytesIO(b"hola"), "text/plain")},
            data={"bank_account_id": "", "bank_name": "X", "currency": "USD"})
        assert r.status_code == 422


class TestConfig:
    def test_validation_and_update(self):
        r = requests.put(f"{API}/config", headers=_h(ADMIN),
                         json={"manual_review_score": 96, "auto_match_score": 95})
        assert r.status_code == 422
        r2 = requests.put(f"{API}/config", headers=_h(ADMIN),
                          json={"date_window_days": 21, "max_auto_confirmation_amount": 5000})
        assert r2.status_code == 200
        body = r2.json()
        assert body["date_window_days"] == 21
        assert body["max_auto_confirmation_amount"] == 5000
        requests.put(f"{API}/config", headers=_h(ADMIN),
                     json={"date_window_days": 14, "max_auto_confirmation_amount": 10000})
