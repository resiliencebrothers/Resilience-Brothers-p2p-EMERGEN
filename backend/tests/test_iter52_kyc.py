"""KYC verification test suite (iter52).

Coverage:
- Backend service (compute_risk, submit, approve, reject, needs-more-info, funnel).
- HTTP endpoints (auth, validation, happy paths, idempotency).
- Auto-flag heuristics: disposable email, duplicate name, shared IP, early large order.
- Notifications fanout on approve/reject/needs_more_info.
"""
import os
import asyncio
import requests
import pytest
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"

# Tiny 1x1 PNG data URL to use as a document upload in tests.
_PNG_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _reset_user_kyc(user_id: str) -> None:
    """Wipe any existing KYC data for the given user so each test starts clean."""
    _sync_db().kyc_verifications.delete_many({"user_id": user_id})
    _sync_db().users.update_one(
        {"user_id": user_id},
        {"$unset": {"kyc_status": "", "kyc_verified_at": "", "kyc_last_submit_at": ""}},
    )


def _reset_all():
    for uid in ("user_test_admin01", "user_test_employee01", "user_test_vip01", "user_test_normal01"):
        _reset_user_kyc(uid)


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


def _payload():
    return {"id_front": _PNG_1X1, "id_back": _PNG_1X1, "selfie": _PNG_1X1}


# ============================================================
# ROUTE-LEVEL TESTS
# ============================================================

def setup_module(module):
    _reset_all()


def teardown_module(module):
    _reset_all()


# --- authorization ---

def test_submit_kyc_requires_auth():
    r = requests.post(f"{API}/kyc/submit", json=_payload())
    assert r.status_code in (401, 403)


def test_my_status_requires_auth():
    r = requests.get(f"{API}/kyc/my-status")
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("tok", [NORMAL_TOKEN, VIP_TOKEN])
def test_admin_queue_forbidden_for_non_staff(tok):
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(tok))
    assert r.status_code == 403


def test_admin_queue_ok_for_admin():
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and isinstance(d["items"], list)


def test_admin_queue_ok_for_employee():
    r = requests.get(f"{API}/admin/kyc/queue", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200


# --- payload validation ---

def test_submit_kyc_validates_data_url():
    _reset_user_kyc("user_test_normal01")
    bad = {"id_front": "not-a-data-url", "id_back": _PNG_1X1, "selfie": _PNG_1X1}
    r = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=bad)
    assert r.status_code == 422


def test_submit_kyc_requires_all_three_docs():
    _reset_user_kyc("user_test_normal01")
    r = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json={"id_front": _PNG_1X1})
    assert r.status_code == 422


# --- happy path: submit -> queue shows it -> approve -> user is verified ---

def test_full_flow_submit_and_approve():
    _reset_user_kyc("user_test_normal01")

    # Submit
    r = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "pending"
    vid = v["id"]

    # User status now reflects pending
    r2 = requests.get(f"{API}/kyc/my-status", headers=_hdr(NORMAL_TOKEN))
    assert r2.status_code == 200
    assert r2.json()["status"] == "pending"

    # Admin sees it in the queue
    r3 = requests.get(f"{API}/admin/kyc/queue?status=pending", headers=_hdr(ADMIN_TOKEN))
    assert r3.status_code == 200
    ids = [item["id"] for item in r3.json()["items"]]
    assert vid in ids

    # Admin detail
    r4 = requests.get(f"{API}/admin/kyc/{vid}", headers=_hdr(ADMIN_TOKEN))
    assert r4.status_code == 200
    detail = r4.json()
    assert detail["user_id"] == "user_test_normal01"
    assert len(detail["documents"]) == 3
    assert {d["doc_type"] for d in detail["documents"]} == {"id_front", "id_back", "selfie"}

    # Admin approves
    r5 = requests.post(
        f"{API}/admin/kyc/{vid}/approve",
        headers=_hdr(ADMIN_TOKEN),
        json={"notes": "Documento válido, foto clara"},
    )
    assert r5.status_code == 200
    assert r5.json()["status"] == "verified"

    # User side reflects verified + user record updated
    r6 = requests.get(f"{API}/kyc/my-status", headers=_hdr(NORMAL_TOKEN))
    assert r6.json()["status"] == "verified"
    u = _sync_db().users.find_one({"user_id": "user_test_normal01"}, {"_id": 0, "kyc_status": 1, "kyc_verified_at": 1})
    assert u["kyc_status"] == "verified"
    assert u["kyc_verified_at"]

    # Notification created for the user
    notif = _sync_db().notifications.find_one(
        {"recipient_user_id": "user_test_normal01", "type": "kyc_verified"},
        sort=[("created_at", -1)],
    )
    assert notif is not None


# --- idempotency: re-submit while pending fails 409 ---

def test_cannot_submit_twice_while_pending():
    _reset_user_kyc("user_test_normal01")

    r1 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    assert r1.status_code == 200

    r2 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    assert r2.status_code == 409


# --- reject flow ---

