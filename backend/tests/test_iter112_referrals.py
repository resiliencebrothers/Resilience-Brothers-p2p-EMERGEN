"""iter112 — Referral system regression tests.

Endpoints under test:
    GET  /api/referrals/me
    POST /api/referrals/claim
    GET  /api/admin/referrals/leaderboard
    PUT  /api/admin/settings   (referral_bonus_pct)

Bonus hook: services/referrals.maybe_award_referral_bonus fired from
run_post_status_side_effects on the referred user's FIRST settled order.
"""
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from conftest import BASE_URL, make_admin_totp, ADMIN_TOKEN, NORMAL_TOKEN

load_dotenv("/app/backend/.env")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

API = f"{BASE_URL}/api"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _mk_user(db, role="normal", **extra):
    """Insert a throwaway active user + session. Returns (user_id, token)."""
    uid = f"user_ref112_{uuid.uuid4().hex[:10]}"
    token = f"test_session_ref112_{uuid.uuid4().hex[:10]}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"{uid}@ref112.test",
        "name": f"Ref112 {uid[-4:]}",
        "role": role,
        "email_verified": True,
        "phone": f"+5352{uuid.uuid4().hex[:6]}",
        "phone_verified": True,
        "account_status": "active",
        "vip_balance_usd": 0.0,
        "vip_balances": {},
        "created_at": "2026-07-26T00:00:00+00:00",
        **extra,
    })
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": uid,
        "created_at": "2026-07-26T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
    })
    return uid, token


def _cleanup(db, *user_ids):
    db.users.delete_many({"user_id": {"$in": list(user_ids)}})
    db.user_sessions.delete_many({"user_id": {"$in": list(user_ids)}})
    db.orders.delete_many({"user_id": {"$in": list(user_ids)}})
    db.referral_bonuses.delete_many({"$or": [
        {"referrer_user_id": {"$in": list(user_ids)}},
        {"referred_user_id": {"$in": list(user_ids)}},
    ]})


def _mk_order(db, uid, from_code="CUP", to_code="USDT",
              amount_from=10000.0, amount_to=24.0):
    oid = uuid.uuid4().hex
    db.orders.insert_one({
        "id": oid,
        "user_id": uid,
        "user_role": "normal",
        "from_code": from_code,
        "to_code": to_code,
        "amount_from": amount_from,
        "amount_to": amount_to,
        "rate_used": amount_to / amount_from,
        "delivery_method": "transfer",
        "delivery_details": "",
        "proof_image": "",
        "status": "pending",
        "admin_note": "",
        "created_at": "2026-07-26T00:00:00+00:00",
        "updated_at": "2026-07-26T00:00:00+00:00",
    })
    return oid


def _approve(oid):
    return requests.put(
        f"{API}/admin/orders/{oid}/status",
        headers=_h(ADMIN_TOKEN),
        json={"status": "approved", "admin_note": "ref112",
              "totp_code": make_admin_totp()},
    )


class TestReferralCode:
    def test_me_generates_stable_unique_code(self):
        r1 = requests.get(f"{API}/referrals/me", headers=_h(NORMAL_TOKEN))
        assert r1.status_code == 200, r1.text
        body = r1.json()
        code = body["referral_code"]
        assert code.startswith("RB") and len(code) == 8
        assert body["bonus_pct"] > 0
        assert {"referred_count", "activated_count",
                "total_bonus_usdt", "bonuses"} <= set(body)
        # Second call returns the SAME code (no regeneration).
        r2 = requests.get(f"{API}/referrals/me", headers=_h(NORMAL_TOKEN))
        assert r2.json()["referral_code"] == code

    def test_me_requires_auth(self):
        r = requests.get(f"{API}/referrals/me")
        assert r.status_code == 401


class TestClaim:
    def setup_method(self):
        self.db = _db()
        self.uids = []

    def teardown_method(self):
        _cleanup(self.db, *self.uids)

    def _fresh_user(self, **extra):
        uid, token = _mk_user(self.db, **extra)
        self.uids.append(uid)
        return uid, token

    def _normal_code(self):
        return requests.get(
            f"{API}/referrals/me", headers=_h(NORMAL_TOKEN),
        ).json()["referral_code"]

    def test_claim_happy_path_and_double_claim_409(self):
        code = self._normal_code()
        _uid, token = self._fresh_user()
        r = requests.post(f"{API}/referrals/claim", headers=_h(token),
                          json={"code": code.lower()})  # case-insensitive
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        # Second claim → 409
        r2 = requests.post(f"{API}/referrals/claim", headers=_h(token),
                           json={"code": code})
        assert r2.status_code == 409

    def test_claim_unknown_code_404(self):
        _uid, token = self._fresh_user()
        r = requests.post(f"{API}/referrals/claim", headers=_h(token),
                          json={"code": "RBZZZZZZ"})
        assert r.status_code == 404

    def test_claim_own_code_400(self):
        _uid, token = self._fresh_user()
        own = requests.get(f"{API}/referrals/me",
                           headers=_h(token)).json()["referral_code"]
        r = requests.post(f"{API}/referrals/claim", headers=_h(token),
                          json={"code": own})
        assert r.status_code == 400

    def test_claim_after_settled_order_400(self):
        code = self._normal_code()
        uid, token = self._fresh_user()
        self.db.orders.insert_one({
            "id": uuid.uuid4().hex, "user_id": uid, "status": "approved",
            "from_code": "USD", "to_code": "CUP",
            "amount_from": 1, "amount_to": 380,
            "created_at": "2026-07-26T00:00:00+00:00",
        })
        r = requests.post(f"{API}/referrals/claim", headers=_h(token),
                          json={"code": code})
        assert r.status_code == 400

    def test_claim_extra_field_422(self):
        _uid, token = self._fresh_user()
        r = requests.post(f"{API}/referrals/claim", headers=_h(token),
                          json={"code": "RBAAAAAA", "hack": True})
        assert r.status_code == 422


