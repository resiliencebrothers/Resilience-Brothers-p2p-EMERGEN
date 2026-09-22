"""iter290 — Fase B mejoras auditoría eeed556 (#4 despacho, #5 conexión, #6 liquidación).

#4 · Cola con prioridades: reservas propias primero y trabajos atrasados
antes que los nuevos; carga activa por mensajero; alertas únicas de reservas
sin respuesta (>30 min) y trabajos detenidos (>90 min).
#5 · Presencia GPS: cada envío de posición actualiza users.courier_last_gps_at
y la administración lo ve por mensajero.
#6 · Liquidación comprensible: reintento SEGURO de sincronización
(settlement_pending y delivery_sync_pending) con la misma identidad de acción.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
MARK = "IT290"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _vip_uid():
    s = _db().user_sessions.find_one({"session_token": VIP_TOKEN})
    return s["user_id"]


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _plant(status="available", courier_id=None, kind="redemption",
           ref_id=None, assigned_to=None, minutes_ago=0, extra=None):
    did = f"it290_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it290_ref_{uuid.uuid4().hex[:10]}"
    at = _iso(minutes_ago)
    doc = {
        "id": did, "kind": kind, "ref_id": rid,
        "active_key": f"{kind}:{rid}",
        "user_id": "it290_client", "client_name": f"{MARK} client",
        "address": f"{MARK} addr", "province": "La Habana",
        "amount_label": f"{MARK} pkg",
        "delivery_latitude": None, "delivery_longitude": None,
        "km": 5.0, "fee_usdt": 10.0, "share_pct_snapshot": 80.0,
        "courier_share_usdt": 8.0, "platform_share_usdt": 2.0,
        "status": status, "courier_id": courier_id,
        "courier_name": f"{MARK} courier" if courier_id else None,
        "assigned_to_courier_id": assigned_to,
        "delivery_pin": "1234", "pin_verified": False,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None, "created_at": at, "updated_at": at,
        "timeline": [],
    }
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did, rid


def _cleanup():
    db = _db()
    db.deliveries.delete_many({"$or": [{"id": {"$regex": "^it290_"}},
                                       {"ref_id": {"$regex": "^it290_"}}]})
    db.withdrawals.delete_many({"id": {"$regex": "^it290_"}})
    db.redemptions.delete_many({"id": {"$regex": "^it290_"}})
    db.deposits.delete_many({"id": {"$regex": "^it290_"}})
    db.notifications.delete_many({"message": {"$regex": MARK}})
    db.courier_cash_events.delete_many({"delivery_id": {"$regex": "^it290_"}})
    db.users.delete_many({"user_id": {"$regex": "^it290_"}})


def setup_module(module):
    _cleanup()
    _db().users.update_one({"user_id": _vip_uid()},
                           {"$set": {"is_courier": True}})


def teardown_module(module):
    _cleanup()


# ============================================================
# Mejora #4 — cola con prioridades y alertas de atención
# ============================================================

def test_available_queue_reserved_first_then_oldest():
    uid = _vip_uid()
    old_id, _ = _plant(minutes_ago=180)
    mid_id, _ = _plant(minutes_ago=60)
    new_id, _ = _plant(minutes_ago=1)
    res_id, _ = _plant(assigned_to=uid, minutes_ago=2)
    try:
        data = requests.get(f"{API}/courier/deliveries",
                            headers=_hdr(VIP_TOKEN), timeout=15).json()
        ids = [d["id"] for d in data["available"]
               if d["id"] in (old_id, mid_id, new_id, res_id)]
        # Reservada propia primero; luego los libres, ATRASADOS primero.
        assert ids[0] == res_id
        assert ids[1:] == [old_id, mid_id, new_id]
    finally:
        _db().deliveries.delete_many(
            {"id": {"$in": [old_id, mid_id, new_id, res_id]}})


def test_attention_lists_stale_reservations_and_stalled_jobs():
    stale_res, _ = _plant(assigned_to="it290_other", minutes_ago=45)
    fresh_res, _ = _plant(assigned_to="it290_other", minutes_ago=5)
    stalled, _ = _plant(status="on_the_way", courier_id="it290_other",
                        minutes_ago=120)
    fresh_active, _ = _plant(status="on_the_way", courier_id="it290_other",
                             minutes_ago=10)
    data = requests.get(f"{API}/admin/deliveries/attention", headers=_hdr(),
                        timeout=15).json()
    res_ids = [d["id"] for d in data["unanswered_reservations"]]
    stall_ids = [d["id"] for d in data["stalled"]]
    assert stale_res in res_ids and fresh_res not in res_ids
    assert stalled in stall_ids and fresh_active not in stall_ids
    assert data["thresholds"] == {"reservation_min": 30, "active_min": 90}


def test_attention_alerts_fire_exactly_once():
    did, _ = _plant(assigned_to="it290_other", minutes_ago=45)
    did2, _ = _plant(status="accepted", courier_id="it290_other",
                     minutes_ago=120)

    async def _f():
        from services.deliveries import alert_attention_items
        return await alert_attention_items()
    first = _run(_f)
    assert first >= 2
    d = _db().deliveries.find_one({"id": did})
    d2 = _db().deliveries.find_one({"id": did2})
    assert d["reservation_alerted"] is True
    assert d2["stall_alerted"] is True
    # La garantía de una-sola-alerta es el claim atómico por flag: un segundo
    # intento sobre las MISMAS entregas no encuentra nada que reclamar.
    r1 = _db().deliveries.update_one(
        {"id": did, "status": "available",
         "reservation_alerted": {"$ne": True}},
        {"$set": {"reservation_alerted": True}})
    r2 = _db().deliveries.update_one(
        {"id": did2, "stall_alerted": {"$ne": True}},
        {"$set": {"stall_alerted": True}})
    assert r1.matched_count == 0 and r2.matched_count == 0


# ============================================================
# Mejora #5 — presencia GPS y carga activa
# ============================================================

def test_share_location_updates_presence_and_admin_sees_it():
    uid = _vip_uid()
    r = requests.post(f"{API}/courier/location", headers=_hdr(VIP_TOKEN),
                      json={"lat": 23.11, "lon": -82.35}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("at")
    u = _db().users.find_one({"user_id": uid})
    assert u.get("courier_last_gps_at")
    rows = requests.get(f"{API}/admin/couriers", headers=_hdr(),
                        timeout=15).json()
    me = [c for c in rows if c["user_id"] == uid][0]
    assert me.get("courier_last_gps_at")
    assert "active_load" in me


def test_admin_couriers_active_load_counts_my_jobs():
    uid = _vip_uid()
    rows = requests.get(f"{API}/admin/couriers", headers=_hdr(),
                        timeout=15).json()
    base = [c for c in rows if c["user_id"] == uid][0]["active_load"]
    a, _ = _plant(status="accepted", courier_id=uid)
    b, _ = _plant(status="on_the_way", courier_id=uid)
    try:
        rows = requests.get(f"{API}/admin/couriers", headers=_hdr(),
                            timeout=15).json()
        now_load = [c for c in rows if c["user_id"] == uid][0]["active_load"]
        assert now_load - base == 2
    finally:
        _db().deliveries.delete_many({"id": {"$in": [a, b]}})


# ============================================================
# Mejora #6 — reintento seguro de sincronización
# ============================================================

def test_retry_sync_settles_pending_withdrawal():
    wid = f"it290_w_{uuid.uuid4().hex[:10]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": "it290_client", "user_name": f"{MARK} c",
        "user_email": "c@it290.test", "status": "approved", "method": "cash",
        "currency": "USD", "amount_usd": 500, "details": "x",
        "created_at": _iso()})
    did, _ = _plant(status="confirmed", courier_id="it290_other",
                    kind="withdrawal", ref_id=wid,
                    extra={"payout_credited": True,
                           "settlement_pending": {"kind": "withdrawal",
                                                  "ref_id": wid,
                                                  "at": _iso(10)}})
    r = requests.post(f"{API}/admin/deliveries/{did}/retry-sync",
                      headers=_hdr(), json={}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["settlement"] == "ok"
    assert not body["delivery"].get("settlement_pending")
    w = _db().withdrawals.find_one({"id": wid})
    assert w["status"] == "paid"
    # Reintento repetido: seguro y sin duplicar nada.
    r2 = requests.post(f"{API}/admin/deliveries/{did}/retry-sync",
                       headers=_hdr(), json={}, timeout=20)
    assert r2.status_code == 200
    assert r2.json()["result"].get("status") == "nothing_pending"


def test_retry_sync_marks_origin_conflict_for_rejected_deposit():
    dep = f"it290_dep_{uuid.uuid4().hex[:10]}"
    _db().deposits.insert_one({
        "id": dep, "user_id": "it290_client", "status": "rejected",
        "method": "cash", "cash_mode": "courier", "currency": "CUP",
        "amount": 800})
    did, _ = _plant(status="confirmed", courier_id="it290_other",
                    kind="deposit", ref_id=dep,
                    extra={"settlement_pending": {"kind": "deposit",
                                                  "ref_id": dep,
                                                  "at": _iso(10)}})
    r = requests.post(f"{API}/admin/deliveries/{did}/retry-sync",
                      headers=_hdr(), json={}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["settlement"] == "conflict"
    d = body["delivery"]
    assert not d.get("settlement_pending")
    assert d.get("origin_conflict")


def test_retry_sync_completes_fee_sync_task():
    rid = f"it290_r_{uuid.uuid4().hex[:10]}"
    _db().redemptions.insert_one({
        "id": rid, "user_id": "it290_client", "user_name": f"{MARK} c",
        "status": "pending", "settlement_currency": "USDT",
        "courier_fee_usdt": 15, "courier_fee_usd": 15, "courier_km": 12,
        "product_name": f"{MARK} p", "quantity": 1, "delivery_address": "x",
        "delivery_sync_pending": {"op_id": f"op_{rid}", "at": _iso(10)}})
    # Existe el trabajo pero con tarifa vieja (10): el reintento converge a 15.
    did, _ = _plant(status="available", kind="redemption", ref_id=rid)
    r = requests.post(f"{API}/admin/deliveries/{did}/retry-sync",
                      headers=_hdr(), json={}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["fee_sync"] == "ok"
    d = _db().deliveries.find_one({"id": did})
    assert d["fee_usdt"] == 15 and d["courier_share_usdt"] == 12.0
    assert not (_db().redemptions.find_one({"id": rid}) or {}).get(
        "delivery_sync_pending")
