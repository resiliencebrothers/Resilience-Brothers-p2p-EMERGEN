"""Iteration 2 tests: email notifications (approve/reject) + VIP daily closing PDF."""
import pytest
import requests

from conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, NORMAL_TOKEN, make_admin_totp


def _h(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _create_vip_order(amount=15, delivery_method="accumulate"):
    payload = {"from_code": "USD", "to_code": "CUP", "amount_from": amount,
               "delivery_method": delivery_method, "delivery_details": "x",
               "sender_name": "VIP Test", "proof_image": ""}
    r = requests.post(f"{BASE_URL}/api/orders", headers=_h(VIP_TOKEN), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ----- Email notification on approve/reject -----
class TestEmailNotificationsAndStatusUpdate:
    @classmethod
    def setup_class(cls):
        # Ensure defensive mode is OFF so test orders don't become requires_double_approval
        requests.put(f"{BASE_URL}/api/admin/settings", headers=_h(ADMIN_TOKEN),
                     json={"vip_threshold_usdt": 5000, "defensive_margin_pct": None,
                           "totp_code": make_admin_totp()})

    def test_approve_does_not_break_endpoint_even_if_email_fails(self):
        order = _create_vip_order()
        oid = order["id"]
        me0 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        before_cup = float((me0.get("vip_balances") or {}).get("CUP", 0.0))
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN),
                         json={"status": "approved", "admin_note": "iter2 approve", "totp_code": make_admin_totp()})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["admin_note"] == "iter2 approve"
        # Balance must have increased in vip_balances.CUP (multi-currency)
        me1 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        after_cup = float((me1.get("vip_balances") or {}).get("CUP", 0.0))
        assert round(after_cup - before_cup, 4) == round(order["amount_to"], 4)

    def test_reject_does_not_break_endpoint(self):
        order = _create_vip_order(amount=8, delivery_method="transfer")
        oid = order["id"]
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "rejected", "admin_note": "iter2 reject"})
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    def test_completed_status_does_not_break(self):
        order = _create_vip_order(amount=6, delivery_method="transfer")
        oid = order["id"]
        # iter41: completed + transfer now requires a payout proof. Send a tiny
        # base64 PNG to satisfy _validate_order_payout_evidence.
        tiny_png = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN),
                         json={"status": "completed",
                               "payout_proof_image": tiny_png})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_pending_status_noop_no_email(self):
        order = _create_vip_order(amount=4, delivery_method="transfer")
        oid = order["id"]
        r = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                         headers=_h(ADMIN_TOKEN), json={"status": "pending"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_double_approve_only_credits_once(self):
        order = _create_vip_order(amount=7)
        oid = order["id"]
        me0 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        cup0 = float((me0.get("vip_balances") or {}).get("CUP", 0.0))
        # First approve
        r1 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "totp_code": make_admin_totp()})
        assert r1.status_code == 200
        me1 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        cup1 = float((me1.get("vip_balances") or {}).get("CUP", 0.0))
        # Second approve (same status) — iter3 guard must prevent double-credit
        r2 = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "totp_code": make_admin_totp()})
        assert r2.status_code == 200
        me2 = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(VIP_TOKEN)).json()
        cup2 = float((me2.get("vip_balances") or {}).get("CUP", 0.0))
        delta1 = round(cup1 - cup0, 4)
        delta2 = round(cup2 - cup1, 4)
        assert delta1 == round(order["amount_to"], 4)
        assert delta2 == 0.0, f"Double-approve credited again (delta2={delta2}). Expected 0."


# ----- VIP daily-closing PDF -----
class TestVipDailyClosing:
    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing")
        assert r.status_code == 401

    def test_normal_403(self):
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing", headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_vip_returns_pdf(self):
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000

    def test_admin_returns_pdf(self):
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000

    def test_invalid_date_400(self):
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing?date=not-a-date", headers=_h(VIP_TOKEN))
        assert r.status_code == 400

    def test_valid_date_filter(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing?date={today}", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_closing_includes_approved_orders_today(self):
        # Create + approve an order today
        order = _create_vip_order(amount=20, delivery_method="accumulate")
        oid = order["id"]
        ra = requests.put(f"{BASE_URL}/api/admin/orders/{oid}/status",
                          headers=_h(ADMIN_TOKEN), json={"status": "approved", "totp_code": make_admin_totp()})
        assert ra.status_code == 200
        # Fetch closing
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing?date={today}", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert len(r.content) > 2000  # Should contain at least one row + summary
        assert r.content[:4] == b"%PDF"

    def test_closing_past_date_still_returns_pdf(self):
        # Use a date with no orders — PDF should still build with placeholder row
        r = requests.get(f"{BASE_URL}/api/vip/daily-closing?date=2020-01-01", headers=_h(VIP_TOKEN))
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
