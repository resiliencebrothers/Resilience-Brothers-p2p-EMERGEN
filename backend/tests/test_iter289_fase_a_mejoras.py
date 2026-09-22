"""iter289 — Fase A mejoras auditoría eeed556 (#1 efectivo, #2 PIN, #3 incidencias).

#2 PIN · Se genera al crear el reparto; SOLO lo ve el cliente (seguimiento);
el mensajero lo introduce para marcar «Entregado» o registra una excepción
con motivo que queda marcada para revisión.
#3 Incidencias · El mensajero reporta tipo+nota(+próximo intento) sobre SU
entrega activa; el operador resuelve con nota; el flag has_open_incident
se limpia al no quedar abiertas.
#1 Efectivo · Ledger courier_cash_events: issued/returned manuales del admin,
collected/delivered_to_recipient automáticos e idempotentes al entregar;
pendiente = issued+collected − delivered − returned.
"""
import asyncio
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
MARK = "IT289"


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
    assert s, "sesión VIP de pruebas no sembrada"
    return s["user_id"]


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _plant_delivery(status="arrived", courier_id=None, kind="redemption",
                    ref_id=None, pin="5678", user_id=None, extra=None):
    did = f"it289_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it289_ref_{uuid.uuid4().hex[:10]}"
    now = _now()
    doc = {
        "id": did, "kind": kind, "ref_id": rid,
        "active_key": f"{kind}:{rid}",
        "user_id": user_id or "it289_client", "client_name": f"{MARK} client",
        "address": f"{MARK} addr", "province": None,
        "amount_label": f"{MARK} pkg",
        "delivery_latitude": None, "delivery_longitude": None,
        "km": 5.0, "fee_usdt": 10.0, "share_pct_snapshot": 80.0,
        "courier_share_usdt": 8.0, "platform_share_usdt": 2.0,
        "status": status, "courier_id": courier_id,
        "courier_name": f"{MARK} courier" if courier_id else None,
        "delivery_pin": pin, "pin_verified": False,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None, "created_at": now, "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": None}],
    }
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did, rid


def _cleanup():
    db = _db()
    uid = _vip_uid()
    db.deliveries.delete_many({"id": {"$regex": "^it289_"}})
    db.deliveries.delete_many({"ref_id": {"$regex": "^it289_"}})
    db.redemptions.delete_many({"id": {"$regex": "^it289_"}})
    db.withdrawals.delete_many({"id": {"$regex": "^it289_"}})
    db.deposits.delete_many({"id": {"$regex": "^it289_"}})
    db.courier_cash_events.delete_many(
        {"$or": [{"courier_id": {"$regex": "^it289_"}},
                 {"delivery_id": {"$regex": "^it289_"}},
                 {"note": {"$regex": MARK}},
                 {"courier_id": uid}]})
    db.users.delete_many({"user_id": {"$regex": "^it289_"}})


def setup_module(module):
    _cleanup()
    _db().users.update_one({"user_id": _vip_uid()},
                           {"$set": {"is_courier": True}})
    _db().users.update_one({"user_id": "it289_courier_b"}, {"$set": {
        "user_id": "it289_courier_b", "email": "b@it289.test",
        "name": f"{MARK} B", "role": "vip", "is_courier": True,
        "account_status": "active"}}, upsert=True)


def teardown_module(module):
    _cleanup()


# ============================================================
# Mejora #2 — PIN de entrega
# ============================================================

def test_pin_generated_on_new_jobs():
    rid = f"it289_ref_{uuid.uuid4().hex[:10]}"
    _db().redemptions.insert_one({
        "id": rid, "user_id": "it289_client", "user_name": f"{MARK} c",
        "status": "pending", "settlement_currency": "USDT",
        "product_name": f"{MARK} p", "quantity": 1,
        "delivery_address": "x"})
    async def _f():
        from services.deliveries import ensure_delivery_job
        ref = await __import__("db_client").db.redemptions.find_one(
            {"id": rid}, {"_id": 0})
        return await ensure_delivery_job("redemption", ref, km=5, fee_usdt=10)
    doc = _run(_f)
    assert doc.get("delivery_pin") and len(doc["delivery_pin"]) == 4 \
        and doc["delivery_pin"].isdigit()
    assert doc.get("pin_verified") is False


def test_pin_hidden_from_courier_but_visible_to_client():
    uid = _vip_uid()
    did, _ = _plant_delivery(status="accepted", courier_id=uid,
                             user_id=uid, pin="4321")
    # Panel del mensajero: SIN el PIN, con pin_required.
    data = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN),
                        timeout=15).json()
    mine = [d for d in data["mine"] if d["id"] == did]
    assert mine and "delivery_pin" not in mine[0]
    assert mine[0]["pin_required"] is True
    # Seguimiento del cliente: CON el PIN.
    track = requests.get(f"{API}/vip/deliveries/track", headers=_hdr(VIP_TOKEN),
                         timeout=15).json()
    item = [x for x in track["items"] if x["id"] == did]
    assert item and item[0]["delivery_pin"] == "4321"


