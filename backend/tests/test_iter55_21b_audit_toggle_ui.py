"""iter55.21b — UI toggle for auto_send_monthly_audit.

Covers the HTTP contract for the new `auto_send_monthly_audit` flag on
`GET /admin/settings` and `PUT /admin/settings`. The scheduler behaviour
itself is already covered by `test_iter55_21_monthly_audit_scheduler.py`;
here we validate that the operator can flip the flag from the UI.
"""
import os
import requests
import pytest
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, EMPLOYEE_TOKEN, make_admin_totp


def _mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _reset_settings_flag():
    """Remove the flag so we start from the default (missing = enabled)."""
    _mongo().settings.update_one(
        {"id": "global"},
        {"$unset": {"auto_send_monthly_audit": ""}},
    )


@pytest.fixture(autouse=True)
def _clean_flag_between_tests():
    _reset_settings_flag()
    yield
    _reset_settings_flag()


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _employee_headers():
    return {"Authorization": f"Bearer {EMPLOYEE_TOKEN}"}


def test_get_settings_defaults_flag_to_true_when_missing():
    """A settings doc without the flag is treated as ENABLED (matches
    scheduler.py opt-out semantics)."""
    r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_admin_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "auto_send_monthly_audit" in data
    assert data["auto_send_monthly_audit"] is True


def test_admin_can_disable_flag_via_put():
    body = {"auto_send_monthly_audit": False, "totp_code": make_admin_totp()}
    r = requests.put(f"{BASE_URL}/api/admin/settings", json=body, headers=_admin_headers())
    assert r.status_code == 200, r.text
    # Confirm persistence via GET
    r2 = requests.get(f"{BASE_URL}/api/admin/settings", headers=_admin_headers())
    assert r2.status_code == 200
    assert r2.json()["auto_send_monthly_audit"] is False
    # And directly in Mongo
    doc = _mongo().settings.find_one({"id": "global"})
    assert doc is not None
    assert doc.get("auto_send_monthly_audit") is False


def test_admin_can_re_enable_flag_via_put():
    # first disable
    body_off = {"auto_send_monthly_audit": False, "totp_code": make_admin_totp()}
    r = requests.put(f"{BASE_URL}/api/admin/settings", json=body_off, headers=_admin_headers())
    assert r.status_code == 200
    # then re-enable
    body_on = {"auto_send_monthly_audit": True, "totp_code": make_admin_totp()}
    r = requests.put(f"{BASE_URL}/api/admin/settings", json=body_on, headers=_admin_headers())
    assert r.status_code == 200
    assert _mongo().settings.find_one({"id": "global"}).get("auto_send_monthly_audit") is True


def test_employee_cannot_update_flag():
    """Only admin can flip global settings (require_admin gate)."""
    body = {"auto_send_monthly_audit": False, "totp_code": "000000"}
    r = requests.put(f"{BASE_URL}/api/admin/settings", json=body, headers=_employee_headers())
    assert r.status_code == 403, r.text


def test_partial_update_does_not_erase_ops_email():
    """PUT with only the toggle flag must NOT clobber unrelated settings
    (regression guard for exclude_unset semantics)."""
    # Seed a real ops_notifications_email + threshold first
    body_full = {
        "vip_threshold_usdt": 4444.0,
        "ops_notifications_email": "keep@example.com",
        "totp_code": make_admin_totp(),
    }
    r = requests.put(f"{BASE_URL}/api/admin/settings", json=body_full, headers=_admin_headers())
    assert r.status_code == 200, r.text
    # Now flip ONLY the flag
    body_flag = {"auto_send_monthly_audit": False, "totp_code": make_admin_totp()}
    r2 = requests.put(f"{BASE_URL}/api/admin/settings", json=body_flag, headers=_admin_headers())
    assert r2.status_code == 200, r2.text
    doc = _mongo().settings.find_one({"id": "global"})
    assert doc.get("ops_notifications_email") == "keep@example.com"
    assert doc.get("vip_threshold_usdt") == 4444.0
    assert doc.get("auto_send_monthly_audit") is False


def test_get_settings_reflects_disabled_flag_when_explicitly_false():
    _mongo().settings.update_one(
        {"id": "global"},
        {"$set": {"auto_send_monthly_audit": False}},
        upsert=True,
    )
    r = requests.get(f"{BASE_URL}/api/admin/settings", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["auto_send_monthly_audit"] is False
