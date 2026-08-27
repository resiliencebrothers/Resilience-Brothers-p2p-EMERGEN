"""iter185 — Per-currency scoping across the reconciliation module.

Summary, dashboard, dashboard/details, transactions and imports all accept
?currency= and must return ONLY data of that currency, so a staff member
assigned to e.g. EUR works isolated from Zelle/USD statements.
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
TAG = "iter185"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed():
    db = _db()
    now = "2099-01-02T00:00:00+00:00"
    imports = [
        {"id": f"imp_{TAG}_eur", "original_file_name": "eur.csv", "bank_name": "BBVA",
         "currency": "EU185", "uploaded_at": now, "processing_status": "processed",
         "processing_started_at": now, "processing_finished_at": now,
         "parse_mode": "structured", "total_transactions_detected": 2, "total_errors": 0},
        {"id": f"imp_{TAG}_usd", "original_file_name": "zelle.csv", "bank_name": "Zelle",
         "currency": "US185", "uploaded_at": now, "processing_status": "processed",
         "processing_started_at": now, "processing_finished_at": now,
         "parse_mode": "structured", "total_transactions_detected": 1, "total_errors": 0},
    ]
    txs = [
        {"id": f"tx_{TAG}_eur1", "statement_import_id": f"imp_{TAG}_eur",
         "fingerprint": f"fp_{TAG}_{uuid.uuid4().hex}",
         "currency": "EU185", "amount": 100.0, "status": "manual_review",
         "sender_name": "Ana EUR", "transaction_date": "2099-01-01",
         "created_at": now, "candidates": []},
        {"id": f"tx_{TAG}_eur2", "statement_import_id": f"imp_{TAG}_eur",
         "fingerprint": f"fp_{TAG}_{uuid.uuid4().hex}",
         "currency": "EU185", "amount": 55.0, "status": "auto_matched",
         "sender_name": "Luis EUR", "transaction_date": "2099-01-01",
         "created_at": now, "confidence_score": 95, "candidates": []},
        {"id": f"tx_{TAG}_usd1", "statement_import_id": f"imp_{TAG}_usd",
         "fingerprint": f"fp_{TAG}_{uuid.uuid4().hex}",
         "currency": "US185", "amount": 200.0, "status": "manual_review",
         "sender_name": "John USD", "transaction_date": "2099-01-01",
         "created_at": now, "candidates": []},
    ]
    db.bank_statement_imports.insert_many(imports)
    db.bank_transactions.insert_many(txs)


def _cleanup():
    db = _db()
    db.bank_statement_imports.delete_many({"id": {"$regex": f"^imp_{TAG}"}})
    db.bank_transactions.delete_many({"id": {"$regex": f"^tx_{TAG}"}})


def setup_module():
    _cleanup()
    _seed()


def teardown_module():
    _cleanup()


def test_summary_scoped_by_currency_and_lists_currencies():
    r = requests.get(f"{API}/admin/reconciliation/summary",
                     params={"currency": "EU185"}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["manual_review"] == 1
    assert d["auto_matched"] == 1
    assert "EU185" in d["currencies"] and "US185" in d["currencies"]

    r2 = requests.get(f"{API}/admin/reconciliation/summary",
                      params={"currency": "US185"}, headers=_hdr(ADMIN_TOKEN))
    d2 = r2.json()
    assert d2["manual_review"] == 1
    assert d2["auto_matched"] == 0


def test_transactions_scoped_by_currency():
    r = requests.get(f"{API}/admin/reconciliation/transactions",
                     params={"currency": "EU185", "status": "manual_review"},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["currency"] == "EU185"
    assert all(i["sender_name"] != "John USD" for i in items)


def test_dashboard_scoped_by_currency():
    # Window must be huge because seeds are dated 2099 (future-proof isolation).
    r = requests.get(f"{API}/admin/reconciliation/dashboard",
                     params={"days": 730, "currency": "EU185"},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["currency"] == "EU185"
    assert d["counts"]["manual_review"] >= 1
    # by-currency table must only contain the scoped currency
    curs = {row["currency"] for row in d["reconciled_by_currency"]}
    assert curs.issubset({"EU185"}), curs


def test_dashboard_details_scoped_by_currency():
    r = requests.get(f"{API}/admin/reconciliation/dashboard/details",
                     params={"bucket": "manual_review", "days": 730,
                             "currency": "US185"},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 1
    assert all(i["currency"] == "US185" for i in items)


def test_imports_scoped_by_currency():
    r = requests.get(f"{API}/admin/reconciliation/imports",
                     params={"currency": "EU185"}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["currency"] == "EU185"


def test_no_currency_returns_everything():
    r = requests.get(f"{API}/admin/reconciliation/transactions",
                     params={"status": "manual_review"}, headers=_hdr(ADMIN_TOKEN))
    senders = {i["sender_name"] for i in r.json()["items"]}
    assert {"Ana EUR", "John USD"}.issubset(senders)
