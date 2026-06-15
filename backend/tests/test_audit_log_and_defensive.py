"""Iter8 — Audit Log (GET /api/admin/audit + writes) and Defensive Mode (requires_double_approval).

Covers:
- Audit Log access control (admin-only) and filters/limit/sort
- Audit writes for rate.update, order.approved/rejected, settings.update, user.update
- Defensive mode auto-flag on order create when profit_pct < defensive_margin_pct
- Defensive mode approval gating (employee 403, admin 200)
- Defensive mode disabled when defensive_margin_pct is null
- Regressions: VIP accumulate flow + /api/admin/revenue excludes requires_double_approval
"""
import time
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL, EMPLOYEE_TOKEN as EMP


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def _ensure_settings(defensive_margin_pct, vip_threshold=5000.0):
    """Set global settings; defensive_margin_pct=None disables."""
    payload = {"vip_threshold_usdt": vip_threshold, "defensive_margin_pct": defensive_margin_pct}
    r = requests.put(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _upsert_rate(from_code, to_code, rate_normal, rate_vip, real_rate):
    """Create or update a rate, returning the rate doc with id."""
    payload = {
        "from_code": from_code,
        "to_code": to_code,
        "rate_normal": rate_normal,
        "rate_vip": rate_vip,
        "real_rate": real_rate,
    }
    r = requests.post(f"{BASE_URL}/api/admin/rates", headers=_h(ADMIN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- AUDIT LOG: access control ----------------
class TestAuditAccess:
    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit")
        assert r.status_code == 401

    def test_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit", headers=_h(NORMAL))
        assert r.status_code == 403

    def test_vip_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit", headers=_h(VIP))
        assert r.status_code == 403

    def test_employee_403(self):
        # Audit log is admin-only (require_admin), not staff
        r = requests.get(f"{BASE_URL}/api/admin/audit", headers=_h(EMP))
        assert r.status_code == 403, "Employee must not access audit log"

    def test_admin_200_list(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit", headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)


# ---------------- AUDIT LOG: writes from staff actions ----------------
class TestAuditWrites:
    def test_rate_update_writes_audit_entry(self):
        # Upsert a unique pair to avoid touching production-like rows
        rate = _upsert_rate("USDT", "MXN", 17.0, 17.2, 17.4)
        rate_id = rate["id"]
        # Trigger PUT to log rate.update
        new_payload = {
            "from_code": "USDT", "to_code": "MXN",
            "rate_normal": 17.05, "rate_vip": 17.25, "real_rate": 17.45,
        }
        r = requests.put(f"{BASE_URL}/api/admin/rates/{rate_id}", headers=_h(ADMIN), json=new_payload)
        assert r.status_code == 200, r.text
        # Verify entry
        time.sleep(0.4)
        logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "rate.update", "limit": 50},
        ).json()
        assert any(e.get("entity_id") == rate_id for e in logs), "rate.update entry not found"
        match = next(e for e in logs if e.get("entity_id") == rate_id)
        for k in ("actor_id", "actor_email", "actor_role", "action", "entity_type",
                  "entity_id", "summary", "details", "created_at"):
            assert k in match, f"missing field {k} in audit entry"
        assert match["actor_role"] == "admin"
        assert match["entity_type"] == "rate"

    def test_settings_update_writes_audit_entry(self):
        _ensure_settings(defensive_margin_pct=None)
        time.sleep(0.3)
        logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "settings.update", "limit": 10},
        ).json()
        assert len(logs) >= 1
        assert logs[0]["entity_type"] == "settings"
        assert logs[0]["actor_id"] == "user_test_admin01"

    def test_user_update_writes_audit_entry(self):
        # UserUpdate model supports role/vip_balance_usd/vip_balances; set VIP role (idempotent)
        payload = {"role": "vip"}
        r = requests.put(
            f"{BASE_URL}/api/admin/users/user_test_vip01",
            headers=_h(ADMIN),
            json=payload,
        )
        assert r.status_code == 200, r.text
        time.sleep(0.3)
        logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "user.update", "actor_id": "user_test_admin01", "limit": 20},
        ).json()
        assert any(e.get("entity_id") == "user_test_vip01" for e in logs), \
            "user.update entry not found"

    def test_order_approved_and_rejected_write_audit_entries(self):
        # Ensure defensive mode disabled so the order stays pending
        _ensure_settings(defensive_margin_pct=None)
        _upsert_rate("USD", "CUP", 380.0, 395.0, 400.0)
        # Create one approved order
        c1 = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_audit_approve",
            },
        )
        assert c1.status_code == 200, c1.text
        oid1 = c1.json()["id"]
        a1 = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid1}/status",
            headers=_h(ADMIN),
            json={"status": "approved", "admin_note": "TEST_audit_ok"},
        )
        assert a1.status_code == 200, a1.text
        # Create one rejected order
        c2 = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 5.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_audit_reject",
            },
        )
        assert c2.status_code == 200, c2.text
        oid2 = c2.json()["id"]
        a2 = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid2}/status",
            headers=_h(ADMIN),
            json={"status": "rejected", "admin_note": "TEST_audit_bad"},
        )
        assert a2.status_code == 200, a2.text

        time.sleep(0.4)
        approved_logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "order.approved", "limit": 50},
        ).json()
        rejected_logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "order.rejected", "limit": 50},
        ).json()
        assert any(e.get("entity_id") == oid1 for e in approved_logs), \
            "order.approved entry not found"
        assert any(e.get("entity_id") == oid2 for e in rejected_logs), \
            "order.rejected entry not found"


