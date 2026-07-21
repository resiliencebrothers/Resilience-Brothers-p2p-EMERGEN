"""iter55.36m — Defensive Mode toggle endpoint: full contract regression.

Rationale
---------
`POST /api/admin/defensive-mode/toggle` is one of the highest-impact admin
switches on the platform (halts new registrations + normal-user withdrawals
system-wide). A UI-freeze bug reported in iter55.36l revealed that the
frontend was silently swallowing the endpoint's response — this file locks
down the *backend* contract so any future frontend regression can be spotted
independently, and any accidental removal of the RBAC/2FA guard is caught by
`make test-critical`.

The existing `test_iter24_defensive_mode.py` covers happy-path + basic
enforcement on `/auth/register` and `/vip/withdraw`. This suite drills
specifically into the **toggle endpoint itself**: auth, TOTP, payload
validation, idempotency, and audit-trail structure.
"""
import os
import time

import pytest
import requests
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, EMPLOYEE_TOKEN


# ---------- helpers ----------

def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli, cli[os.environ["DB_NAME"]]


def _reset_defensive():
    cli, db = _db()
    db.system_config.delete_many({"key": "defensive_mode"})
    db.audit_log.delete_many({"action": "system.defensive_mode"})
    cli.close()


def _toggle(*, enabled: bool, token: str = ADMIN_TOKEN,
            totp_code=None, reason: str = "iter55.36m test",
            include_totp: bool = True):
    body = {"enabled": enabled, "reason": reason}
    if include_totp:
        body["totp_code"] = totp_code if totp_code is not None else make_admin_totp()
    return requests.post(
        f"{BASE_URL}/api/admin/defensive-mode/toggle",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _clean_state():
    _reset_defensive()
    yield
    _reset_defensive()


# ============================================================
# 1. Happy-path (valid admin + valid TOTP)
# ============================================================

class TestToggleHappyPath:
    def test_enable_returns_200_with_full_state(self):
        r = _toggle(enabled=True, reason="market anomaly")
        assert r.status_code == 200, r.text
        body = r.json()
        # Contract: response mirrors persisted document
        assert body["key"] == "defensive_mode"
        assert body["enabled"] is True
        assert body["reason"] == "market anomaly"
        assert body["enabled_at"] is not None
        assert body["enabled_by_email"], "enabled_by_email must be populated on enable"

    def test_disable_clears_timestamp_and_email(self):
        _toggle(enabled=True, reason="pre-condition")
        r = _toggle(enabled=False, reason="all clear")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["enabled_at"] is None
        assert body["enabled_by_email"] == ""

    def test_state_persists_to_system_config(self):
        _toggle(enabled=True, reason="persist check")
        cli, db = _db()
        doc = db.system_config.find_one({"key": "defensive_mode"})
        cli.close()
        assert doc is not None
        assert doc["enabled"] is True
        assert doc["reason"] == "persist check"

    def test_empty_reason_accepted_and_stripped(self):
        r = _toggle(enabled=True, reason="   ")
        assert r.status_code == 200
        assert r.json()["reason"] == "", "reason must be trimmed to empty"

    def test_omit_reason_still_works(self):
        body = {"enabled": True, "totp_code": make_admin_totp()}
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json=body,
        )
        assert r.status_code == 200
        assert r.json()["reason"] == ""


# ============================================================
# 2. RBAC — admin-only guard
# ============================================================

class TestToggleRBAC:
    def test_no_token_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            json={"enabled": True, "totp_code": "000000"},
        )
        # No Authorization → 401 (unauthenticated)
        assert r.status_code == 401, r.text

    def test_invalid_token_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": "Bearer not-a-real-session"},
            json={"enabled": True, "totp_code": "000000"},
        )
        assert r.status_code == 401

    def test_employee_role_rejected(self):
        # Staff cannot enable defensive mode — admin only.
        r = _toggle(enabled=True, token=EMPLOYEE_TOKEN)
        assert r.status_code == 403, r.text

    def test_vip_role_rejected(self):
        r = _toggle(enabled=True, token=VIP_TOKEN)
        assert r.status_code == 403

    def test_normal_user_rejected(self):
        r = _toggle(enabled=True, token=NORMAL_TOKEN)
        assert r.status_code == 403


# ============================================================
# 3. 2FA / TOTP step-up guard
# ============================================================

class TestToggleTotp:
    def test_missing_totp_field_rejected(self):
        r = _toggle(enabled=True, include_totp=False)
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    def test_empty_totp_string_rejected(self):
        r = _toggle(enabled=True, totp_code="")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_CODE_REQUIRED"

    def test_invalid_numeric_totp_rejected(self):
        # 6-digit code that is guaranteed not to match the docs-sample secret
        r = _toggle(enabled=True, totp_code="000000")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_INVALID"

    def test_wrong_length_totp_rejected(self):
        # 5-digit code — deterministic invalid regardless of clock skew
        r = _toggle(enabled=True, totp_code="12345")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_INVALID"

    def test_alphabetic_totp_rejected(self):
        r = _toggle(enabled=True, totp_code="abcdef")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "TOTP_INVALID"

    def test_totp_field_length_hard_capped_at_11(self):
        # Pydantic Field(max_length=11) — must return 422 for oversize input
        body = {"enabled": True, "totp_code": "1" * 20}
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json=body,
        )
        assert r.status_code == 422

    def test_invalid_totp_does_not_change_state(self):
        # State should NOT flip when TOTP fails.
        r = _toggle(enabled=True, totp_code="000000")
        assert r.status_code == 401
        cli, db = _db()
        doc = db.system_config.find_one({"key": "defensive_mode"})
        cli.close()
        # No doc should exist (setup left it clean)
        assert doc is None or doc.get("enabled") is False


