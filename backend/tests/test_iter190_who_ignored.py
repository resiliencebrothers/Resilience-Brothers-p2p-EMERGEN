"""iter190 — "Quién ignoró": ignoring stores actor name + note; the list
endpoint enriches legacy rows (reviewed_by only) with the user's name.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
TAG = "it190"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_tx(txid, status="unmatched", **extra):
    doc = {"id": txid, "fingerprint": f"fp_{TAG}_{uuid.uuid4().hex}",
           "statement_import_id": f"imp_{TAG}", "currency": "IG190",
           "amount": 42.0, "status": status, "sender_name": "Pepe Prueba",
           "direction": "credit", "transaction_date": "2099-07-01",
           "created_at": "2099-07-01T00:00:00+00:00", "candidates": [], **extra}
    _db().bank_transactions.insert_one(doc)


def _cleanup():
    _db().bank_transactions.delete_many({"currency": "IG190"})


def setup_module():
    _cleanup()


def teardown_module():
    _cleanup()


def test_ignore_stores_actor_name_note_and_timestamp():
    txid = f"tx_{TAG}_a"
    _seed_tx(txid)
    r = requests.post(f"{API}/admin/reconciliation/transactions/{txid}/ignore",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"note": "pago personal, no es una orden"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ignored"
    assert d["ignored_reason"] == "manual"
    assert d["review_note"] == "pago personal, no es una orden"
    assert d["reviewed_by"]
    assert d["reviewed_by_name"]
    assert d["reviewed_at"]


def test_list_enriches_legacy_ignored_rows_with_name():
    txid = f"tx_{TAG}_b"
    admin = _db().users.find_one({"role": "admin"}, {"user_id": 1, "name": 1, "email": 1})
    _seed_tx(txid, status="ignored", ignored_reason="manual",
             reviewed_by=admin["user_id"], reviewed_at="2099-07-02T10:00:00+00:00",
             review_note="nota vieja")
    r = requests.get(f"{API}/admin/reconciliation/transactions",
                     params={"status": "ignored", "currency": "IG190"},
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    row = next(i for i in r.json()["items"] if i["id"] == txid)
    assert row.get("reviewed_by_name") == (admin.get("name") or admin.get("email"))
    assert row["review_note"] == "nota vieja"


def test_restore_clears_who_ignored_fields():
    txid = f"tx_{TAG}_c"
    _seed_tx(txid)
    requests.post(f"{API}/admin/reconciliation/transactions/{txid}/ignore",
                  headers=_hdr(ADMIN_TOKEN), json={"note": "x"})
    r = requests.post(f"{API}/admin/reconciliation/transactions/{txid}/restore",
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    doc = _db().bank_transactions.find_one({"id": txid}, {"_id": 0})
    assert doc["status"] == "unmatched"
    assert doc.get("reviewed_by") is None
    assert doc.get("reviewed_by_name") is None
    assert doc.get("review_note") is None
