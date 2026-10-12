"""MEN-03 (backend) — auditoría de asignación + filtros active/history.

- Al reservar, la entrega guarda `assigned_by` / `assigned_by_name` /
  `assigned_at` (trazabilidad: quién asignó y cuándo).
- `GET /admin/deliveries?status=active` EXCLUYE completadas/canceladas.
- `GET /admin/deliveries?status=history` devuelve SOLO completadas/canceladas.
(El recorrido de UI del mensajero —secciones, botones de texto y deep-link del
aviso— lo cubre el testing_agent de frontend.)
"""
import os
import uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_delivery(status="available", **extra):
    did = f"men03_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": did, "status": status, "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN03 Cliente",
        "amount_label": "100 USDT", "address": "Calle Falsa 123",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4,
        "platform_share_usdt": 1, "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(doc)
    return did


def _ensure_vip_courier():
    _db().users.update_one({"user_id": VIP_ID}, {"$set": {"is_courier": True}})


def _list(status=None):
    params = {"status": status} if status else {}
    r = requests.get(f"{API}/admin/deliveries", headers=_hdr(ADMIN_TOKEN),
                     params=params, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def test_assign_records_assigned_by_and_at():
    _ensure_vip_courier()
    did = _mk_delivery()
    try:
        r = requests.post(f"{API}/admin/deliveries/{did}/assign",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"courier_id": VIP_ID}, timeout=15)
        assert r.status_code == 200, r.text
        doc = _db().deliveries.find_one({"id": did})
        # user_test_admin01 es el actor.
        assert doc.get("assigned_by") == "user_test_admin01"
        assert doc.get("assigned_by_name")
        assert doc.get("assigned_at")
        # Visible en el detalle del admin.
        row = [d for d in _list("assigned") if d["id"] == did][0]
        assert row.get("assigned_by_name")
        assert row.get("assigned_at")
    finally:
        _db().deliveries.delete_one({"id": did})


def test_active_filter_excludes_completed_and_cancelled():
    did_active = _mk_delivery(status="accepted", courier_id=VIP_ID,
                              courier_name="VIP Test")
    did_done = _mk_delivery(status="confirmed", courier_id=VIP_ID,
                            courier_name="VIP Test")
    did_cancel = _mk_delivery(status="cancelled")
    try:
        ids = {d["id"] for d in _list("active")}
        assert did_active in ids
        assert did_done not in ids
        assert did_cancel not in ids
    finally:
        _db().deliveries.delete_many(
            {"id": {"$in": [did_active, did_done, did_cancel]}})


def test_history_filter_returns_only_completed_and_cancelled():
    did_active = _mk_delivery(status="accepted", courier_id=VIP_ID,
                              courier_name="VIP Test")
    did_done = _mk_delivery(status="confirmed", courier_id=VIP_ID,
                            courier_name="VIP Test")
    did_cancel = _mk_delivery(status="cancelled")
    try:
        ids = {d["id"] for d in _list("history")}
        assert did_done in ids
        assert did_cancel in ids
        assert did_active not in ids
    finally:
        _db().deliveries.delete_many(
            {"id": {"$in": [did_active, did_done, did_cancel]}})


def test_courier_can_claim_unassigned_available_delivery():
    """Un mensajero puede TOMAR una entrega disponible que aún NO está
    asignada a nadie (cola libre). Pasa a 'accepted' a su nombre."""
    from tests.conftest import VIP_TOKEN
    _ensure_vip_courier()
    did = _mk_delivery(status="available")  # sin assigned_to_courier_id
    try:
        r = requests.post(f"{API}/courier/deliveries/{did}/claim",
                          headers=_hdr(VIP_TOKEN), timeout=15)
        assert r.status_code == 200, r.text
        doc = _db().deliveries.find_one({"id": did})
        assert doc["status"] == "accepted"
        assert doc["courier_id"] == VIP_ID
    finally:
        _db().deliveries.delete_one({"id": did})


def test_attention_flags_stale_reservation():
    """Aviso de reserva lenta: una reserva sin aceptar hace > 30 min aparece
    en unanswered_reservations del endpoint /admin/deliveries/attention."""
    from datetime import timedelta
    _ensure_vip_courier()
    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    did = _mk_delivery(status="available", assigned_to_courier_id=VIP_ID,
                       assigned_to_courier_name="VIP Test", updated_at=old)
    try:
        r = requests.get(f"{API}/admin/deliveries/attention",
                         headers=_hdr(ADMIN_TOKEN), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        ids = {x["id"] for x in body.get("unanswered_reservations", [])}
        assert did in ids
        assert body["thresholds"]["reservation_min"] == 30
    finally:
        _db().deliveries.delete_one({"id": did})
