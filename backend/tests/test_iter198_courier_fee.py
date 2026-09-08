"""iter198 — courier fee per km (cash withdrawals + marketplace deliveries).

Business rules (operator PDF):
- fee = MAX(min_fee 2 USDT, km × 0.50 USDT)      [configurable]
- FREE when the operation's USDT equivalent ≥ 1000 [configurable]
- Charged SEPARATELY from the amount, refunded on rejection/cancellation.
- Tariff snapshot stored on every charge.
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_courier_settings(rate=0.5, min_fee=2.0, free_min=1000.0):
    _db().settings.update_one({"id": "global"}, {"$set": {
        "courier_rate_usdt_per_km": rate,
        "courier_min_fee_usdt": min_fee,
        "courier_free_min_usdt": free_min,
    }}, upsert=True)


def _vip_balance(code):
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0, "vip_balances": 1,
                                                   "vip_balance_usd": 1})
    bal = float((u.get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        bal += float(u.get("vip_balance_usd") or 0.0)
    return bal


def _mk_cash_withdrawal(amount=10000, currency="CUP"):
    wid = f"w_{uuid.uuid4().hex[:12]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": "VIP Test", "amount_usd": amount, "currency": currency,
        "method": "cash", "details": "Receptor Prueba 12345678 +5355555555 dir",
        "status": "pending", "province": "La Habana",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    return wid


def _mk_product(price_usd=50.0, stock=10):
    pid = f"prod_{uuid.uuid4().hex[:10]}"
    _db().products.insert_one({
        "id": pid, "name": f"Producto Test {pid[-4:]}", "description": "t",
        "category": "test", "price_usd": price_usd, "cost_usd": 0.0,
        "stock": stock, "image_url": "", "created_at": _now_iso(),
    })
    return pid


# ------------------------------------------------------------------
# Pricing engine (pure)
# ------------------------------------------------------------------

def test_compute_fee_formula():
    from services.courier_fee import compute_fee_usdt
    # Mandatory PDF cases (rate 0.5, min 2.0)
    assert compute_fee_usdt(1, 0.5, 2.0) == 2.00     # below min → min
    assert compute_fee_usdt(4, 0.5, 2.0) == 2.00     # exactly covered by min
    assert compute_fee_usdt(8, 0.5, 2.0) == 4.00     # 8 × 0.50 = 4.00
    assert compute_fee_usdt(20, 0.5, 2.0) == 10.00
    assert compute_fee_usdt(7.36, 0.5, 2.0) == 3.68  # no km rounding
    assert compute_fee_usdt(0, 0.5, 2.0) == 0.0      # 0 km = no charge
    assert compute_fee_usdt(5, 0.0, 2.0) == 0.0      # tariff 0 = disabled


# ------------------------------------------------------------------
# Quote endpoint
# ------------------------------------------------------------------

def test_quote_endpoint_includes_min_fee_and_free_flag():
    _set_courier_settings()
    r = requests.get(f"{API}/vip/courier-fee-quote",
                     params={"currency": "CUP", "amount": 10000},
                     headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["rate_usdt_per_km"] == 0.5
    assert q["min_fee_usdt"] == 2.0
    assert q["free_min_usdt"] == 1000.0
    assert q["enabled"] is True
    assert q["free"] is False  # 10000 CUP ≈ 25 USDT < 1000

    r2 = requests.get(f"{API}/vip/courier-fee-quote",
                      params={"currency": "CUP", "amount": 500000},
                      headers=_hdr(VIP_TOKEN))
    assert r2.json()["free"] is True  # 500000 CUP ≈ 1265 USDT ≥ 1000


# ------------------------------------------------------------------
# Withdrawal charge: MAX formula + snapshot + refund on rejection
# ------------------------------------------------------------------

def test_withdrawal_min_fee_applies():
    _set_courier_settings()
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.CUP": 5000.0}})
    wid = _mk_cash_withdrawal()
    bal0 = _vip_balance("CUP")
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": 1}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["courier_fee_usdt"] == 2.00  # min fee, not 0.50
    assert w["courier_rate_snapshot"] == 0.5
    assert w["courier_min_fee_snapshot"] == 2.0
    assert w["courier_fee_currency_amount"] > 0
    assert round(bal0 - _vip_balance("CUP"), 2) == w["courier_fee_currency_amount"]
    # annul → full refund
    r2 = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                       json=with_totp_admin({"km": 0}), headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200, r2.text
    assert r2.json()["courier_fee_usdt"] == 0.0
    assert round(_vip_balance("CUP") - bal0, 2) == 0.0
    _db().withdrawals.delete_one({"id": wid})
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.CUP": -5000.0}})


def test_withdrawal_fee_above_min():
    _set_courier_settings()
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.CUP": 5000.0}})
    wid = _mk_cash_withdrawal()
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": 8}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["courier_fee_usdt"] == 4.00
    # cleanup: annul + delete
    requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                  json=with_totp_admin({"km": 0}), headers=_hdr(ADMIN_TOKEN))
    _db().withdrawals.delete_one({"id": wid})
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.CUP": -5000.0}})


def test_withdrawal_free_threshold_blocks_charge():
    _set_courier_settings()
    wid = _mk_cash_withdrawal(amount=500000, currency="CUP")  # ≈1265 USDT
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": 5}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 400, r.text
    assert "GRATIS" in r.json()["detail"]
    _db().withdrawals.delete_one({"id": wid})


def test_withdrawal_rejection_refunds_fee_too():
    _set_courier_settings()
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.CUP": 5000.0}})
    wid = _mk_cash_withdrawal(amount=1000, currency="CUP")
    bal0 = _vip_balance("CUP")
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": 8}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    fee_cur = r.json()["courier_fee_currency_amount"]
    assert round(bal0 - _vip_balance("CUP"), 2) == fee_cur
    r2 = requests.put(f"{API}/admin/withdrawals/{wid}/status",
                      json=with_totp_admin({"status": "rejected",
                                            "admin_note": "test iter198"}),
                      headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200, r2.text
    # amount (1000) + fee refunded
    assert round(_vip_balance("CUP") - bal0, 2) == 1000.0
    _db().withdrawals.delete_one({"id": wid})
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.CUP": -6000.0}})


def test_non_cash_withdrawal_rejects_courier_fee():
    _set_courier_settings()
    wid = f"w_{uuid.uuid4().hex[:12]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": VIP_ID, "user_email": "vip@test",
        "user_name": "VIP Test", "amount_usd": 100, "currency": "USDT",
        "method": "crypto", "details": "TXYZ...", "status": "pending",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    r = requests.post(f"{API}/admin/withdrawals/{wid}/courier-fee",
                      json=with_totp_admin({"km": 5}), headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 400
    _db().withdrawals.delete_one({"id": wid})


# ------------------------------------------------------------------
# Marketplace redemptions
# ------------------------------------------------------------------

def test_redemption_without_coords_is_manual_review():
    _set_courier_settings()
    pid = _mk_product(price_usd=50.0)
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.USDT": 100.0}})
    bal0 = _vip_balance("USDT")
    # iter211 — la dirección NO debe contener un municipio conocido: si lo
    # contiene (ej. "Vedado") ahora se cobra la tarifa fija automáticamente.
    r = requests.post(f"{API}/vip/redeem",
                      json={"product_id": pid, "quantity": 1,
                            "delivery_address": "Calle sin nombre #456, reparto perdido"},
                      headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    red = r.json()
    assert red["courier_fee_status"] == "manual_review"
    assert red["courier_fee_usd"] == 0.0
    assert red["courier_rate_snapshot"] == 0.5
    assert round(bal0 - _vip_balance("USDT"), 2) == 50.0  # only the product

    # staff sets 8 km manually → MAX(2, 8×0.5) = 4 USDT
    r2 = requests.post(f"{API}/admin/redemptions/{red['id']}/courier-fee",
                       json=with_totp_admin({"km": 8}), headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 200, r2.text
    upd = r2.json()
    assert upd["courier_fee_usdt"] == 4.00
    assert upd["courier_fee_usd"] > 0
    assert upd["courier_fee_status"] == "charged"
    assert round(bal0 - _vip_balance("USDT"), 2) == round(50.0 + upd["courier_fee_usd"], 2)

    # rejection refunds product + courier fee and restores stock
    r3 = requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                      json={"status": "rejected", "admin_note": "test"},
                      headers=_hdr(ADMIN_TOKEN))
    assert r3.status_code == 200, r3.text
    assert round(_vip_balance("USDT") - bal0, 2) == 0.0
    _db().redemptions.delete_one({"id": red["id"]})
    _db().products.delete_one({"id": pid})
    _db().users.update_one({"user_id": VIP_ID}, {"$inc": {"vip_balances.USDT": -100.0}})


def test_redemption_free_threshold():
    _set_courier_settings()
    # 1200 USD ≈ 1142 USDT ≥ 1000 → free courier
    pid = _mk_product(price_usd=1200.0)
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": 1200.0}})
    r = requests.post(f"{API}/vip/redeem",
                      json={"product_id": pid, "quantity": 1,
                            "delivery_address": "Calle 23 #456, Vedado"},
                      headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200, r.text
    red = r.json()
    assert red["courier_fee_status"] == "free"
    # admin can't charge a free delivery
    r2 = requests.post(f"{API}/admin/redemptions/{red['id']}/courier-fee",
                       json=with_totp_admin({"km": 8}), headers=_hdr(ADMIN_TOKEN))
    assert r2.status_code == 400
    # cleanup: reject (refunds 1200) then remove the extra credit
    requests.put(f"{API}/admin/redemptions/{red['id']}/status",
                 json={"status": "rejected"}, headers=_hdr(ADMIN_TOKEN))
    _db().users.update_one({"user_id": VIP_ID},
                           {"$inc": {"vip_balances.USDT": -1200.0}})
    _db().redemptions.delete_one({"id": red["id"]})
    _db().products.delete_one({"id": pid})


# ------------------------------------------------------------------
# Settings + geo endpoints
# ------------------------------------------------------------------

def test_settings_roundtrip_courier_fields():
    r = requests.put(f"{API}/admin/settings",
                     json=with_totp_admin({
                         "courier_rate_usdt_per_km": 0.6,
                         "courier_min_fee_usdt": 2.5,
                         "courier_free_min_usdt": 900,
                         "office_latitude": 23.1136,
                         "office_longitude": -82.3666,
                     }),
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    g = requests.get(f"{API}/admin/settings", headers=_hdr(ADMIN_TOKEN)).json()
    assert g["courier_rate_usdt_per_km"] == 0.6
    assert g["courier_min_fee_usdt"] == 2.5
    assert g["courier_free_min_usdt"] == 900
    assert g["office_latitude"] == 23.1136
    assert g["office_longitude"] == -82.3666
    _set_courier_settings()  # restore defaults


def test_geo_search_returns_shape():
    r = requests.get(f"{API}/vip/geo-search", params={"q": "La Habana"},
                     headers=_hdr(VIP_TOKEN), timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    for row in body["results"]:
        assert {"display_name", "lat", "lon"} <= set(row.keys())


def test_route_quote_manual_review_when_office_missing():
    _db().settings.update_one({"id": "global"}, {"$unset": {
        "office_latitude": "", "office_longitude": ""}})
    try:
        r = requests.get(f"{API}/vip/courier-route-quote",
                         params={"lat": 23.1, "lon": -82.4,
                                 "currency": "CUP", "amount": 10000},
                         headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        q = r.json()
        assert q["requires_manual_review"] is True
        assert q["reason"] == "office_not_configured"
    finally:
        # iter212 — restaurar la oficina para no contaminar otros tests
        # (test_iter205 crea retiros con coords y espera cobro por km).
        _db().settings.update_one({"id": "global"}, {"$set": {
            "office_latitude": 23.1136, "office_longitude": -82.3666}})
