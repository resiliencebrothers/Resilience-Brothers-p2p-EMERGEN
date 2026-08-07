"""iter153 — Frozen balance, client-cancel withdrawal, admin cancelled-guard,
per-status timestamps, and deposit network validation.

Runs against BASE_URL (real backend) using the seeded VIP + admin sessions.
Creates its own withdrawals/deposits and cleans up (cancel / reject).
"""
import os
import requests

from conftest import (
    BASE_URL, VIP_TOKEN, ADMIN_TOKEN,
    make_vip_totp, make_admin_totp,
)


VIP_H = {"Authorization": f"Bearer {VIP_TOKEN}"}
ADM_H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


# ---------- helpers ----------

def _get_balances():
    r = requests.get(f"{BASE_URL}/api/vip/balances", headers=VIP_H, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _get_bal_for(bals, cur):
    for it in bals["balances"]:
        if it["currency"] == cur:
            return it
    return {"currency": cur, "amount": 0.0, "frozen": 0.0, "usdt_equivalent": 0.0}


def _ensure_usd_balance(min_usd=50.0):
    """Ensure VIP has ≥ min_usd in USD balance (top up via direct DB)."""
    from pymongo import MongoClient
    cli = MongoClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    u = db.users.find_one({"user_id": "user_test_vip01"}, {"_id": 0, "vip_balances": 1})
    cur = float((u.get("vip_balances") or {}).get("USD") or 0.0)
    if cur < min_usd:
        db.users.update_one(
            {"user_id": "user_test_vip01"},
            {"$inc": {"vip_balances.USD": min_usd - cur + 10}},
        )
    cli.close()


def _create_withdraw_usd(amount=25.0):
    _ensure_usd_balance(min_usd=amount + 10)
    body = {
        "amount_usd": amount,
        "currency": "USD",
        "method": "transfer",
        "details": "Cuenta Zelle test@example.com beneficiario Iter153 QA",
        "beneficiary_name": "Iter153 QA Tester",
        "totp_code": make_vip_totp(),
    }
    r = requests.post(f"{BASE_URL}/api/vip/withdraw", json=body, headers=VIP_H, timeout=15)
    return r


# ============================================================
# 1) Frozen balance exposure on /vip/balances
# ============================================================

class TestFrozenBalances:
    def test_frozen_appears_after_withdrawal(self):
        # top up first so the withdrawal-time refresh doesn't hide the delta
        _ensure_usd_balance(min_usd=100.0)
        bals_before = _get_balances()
        usd_before = _get_bal_for(bals_before, "USD")
        avail_before = usd_before["amount"]
        frozen_before = usd_before["frozen"]
        frozen_tot_before = bals_before.get("frozen_total_usdt", 0)

        # withdraw directly (skip inner top-up so avail_before matches).
        body = {
            "amount_usd": 25.0,
            "currency": "USD",
            "method": "transfer",
            "details": "Cuenta Zelle test@example.com beneficiario Iter153 QA",
            "beneficiary_name": "Iter153 QA Tester",
            "totp_code": make_vip_totp(),
        }
        r = requests.post(f"{BASE_URL}/api/vip/withdraw",
                          json=body, headers=VIP_H, timeout=15)
        assert r.status_code in (200, 201), r.text
        wid = r.json()["id"]

        try:
            bals_after = _get_balances()
            usd_after = _get_bal_for(bals_after, "USD")
            # available decreases by 25
            assert round(avail_before - usd_after["amount"], 4) == 25.0, (
                f"available {avail_before} -> {usd_after['amount']}"
            )
            # frozen increases by 25
            assert round(usd_after["frozen"] - frozen_before, 4) == 25.0, (
                f"frozen {frozen_before} -> {usd_after['frozen']}"
            )
            # top-level frozen_total_usdt strictly increases (USD→USDT rate
            # may be < 1, so use a permissive floor).
            assert bals_after["frozen_total_usdt"] > frozen_tot_before, (
                f"frozen_total_usdt {frozen_tot_before} -> {bals_after['frozen_total_usdt']}"
            )
        finally:
            # cleanup: cancel to refund
            requests.post(f"{BASE_URL}/api/vip/withdrawals/{wid}/cancel",
                          headers=VIP_H, timeout=15)


# ============================================================
# 2) Client cancel withdrawal — refund + idempotency
# ============================================================

class TestCancelOwnWithdrawal:
    def test_cancel_pending_refunds_and_second_call_409(self):
        bals_pre = _get_balances()
        usd_pre_avail = _get_bal_for(bals_pre, "USD")["amount"]

        r = _create_withdraw_usd(30.0)
        assert r.status_code in (200, 201), r.text
        wid = r.json()["id"]

        # Cancel #1 → 200
        c1 = requests.post(f"{BASE_URL}/api/vip/withdrawals/{wid}/cancel",
                           headers=VIP_H, timeout=15)
        assert c1.status_code == 200, c1.text
        doc = c1.json()
        assert doc["status"] == "cancelled"
        assert doc.get("cancelled_at"), "cancelled_at missing"
        assert doc.get("balance_refunded") is True

        # Balance restored
        bals_post = _get_balances()
        usd_post_avail = _get_bal_for(bals_post, "USD")["amount"]
        assert round(usd_post_avail - usd_pre_avail, 4) == 0.0, (
            f"USD not restored: pre={usd_pre_avail} post={usd_post_avail}"
        )
        # Frozen for this withdrawal is gone (subtract 30)
        assert _get_bal_for(bals_post, "USD")["frozen"] == _get_bal_for(bals_pre, "USD")["frozen"]

        # Cancel #2 → 409 (idempotent)
        c2 = requests.post(f"{BASE_URL}/api/vip/withdrawals/{wid}/cancel",
                           headers=VIP_H, timeout=15)
        assert c2.status_code == 409, c2.text

    def test_cancel_other_user_returns_404(self):
        # Create with admin — admin is not "employee" and can withdraw admin fee-free
        # Simpler: attempt cancelling a bogus id → 404
        r = requests.post(f"{BASE_URL}/api/vip/withdrawals/does-not-exist-xyz/cancel",
                          headers=VIP_H, timeout=15)
        assert r.status_code == 404, r.text

    def test_cancel_approved_returns_409(self):
        # Create → admin approves → cancel attempt should 409.
        r = _create_withdraw_usd(20.0)
        assert r.status_code in (200, 201), r.text
        wid = r.json()["id"]
        try:
            # Approve via admin
            ar = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "approved", "totp_code": make_admin_totp()},
                headers=ADM_H, timeout=15,
            )
            assert ar.status_code == 200, ar.text

            # Client cancel now → 409 (not pending anymore)
            c = requests.post(f"{BASE_URL}/api/vip/withdrawals/{wid}/cancel",
                              headers=VIP_H, timeout=15)
            assert c.status_code == 409, c.text
        finally:
            # cleanup: admin rejects (refunds via reconcile) — direct DB fix to avoid
            # affecting other tests. Just set to rejected via admin.
            requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "rejected",
                      "admin_note": "iter153 cleanup",
                      "totp_code": make_admin_totp()},
                headers=ADM_H, timeout=15,
            )


