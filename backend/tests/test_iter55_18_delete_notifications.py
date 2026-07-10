"""iter55.18 — Delete notifications (individual + bulk read cleanup).

Covers:
1. DELETE /notifications/{id} removes the row for its owner
2. DELETE /notifications/{id} on someone else's inbox is a no-op (idempotent 200 with already_gone=True)
3. DELETE /notifications/{id} on an unknown id → 200 already_gone=True (idempotent)
4. DELETE /notifications/read only removes read rows, keeps unread
5. Unauth callers → 401/403
"""
import os
import uuid
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _plant_notification(user_id: str, read: bool = False) -> str:
    nid = uuid.uuid4().hex
    _sync_db().notifications.insert_one({
        "id": nid,
        "recipient_user_id": user_id,
        "type": "info",
        "title": "Test",
        "message": "Test message",
        "data": {},
        "read": read,
        "created_at": "2026-07-08T00:00:00+00:00",
        "read_at": "2026-07-08T00:05:00+00:00" if read else None,
    })
    return nid


def _clear_test_notifications(user_id: str) -> None:
    _sync_db().notifications.delete_many({
        "recipient_user_id": user_id,
        "title": "Test",
    })


# ------------------------------------------------------------------
# 1. Delete individual (happy path)
# ------------------------------------------------------------------

def test_delete_own_notification_removes_it():
    _clear_test_notifications("user_test_vip01")
    nid = _plant_notification("user_test_vip01", read=True)

    r = requests.delete(f"{API}/notifications/{nid}", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body.get("already_gone") is not True

    # DB confirms the row is gone
    row = _sync_db().notifications.find_one({"id": nid})
    assert row is None


# ------------------------------------------------------------------
# 2. Cross-owner: cannot delete someone else's notification
# ------------------------------------------------------------------

def test_delete_someone_elses_notification_is_noop():
    _clear_test_notifications("user_test_vip01")
    nid = _plant_notification("user_test_vip01", read=False)

    # Employee attempts to delete the VIP's notification → idempotent noop
    r = requests.delete(f"{API}/notifications/{nid}", headers=_hdr(EMPLOYEE_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("already_gone") is True

    # The row must still exist for the VIP
    row = _sync_db().notifications.find_one({"id": nid})
    assert row is not None
    _clear_test_notifications("user_test_vip01")


# ------------------------------------------------------------------
# 3. Unknown id is idempotent
# ------------------------------------------------------------------

def test_delete_unknown_id_is_idempotent():
    r = requests.delete(
        f"{API}/notifications/does-not-exist-{uuid.uuid4().hex}",
        headers=_hdr(ADMIN_TOKEN),
    )
    assert r.status_code == 200
    assert r.json().get("already_gone") is True


# ------------------------------------------------------------------
# 4. Bulk delete only touches read notifications
# ------------------------------------------------------------------

def test_bulk_delete_read_only_removes_read_rows():
    _clear_test_notifications("user_test_vip01")
    read_id = _plant_notification("user_test_vip01", read=True)
    read_id2 = _plant_notification("user_test_vip01", read=True)
    unread_id = _plant_notification("user_test_vip01", read=False)

    r = requests.delete(f"{API}/notifications/read", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] >= 2  # our two + potentially older read rows

    # Read rows gone
    assert _sync_db().notifications.find_one({"id": read_id}) is None
    assert _sync_db().notifications.find_one({"id": read_id2}) is None
    # Unread survives
    assert _sync_db().notifications.find_one({"id": unread_id}) is not None

    _clear_test_notifications("user_test_vip01")


def test_bulk_delete_only_affects_current_user():
    _clear_test_notifications("user_test_vip01")
    _clear_test_notifications("user_test_admin01")

    vip_read = _plant_notification("user_test_vip01", read=True)
    admin_read = _plant_notification("user_test_admin01", read=True)

    # VIP triggers bulk delete → only their read rows should be gone
    r = requests.delete(f"{API}/notifications/read", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200

    assert _sync_db().notifications.find_one({"id": vip_read}) is None
    # Admin's read notification MUST still exist
    assert _sync_db().notifications.find_one({"id": admin_read}) is not None

    _clear_test_notifications("user_test_vip01")
    _clear_test_notifications("user_test_admin01")


# ------------------------------------------------------------------
# 5. Auth guards
# ------------------------------------------------------------------

def test_delete_requires_auth():
    r = requests.delete(f"{API}/notifications/anything")
    assert r.status_code in (401, 403)
    r2 = requests.delete(f"{API}/notifications/read")
    assert r2.status_code in (401, 403)


# ------------------------------------------------------------------
# 6. Full round-trip: unread-count updates after delete
# ------------------------------------------------------------------

def test_unread_count_drops_after_deleting_unread_notification():
    _clear_test_notifications("user_test_vip01")

    # Baseline count
    r0 = requests.get(f"{API}/notifications/unread-count", headers=_hdr(VIP_TOKEN))
    base = r0.json()["count"]

    nid = _plant_notification("user_test_vip01", read=False)

    r1 = requests.get(f"{API}/notifications/unread-count", headers=_hdr(VIP_TOKEN))
    assert r1.json()["count"] == base + 1

    # Delete → count returns to baseline
    r_del = requests.delete(f"{API}/notifications/{nid}", headers=_hdr(VIP_TOKEN))
    assert r_del.status_code == 200

    r2 = requests.get(f"{API}/notifications/unread-count", headers=_hdr(VIP_TOKEN))
    assert r2.json()["count"] == base

    _clear_test_notifications("user_test_vip01")
