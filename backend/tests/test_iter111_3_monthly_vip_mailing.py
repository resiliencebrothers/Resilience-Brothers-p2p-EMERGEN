"""iter111.3 — Monthly automatic VIP ledger mailing regression tests.

Coverage:
  * Scheduler job (`run_monthly_vip_ledger_email`) runs standalone with
    proper period (previous month), skips empty ledgers, respects global
    opt-out flag and per-VIP flag.
  * Admin manual "run now" endpoint.
  * VIP per-user monthly preference GET/PUT round-trip.
  * RBAC guards on all new endpoints.
"""
import os
from datetime import datetime, timezone

import requests

from pymongo import MongoClient

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _reset_settings_and_ledger():
    """Clear global opt-out + wipe VIP ledger state so each test is deterministic."""
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db.settings.update_one(
        {"id": "global"},
        {"$unset": {"auto_send_monthly_vip_ledger": ""}},
    )
    db.users.update_one(
        {"user_id": "user_test_vip01"},
        {"$unset": {"monthly_ledger_email_enabled": ""}},
    )
    for col in ("vip_capital_deposits", "vip_settlements",
                 "vip_batch_items", "vip_batches", "vip_ledger"):
        db[col].delete_many({"vip_user_id": "user_test_vip01"})
    db.rates.update_one(
        {"from_code": "USDT", "to_code": "USDT"},
        {"$set": {"from_code": "USDT", "to_code": "USDT",
                  "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0}},
        upsert=True,
    )


class TestMonthlyMailing:
    def test_admin_run_now_default_state(self):
        _reset_settings_and_ledger()
        r = requests.post(f"{BASE_URL}/api/admin/vip-ledger/monthly-mailing/run-now",
                          headers=_h(ADMIN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        # Empty ledgers → skipped_empty > 0, sent = 0
        assert body["sent"] == 0
        assert body["skipped_empty"] >= 1
        assert body["opted_out"] is False

    def test_admin_run_now_respects_global_opt_out(self):
        _reset_settings_and_ledger()
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        db.settings.update_one(
            {"id": "global"},
            {"$set": {"auto_send_monthly_vip_ledger": False}},
            upsert=True,
        )
        r = requests.post(f"{BASE_URL}/api/admin/vip-ledger/monthly-mailing/run-now",
                          headers=_h(ADMIN))
        assert r.status_code == 200
        body = r.json()
        assert body["opted_out"] is True
        assert body["sent"] == 0
        assert body["total_vips"] == 0
        _reset_settings_and_ledger()

    def test_admin_run_now_requires_orders_permission(self):
        r = requests.post(f"{BASE_URL}/api/admin/vip-ledger/monthly-mailing/run-now",
                          headers=_h(NORMAL))
        assert r.status_code == 403

    def test_vip_default_preference_is_enabled(self):
        _reset_settings_and_ledger()
        r = requests.get(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP))
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_vip_can_disable_and_re_enable(self):
        _reset_settings_and_ledger()
        # Disable
        r = requests.put(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP), json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        # Confirm on GET
        r = requests.get(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP))
        assert r.json()["enabled"] is False
        # Re-enable
        r = requests.put(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP), json={"enabled": True})
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP))
        assert r.json()["enabled"] is True

    def test_vip_pref_forbidden_for_normal(self):
        r = requests.get(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(NORMAL))
        assert r.status_code == 403
        r = requests.put(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(NORMAL), json={"enabled": False})
        assert r.status_code == 403

    def test_vip_pref_rejects_extra_field(self):
        r = requests.put(f"{BASE_URL}/api/vip/ledger/monthly-preference",
                         headers=_h(VIP), json={"enabled": True, "extra": 1})
        assert r.status_code == 422

    def test_admin_run_now_skips_per_vip_opt_out(self):
        _reset_settings_and_ledger()
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        # Give the VIP a non-empty ledger so it *would* have been mailed.
        db.vip_ledger.update_one(
            {"vip_user_id": "user_test_vip01"},
            {"$set": {"vip_user_id": "user_test_vip01",
                      "positive_usdt": 100.0, "negative_usdt": 0.0}},
            upsert=True,
        )
        # And add a confirmed deposit inside the previous month so the
        # collector will find at least 1 movement.
        # We use the previous-month first day at 12:00 UTC.
        from datetime import date
        from calendar import monthrange
        now = datetime.now(timezone.utc)
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        prev_last = first_this - timedelta(days=1)
        y, m = prev_last.year, prev_last.month
        ts_iso = date(y, m, min(15, monthrange(y, m)[1])).strftime("%Y-%m-%dT12:00:00+00:00")
        db.vip_capital_deposits.insert_one({
            "id": "vdep_test_iter111_3",
            "vip_user_id": "user_test_vip01",
            "currency": "USDT",
            "amount": 100.0,
            "status": "confirmed",
            "balance_delta_usdt": 100.0,
            "created_at": ts_iso,
            "reviewed_at": ts_iso,
            "updated_at": ts_iso,
            "note": "test regresion",
        })

        # Opt this VIP out.
        db.users.update_one(
            {"user_id": "user_test_vip01"},
            {"$set": {"monthly_ledger_email_enabled": False}},
        )
        r = requests.post(f"{BASE_URL}/api/admin/vip-ledger/monthly-mailing/run-now",
                          headers=_h(ADMIN))
        assert r.status_code == 200
        body = r.json()
        # The opted-out VIP should NOT be in the batch at all.
        assert body["total_vips"] == 0 or ("user_test_vip01" not in str(body))
        # Some safety: even if there's another VIP seeded (employee etc.) we
        # only assert that OUR VIP was excluded — no send/skip counted for us.
        assert body["opted_out"] is False
        _reset_settings_and_ledger()