# ---------------- AUDIT LOG: query options ----------------
class TestAuditQueryOptions:
    def test_sort_desc_by_created_at(self):
        # Generate two settings updates to ensure recency
        _ensure_settings(defensive_margin_pct=None)
        time.sleep(0.05)
        _ensure_settings(defensive_margin_pct=None)
        time.sleep(0.3)
        logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"limit": 20},
        ).json()
        assert len(logs) >= 2
        # created_at strings are ISO8601 so lexical sort == temporal sort
        for i in range(len(logs) - 1):
            assert logs[i]["created_at"] >= logs[i + 1]["created_at"]

    def test_limit_cap_clamps_to_500(self):
        # limit beyond 500 must not error; effective list <= 500
        r = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"limit": 5000},
        )
        assert r.status_code == 200
        assert len(r.json()) <= 500

    def test_limit_min_1(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"limit": 0},
        )
        assert r.status_code == 200
        assert len(r.json()) <= 1

    def test_filter_by_actor_id(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"actor_id": "user_test_admin01", "limit": 20},
        )
        assert r.status_code == 200
        for e in r.json():
            assert e["actor_id"] == "user_test_admin01"

    def test_pagination_headers_and_offset(self):
        # Total count + offset windowing
        r1 = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"limit": 5, "offset": 0},
        )
        assert r1.status_code == 200
        total = int(r1.headers.get("X-Total-Count", "0"))
        assert int(r1.headers.get("X-Offset", "-1")) == 0
        assert int(r1.headers.get("X-Limit", "0")) == 5
        page1 = r1.json()
        assert len(page1) <= 5
        if total <= 5:
            pytest.skip(f"only {total} audit entries — cannot validate offset paging")
        r2 = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"limit": 5, "offset": 5},
        )
        assert r2.status_code == 200
        assert int(r2.headers.get("X-Offset", "-1")) == 5
        page2 = r2.json()
        # No overlap between page 1 and page 2
        ids1 = {e["id"] for e in page1}
        ids2 = {e["id"] for e in page2}
        assert ids1.isdisjoint(ids2), "pagination overlap detected"
        # Total header is consistent across pages
        assert int(r2.headers.get("X-Total-Count", "0")) == total


# ---------------- DEFENSIVE MODE on order create ----------------
class TestDefensiveModeAutoFlag:
    def test_order_flagged_when_margin_below_threshold(self):
        # Margin: profit_pct = (real_value - amount_to) / real_value * 100
        # rate_normal=395, real_rate=400 -> amount_to=10*395*0.95=3752.5,
        # real_value=10*400=4000 -> profit_pct = (4000-3752.5)/4000 = 6.19%
        # Set threshold to 10% so below threshold -> flagged
        _upsert_rate("USD", "CUP", 395.0, 398.0, 400.0)
        _ensure_settings(defensive_margin_pct=10.0)
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_defensive_low_margin",
            },
        )
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        # Re-fetch via admin list to see the post-update status
        time.sleep(0.3)
        all_orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN)).json()
        match = next((o for o in all_orders if o["id"] == oid), None)
        assert match is not None, "order not found in admin list"
        assert match["status"] == "requires_double_approval", \
            f"expected requires_double_approval, got {match['status']}"

    def test_order_not_flagged_when_margin_above_threshold(self):
        # rate_normal=380, real_rate=420 -> profit_pct large; threshold=5% -> NOT flagged
        _upsert_rate("USD", "CUP", 380.0, 395.0, 420.0)
        _ensure_settings(defensive_margin_pct=5.0)
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_defensive_high_margin",
            },
        )
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        time.sleep(0.3)
        all_orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN)).json()
        match = next((o for o in all_orders if o["id"] == oid), None)
        assert match is not None
        assert match["status"] == "pending", f"expected pending, got {match['status']}"

    def test_defensive_disabled_when_setting_none(self):
        # Even with very thin margin, when defensive_margin_pct is null -> stays pending
        _upsert_rate("USD", "CUP", 399.0, 399.5, 400.0)
        _ensure_settings(defensive_margin_pct=None)
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_defensive_disabled",
            },
        )
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        time.sleep(0.3)
        all_orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN)).json()
        match = next((o for o in all_orders if o["id"] == oid), None)
        assert match is not None
        assert match["status"] == "pending"