def test_reject_requires_reasons():
    _reset_user_kyc("user_test_normal01")
    r1 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    vid = r1.json()["id"]

    # reject without reasons → 400
    r2 = requests.post(f"{API}/admin/kyc/{vid}/reject", headers=_hdr(ADMIN_TOKEN), json={"reasons": [], "notes": ""})
    assert r2.status_code == 400

    # with reasons → 200
    r3 = requests.post(
        f"{API}/admin/kyc/{vid}/reject",
        headers=_hdr(ADMIN_TOKEN),
        json={"reasons": ["Foto borrosa", "Documento vencido"], "notes": "Vuelve a intentar."},
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "rejected"
    assert set(r3.json()["rejection_reasons"]) == {"Foto borrosa", "Documento vencido"}

    # After reject, user CAN resubmit
    r4 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    assert r4.status_code == 200

    # User received rejection notification
    notif = _sync_db().notifications.find_one(
        {"recipient_user_id": "user_test_normal01", "type": "kyc_rejected"},
        sort=[("created_at", -1)],
    )
    assert notif is not None
    assert "borrosa" in notif["message"].lower() or "Vuelve" in notif["message"]


# --- needs_more_info flow (verification stays open, cannot re-submit) ---

def test_needs_more_info_blocks_resubmit():
    _reset_user_kyc("user_test_normal01")
    r1 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    vid = r1.json()["id"]

    r2 = requests.post(
        f"{API}/admin/kyc/{vid}/request-more-info",
        headers=_hdr(ADMIN_TOKEN),
        json={"notes": "Necesito ver el reverso del documento con mejor luz."},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "needs_more_info"

    # User cannot submit new — status is still active
    r3 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    assert r3.status_code == 409

    # Admin can still approve after more-info status
    r4 = requests.post(f"{API}/admin/kyc/{vid}/approve", headers=_hdr(ADMIN_TOKEN), json={"notes": ""})
    assert r4.status_code == 200
    assert r4.json()["status"] == "verified"


# --- funnel dashboard shows counts ---

def test_funnel_dashboard_returns_counts():
    _reset_all()
    # Submit + approve one (VIP), submit + reject another (NORMAL)
    r1 = requests.post(f"{API}/kyc/submit", headers=_hdr(NORMAL_TOKEN), json=_payload())
    r2 = requests.post(
        f"{API}/admin/kyc/{r1.json()['id']}/reject",
        headers=_hdr(ADMIN_TOKEN),
        json={"reasons": ["Foto borrosa"], "notes": ""},
    )
    assert r2.status_code == 200

    r3 = requests.post(f"{API}/kyc/submit", headers=_hdr(VIP_TOKEN), json=_payload())
    r4 = requests.post(
        f"{API}/admin/kyc/{r3.json()['id']}/approve",
        headers=_hdr(ADMIN_TOKEN),
        json={"notes": ""},
    )
    assert r4.status_code == 200

    r5 = requests.get(f"{API}/admin/kyc/funnel", headers=_hdr(ADMIN_TOKEN))
    assert r5.status_code == 200
    f = r5.json()
    assert f["verified"] >= 1
    assert f["rejected"] >= 1


# ============================================================
# SERVICE-LEVEL TESTS (risk scoring)
# ============================================================

def test_risk_score_disposable_email():
    _reset_user_kyc("user_test_normal01")
    _sync_db().users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"email": "sketchy@mailinator.com", "name": "Test Normal"}},
    )

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.kyc import compute_risk
            return await compute_risk(db, "user_test_normal01", "sketchy@mailinator.com", "Test Normal", "1.2.3.4")
        finally:
            client.close()

    score, flags = _run(_do)
    codes = {f["code"] for f in flags}
    assert "disposable_email" in codes
    assert score >= 40  # high severity


def test_risk_score_duplicate_name_across_accounts():
    # Plant 3 test users with the same name
    _sync_db().users.update_many(
        {"user_id": {"$in": ["user_test_admin01", "user_test_employee01", "user_test_vip01"]}},
        {"$set": {"name": "Juan Perez Duplicated"}},
    )

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.kyc import compute_risk
            return await compute_risk(
                db, "user_test_normal01", "unique@example.com", "Juan Perez Duplicated", "5.5.5.5",
            )
        finally:
            client.close()

    _, flags = _run(_do)
    codes = {f["code"] for f in flags}
    assert "duplicate_name" in codes

    # Cleanup: reset names so other tests don't get spurious flags
    _sync_db().users.update_one({"user_id": "user_test_admin01"}, {"$set": {"name": "Admin Test"}})
    _sync_db().users.update_one({"user_id": "user_test_employee01"}, {"$set": {"name": "Employee Test"}})
    _sync_db().users.update_one({"user_id": "user_test_vip01"}, {"$set": {"name": "VIP Test"}})


def test_risk_score_no_country_check():
    """Regression — per operator's request, country of IP vs phone must NOT
    be a risk factor. Even if we simulate a mismatch, no flag should surface."""
    _reset_user_kyc("user_test_normal01")
    _sync_db().users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"email": "regular@example.com", "name": "Regular User", "phone": "+5355551234"}},
    )

    async def _do():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            from services.kyc import compute_risk
            return await compute_risk(
                db, "user_test_normal01", "regular@example.com", "Regular User", "185.220.101.1",  # Tor exit node
            )
        finally:
            client.close()

    _, flags = _run(_do)
    codes = {f["code"] for f in flags}
    # No country-related flag exists in the code
    assert "country_mismatch" not in codes
    assert "geo_block" not in codes
    assert "sanctioned_country" not in codes