def test_delivered_requires_correct_pin():
    uid = _vip_uid()
    did, _ = _plant_delivery(status="arrived", courier_id=uid, pin="7913")
    # Sin PIN → 400
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered"}, timeout=15)
    assert r.status_code == 400, r.text
    # PIN incorrecto → 400 y el estado NO cambia
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered", "pin": "0000"}, timeout=15)
    assert r.status_code == 400
    assert _db().deliveries.find_one({"id": did})["status"] == "arrived"
    # PIN correcto → entregada, verificada y sin filtrar el PIN al mensajero
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered", "pin": "7913"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "delivery_pin" not in body and body["pin_required"] is False
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "delivered" and d["pin_verified"] is True


def test_delivered_pin_exception_is_recorded_and_flagged():
    uid = _vip_uid()
    did, _ = _plant_delivery(status="arrived", courier_id=uid, pin="1122")
    reason = f"{MARK} cliente sin conexión, verifiqué carnet"
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered",
                            "pin_exception_reason": reason}, timeout=15)
    assert r.status_code == 200, r.text
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "delivered"
    assert d.get("pin_verified") is not True
    assert d["pin_exception"]["reason"] == reason
    assert any("SIN PIN" in (e.get("note") or "") for e in d["timeline"])


def test_legacy_jobs_without_pin_still_deliverable():
    uid = _vip_uid()
    did, _ = _plant_delivery(status="arrived", courier_id=uid, pin=None)
    _db().deliveries.update_one({"id": did},
                                {"$unset": {"delivery_pin": ""}})
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered"}, timeout=15)
    assert r.status_code == 200, r.text


# ============================================================
# Mejora #3 — incidencias y reprogramación
# ============================================================