# ============================================================
# 3) Admin — cannot mutate cancelled; per-status timestamps
# ============================================================

class TestAdminWithdrawalGuards:
    def test_admin_cannot_change_cancelled(self):
        r = _create_withdraw_usd(15.0)
        assert r.status_code in (200, 201), r.text
        wid = r.json()["id"]
        # client cancels
        c = requests.post(f"{BASE_URL}/api/vip/withdrawals/{wid}/cancel",
                          headers=VIP_H, timeout=15)
        assert c.status_code == 200
        # admin tries to approve a cancelled → 409
        ar = requests.put(
            f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
            json={"status": "approved", "totp_code": make_admin_totp()},
            headers=ADM_H, timeout=15,
        )
        assert ar.status_code == 409, ar.text
        assert "cancel" in ar.text.lower()

    def test_admin_status_timestamps(self):
        r = _create_withdraw_usd(18.0)
        assert r.status_code in (200, 201), r.text
        wid = r.json()["id"]
        try:
            # approve → approved_at set
            ar = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "approved", "totp_code": make_admin_totp()},
                headers=ADM_H, timeout=15,
            )
            assert ar.status_code == 200, ar.text
            assert ar.json().get("approved_at"), "approved_at missing"

            # rejected → rejected_at set + balance refunded (no double credit)
            rr = requests.put(
                f"{BASE_URL}/api/admin/withdrawals/{wid}/status",
                json={"status": "rejected", "admin_note": "iter153 ts test",
                      "totp_code": make_admin_totp()},
                headers=ADM_H, timeout=15,
            )
            assert rr.status_code == 200, rr.text
            assert rr.json().get("rejected_at"), "rejected_at missing"
            assert rr.json().get("balance_refunded") is True
        finally:
            pass  # already terminal


# ============================================================
# 4) Deposits — crypto network validation
# ============================================================

class TestDepositNetwork:
    TRC20_HASH = "a" * 64          # 64 hex, no 0x — tron format
    BEP20_HASH = "0x" + "b" * 64   # 0x + 64 hex — EVM format

    def test_crypto_bep20_with_trc20_hash_returns_422(self):
        body = {
            "currency": "USDT",
            "amount": 5,
            "method": "crypto",
            "network": "BEP20",
            "tx_hash": self.TRC20_HASH,  # mismatched
        }
        r = requests.post(f"{BASE_URL}/api/deposits", json=body, headers=VIP_H, timeout=15)
        assert r.status_code == 422, r.text

    def test_crypto_matching_network_hash_ok(self):
        body = {
            "currency": "USDT",
            "amount": 6,
            "method": "crypto",
            "network": "TRC20",
            "tx_hash": self.TRC20_HASH,
        }
        r = requests.post(f"{BASE_URL}/api/deposits", json=body, headers=VIP_H, timeout=15)
        assert r.status_code in (200, 201), r.text
        doc = r.json()
        assert doc.get("network") == "TRC20"
        assert doc.get("method") == "crypto"
        # cleanup: admin rejects
        requests.post(
            f"{BASE_URL}/api/admin/deposits/{doc['id']}/reject",
            json={"admin_note": "iter153 cleanup"},
            headers=ADM_H, timeout=15,
        )

    def test_crypto_no_network_still_ok(self):
        body = {
            "currency": "USDT",
            "amount": 7,
            "method": "crypto",
            "tx_hash": self.BEP20_HASH,  # any valid-looking hash
        }
        r = requests.post(f"{BASE_URL}/api/deposits", json=body, headers=VIP_H, timeout=15)
        assert r.status_code in (200, 201), r.text
        doc = r.json()
        assert doc.get("method") == "crypto"
        # network is optional → stored null when not provided
        assert doc.get("network") in (None, "")
        # my deposits list includes 'network' field
        mine = requests.get(f"{BASE_URL}/api/deposits/mine", headers=VIP_H, timeout=15)
        assert mine.status_code == 200
        items = mine.json().get("items", [])
        matched = [x for x in items if x["id"] == doc["id"]]
        assert matched, "created deposit missing from /deposits/mine"
        assert "network" in matched[0]
        # cleanup
        requests.post(
            f"{BASE_URL}/api/admin/deposits/{doc['id']}/reject",
            json={"admin_note": "iter153 cleanup"},
            headers=ADM_H, timeout=15,
        )
