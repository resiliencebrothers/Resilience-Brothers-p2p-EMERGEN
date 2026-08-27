"""iter207 — Ubicación en vivo (ETA) + Aviso Mensajería Pendiente.

1. Solo mensajeros pueden compartir ubicación (/courier/location).
2. Coordenadas inválidas → 400.
3. La ubicación se refleja solo en trabajos activos del mensajero.
4. /vip/deliveries/track expone mensajero (nombre + teléfono), su ubicación
   y el cronograma (timeline) de estados.
5. Retiro cash sin coords (manual_review) dispara la alerta a admins.
"""
import os
import subprocess
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN, make_vip_totp

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
EMP_ID = "user_test_employee01"
HAVANA = {"lat": 23.1136, "lon": -82.3666}


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_delivery(status="accepted", courier_id=None, user_id=VIP_ID,
                   with_location=False):
    did = f"test207_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": did, "kind": "withdrawal", "ref_id": f"ref_{did}",
        "user_id": user_id, "client_name": "Cliente Test",
        "address": "Calle 23, Vedado", "province": "La Habana",
        "amount_label": "100 CUP", "delivery_latitude": 23.1395,
        "delivery_longitude": -82.3825, "km": 3.2, "fee_usdt": 4.0,
        "share_pct_snapshot": 80.0, "courier_share_usdt": 3.2,
        "platform_share_usdt": 0.8, "status": status,
        "courier_id": courier_id, "courier_name": "Mensajero Test" if courier_id else None,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None,
        "created_at": "2026-08-12T10:00:00+00:00",
        "updated_at": "2026-08-12T10:05:00+00:00",
        "timeline": [
            {"status": "available", "at": "2026-08-12T10:00:00+00:00", "by": None},
            {"status": "accepted", "at": "2026-08-12T10:05:00+00:00", "by": courier_id},
        ],
    }
    if with_location:
        doc["courier_location"] = {"lat": HAVANA["lat"], "lon": HAVANA["lon"],
                                   "updated_at": "2026-08-12T10:06:00+00:00"}
    _db().deliveries.insert_one(doc)
    return did


def _cleanup(*dids):
    _db().deliveries.delete_many({"id": {"$in": list(dids)}})


def test_location_requires_courier_role():
    db = _db()
    db.users.update_one({"user_id": "user_test_normal01"},
                        {"$set": {"is_courier": False}})
    r = requests.post(f"{API}/courier/location", headers=_hdr(NORMAL_TOKEN),
                      json=HAVANA)
    assert r.status_code == 403, r.text


def test_location_invalid_coords():
    r = requests.post(f"{API}/courier/location", headers=_hdr(VIP_TOKEN),
                      json={"lat": 999, "lon": 0})
    assert r.status_code == 400, r.text
    r = requests.post(f"{API}/courier/location", headers=_hdr(VIP_TOKEN),
                      json={"lat": "abc", "lon": None})
    assert r.status_code == 400, r.text


def test_location_updates_only_active_jobs():
    active = _seed_delivery(status="on_the_way", courier_id=VIP_ID)
    done = _seed_delivery(status="delivered", courier_id=VIP_ID)
    try:
        r = requests.post(f"{API}/courier/location", headers=_hdr(VIP_TOKEN),
                          json=HAVANA)
        assert r.status_code == 200, r.text
        assert r.json()["updated"] >= 1
        db = _db()
        a = db.deliveries.find_one({"id": active})
        d = db.deliveries.find_one({"id": done})
        assert a.get("courier_location", {}).get("lat") == HAVANA["lat"]
        assert "courier_location" not in (d or {})
    finally:
        _cleanup(active, done)


def test_track_returns_courier_phone_location_and_timeline():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {"phone": "+5355512399"}})
    did = _seed_delivery(status="on_the_way", courier_id=EMP_ID,
                         with_location=True)
    try:
        r = requests.get(f"{API}/vip/deliveries/track", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200, r.text
        items = [i for i in r.json()["items"] if i["id"] == did]
        assert items, "la entrega sembrada no aparece en el tracking"
        it = items[0]
        assert it["status"] == "on_the_way"
        assert it["courier"]["name"] == "Mensajero Test"
        assert it["courier"]["phone"] == "+5355512399"
        assert it["courier"]["location"]["lat"] == HAVANA["lat"]
        assert it["delivery_latitude"] == 23.1395
        statuses = [e["status"] for e in it["timeline"]]
        assert statuses == ["available", "accepted"]
        assert all("at" in e for e in it["timeline"])
    finally:
        _cleanup(did)


def test_track_only_own_deliveries():
    other = _seed_delivery(status="accepted", courier_id=EMP_ID,
                           user_id="user_test_normal01")
    try:
        r = requests.get(f"{API}/vip/deliveries/track", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 200
        assert other not in [i["id"] for i in r.json()["items"]]
    finally:
        _cleanup(other)


def test_manual_review_withdrawal_alerts_admins():
    db = _db()
    db.users.update_one({"user_id": VIP_ID}, {"$set": {"vip_balances.CUP": 500}})
    body = {
        "amount_usd": 100.0, "currency": "CUP", "method": "cash",
        "cash_delivery_mode": "courier", "province": "La Habana",
        "details": ("Provincia: La Habana\nNombre: Iter207 Test\n"
                    "Celular: 5355512345\nDirección: dirección inexistente xyz"),
        "totp_code": make_vip_totp(),
    }
    r = requests.post(f"{API}/vip/withdraw", headers=_hdr(VIP_TOKEN), json=body)
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    try:
        w = db.withdrawals.find_one({"id": wid})
        assert w["courier_fee_status"] == "manual_review"
        out = subprocess.run(
            ["bash", "-c",
             f"grep -h 'manual_review admin alert sent for withdrawal {wid}' "
             "/var/log/supervisor/backend.*.log | tail -1"],
            capture_output=True, text=True)
        assert wid in out.stdout, "la alerta a admins no se registró en el log"
    finally:
        db.withdrawals.delete_one({"id": wid})
        db.deliveries.delete_many({"ref_id": wid})
        db.users.update_one({"user_id": VIP_ID},
                            {"$set": {"vip_balances.CUP": 0}})
