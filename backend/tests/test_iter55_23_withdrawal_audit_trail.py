"""iter55.23 — Audit trail for withdrawal & redemption status changes.

Bug reported by owner: "en auditoría cuando se rechaza un pago no sale quién
lo rechazó". Root cause: `admin_withdrawals.update_withdrawal` and
`admin.update_redemption` mutated the row but NEVER called `log_action`. The
audit ledger simply had no record of who flipped the status.

These tests verify that every status change now produces one and only one
audit entry, tagged with the actor, before/after status, entity, and amount.
"""
import os
import uuid
import time
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import (
    BASE_URL as API_ROOT, ADMIN_TOKEN, VIP_TOKEN, make_admin_totp, make_vip_totp,
)

API = f"{API_ROOT}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _upsert_currency(code):
    _db().currencies.update_one(
        {"code": code},
        {"$set": {"code": code, "name": f"Test {code}", "type": "fiat", "is_active": True,
                  "delivery_methods": ["cash", "transfer"], "updated_at": _iso()},
         "$setOnInsert": {"id": uuid.uuid4().hex, "created_at": _iso()}},
        upsert=True,
    )


def _seed_withdrawal(status="pending"):
    wid = f"test-wd-iter55-23-{uuid.uuid4().hex[:8]}"
    _db().withdrawals.insert_one({
        "id": wid,
        "user_id": "user_test_vip01",
        "method": "transfer",
        "currency": "USDW23",
        "amount_usd": 25,
        "status": status,
        "details": "Bank Test — 12345",
        "beneficiary_name": "Test Beneficiary",
        "created_at": _iso(),
    })
    return wid


def _seed_redemption(status="pending"):
    rid = f"test-rd-iter55-23-{uuid.uuid4().hex[:8]}"
    _db().redemptions.insert_one({
        "id": rid,
        "user_id": "user_test_vip01",
        "product_id": "prod-test-x",
        "quantity": 1,
        "total_usd": 40,
        "status": status,
        "created_at": _iso(),
    })
    return rid


def _cleanup(wid=None, rid=None):
    if wid:
        _db().withdrawals.delete_many({"id": wid})
    if rid:
        _db().redemptions.delete_many({"id": rid})
    _db().audit_log.delete_many({"entity_id": {"$regex": "^test-(wd|rd)-iter55-23-"}})
    _db().currencies.delete_many({"code": {"$regex": "^USDW23"}})


def test_reject_withdrawal_logs_actor_to_audit():
    """The reported bug — rechazar un retiro debe dejar constancia del actor."""
    _upsert_currency("USDW23")
    wid = _seed_withdrawal("pending")

    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "rejected", "admin_note": "Motivo de prueba",
              "totp_code": make_admin_totp()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    # Exactly ONE new audit entry for this entity
    entries = list(_db().audit_log.find({"entity_id": wid}))
    assert len(entries) == 1, f"Expected 1 audit row, got {len(entries)}"
    e = entries[0]
    # Actor must be identified
    assert e["actor_id"], "actor_id must be populated"
    assert e["actor_email"], "actor_email must be populated"
    assert e["actor_role"] == "admin"
    # Action + entity
    assert e["action"] == "withdrawal.rejected"
    assert e["entity_type"] == "withdrawal"
    # Details must include prev/new status + amount
    d = e["details"]
    assert d["prev"] == "pending"
    assert d["new"] == "rejected"
    assert d["amount_usd"] == 25
    assert d["currency"] == "USDW23"
    assert d["admin_note"] == "Motivo de prueba"

    _cleanup(wid=wid)


def test_approve_withdrawal_also_logs():
    """Same audit trail for the happy-path transition."""
    _upsert_currency("USDW23")
    wid = _seed_withdrawal("pending")

    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "approved", "totp_code": make_admin_totp()},
    )
    assert r.status_code == 200, r.text

    e = _db().audit_log.find_one({"entity_id": wid})
    assert e is not None
    assert e["action"] == "withdrawal.approved"
    assert e["details"]["prev"] == "pending" and e["details"]["new"] == "approved"

    _cleanup(wid=wid)


def test_noop_status_change_does_not_double_log():
    """Setting the same status again must NOT insert a duplicate audit row
    (idempotency guard)."""
    _upsert_currency("USDW23")
    wid = _seed_withdrawal("rejected")

    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "rejected", "totp_code": make_admin_totp()},
    )
    assert r.status_code == 200, r.text

    entries = list(_db().audit_log.find({"entity_id": wid}))
    assert len(entries) == 0, f"No-op transition must not log; found {len(entries)}"

    _cleanup(wid=wid)


def test_reject_redemption_also_logs_actor():
    """Same fix applied to redemption cancels (canjes VIP)."""
    rid = _seed_redemption("pending")

    r = requests.put(
        f"{API}/admin/redemptions/{rid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "rejected", "admin_note": "Producto agotado"},
    )
    assert r.status_code == 200, r.text

    e = _db().audit_log.find_one({"entity_id": rid})
    assert e is not None, "Redemption reject must produce an audit entry"
    assert e["action"] == "redemption.rejected"
    assert e["actor_id"] and e["actor_email"]
    assert e["details"]["prev"] == "pending"
    assert e["details"]["new"] == "rejected"
    assert e["details"]["admin_note"] == "Producto agotado"

    _cleanup(rid=rid)


def test_audit_entries_appear_in_csv_export():
    """End-to-end: the new entries must be reachable via the audit CSV export
    that ops uses to review 'who did what'."""
    _upsert_currency("USDW23")
    wid = _seed_withdrawal("pending")

    r = requests.put(
        f"{API}/admin/withdrawals/{wid}/status",
        headers=_hdr(ADMIN_TOKEN),
        json={"status": "rejected", "totp_code": make_admin_totp()},
    )
    assert r.status_code == 200
    time.sleep(0.1)

    r = requests.get(f"{API}/admin/audit/export.csv", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.text
    assert wid in body, "Withdrawal id not present in audit CSV"
    assert "withdrawal.rejected" in body, "Action label missing from CSV"

    _cleanup(wid=wid)