# ---------------- DEFENSIVE MODE approval gating ----------------
class TestDefensiveApprovalGating:
    def _create_flagged_order(self, label):
        _upsert_rate("USD", "CUP", 395.0, 398.0, 400.0)
        _ensure_settings(defensive_margin_pct=10.0)
        r = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": f"TEST_gate_{label}",
            },
        )
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        time.sleep(0.3)
        all_orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN)).json()
        match = next((o for o in all_orders if o["id"] == oid), None)
        assert match and match["status"] == "requires_double_approval"
        return oid

    def test_employee_cannot_approve_flagged_order(self):
        oid = self._create_flagged_order("emp")
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(EMP),
            json={"status": "approved", "admin_note": "emp tries"},
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_admin_can_approve_flagged_order(self):
        oid = self._create_flagged_order("admin")
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(ADMIN),
            json={"status": "approved", "admin_note": "admin approves"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # Audit log entry has action=order.approved
        time.sleep(0.3)
        logs = requests.get(
            f"{BASE_URL}/api/admin/audit",
            headers=_h(ADMIN),
            params={"action": "order.approved", "limit": 50},
        ).json()
        assert any(e.get("entity_id") == oid for e in logs)

    def test_employee_can_still_approve_non_flagged_order(self):
        # Sanity: defensive gating must not block normal approvals by employees
        _upsert_rate("USD", "CUP", 380.0, 395.0, 420.0)
        _ensure_settings(defensive_margin_pct=5.0)
        c = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_gate_emp_normal",
            },
        )
        assert c.status_code == 200, c.text
        oid = c.json()["id"]
        time.sleep(0.3)
        r = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(EMP),
            json={"status": "approved", "admin_note": "emp on pending"},
        )
        assert r.status_code == 200, f"employee should approve pending: {r.text}"
        assert r.json()["status"] == "approved"


# ---------------- REGRESSIONS ----------------
class TestRegressions:
    def test_vip_accumulate_flow_still_increments_balance(self):
        _ensure_settings(defensive_margin_pct=None)  # avoid flagging
        _upsert_rate("USD", "CUP", 380.0, 395.0, 420.0)
        # snapshot balance
        me_before = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP)).json()
        cup_before = float((me_before.get("vip_balances") or {}).get("CUP", 0.0))

        c = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(VIP),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 4.0,
                "delivery_method": "accumulate",
                "delivery_details": "TEST_vip_accumulate",
            },
        )
        assert c.status_code == 200, c.text
        oid = c.json()["id"]
        amount_to_credit = float(c.json()["amount_to"])
        a = requests.put(
            f"{BASE_URL}/api/admin/orders/{oid}/status",
            headers=_h(ADMIN),
            json={"status": "approved", "admin_note": "vip accum"},
        )
        assert a.status_code == 200, a.text
        me_after = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP)).json()
        cup_after = float((me_after.get("vip_balances") or {}).get("CUP", 0.0))
        assert cup_after == pytest.approx(cup_before + amount_to_credit, rel=1e-3), \
            f"VIP CUP balance not incremented correctly: {cup_before} -> {cup_after} (+{amount_to_credit})"

    def test_revenue_excludes_requires_double_approval(self):
        # Snapshot revenue
        rev_before = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        orders_before = rev_before.get("orders_total", 0)
        # Create a flagged order
        _upsert_rate("USD", "CUP", 395.0, 398.0, 400.0)
        _ensure_settings(defensive_margin_pct=10.0)
        c = requests.post(
            f"{BASE_URL}/api/orders",
            headers=_h(NORMAL),
            json={
                "from_code": "USD", "to_code": "CUP", "amount_from": 10.0,
                "delivery_method": "transfer",
                "delivery_details": "TEST_revenue_excl_flagged",
            },
        )
        assert c.status_code == 200, c.text
        oid = c.json()["id"]
        time.sleep(0.3)
        all_orders = requests.get(f"{BASE_URL}/api/admin/orders", headers=_h(ADMIN)).json()
        match = next((o for o in all_orders if o["id"] == oid), None)
        assert match and match["status"] == "requires_double_approval"

        rev_after = requests.get(f"{BASE_URL}/api/admin/revenue", headers=_h(ADMIN)).json()
        # The flagged order is NOT counted as approved/completed -> orders_total unchanged from this op
        assert rev_after.get("orders_total", 0) == orders_before, \
            "requires_double_approval order should not be counted by revenue"