# ============================================================
# 4. Payload validation
# ============================================================

class TestTogglePayloadValidation:
    def test_missing_enabled_flag_returns_422(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json={"totp_code": make_admin_totp()},
        )
        assert r.status_code == 422

    def test_reason_length_hard_capped_at_500(self):
        body = {
            "enabled": True,
            "reason": "x" * 501,
            "totp_code": make_admin_totp(),
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json=body,
        )
        assert r.status_code == 422

    def test_reason_at_length_boundary_accepted(self):
        r = _toggle(enabled=True, reason="y" * 500)
        assert r.status_code == 200
        assert len(r.json()["reason"]) == 500

    def test_non_boolean_enabled_coerces_or_422(self):
        # Pydantic will coerce truthy/falsy but reject arbitrary strings.
        body = {"enabled": "not-a-bool", "totp_code": make_admin_totp()}
        r = requests.post(
            f"{BASE_URL}/api/admin/defensive-mode/toggle",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            json=body,
        )
        assert r.status_code == 422


# ============================================================
# 5. Idempotency + edge cases
# ============================================================

class TestToggleIdempotency:
    def test_enable_twice_stays_enabled(self):
        _toggle(enabled=True, reason="first")
        r = _toggle(enabled=True, reason="second")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["reason"] == "second"

    def test_disable_when_already_disabled(self):
        # Never enabled — first call should still succeed and be a no-op
        r = _toggle(enabled=False, reason="never on")
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["enabled_at"] is None

    def test_enable_then_disable_then_enable_updates_timestamp(self):
        r1 = _toggle(enabled=True, reason="round 1")
        first_ts = r1.json()["enabled_at"]
        _toggle(enabled=False, reason="off")
        # Sleep 1s to guarantee ISO string strictly changes (second precision).
        time.sleep(1.1)
        r3 = _toggle(enabled=True, reason="round 2")
        assert r3.status_code == 200
        second_ts = r3.json()["enabled_at"]
        assert second_ts != first_ts, "enabled_at must refresh on re-enable"
        assert second_ts > first_ts


# ============================================================
# 6. Audit log integration
# ============================================================

class TestToggleAudit:
    def test_enable_creates_audit_entry(self):
        _toggle(enabled=True, reason="audit trail test 1")
        cli, db = _db()
        log = db.audit_log.find_one(
            {"action": "system.defensive_mode",
             "details.reason": "audit trail test 1"}
        )
        cli.close()
        assert log is not None
        assert log["entity_type"] == "system"
        assert log["entity_id"] == "defensive_mode"
        assert "activado" in log["summary"].lower()

    def test_disable_creates_separate_audit_entry(self):
        _toggle(enabled=True, reason="audit trail test 2")
        _toggle(enabled=False, reason="close incident")
        cli, db = _db()
        # Two log entries, distinct summaries
        logs = list(db.audit_log.find({"action": "system.defensive_mode"}))
        cli.close()
        assert len(logs) == 2
        summaries = [log["summary"].lower() for log in logs]
        assert any("activado" in s for s in summaries)
        assert any("desactivado" in s for s in summaries)

    def test_failed_totp_does_not_create_audit_entry(self):
        # Failed 2FA MUST NOT leave a "defensive mode toggled" trail.
        _toggle(enabled=True, totp_code="000000")
        cli, db = _db()
        count = db.audit_log.count_documents({"action": "system.defensive_mode"})
        cli.close()
        assert count == 0

    def test_rejected_non_admin_does_not_create_audit_entry(self):
        _toggle(enabled=True, token=EMPLOYEE_TOKEN)
        cli, db = _db()
        count = db.audit_log.count_documents({"action": "system.defensive_mode"})
        cli.close()
        assert count == 0


# ============================================================
# 7. Cross-endpoint consistency: public GET reflects toggle output
# ============================================================

class TestToggleReflectsInPublicEndpoint:
    def test_public_get_matches_toggle_response(self):
        r_post = _toggle(enabled=True, reason="visible externally")
        assert r_post.status_code == 200
        r_get = requests.get(f"{BASE_URL}/api/system/defensive-mode")
        assert r_get.status_code == 200
        pub = r_get.json()
        assert pub["enabled"] is True
        assert pub["enabled_at"] == r_post.json()["enabled_at"]
        # Public endpoint MUST NOT leak sensitive fields
        assert "reason" not in pub
        assert "enabled_by_email" not in pub

    def test_disable_reflected_in_public_get(self):
        _toggle(enabled=True)
        _toggle(enabled=False)
        r_get = requests.get(f"{BASE_URL}/api/system/defensive-mode")
        assert r_get.status_code == 200
        assert r_get.json()["enabled"] is False