class TestBonusFlow:
    """First approved order pays the referrer 10% of the company profit.
    Deterministic setup: pinned CUP→USDT rate with real_rate so profit is
    exactly 1.0 USDT → bonus 0.1 USDT at the default 10%."""

    def setup_method(self):
        self.db = _db()
        self.uids = []
        self.prev_rate = self.db.rates.find_one(
            {"from_code": "CUP", "to_code": "USDT"})
        # profit = 10000 * 0.0025 - 24.0 = 1.0 USDT
        self.db.rates.update_one(
            {"from_code": "CUP", "to_code": "USDT"},
            {"$set": {"rate_normal": 0.0024, "rate_vip": 0.00245,
                      "real_rate": 0.0025}},
            upsert=True,
        )

    def teardown_method(self):
        _cleanup(self.db, *self.uids)
        if self.prev_rate is not None:
            self.db.rates.update_one(
                {"from_code": "CUP", "to_code": "USDT"},
                {"$set": {k: self.prev_rate.get(k) for k in
                          ("rate_normal", "rate_vip", "real_rate")}},
            )
        else:
            self.db.rates.delete_one({"from_code": "CUP", "to_code": "USDT"})

    def _pair(self):
        referrer_id, referrer_tok = _mk_user(self.db)
        referred_id, referred_tok = _mk_user(self.db)
        self.uids += [referrer_id, referred_id]
        code = requests.get(f"{API}/referrals/me",
                            headers=_h(referrer_tok)).json()["referral_code"]
        r = requests.post(f"{API}/referrals/claim",
                          headers=_h(referred_tok), json={"code": code})
        assert r.status_code == 200, r.text
        return referrer_id, referrer_tok, referred_id

    def test_first_order_pays_bonus_once(self):
        referrer_id, referrer_tok, referred_id = self._pair()
        oid = _mk_order(self.db, referred_id)
        r = _approve(oid)
        assert r.status_code == 200, r.text

        referrer = self.db.users.find_one({"user_id": referrer_id})
        assert referrer["vip_balances"].get("USDT") == pytest.approx(0.1, abs=1e-6)

        row = self.db.referral_bonuses.find_one({"referred_user_id": referred_id})
        assert row is not None
        assert row["referrer_user_id"] == referrer_id
        assert row["bonus_usdt"] == pytest.approx(0.1, abs=1e-6)
        assert row["order_profit_usdt"] == pytest.approx(1.0, abs=1e-6)
        assert row["order_id"] == oid

        referred = self.db.users.find_one({"user_id": referred_id})
        assert referred["referral_bonus_paid"] is True

        # In-app notification reached the referrer.
        note = self.db.notifications.find_one(
            {"recipient_user_id": referrer_id, "type": "referral_bonus"})
        assert note is not None

        # /referrals/me reflects the activation.
        me = requests.get(f"{API}/referrals/me",
                          headers=_h(referrer_tok)).json()
        assert me["activated_count"] == 1
        assert me["total_bonus_usdt"] == pytest.approx(0.1, abs=1e-6)

    def test_second_order_does_not_double_pay(self):
        referrer_id, _tok, referred_id = self._pair()
        assert _approve(_mk_order(self.db, referred_id)).status_code == 200
        assert _approve(_mk_order(self.db, referred_id)).status_code == 200
        rows = list(self.db.referral_bonuses.find(
            {"referred_user_id": referred_id}))
        assert len(rows) == 1
        referrer = self.db.users.find_one({"user_id": referrer_id})
        assert referrer["vip_balances"].get("USDT") == pytest.approx(0.1, abs=1e-6)

    def test_no_bonus_without_referrer(self):
        uid, _tok = _mk_user(self.db)
        self.uids.append(uid)
        assert _approve(_mk_order(self.db, uid)).status_code == 200
        assert self.db.referral_bonuses.find_one(
            {"referred_user_id": uid}) is None


class TestLeaderboardAndSettings:
    def test_leaderboard_staff_only(self):
        r = requests.get(f"{API}/admin/referrals/leaderboard",
                         headers=_h(NORMAL_TOKEN))
        assert r.status_code == 403

    def test_leaderboard_shape(self):
        r = requests.get(f"{API}/admin/referrals/leaderboard",
                         headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"items", "bonus_pct", "total_paid_usdt"} <= set(body)
        for item in body["items"][:3]:
            assert {"referrer_user_id", "name", "email", "referred_count",
                    "activated_count", "total_bonus_usdt"} <= set(item)

    def test_settings_pct_roundtrip(self):
        prev = requests.get(f"{API}/admin/settings",
                            headers=_h(ADMIN_TOKEN)).json()["referral_bonus_pct"]
        try:
            r = requests.put(
                f"{API}/admin/settings", headers=_h(ADMIN_TOKEN),
                json={"referral_bonus_pct": 15.0,
                      "totp_code": make_admin_totp()},
            )
            assert r.status_code == 200, r.text
            got = requests.get(f"{API}/admin/settings",
                               headers=_h(ADMIN_TOKEN)).json()
            assert got["referral_bonus_pct"] == 15.0
        finally:
            requests.put(
                f"{API}/admin/settings", headers=_h(ADMIN_TOKEN),
                json={"referral_bonus_pct": prev,
                      "totp_code": make_admin_totp()},
            )

    def test_settings_pct_over_100_rejected(self):
        r = requests.put(
            f"{API}/admin/settings", headers=_h(ADMIN_TOKEN),
            json={"referral_bonus_pct": 150.0, "totp_code": make_admin_totp()},
        )
        assert r.status_code == 422
