"""Regression + happy-path suite for the self-service appeals flow (iter46).

Covers:
- Client under_review can submit an appeal (POST /appeals) and receives 400
  when their account is `active`.
- Only ONE pending appeal per user (409 on double submit).
- Staff (admin + employee-with-blocklist-perm) sees the queue and can
  resolve/reject with a response. Non-privileged employees are 403.
- Notifications are inserted for both the staff fanout and the client review.
- Resolving an appeal does NOT flip `account_status` (staff must still go
  through /admin/users/{id}/verify-phone to reactivate).
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _set_normal_status(status: str):
    """Force the normal test user into a specific account_status for the
    duration of a test. Returns the previous status so tests can restore it."""
    db = _db()
    prev = db.users.find_one({"user_id": "user_test_normal01"}, {"_id": 0, "account_status": 1})
    db.users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"account_status": status}},
        upsert=False,
    )
    return (prev or {}).get("account_status", "active")


def _cleanup_appeals():
    _db().appeals.delete_many({"user_id": "user_test_normal01"})


def test_client_cannot_appeal_when_active():
    prev = _set_normal_status("active")
    _cleanup_appeals()
    try:
        r = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Hola staff, por favor reactiven mi cuenta, es un error."},
        )
        assert r.status_code == 400, r.text
        assert "bajo revisión" in r.json()["detail"]
    finally:
        _set_normal_status(prev)


def test_client_can_appeal_when_under_review():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    try:
        r = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Soy legítimo, el bloqueo fue por confusión con otro cliente."},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["appeal"]["status"] == "pending"
        assert data["appeal"]["user_id"] == "user_test_normal01"

        # Second submission while pending → 409
        r2 = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Segundo intento de spam, debería ser rechazado."},
        )
        assert r2.status_code == 409, r2.text
        assert r2.json()["detail"]["code"] == "APPEAL_ALREADY_PENDING"

        # Client can list their own appeals
        r3 = requests.get(f"{API}/appeals/me", headers=_hdr(NORMAL_TOKEN))
        assert r3.status_code == 200
        assert len(r3.json()["items"]) >= 1

        # Staff fanout notification exists for admin
        db = _db()
        n = db.notifications.count_documents(
            {"recipient_user_id": "user_test_admin01", "type": "new_appeal"}
        )
        assert n >= 1
    finally:
        _cleanup_appeals()
        _set_normal_status(prev)


def test_client_appeal_rejects_short_message():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    try:
        r = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "corto"},  # <10 chars
        )
        assert r.status_code == 422, r.text  # pydantic min_length
    finally:
        _cleanup_appeals()
        _set_normal_status(prev)


def test_staff_can_list_appeals_and_resolve():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    try:
        # Client submits
        r = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Envío mi apelación, comprobante adjunto por WhatsApp."},
        )
        assert r.status_code == 200
        appeal_id = r.json()["appeal"]["id"]

        # Admin lists queue
        r2 = requests.get(f"{API}/admin/appeals", headers=_hdr(ADMIN_TOKEN))
        assert r2.status_code == 200, r2.text
        assert r2.json()["pending_count"] >= 1
        assert any(a["id"] == appeal_id for a in r2.json()["items"])

        # Admin resolves it
        r3 = requests.post(
            f"{API}/admin/appeals/{appeal_id}/resolve",
            headers=_hdr(ADMIN_TOKEN),
            json={"response": "Verificado, activaremos tu cuenta pronto."},
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["appeal"]["status"] == "resolved"
        assert r3.json()["appeal"]["resolved_by"] == "user_test_admin01"

        # Second resolve on same appeal → 409
        r4 = requests.post(
            f"{API}/admin/appeals/{appeal_id}/resolve",
            headers=_hdr(ADMIN_TOKEN),
            json={"response": "Duplicado"},
        )
        assert r4.status_code == 409

        # Client got a notification about the review
        db = _db()
        n = db.notifications.count_documents(
            {"recipient_user_id": "user_test_normal01", "type": "appeal_resolved"}
        )
        assert n >= 1

        # Resolving does NOT flip account_status — user still under_review
        u = db.users.find_one({"user_id": "user_test_normal01"}, {"_id": 0, "account_status": 1})
        assert u["account_status"] == "under_review"

        # Client CAN submit a new appeal now that the previous one is resolved
        r5 = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Sigo esperando la activación de mi cuenta."},
        )
        assert r5.status_code == 200
    finally:
        _cleanup_appeals()
        _set_normal_status(prev)


def test_staff_can_reject_appeal():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    try:
        r = requests.post(
            f"{API}/appeals",
            headers=_hdr(NORMAL_TOKEN),
            json={"message": "Otro intento de reactivación, con capturas adjuntas."},
        )
        appeal_id = r.json()["appeal"]["id"]

        r3 = requests.post(
            f"{API}/admin/appeals/{appeal_id}/reject",
            headers=_hdr(ADMIN_TOKEN),
            json={"response": "Sigue en la lista de bloqueados, no procede."},
        )
        assert r3.status_code == 200
        assert r3.json()["appeal"]["status"] == "rejected"

        db = _db()
        n = db.notifications.count_documents(
            {"recipient_user_id": "user_test_normal01", "type": "appeal_rejected"}
        )
        assert n >= 1
    finally:
        _cleanup_appeals()
        _set_normal_status(prev)


def test_employee_without_permission_is_forbidden():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    # Ensure employee test user does NOT have can_manage_blocklist
    _db().users.update_one(
        {"user_id": "user_test_employee01"},
        {"$set": {"can_manage_blocklist": False}},
    )
    try:
        r = requests.get(f"{API}/admin/appeals", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 403, r.text
    finally:
        _cleanup_appeals()
        _set_normal_status(prev)


def test_employee_with_permission_can_list():
    prev = _set_normal_status("under_review")
    _cleanup_appeals()
    _db().users.update_one(
        {"user_id": "user_test_employee01"},
        {"$set": {"can_manage_blocklist": True, "role": "employee"}},
    )
    try:
        r = requests.get(f"{API}/admin/appeals", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
    finally:
        _cleanup_appeals()
        # Reset permission so we don't leak state into other tests
        _db().users.update_one(
            {"user_id": "user_test_employee01"},
            {"$set": {"can_manage_blocklist": False}},
        )
        _set_normal_status(prev)