def test_incident_full_flow_report_and_resolve():
    uid = _vip_uid()
    did, _ = _plant_delivery(status="on_the_way", courier_id=uid)
    # tipo inválido / nota corta → 400
    r = requests.post(f"{API}/courier/deliveries/{did}/incident",
                      headers=_hdr(VIP_TOKEN),
                      json={"type": "otra_cosa", "note": "algo pasó aquí"},
                      timeout=15)
    assert r.status_code == 400
    r = requests.post(f"{API}/courier/deliveries/{did}/incident",
                      headers=_hdr(VIP_TOKEN),
                      json={"type": "importe_diferente", "note": "x"},
                      timeout=15)
    assert r.status_code == 400
    # válida → registrada, entrega marcada
    r = requests.post(f"{API}/courier/deliveries/{did}/incident",
                      headers=_hdr(VIP_TOKEN),
                      json={"type": "importe_diferente",
                            "note": f"{MARK} el cliente entrega 1400 y no 1500",
                            "next_attempt_at": "2026-09-23T10:00"},
                      timeout=15)
    assert r.status_code == 200, r.text
    d = _db().deliveries.find_one({"id": did})
    assert d["has_open_incident"] is True
    assert len(d["incidents"]) == 1
    inc = d["incidents"][0]
    assert inc["type"] == "importe_diferente" and inc["status"] == "open"
    assert inc["next_attempt_at"] == "2026-09-23T10:00"
    # el filtro del operador la encuentra
    rows = requests.get(f"{API}/admin/deliveries", headers=_hdr(),
                        params={"incident": "open"}, timeout=15).json()
    assert any(x["id"] == did for x in rows)
    # el admin resuelve con nota — flag limpio, segunda resolución 404
    r = requests.post(
        f"{API}/admin/deliveries/{did}/incidents/{inc['id']}/resolve",
        headers=_hdr(), json={"note": f"{MARK} conciliado con el cliente"},
        timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_open_incident"] is False
    assert body["incidents"][0]["status"] == "resolved"
    assert body["incidents"][0]["resolution_note"].startswith(MARK)
    r = requests.post(
        f"{API}/admin/deliveries/{did}/incidents/{inc['id']}/resolve",
        headers=_hdr(), json={}, timeout=15)
    assert r.status_code == 404


def test_incident_only_on_own_active_delivery():
    did, _ = _plant_delivery(status="on_the_way",
                             courier_id="it289_courier_b")
    r = requests.post(f"{API}/courier/deliveries/{did}/incident",
                      headers=_hdr(VIP_TOKEN),
                      json={"type": "no_responde",
                            "note": f"{MARK} intento de otro mensajero"},
                      timeout=15)
    assert r.status_code == 403
    # tampoco sobre entregas canceladas
    did2, _ = _plant_delivery(status="cancelled", courier_id=_vip_uid(),
                              extra={"active_key": None})
    _db().deliveries.update_one({"id": did2}, {"$unset": {"active_key": ""}})
    r = requests.post(f"{API}/courier/deliveries/{did2}/incident",
                      headers=_hdr(VIP_TOKEN),
                      json={"type": "no_responde", "note": f"{MARK} tarde"},
                      timeout=15)
    assert r.status_code == 409


# ============================================================
# Mejora #1 — control de efectivo por mensajero
# ============================================================

def _pending_for(courier_id, currency):
    rows = requests.get(f"{API}/admin/courier-cash/summary", headers=_hdr(),
                        timeout=15).json()["couriers"]
    m = [r for r in rows
         if r["courier_id"] == courier_id and r["currency"] == currency]
    return m[0] if m else None


def test_cash_issue_and_return_cycle():
    uid = _vip_uid()
    r = requests.post(f"{API}/admin/courier-cash", headers=_hdr(),
                      json={"courier_id": uid, "kind": "issued",
                            "currency": "cup", "amount": 3000,
                            "note": f"{MARK} salida matutina"}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "CUP"
    row = _pending_for(uid, "CUP")
    assert row and row["pending"] == 3000.0 and row["issued"] == 3000.0
    # rendición parcial con diferencia → evento marcado
    r = requests.post(f"{API}/admin/courier-cash", headers=_hdr(),
                      json={"courier_id": uid, "kind": "returned",
                            "currency": "CUP", "amount": 2900,
                            "note": f"{MARK} rendición",
                            "discrepancy_note": "faltan 100 CUP"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["discrepancy"] is True
    row = _pending_for(uid, "CUP")
    assert row["pending"] == 100.0
    # el mensajero ve su pendiente y sus eventos
    mine = requests.get(f"{API}/courier/cash", headers=_hdr(VIP_TOKEN),
                        timeout=15).json()
    cup = [p for p in mine["pending"] if p["currency"] == "CUP"]
    assert cup and cup[0]["pending"] == 100.0
    assert len(mine["events"]) >= 2
    # y el panel embebe el pendiente
    panel = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN),
                         timeout=15).json()
    assert any(c["currency"] == "CUP" and c["pending"] == 100.0
               for c in panel["cash_pending"])


def test_cash_auto_event_on_withdrawal_delivered():
    uid = _vip_uid()
    wid = f"it289_w_{uuid.uuid4().hex[:10]}"
    _db().withdrawals.insert_one({
        "id": wid, "user_id": "it289_client", "user_name": f"{MARK} c",
        "status": "approved", "method": "cash", "currency": "USD",
        "amount_usd": 1500, "details": "x"})
    did, _ = _plant_delivery(status="arrived", courier_id=uid,
                             kind="withdrawal", ref_id=wid, pin="3344")
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered", "pin": "3344"}, timeout=15)
    assert r.status_code == 200, r.text
    evs = list(_db().courier_cash_events.find({"delivery_id": did}))
    assert len(evs) == 1
    assert evs[0]["kind"] == "delivered_to_recipient"
    assert evs[0]["amount"] == 1500.0 and evs[0]["currency"] == "USD"
    # idempotencia del evento automático (reintento del mismo op_key)
    async def _f():
        from services.courier_cash import auto_events_for_delivered
        d = await __import__("db_client").db.deliveries.find_one(
            {"id": did}, {"_id": 0})
        await auto_events_for_delivered(d, uid)
    _run(_f)
    assert _db().courier_cash_events.count_documents(
        {"delivery_id": did}) == 1


def test_cash_auto_event_on_deposit_pickup_delivered():
    uid = _vip_uid()
    dep = f"it289_dep_{uuid.uuid4().hex[:10]}"
    _db().deposits.insert_one({
        "id": dep, "user_id": "it289_client", "status": "pending",
        "method": "cash", "cash_mode": "courier", "currency": "CUP",
        "amount": 2500})
    did, _ = _plant_delivery(status="arrived", courier_id=uid,
                             kind="deposit", ref_id=dep, pin="9090")
    r = requests.post(f"{API}/courier/deliveries/{did}/status",
                      headers=_hdr(VIP_TOKEN),
                      json={"status": "delivered", "pin": "9090"}, timeout=15)
    assert r.status_code == 200, r.text
    evs = list(_db().courier_cash_events.find({"delivery_id": did}))
    assert len(evs) == 1
    assert evs[0]["kind"] == "collected"
    assert evs[0]["amount"] == 2500.0 and evs[0]["currency"] == "CUP"


def test_cash_register_validation():
    uid = _vip_uid()
    for bad in ({"kind": "collected"},           # solo issued/returned manual
                {"kind": "issued", "amount": "NaN"},
                {"kind": "issued", "amount": -5},
                {"kind": "issued", "amount": 100, "currency": ""}):
        payload = {"courier_id": uid, "currency": "CUP", **bad}
        r = requests.post(f"{API}/admin/courier-cash", headers=_hdr(),
                          json=payload, timeout=15)
        assert r.status_code == 400, f"{bad}: {r.status_code} {r.text}"
    r = requests.post(f"{API}/admin/courier-cash", headers=_hdr(),
                      json={"courier_id": "no_existe_x", "kind": "issued",
                            "currency": "CUP", "amount": 10}, timeout=15)
    assert r.status_code == 404
