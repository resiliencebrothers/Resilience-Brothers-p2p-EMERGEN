"""iter199 — courier panel (Fase 2): delivery jobs, states and 80/20 split.

Flow under test:
1. admin toggles is_courier on the VIP test user
2. charging a withdrawal courier fee auto-creates a delivery (80/20 split)
3. courier claims it (double claim → 409) and walks the state machine
4. wrong transitions are rejected
5. admin confirms → 80% credited to courier USDT balance (idempotent)
6. annulling the fee cancels the delivery
7. admin can assign directly and create manual (free) deliveries
"""
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _set_settings():
    _db().settings.update_one({"id": "global"}, {"$set": {
        "courier_rate_usdt_per_km": 0.5, "courier_min_fee_usdt": 2.0,
        "courier_free_min_usdt": 1000.0, "courier_share_pct": 80.0,
    }}, upsert=True)


def _mk_cash_withdrawal(amount=10000, currency="CUP"):
    wid = f"w_{uuid.uuid4().hex[:12]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": "VIP Test", "amount_usd": amount, "currency": currency,
        "method": "cash", "details": "Receptor Prueba, Calle 23, Vedado",
        "status": "pending", "province": "La Habana",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    return wid


def _charge_fee(wid, km=8):
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": km}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    return r.json()


def _delivery_for(wid):
    return _db().deliveries.find_one(
        {"kind": "withdrawal", "ref_id": wid, "status": {"$ne": "cancelled"}},
        {"_id": 0})


def _vip_usdt():
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0, "vip_balances": 1})
    return float((u.get("vip_balances") or {}).get("USDT") or 0.0)


def _cleanup(wid, delivery_id=None):
    _db().withdrawals.delete_one({"id": wid})
    if delivery_id:
        _db().deliveries.delete_one({"id": delivery_id})


def _seed_cup(amount=10000.0):
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.CUP": amount}})


def _unseed_cup(amount=10000.0):
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.CUP": -amount}})


def test_toggle_is_courier():
    r = requests.put(f"{API}/admin/users/{VIP_ID}",
                     json=with_totp_admin({"is_courier": True}),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["is_courier"] is True
    couriers = requests.get(f"{API}/admin/couriers", headers=_hdr(ADMIN_TOKEN)).json()
    assert any(c["user_id"] == VIP_ID for c in couriers)


def test_charge_creates_delivery_with_split():
    _set_settings()
    _seed_cup()
    wid = _mk_cash_withdrawal()
    _charge_fee(wid, km=8)  # fee 4 USDT
    d = _delivery_for(wid)
    assert d, "delivery not auto-created"
    assert d["status"] == "available"
    assert d["fee_usdt"] == 4.0
    assert d["courier_share_usdt"] == 3.2   # 80%
    assert d["platform_share_usdt"] == 0.8  # 20%
    assert d["share_pct_snapshot"] == 80.0
    # annul → cancelled
    _charge_fee(wid, km=0)
    assert _delivery_for(wid) is None
    _cleanup(wid, d["id"])
    _unseed_cup()


def test_full_courier_lifecycle_and_payout():
    _set_settings()
    _seed_cup()
    wid = _mk_cash_withdrawal()
    _charge_fee(wid, km=10)  # fee 5 USDT → share 4.0
    d = _delivery_for(wid)

    # courier sees it as available
    lst = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN)).json()
    assert any(x["id"] == d["id"] for x in lst["available"])

    # claim (race-safe: second claim conflicts)
    r = requests.post(f"{API}/courier/deliveries/{d['id']}/claim",
                      headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    r2 = requests.post(f"{API}/courier/deliveries/{d['id']}/claim",
                       headers=_hdr(VIP_TOKEN))
    assert r2.status_code == 409

    # invalid jump accepted → delivered
    bad = requests.post(f"{API}/courier/deliveries/{d['id']}/status",
                        json={"status": "delivered"}, headers=_hdr(VIP_TOKEN))
    assert bad.status_code == 400

    for step in ("on_the_way", "arrived", "delivered"):
        r = requests.post(f"{API}/courier/deliveries/{d['id']}/status",
                          json={"status": step}, headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text

    # earnings show it pending
    lst = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN)).json()
    assert lst["earnings"]["pending_usdt"] == 4.0

    # admin confirms → 80% credited (TOTP)
    bal0 = _vip_usdt()
    r = requests.post(f"{API}/admin/deliveries/{d['id']}/confirm",
                      json=with_totp_admin({}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["payout_credited"] is True
    assert round(_vip_usdt() - bal0, 2) == 4.0

    # idempotent: re-confirm rejected, no double credit
    r = requests.post(f"{API}/admin/deliveries/{d['id']}/confirm",
                      json=with_totp_admin({}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 409
    assert round(_vip_usdt() - bal0, 2) == 4.0

    # cleanup: remove credited USDT + return the client fee + docs
    w_doc = _db().withdrawals.find_one({"id": wid}, {"_id": 0}) or {}
    fee_cur = float(w_doc.get("courier_fee_currency_amount") or 0.0)
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": -4.0,
                                     "vip_balances.CUP": fee_cur}})
    _cleanup(wid, d["id"])
    _unseed_cup()


def test_admin_assign_direct():
    _set_settings()
    _seed_cup()
    wid = _mk_cash_withdrawal()
    _charge_fee(wid, km=8)
    d = _delivery_for(wid)
    r = requests.post(f"{API}/admin/deliveries/{d['id']}/assign",
                      json={"courier_id": VIP_ID}, headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    # iter208 — assign ahora RESERVA (status sigue available hasta que el
    # mensajero acepte desde su panel).
    assert r.json()["status"] == "available"
    assert r.json()["assigned_to_courier_id"] == VIP_ID
    # refund fee before cleanup
    _charge_fee(wid, km=0)
    _cleanup(wid, d["id"])
    _db().deliveries.delete_many({"ref_id": wid})
    _unseed_cup()


def test_manual_delivery_for_free_withdrawal():
    _set_settings()
    wid = _mk_cash_withdrawal(amount=500000, currency="CUP")  # free (≥1000 USDT)
    r = requests.post(f"{API}/admin/deliveries",
                      json={"kind": "withdrawal", "ref_id": wid},
                      headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fee_usdt"] == 0.0
    assert d["courier_share_usdt"] == 0.0
    assert d["status"] == "available"
    # duplicate → 409
    r2 = requests.post(f"{API}/admin/deliveries",
                       json={"kind": "withdrawal", "ref_id": wid},
                       headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 409
    # cancel works
    r3 = requests.post(f"{API}/admin/deliveries/{d['id']}/cancel", json={},
                       headers=_hdr(ADMIN_TOKEN))
    assert r3.status_code == 200
    _cleanup(wid, d["id"])


def test_non_courier_user_blocked():
    # normal test user is not a courier
    r = requests.get(f"{API}/courier/deliveries",
                     headers={"Authorization": "Bearer test_session_normal_X"})
    assert r.status_code in (401, 403)


def test_remove_courier_flag():
    r = requests.put(f"{API}/admin/users/{VIP_ID}",
                     json=with_totp_admin({"is_courier": False}),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    # VIP loses access
    r2 = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN))
    assert r2.status_code == 403
    # restore for future iterations
    requests.put(f"{API}/admin/users/{VIP_ID}",
                 json=with_totp_admin({"is_courier": True}),
                 headers=_hdr(ADMIN_TOKEN))
